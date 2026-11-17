"""BISS Mode E end-to-end chain (SPEC-611 §12 AC-611-03, ticket #127).

Integration layer: the real crypto (pycryptodome AES/DES) drives the
whole face over real TS material —

- 场景 biss 段 → 派生 → 加扰 → 解扰证据: a scenario document with a
  ``mode: "E"`` biss section parses (the SPEC-611 §5 wire face), the
  declared chain derives, CISSA-scrambles the stream, and the declared
  descramble restores it with all structural self-checks green;
- the wrong-key fault variants produce the SPEC-610 §7 / SPEC-611 §8
  evidence (``biss.descramble_failed`` shape with the ``mode`` field)
  and the two mismatch faces are distinguishable end-to-end
  (``mismatch_variants`` + which chain fingerprint diverges).

The diagnosis-candidate leg of AC-611-03 is the SPEC-307 rule set
(ticket #130) — this layer pins the scramble/descramble/evidence legs.

Crypto dependency: pycryptodome — absent → the module skips loudly with
the SPEC-611 §8 dependency reason (honest NOT RUN, ``-ra`` visible).
"""

from __future__ import annotations

import pytest

try:
    import Crypto.Cipher.AES  # noqa: F401 — the dependency probe
except ImportError:
    pytest.skip(
        "pycryptodome absent — SPEC-611 §8 dependency face; the Mode E "
        "end-to-end chain is honestly NOT RUN without it",
        allow_module_level=True,
    )

from faults.definition import FaultActivation, FaultDefinition
from faults.filters.biss_mode_e import (
    BissModeEMismatchTransform,
    build_biss_key_mismatch,
)
from simulation.scenario.schema import BissModeEConfig, parse_scenario_document
from ts.biss.biss1 import SELF_CHECK_PSI_CRC32, SELF_CHECK_TSC_STATE
from ts.biss.cissa import BISS_MODE_E, descramble, scramble
from ts.biss.mode_e import (
    derive_ciss_key,
    derivation_ref,
    key_fingerprint,
)
from tests._support.deterministic import seeded_bytes
from tests.unit.faults._fault_builders import (
    GOLDEN_ES1_PID,
    GOLDEN_PAT_PID,
    golden_baseline_packets,
)
from tests.unit.simulation.scenario._scenario_builders import raw_scenario

pytestmark = pytest.mark.integration

ENCRYPTED_SW = "BCD10F7EA1978B2C"
INJECTED_ID = seeded_bytes(0x5CE7A, 16).hex().upper()
PID_SCOPE = (GOLDEN_PAT_PID, GOLDEN_ES1_PID)


def _scenario_document() -> BissModeEConfig:
    document = raw_scenario()
    document["biss"] = {
        "mode": "E",
        "encrypted_sw": ENCRYPTED_SW,
        "injected_id": INJECTED_ID,
        "pid_scope": list(PID_SCOPE),
    }
    parsed = parse_scenario_document(document)
    assert isinstance(parsed.biss, BissModeEConfig)
    return parsed.biss


def _fault_definition(**parameters) -> FaultDefinition:
    base = {
        "pid_scope": list(PID_SCOPE),
        "activation": None,
    }
    base.update(parameters)
    activation = FaultActivation(kind="session_start", packet_index=None)
    return FaultDefinition(
        fault_id="f-biss-mode-e",
        fault_type="BISS_KEY_MISMATCH",
        target_id="mux-0",
        parameters={k: v for k, v in base.items() if k != "activation"},
        activation=activation,
        expected_observations=("biss.descramble_failed",),
        layer="BISS",
    )


class TestDeclaredChainGreen:
    def test_scenario_biss_section_drives_scramble_descramble(self) -> None:
        """场景 biss 段（mode E）→ 派生 → CISSA 加扰 → 声明密钥解扰全部
        结构自检绿（AC-611-03 的加扰/证据腿）。"""
        biss = _scenario_document()
        ciss_key = derive_ciss_key(biss.encrypted_sw, biss.injected_id)
        packets = golden_baseline_packets()

        seen: list[dict] = []
        scrambled = scramble(
            packets,
            ciss_key,
            PID_SCOPE,
            mode="E",
            on_scramble_applied=seen.append,
        )
        assert seen == [
            {
                "pid_scope": sorted(PID_SCOPE),
                "packet_count": sum(
                    1
                    for p in packets
                    if p.pid in PID_SCOPE and p.payload is not None
                ),
                "key_fingerprint": key_fingerprint(ciss_key),
                "mutation_log_ref": None,
                "mode": "E",
            }
        ]

        clear, checks = descramble(scrambled, ciss_key, PID_SCOPE, mode="E")
        in_scope = [c for c in checks if c.pid in PID_SCOPE]
        assert in_scope
        # The declared chain clears everything — the PSI sections' CRC-32
        # verdicts are all green (解扰成功，不是 INCONCLUSIVE).
        assert all(check.ok for check in in_scope)
        assert {c.self_check_kind for c in in_scope} >= {
            SELF_CHECK_PSI_CRC32,
        }
        for original, after in zip(packets, clear):
            if original.pid in PID_SCOPE and original.payload is not None:
                assert after.payload == original.payload
                assert after.transport_scrambling_control == 0

    def test_wrong_esw_fault_produces_descramble_failed_evidence(self) -> None:
        """错 ESW → 派生错 SW → 加扰流在声明密钥下解扰失败，证据为
        ``biss.descramble_failed`` 形态（候选 ≠ 事实，解扰失败 ≠ 码流
        损坏）。"""
        packets = golden_baseline_packets()
        transform = BissModeEMismatchTransform(
            _fault_definition(wrong_esw=ENCRYPTED_SW[::-1])
        )
        faulted = [transform.apply(i, p) for i, p in enumerate(packets)]

        declared_key = derive_ciss_key(ENCRYPTED_SW, INJECTED_ID)
        seen: list[dict] = []
        _clear, checks = descramble(
            faulted,
            declared_key,
            PID_SCOPE,
            mode="E",
            on_descramble_failed=seen.append,
        )
        failures = [c for c in checks if not c.ok]
        assert failures, "the wrong-ESW stream must fail descrambling"
        assert len(seen) == 1
        payload = seen[0]
        assert payload["mode"] == BISS_MODE_E
        assert payload["self_check_kind"] == failures[0].self_check_kind
        assert (
            payload["key_fingerprint_ref"]
            == key_fingerprint(declared_key)
        )
        assert payload["failed_indices_sample"] == [
            c.index for c in failures
        ][:16]

    def test_two_mismatch_faces_distinguishable_end_to_end(self) -> None:
        """SPEC-611 §8 教学点（端到端）：错 ESW 与错 Injected ID 的
        fault 证据可区分——variant 列表不同、生效密钥指纹不同、派生链
        指纹在不同面上偏离声明链。"""
        packets = golden_baseline_packets()
        declared_ref = derivation_ref(ENCRYPTED_SW, INJECTED_ID)

        esw_fault = BissModeEMismatchTransform(
            _fault_definition(wrong_esw=ENCRYPTED_SW[::-1])
        )
        id_fault = BissModeEMismatchTransform(
            _fault_definition(wrong_injected_id=INJECTED_ID.lower()[:31] + "0")
        )
        esw_summary = esw_fault.scramble_summary()
        id_summary = id_fault.scramble_summary()

        assert esw_summary["mismatch_variants"] == ["wrong_esw"]
        assert id_summary["mismatch_variants"] == ["wrong_injected_id"]
        assert (
            esw_summary["key_fingerprint"] != id_summary["key_fingerprint"]
        )
        assert (
            esw_summary["derivation_ref"]["esw_fingerprint"]
            != declared_ref["esw_fingerprint"]
        )
        assert (
            id_summary["derivation_ref"]["injected_id_fingerprint"]
            != declared_ref["injected_id_fingerprint"]
        )

        # Both faulted streams fail the declared-key descramble (the
        # wrong keys never equal the declared chain).
        declared_key = derive_ciss_key(ENCRYPTED_SW, INJECTED_ID)
        for transform in (esw_fault, id_fault):
            faulted = [transform.apply(i, p) for i, p in enumerate(packets)]
            seen: list[dict] = []
            _clear, checks = descramble(
                faulted,
                declared_key,
                PID_SCOPE,
                mode="E",
                on_descramble_failed=seen.append,
            )
            assert any(not c.ok for c in checks)
            assert seen and seen[0]["mode"] == "E"

    def test_builder_path_resolves_the_real_chain(self) -> None:
        """The registered builder (ruling §10-4 self-registration) builds
        the Mode E transform from a plan-shaped definition — the
        registry → factory → semantic-filter plumbing stays whole."""
        builder = build_biss_key_mismatch
        transform = builder(_fault_definition(wrong_esw=ENCRYPTED_SW[::-1]))
        assert isinstance(transform, BissModeEMismatchTransform)
        assert transform.LAYER == "BISS"
