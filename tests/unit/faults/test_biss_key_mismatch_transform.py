"""The real BISS scrambler filter (ADR-0011 §2/§3/§4, SPEC-610 §6/§9,
ticket #126 — replaces the #121 skeleton).

Seams under test:

- :class:`faults.filters.scrambler.ScramblerTransform` — the scrambler
  filter type (layer=BISS), key-source agnostic: the fault path injects
  the mismatched key from ``FaultDefinition.parameters``, the
  construction path (scenario ``biss`` section) injects the declared key
  (#128 wiring);
- the ``BISS_KEY_MISMATCH`` builder resolution through
  :func:`faults.factory.transform_builder_for` (self-registration via
  import side effect, ruling §10-4 — factory.py untouched);
- the mutation-log key discipline (SPEC-610 §9: 密钥本体不落 mutation
  log — only the key fingerprint does), audited at the
  :meth:`SemanticFaultFilter.mutation_log` seam.

Packet bytes come from the canonical Null packet shape — nothing
hand-packed.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from faults.definition import FaultActivation, FaultDefinition
from faults.factory import transform_builder_for
from faults.filters.pat_missing import null_packet
from faults.filters import scrambler as scrambler_module
from faults.filters.scrambler import (
    BissKeyMismatchTransform,
    ScramblerTransform,
)
from faults.filters.semantic import SemanticFaultFilter
from ts.biss.biss1 import key_fingerprint
from ts.packet import TSPacket

pytestmark = pytest.mark.unit

WRONG_SESSION_WORD = "0123456789AB"
PID_SCOPE = (0x0100,)


@contextlib.contextmanager
def _fake_default_backend():
    """Swap the default-backend loader seam (plain context manager — the
    unit layer forbids fixture requests, SPEC-505 §8 io_rules)."""
    original = scrambler_module._DEFAULT_BACKEND_LOADER
    scrambler_module._DEFAULT_BACKEND_LOADER = lambda: _FakeBackend()
    try:
        yield
    finally:
        scrambler_module._DEFAULT_BACKEND_LOADER = original


class _FakeBackend:
    """Deterministic stand-in for the batch backend (shape only — the
    real CSA1 transform is verified in the ts.biss and adapter suites)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, bytes]] = []

    def encrypt_batch(self, payloads, cw):
        self.calls.append((len(payloads), cw))
        return tuple(bytes(len(p)) for p in payloads)

    def decrypt_batch(self, payloads, cw):
        self.calls.append((len(payloads), cw))
        return tuple(bytes(len(p)) for p in payloads)


def _definition() -> FaultDefinition:
    return FaultDefinition(
        fault_id="f-biss-mismatch",
        fault_type="BISS_KEY_MISMATCH",
        target_id="mux-0",
        parameters={
            "wrong_session_word": WRONG_SESSION_WORD,
            "pid_scope": [0x0100],
        },
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("biss.descramble_failed",),
        layer="BISS",
    )


def _in_scope_packet():
    """An in-scope slot with the canonical Null packet payload shape."""
    return TSPacket(
        pid=0x0100,
        continuity_counter=1,
        payload=null_packet().payload,
    )


class TestBuilderResolution:
    def test_biss_key_mismatch_resolves_to_real_transform(self) -> None:
        import faults.filters.scrambler  # noqa: F401 — self-registration

        builder = transform_builder_for("BISS_KEY_MISMATCH")
        transform = builder(_definition())
        assert isinstance(transform, ScramblerTransform)

    def test_mode_e_variant_dispatch_is_explicit(self) -> None:
        """wrong_esw / wrong_injected_id belong to #127 (SPEC-611) — the
        Mode 1 filter refuses them loudly instead of guessing."""
        definition = FaultDefinition(
            fault_id="f-biss-mode-e",
            fault_type="BISS_KEY_MISMATCH",
            target_id="mux-0",
            parameters={
                "wrong_esw": "0123456789ABCDEF",
                "wrong_injected_id": "0123456789ABCDEF0123456789ABCDEF",
                "pid_scope": [0x0100],
            },
            activation=FaultActivation(kind="session_start", packet_index=None),
            layer="BISS",
        )
        with pytest.raises(NotImplementedError) as excinfo:
            BissKeyMismatchTransform(definition)
        assert "#127" in str(excinfo.value)


class TestScramblerTransformBehavior:
    def test_in_scope_slot_is_scrambled_and_tsc_marked(self) -> None:
        transform = BissKeyMismatchTransform(
            _definition(), backend=_FakeBackend()
        )
        target = _in_scope_packet()
        after = transform.apply(0, target)
        assert after.payload != target.payload
        assert after.transport_scrambling_control == 0b10
        assert transform.applied_packet_indexes == (0,)

    def test_out_of_scope_slot_untouched(self) -> None:
        transform = BissKeyMismatchTransform(
            _definition(), backend=_FakeBackend()
        )
        original = null_packet()
        assert transform.apply(0, original) is original

    def test_packet_index_activation_gate(self) -> None:
        definition = FaultDefinition(
            fault_id="f-biss-mismatch",
            fault_type="BISS_KEY_MISMATCH",
            target_id="mux-0",
            parameters={
                "wrong_session_word": WRONG_SESSION_WORD,
                "pid_scope": [0x0100],
            },
            activation=FaultActivation(kind="packet_index", packet_index=3),
            layer="BISS",
        )
        transform = BissKeyMismatchTransform(definition, backend=_FakeBackend())
        target = _in_scope_packet()
        assert transform.apply(2, target) is target  # before activation
        after = transform.apply(3, target)
        assert after.transport_scrambling_control == 0b10

    def test_summary_payload_shape(self) -> None:
        transform = BissKeyMismatchTransform(
            _definition(), backend=_FakeBackend()
        )
        transform.apply(0, _in_scope_packet())
        summary = transform.scramble_summary()
        # #127 (SPEC-611 §5, ruling §10-7) added the `mode` field to the
        # biss.* emission payloads; this CSA1 face emits "1".
        assert set(summary) == {
            "pid_scope",
            "packet_count",
            "key_fingerprint",
            "mutation_log_ref",
            "mode",
        }
        assert summary["mode"] == "1"
        assert summary["pid_scope"] == [0x0100]
        assert summary["packet_count"] == 1
        assert summary["key_fingerprint"] == key_fingerprint(
            WRONG_SESSION_WORD
        )
        assert summary["mutation_log_ref"] is None


class TestMutationLogKeyDiscipline:
    """SPEC-610 §9: 密钥本体不进 mutation log（密钥指纹除外）."""

    def test_mutation_log_carries_fingerprint_not_key(self) -> None:
        import faults.filters.scrambler  # noqa: F401 — self-registration

        with _fake_default_backend():
            filter_ = SemanticFaultFilter((_definition(),))
            filter_.apply(0, _in_scope_packet())
        serialized = filter_.mutation_log().decode("utf-8")

        # The key body never appears anywhere in the log document.
        assert WRONG_SESSION_WORD.lower() not in serialized.lower()
        # The fingerprint does — as the only key trace.
        assert key_fingerprint(WRONG_SESSION_WORD) in serialized

    def test_fault_summary_parameters_are_redacted(self) -> None:
        import faults.filters.scrambler  # noqa: F401 — self-registration

        with _fake_default_backend():
            filter_ = SemanticFaultFilter((_definition(),))
            filter_.apply(0, _in_scope_packet())
        log = json.loads(filter_.mutation_log().decode("utf-8"))
        parameters = log["faults"][0]["parameters"]
        assert "wrong_session_word" not in parameters
        assert (
            parameters["wrong_session_word_fingerprint"]
            == key_fingerprint(WRONG_SESSION_WORD)
        )
        assert parameters["pid_scope"] == [0x0100]

    def test_mutation_record_parameters_redacted_too(self) -> None:
        import faults.filters.scrambler  # noqa: F401 — self-registration

        with _fake_default_backend():
            filter_ = SemanticFaultFilter((_definition(),))
            filter_.apply(0, _in_scope_packet())
        log = json.loads(filter_.mutation_log().decode("utf-8"))
        for mutation in log["mutations"]:
            assert "wrong_session_word" not in mutation["parameters"]
            assert (
                mutation["parameters"]["wrong_session_word_fingerprint"]
                == key_fingerprint(WRONG_SESSION_WORD)
            )
