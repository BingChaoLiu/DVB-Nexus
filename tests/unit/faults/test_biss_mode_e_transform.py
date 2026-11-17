"""The BISS Mode E face of the ``BISS_KEY_MISMATCH`` scrambler filter
(SPEC-611 §7/§8, ticket #127 — lands #126's explicit dispatch point).

Seams under test:

- :class:`faults.filters.biss_mode_e.BissModeEMismatchTransform` — the
  ``wrong_esw`` / ``wrong_injected_id`` fault path: wrong key chain,
  slot-preserving CISSA scramble, TSC marking;
- the dispatching builder (``transform_builder_for("BISS_KEY_MISMATCH")``
  routes Mode E variants to this transform and Mode 1 back to #126's —
  self-registration with ``allow_replace=True``, ruling §10-4);
- the mutation-log key discipline (SPEC-611 inherited: 密钥本体不落 —
  the redacted parameters carry fingerprints only) at the record seam;
- the evidence distinguishability (SPEC-611 §8 教学点): ``mode: "E"`` +
  ``derivation_ref`` + ``mismatch_variants`` — which face is wrong is
  readable from the payload.

Test discipline: the derivation and cipher seams are injected (plain
arguments, no fixtures — the unit layer forbids fixture requests), so
this file exercises the filter/evidence faces crypto-free; the real
chain/cipher integration lives in the integration and conformance
layers.  Packet bytes come from the canonical Null packet shape and the
SPEC-108 frozen-geometry chain — nothing hand-packed.
"""

from __future__ import annotations

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.factory import transform_builder_for
from faults.filters.biss_mode_e import BissModeEMismatchTransform
from faults.filters.pat_missing import null_packet
from faults.filters.scrambler import BissKeyMismatchTransform
from ts.packet import TSPacket
from tests._support.deterministic import seeded_bytes

pytestmark = pytest.mark.unit

# Deterministic key material via the sanctioned generator (32-hex
# literals are a data-rule violation).
WRONG_ESW = seeded_bytes(0x0E5, 8).hex().upper()
WRONG_ID = seeded_bytes(0x1D5, 16).hex().upper()
PID_SCOPE = (0x0100,)


def _fake_chain(esw_bytes, injected_id_bytes):
    """Deterministic stand-in for the Mode E derivation seam: a
    chain-derived wrong key plus a redacted-shaped reference (only
    fingerprints)."""
    import hashlib

    digest = hashlib.sha256(esw_bytes + injected_id_bytes).hexdigest()
    return (
        bytes.fromhex(digest[:32]),
        {
            "esw_fingerprint": f"sha256:{digest[:16]}",
            "injected_id_fingerprint": f"sha256:{digest[16:32]}",
            "session_word_fingerprint": f"sha256:{digest[32:48]}",
            "ciss_key_fingerprint": f"sha256:{digest[48:64]}",
        },
    )


class _FakeCipher:
    """Reversible deterministic stand-in for the CISSA payload cipher
    (shape only — the real AES face is verified in the ts.biss and
    integration suites)."""

    def __call__(self, payload: bytes, ciss_key) -> bytes:
        key = ciss_key if isinstance(ciss_key, bytes) else ciss_key.encode()
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(payload))


def _mode_e_definition(**parameter_overrides) -> FaultDefinition:
    parameters = {
        "wrong_esw": WRONG_ESW,
        "wrong_injected_id": WRONG_ID,
        "pid_scope": [0x0100],
    }
    parameters.update(parameter_overrides)
    for absent in [k for k, v in parameters.items() if v is None]:
        del parameters[absent]
    return FaultDefinition(
        fault_id="f-biss-mode-e",
        fault_type="BISS_KEY_MISMATCH",
        target_id="mux-0",
        parameters=parameters,
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("biss.descramble_failed",),
        layer="BISS",
    )


def _transform(**overrides) -> BissModeEMismatchTransform:
    return BissModeEMismatchTransform(
        _mode_e_definition(**overrides),
        encrypt_payload=_FakeCipher(),
        derive_chain=_fake_chain,
    )


def _in_scope_packet() -> TSPacket:
    return TSPacket(
        pid=0x0100,
        continuity_counter=1,
        payload=null_packet().payload,
    )


class TestBuilderDispatch:
    def test_builder_resolves_to_the_real_transforms(self) -> None:
        """The registered ``BISS_KEY_MISMATCH`` builder routes Mode E
        variants to the SPEC-611 transform and Mode 1 back to #126's."""
        import faults.filters.biss_mode_e  # noqa: F401 — self-registration

        builder = transform_builder_for("BISS_KEY_MISMATCH")
        assert isinstance(
            builder(_mode_e_definition()), BissModeEMismatchTransform
        )
        mode1_definition = FaultDefinition(
            fault_id="f-biss-mismatch",
            fault_type="BISS_KEY_MISMATCH",
            target_id="mux-0",
            parameters={
                "wrong_session_word": "0123456789AB",
                "pid_scope": [0x0100],
            },
            activation=FaultActivation(
                kind="session_start", packet_index=None
            ),
            layer="BISS",
        )
        assert isinstance(builder(mode1_definition), BissKeyMismatchTransform)

    def test_mode_e_variants_never_reach_the_mode1_transform(self) -> None:
        """The Mode 1 class-level guard stays loud (its refusal is the
        explicit dispatch point #126 left for this ticket)."""
        with pytest.raises(NotImplementedError):
            BissKeyMismatchTransform(_mode_e_definition())


class TestVariantParameters:
    def test_requires_at_least_one_mode_e_variant(self) -> None:
        with pytest.raises(ValueError):
            BissModeEMismatchTransform(
                _mode_e_definition(wrong_esw=None, wrong_injected_id=None),
                encrypt_payload=_FakeCipher(),
                derive_chain=_fake_chain,
            )

    def test_requires_non_empty_pid_scope(self) -> None:
        with pytest.raises(ValueError):
            BissModeEMismatchTransform(
                _mode_e_definition(pid_scope=[]),
                encrypt_payload=_FakeCipher(),
                derive_chain=_fake_chain,
            )


class TestScrambleBehavior:
    def test_in_scope_slot_scrambled_and_tsc_marked(self) -> None:
        transform = _transform()
        target = _in_scope_packet()
        after = transform.apply(0, target)
        assert after.payload != target.payload
        assert after.transport_scrambling_control == 0b10
        assert transform.applied_packet_indexes == (0,)
        # The fake cipher is reversible — roundtrip sanity over the seam
        # (the transform drives it with the derived wrong key).
        restored = _FakeCipher()(after.payload, transform._ciss_key)
        assert restored == target.payload

    def test_out_of_scope_slot_untouched(self) -> None:
        transform = _transform()
        original = null_packet()
        assert transform.apply(0, original) is original

    def test_packet_index_activation_gate(self) -> None:
        definition = _mode_e_definition()
        definition = FaultDefinition(
            fault_id=definition.fault_id,
            fault_type=definition.fault_type,
            target_id=definition.target_id,
            parameters=dict(definition.parameters),
            activation=FaultActivation(kind="packet_index", packet_index=3),
            expected_observations=definition.expected_observations,
            layer="BISS",
        )
        transform = BissModeEMismatchTransform(
            definition,
            encrypt_payload=_FakeCipher(),
            derive_chain=_fake_chain,
        )
        target = _in_scope_packet()
        assert transform.apply(2, target) is target  # before activation
        assert transform.apply(3, target).transport_scrambling_control == 0b10

    def test_zero_face_convention_for_single_variant_faults(self) -> None:
        """A single-face fault derives its chain with the zero block for
        the missing face — still a complete, deterministic wrong key."""
        transform = _transform(wrong_injected_id=None)
        assert transform._chain[0] == bytes.fromhex(WRONG_ESW.lower())
        assert transform._chain[1] == bytes(16)
        transform = _transform(wrong_esw=None)
        assert transform._chain[0] == bytes(8)
        assert transform._chain[1] == bytes.fromhex(WRONG_ID.lower())


class TestEvidenceFace:
    def test_summary_payload_shape_with_mode_e_evidence(self) -> None:
        """SPEC-611 §5/§8 + ruling §10-7: the shared scrambler keys plus
        ``mode: "E"`` and the redacted chain/variant evidence."""
        transform = _transform(wrong_injected_id=None)
        transform.apply(0, _in_scope_packet())
        summary = transform.scramble_summary()
        assert set(summary) == {
            "pid_scope",
            "packet_count",
            "key_fingerprint",
            "mutation_log_ref",
            "mode",
            "derivation_ref",
            "mismatch_variants",
        }
        assert summary["mode"] == "E"
        assert summary["pid_scope"] == [0x0100]
        assert summary["packet_count"] == 1
        assert summary["mutation_log_ref"] is None
        assert summary["mismatch_variants"] == ["wrong_esw"]
        assert set(summary["derivation_ref"]) == {
            "esw_fingerprint",
            "injected_id_fingerprint",
            "session_word_fingerprint",
            "ciss_key_fingerprint",
        }

    def test_mismatch_variants_distinguish_the_two_faces(self) -> None:
        """SPEC-611 §8 教学点: wrong ESW vs wrong Injected ID are
        readable from the evidence — different variant lists and
        different chain fingerprints."""
        esw_only = _transform(wrong_injected_id=None).scramble_summary()
        id_only = _transform(wrong_esw=None).scramble_summary()
        both = _transform().scramble_summary()
        assert esw_only["mismatch_variants"] == ["wrong_esw"]
        assert id_only["mismatch_variants"] == ["wrong_injected_id"]
        assert both["mismatch_variants"] == [
            "wrong_esw",
            "wrong_injected_id",
        ]
        # The wrong chains differ → the effective key fingerprints differ.
        assert (
            esw_only["key_fingerprint"] != id_only["key_fingerprint"]
        )
        assert (
            esw_only["derivation_ref"]["session_word_fingerprint"]
            != id_only["derivation_ref"]["session_word_fingerprint"]
        )

    def test_summary_never_carries_key_bodies(self) -> None:
        """Hard red line: no wrong-key body in the payload — only
        fingerprints."""
        summary = str(_transform().scramble_summary())
        assert WRONG_ESW.lower() not in summary.lower()
        assert WRONG_ID.lower() not in summary.lower()

    def test_mutation_records_carry_redacted_parameters(self) -> None:
        """SPEC-611 inherited key discipline: the effective-parameter
        snapshot on every record shows fingerprints, never bodies."""
        transform = _transform()
        transform.apply(0, _in_scope_packet())
        assert len(transform.records) == 1
        parameters = transform.records[0].parameters
        assert "wrong_esw" not in parameters
        assert "wrong_injected_id" not in parameters
        assert (
            parameters["wrong_esw_fingerprint"].startswith("sha256:")
        )
        assert (
            parameters["wrong_injected_id_fingerprint"].startswith(
                "sha256:"
            )
        )
        assert parameters["pid_scope"] == [0x0100]
