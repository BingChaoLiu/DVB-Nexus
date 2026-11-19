"""Phase 2 rules × the four training-range injection paths (ticket #130
acceptance + the #138 diagnose-face upgrade, SPEC-307 §Phase2 + §9 row 4
extension).

Each rule is interlocked against the REAL injected run of its paired
primitive through the #128 layered pipeline — the B1 (T2MI_PLP_MISMATCH),
B2 (BBHEADER_SYNC_FAULT) and BISS (BISS_KEY_MISMATCH, Mode 1 via the CSA1
CI oracle) paths emit their candidate events with the exact registered
payload key sets, and the paired rule's declaration is proven to consume
exactly those shapes (the expected_evidence 互证 + the match/predicate
key interlock against REAL producer output, not fixture mirrors).

#138 diagnose-face 点亮 (SPEC-306 §Phase2 补丁修订): the three evidence
events now travel the engine's expanded input family, and each anchored
record produces its candidate through the FULL evaluator path — the
anchor is the application-resolved ``evidence_artifact_id`` (the run's
received-leg Inner TS artifact for ``t2mi.*``/``bbframe.*`` — read from
the run's real sink records exactly as the composition resolver would;
the journal reference-chain ``mutation_log_ref`` for ``biss.*``), the
locator is the payload locator fields verbatim. The rules themselves are
UNTOUCHED (四规则声明两态通用, #130 已钉 — 点亮 = 馈送扩容 + 锚定形态).
The unanchored honesty face stays asserted: an evidence record without
its resolved anchor produces no candidate (no anchor, no candidate,
SPEC-306 §6). The one MVP-family rule — DIA-PMT-PID-DRIFT on the ts.*
observation family (ruling §10-16-③) — keeps its full candidate path
proof.

Marked integration: drives the real TSRuntime layered pipeline (real
SPEC-108 generator bytes, no wall clock — asyncio.run over the driver).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytestmark = pytest.mark.integration

from domain.diagnosis.engine import DiagnosisEvaluator, ObservationRecord
from domain.diagnosis.rules import load_builtin_rules
from domain.observation.registry import validate_payload
from simulation.layered_pipeline import LayerPipelineConfig
from simulation.ts_runtime import TSRuntime

from faults.factory import build_semantic_filter_factory
from faults.definition import FaultDefinition
from simulation.fault_plan import FaultActivation

from tests.integration.simulation.test_layered_runtime_t2mi import (
    LayeredFakeSink,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

import faults.filters.bbheader_sync  # noqa: F401 — self-registration activation
import faults.filters.biss_mode_e  # noqa: F401
import faults.filters.scrambler  # noqa: F401
import faults.filters.t2mi_plp_mismatch  # noqa: F401

from tests._support.csa1_oracle import Csa1Oracle

EVALUATOR = DiagnosisEvaluator()
NOW_MS = 1_700_000_000_000

MVP_RULE_IDS = (
    "DIA-PAT-MISSING",
    "DIA-PMT-CRC-BAD",
    "DIA-CC-DISCONTINUITY",
    "DIA-PMT-PID-MISMATCH",
)


def _collected(events: list[dict], event_type: str) -> list[dict]:
    """The run's REAL delivered payloads for one event type (the chain
    emission order preserved) — envelopes that already cleared the full
    ADR-0006 path (registry guard + payload schema)."""
    return [
        dict(event["payload"])
        for event in events
        if event["event_type"] == event_type
    ]


def _rule(rule_id: str):
    return next(rule for rule in load_builtin_rules() if rule.rule_id == rule_id)


def _run_layered(
    plan: tuple[FaultDefinition, ...], pipeline=LayerPipelineConfig()
) -> tuple[list[dict], LayeredFakeSink]:
    """One real layered run through the full wired delivery posture (the
    #128/#129 harness): the emitted events cross the shared envelope path
    — unregistered types are refused, payload schemas validated — and the
    delivered envelopes are what the assertions consume. The sink comes
    back too: the Inner-TS artifact ids the anchor chain stamps (the
    composition resolver reads the SAME records face, ticket #138)."""
    from simulation.runtime import SimulationRuntime

    events: list[dict] = []

    class RecordingGateway:
        def publish(self, event) -> None:
            events.append(dict(event))

    async def main() -> LayeredFakeSink:
        sim_runtime = SimulationRuntime(event_sink=RecordingGateway())
        config = make_generator_config(output_packet_count=60)
        session = make_session_spec(session_id="dia-phase2-130")
        await sim_runtime.create_session(session)
        await sim_runtime.validate_session(session.session_id)
        await sim_runtime.start(session.session_id)
        ts_runtime = TSRuntime(
            runtime=sim_runtime, filter_factory=build_semantic_filter_factory()
        )
        prepared = ts_runtime.prepare(session, config, plan, pipeline=pipeline)
        sink = LayeredFakeSink()
        result = await ts_runtime.run(prepared, sink)
        assert result.status == "completed", result.error
        ts_runtime.shutdown()
        return sink

    sink = asyncio.run(main())
    return events, sink


def _interlock_asserts(rule_id: str, event_type: str, payloads: list[dict]) -> None:
    """The shared interlock: the rule references exactly the event symbol
    its primitive really emits, its predicates address exactly the REAL
    payload keys, and every real payload clears the engine's own
    registry gate (the payload shapes the rules pin are the producer's)."""
    rule = _rule(rule_id)
    assert rule.match.event_type == event_type
    assert rule.expected_evidence == (event_type,)
    assert payloads, f"the {event_type} candidate never fired in the real run"
    for payload in payloads:
        validate_payload(event_type, payload)
        real_keys = {f"payload.{key}" for key in payload}
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        assert predicate_fields == real_keys


def _records_of(event_type: str, payloads: list[dict]) -> tuple[ObservationRecord, ...]:
    return tuple(
        ObservationRecord(
            journal_seq=index + 1,
            event_type=event_type,
            event_id=f"obs-{event_type}-{index}",
            payload=dict(payload),
            node_id="enc-0",
        )
        for index, payload in enumerate(payloads)
    )


def _anchored_records_of(
    event_type: str, payloads: list[dict], anchor: str | None
) -> tuple[ObservationRecord, ...]:
    """The same records with the application-resolved evidence anchor
    stamped (the ``ObservationRecord.evidence_artifact_id`` face the
    diagnosis service builds — ticket #138)."""
    return tuple(
        record.model_copy(update={"evidence_artifact_id": anchor})
        for record in _records_of(event_type, payloads)
    )


def _received_inner_ts_artifact_id(sink: LayeredFakeSink) -> str:
    """The run's received-leg Inner TS artifact id — the LAST
    ``kind=inner_ts`` sink record (the chain reconstructs the baseline
    leg first, the received leg second; the composition resolver's
    ``find_by_run`` pick, ticket #138)."""
    inner_rows = [
        record for record in sink.records if record["kind"] == "inner_ts"
    ]
    assert inner_rows, "the run never landed an Inner TS artifact"
    return str(inner_rows[-1]["artifact_id"])


def _mutation_log_ref_of(events: list[dict]) -> str:
    """The run's journal reference chain (the service's ``biss.*`` anchor
    resolution): the first non-None ``mutation_log_ref`` on
    ``fault.applied`` / ``biss.scramble_applied``."""
    for event in events:
        if event["event_type"] in ("fault.applied", "biss.scramble_applied"):
            ref = event["payload"].get("mutation_log_ref")
            if isinstance(ref, str) and ref:
                return ref
    raise AssertionError("the run never carried a mutation_log_ref reference")


def _assert_phase2_candidate(
    outcome, code: str, rule_id: str, anchor: str, locator_keys: set[str]
) -> None:
    """The #138 candidate face, asserted on the FULL evaluator outcome:
    the one expected candidate, its evidence locator verbatim and its
    anchor resolvable."""
    candidates = outcome.report.candidates
    assert [candidate.code for candidate in candidates] == [code]
    candidate = candidates[0]
    assert candidate.rule_id == rule_id
    assert candidate.evidence.artifact_id == anchor
    assert set(candidate.evidence.locator) == locator_keys
    assert candidate.evidence.pid is None
    assert candidate.evidence.packet_index is None
    assert candidate.observation_refs, "a candidate without evidence hops"
    assert candidate.observation_refs[0].journal_seq >= 1


class TestB1PlpMappingCandidate:
    """「PLP 映射错位」: the real B1 layered run emits the
    ``t2mi.plp_mismatch`` candidate and DIA-T2MI-PLP-MISMATCH consumes
    exactly that shape."""

    def test_rule_interlocks_with_the_real_run_emission(self):
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f006",
            fault_type="T2MI_PLP_MISMATCH",
            target_id="enc-0",
            parameters={"expected_plp": 0, "actual_plp": 1},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("t2mi.plp_mismatch",),
            layer="T2MI",
        )
        events, _sink = _run_layered((fault,))
        payloads = _collected(events, "t2mi.plp_mismatch")
        _interlock_asserts("DIA-T2MI-PLP-MISMATCH", "t2mi.plp_mismatch", payloads)
        # The honest 缺失 ≠ 零 face: the demux filtered to nothing.
        assert payloads[0]["expected_plp"] == 0
        assert payloads[0]["business_absent_evidence"]["filtered_packet_count"] == 0

    def test_anchored_candidate_event_lights_the_rule(self):
        """#138 点亮: the real evidence payload, anchored to the run's
        received-leg Inner TS artifact, produces the candidate through
        the FULL evaluator — the rule declaration untouched."""
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f006",
            fault_type="T2MI_PLP_MISMATCH",
            target_id="enc-0",
            parameters={"expected_plp": 0, "actual_plp": 1},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("t2mi.plp_mismatch",),
            layer="T2MI",
        )
        events, sink = _run_layered((fault,))
        payloads = _collected(events, "t2mi.plp_mismatch")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _anchored_records_of(
                "t2mi.plp_mismatch",
                payloads,
                _received_inner_ts_artifact_id(sink),
            ),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        _assert_phase2_candidate(
            outcome,
            "DIAG_T2MI_PLP_MISMATCH",
            "DIA-T2MI-PLP-MISMATCH",
            _received_inner_ts_artifact_id(sink),
            {"expected_plp", "actual_plp", "business_absent_evidence"},
        )

    def test_unanchored_candidate_event_stays_candidate_free(self):
        """候选 ≠ 事实 honesty face kept: the real payload carries no
        SPEC-306 §6 anchor triple, and an UNANCHORED evidence record (no
        resolved Inner TS — e.g. the resolver port unwired) produces no
        candidate and no warnings (the payload is registry-valid) — no
        anchor, no candidate."""
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f006",
            fault_type="T2MI_PLP_MISMATCH",
            target_id="enc-0",
            parameters={"expected_plp": 0, "actual_plp": 1},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("t2mi.plp_mismatch",),
            layer="T2MI",
        )
        events, _sink = _run_layered((fault,))
        payloads = _collected(events, "t2mi.plp_mismatch")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _records_of("t2mi.plp_mismatch", payloads),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()


class TestB2BbheaderSyncCandidate:
    """「BBHEADER 同步错位」: the real B2 layered run emits
    ``bbframe.recovery_failed`` and DIA-BBHEADER-SYNC-FAULT consumes
    exactly that shape."""

    def test_rule_interlocks_with_the_real_run_emission(self):
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f007",
            fault_type="BBHEADER_SYNC_FAULT",
            target_id="enc-0",
            parameters={"field": "SYNCD", "mode": "corrupt"},
            activation=FaultActivation(kind="packet_index", packet_index=1),
            expected_observations=("bbframe.recovery_failed",),
            layer="BBFRAME",
        )
        events, _sink = _run_layered((fault,))
        payloads = _collected(events, "bbframe.recovery_failed")
        _interlock_asserts(
            "DIA-BBHEADER-SYNC-FAULT", "bbframe.recovery_failed", payloads
        )
        assert payloads[0]["failure_count"] > 0

    def test_anchored_evidence_event_lights_the_rule(self):
        """#138 点亮: the real recovery evidence, anchored to the run's
        received-leg Inner TS artifact, produces the candidate."""
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f007",
            fault_type="BBHEADER_SYNC_FAULT",
            target_id="enc-0",
            parameters={"field": "SYNCD", "mode": "corrupt"},
            activation=FaultActivation(kind="packet_index", packet_index=1),
            expected_observations=("bbframe.recovery_failed",),
            layer="BBFRAME",
        )
        events, sink = _run_layered((fault,))
        payloads = _collected(events, "bbframe.recovery_failed")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _anchored_records_of(
                "bbframe.recovery_failed",
                payloads,
                _received_inner_ts_artifact_id(sink),
            ),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        _assert_phase2_candidate(
            outcome,
            "DIAG_BBHEADER_SYNC_FAULT",
            "DIA-BBHEADER-SYNC-FAULT",
            _received_inner_ts_artifact_id(sink),
            {"first_failed_frame_index", "failure_count"},
        )

    def test_unanchored_evidence_event_stays_candidate_free(self):
        """候选 ≠ 事实 honesty face kept (no resolved anchor → no
        candidate, no warnings)."""
        fault = FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f007",
            fault_type="BBHEADER_SYNC_FAULT",
            target_id="enc-0",
            parameters={"field": "SYNCD", "mode": "corrupt"},
            activation=FaultActivation(kind="packet_index", packet_index=1),
            expected_observations=("bbframe.recovery_failed",),
            layer="BBFRAME",
        )
        events, _sink = _run_layered((fault,))
        payloads = _collected(events, "bbframe.recovery_failed")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _records_of("bbframe.recovery_failed", payloads),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()


class TestBissKeyMismatchCandidate:
    """「BISS 密钥错位」: the real BISS layered run (Mode 1, CSA1 CI
    oracle) emits ``biss.descramble_failed`` and DIA-BISS-KEY-MISMATCH
    consumes exactly that shape — fingerprints only, never key material."""

    @pytest.fixture(autouse=True)
    def _oracle_backend_loader(self, monkeypatch):
        """The scrambler's sanctioned default-backend seam (the pure-Python
        CSA1 oracle is the CI face — no DLL anywhere, ADR-0011 §5)."""
        from faults.filters import scrambler as scrambler_module

        monkeypatch.setattr(
            scrambler_module, "_DEFAULT_BACKEND_LOADER", lambda: Csa1Oracle()
        )

    @staticmethod
    def _fault() -> FaultDefinition:
        return FaultDefinition(
            fault_id="fd000000-0000-4000-8000-00000000f008",
            fault_type="BISS_KEY_MISMATCH",
            target_id="mux-0",
            parameters={
                "wrong_session_word": "0123456789ab",
                "pid_scope": [256],
            },
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("biss.descramble_failed",),
            layer="BISS",
        )

    @staticmethod
    def _pipeline(golden_loader) -> LayerPipelineConfig:
        """The declared-key construction face over the golden manifest
        constants (public standard J.96 material with provenance — no
        in-test key literals for the construction face)."""
        from simulation.layered_pipeline import BissFaceConfig

        manifest_path = golden_loader.root / "biss-j96-mode1" / "manifest.json"
        biss = json.loads(manifest_path.read_text(encoding="utf-8"))["biss"]
        return LayerPipelineConfig(
            biss=BissFaceConfig(
                mode=str(biss["mode"]),
                session_word=str(biss["session_word"]),
                pid_scope=tuple(biss["pid_scope"]),
            ),
            csa_backend_factory=lambda: Csa1Oracle(),
        )

    def test_rule_interlocks_with_the_real_run_emission(self, golden_loader):
        events, _sink = _run_layered((self._fault(),), self._pipeline(golden_loader))
        payloads = _collected(events, "biss.descramble_failed")
        _interlock_asserts(
            "DIA-BISS-KEY-MISMATCH", "biss.descramble_failed", payloads
        )
        # 密钥纪律: the synthetic WRONG key never rides a payload.
        for payload in payloads:
            assert "0123456789ab" not in json.dumps(payload)
        assert payloads[0]["mode"] == "1"

    def test_anchored_candidate_event_lights_the_rule(self, golden_loader):
        """#138 点亮: the real descramble evidence, anchored through the
        journal reference chain (the run's ``mutation_log_ref`` — the
        mutation-log artifact binding, exactly what the diagnosis service
        resolves), produces the candidate."""
        events, _sink = _run_layered((self._fault(),), self._pipeline(golden_loader))
        payloads = _collected(events, "biss.descramble_failed")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _anchored_records_of(
                "biss.descramble_failed",
                payloads,
                _mutation_log_ref_of(events),
            ),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        _assert_phase2_candidate(
            outcome,
            "DIAG_BISS_KEY_MISMATCH",
            "DIA-BISS-KEY-MISMATCH",
            _mutation_log_ref_of(events),
            {"failed_indices_sample", "pid_scope"},
        )
        # 密钥纪律 survives the anchor chain: the candidate summary and
        # locator carry fingerprints/shapes only, never key material.
        candidate = outcome.report.candidates[0]
        assert "0123456789ab" not in json.dumps(candidate.summary)
        assert "0123456789ab" not in json.dumps(candidate.evidence.locator)

    def test_unanchored_candidate_event_stays_candidate_free(self, golden_loader):
        """候选 ≠ 事实 honesty face kept (no resolved anchor → no
        candidate, no warnings)."""
        events, _sink = _run_layered((self._fault(),), self._pipeline(golden_loader))
        payloads = _collected(events, "biss.descramble_failed")
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            _records_of("biss.descramble_failed", payloads),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()


class TestPmtPidDriftCandidatePath:
    """「PMT/Demux 过滤不同步」: the drift rule's evidence face is the
    ts.* observation family (ruling §10-16-③ — ts.pmt_pid_drift is NOT a
    registered envelope event), and it is the one Phase 2 rule whose
    candidate path is anchor-capable today: a registry-valid, anchored
    contradiction record drives the FULL evaluator candidate.

    The primitive itself stays a TS-layer skeleton (ruling §10-15-④) — a
    real injected run would refuse loudly rather than mis-generate, so
    no layered run is driven here (that would fake the evidence)."""

    def test_expected_evidence_interlocks_with_the_ruling_symbols(self):
        rule = _rule("DIA-PMT-PID-DRIFT")
        assert rule.expected_evidence == ("ts.psi_section_observed", "fault.applied")

    def test_drift_candidate_through_the_full_evaluator(self):
        from tests._support.diagnosis_fixtures import ARTIFACT_ID

        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "artifact_id": ARTIFACT_ID,
            "pid": 16,
            "packet_index": 300,
            "section": "PMT",
            "present": True,
            "pmt_version": 7,
            "expected_pmt_version": 6,
        }
        record = ObservationRecord(
            journal_seq=1,
            event_type="ts.psi_section_observed",
            event_id="obs-pmt-drift-1",
            payload=payload,
            node_id="mon-0",
            pid=16,
        )
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            (record,),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        assert [c.code for c in outcome.report.candidates] == [
            "DIAG_PMT_PID_DRIFT"
        ]
        candidate = outcome.report.candidates[0]
        assert candidate.rule_id == "DIA-PMT-PID-DRIFT"
        assert candidate.rule_version == "1.0.0"
        assert candidate.confidence.value == "low"
        # The SPEC-306 §6 evidence chain resolves end to end.
        assert candidate.evidence.artifact_id == ARTIFACT_ID
        assert candidate.observation_refs[0].event_type == "ts.psi_section_observed"

    def test_mvp_rules_stay_silent_on_the_drift_candidate(self):
        """Single attributable symptom across the additive boundary: the
        drift record triggers ONLY the paired Phase 2 rule."""
        from tests._support.diagnosis_fixtures import ARTIFACT_ID

        payload = {
            "source": "internal_parser",
            "confidence": "parsed",
            "artifact_id": ARTIFACT_ID,
            "pid": 16,
            "packet_index": 300,
            "section": "PMT",
            "present": True,
            "pmt_version": 7,
            "expected_pmt_version": 6,
        }
        record = ObservationRecord(
            journal_seq=1,
            event_type="ts.psi_section_observed",
            event_id="obs-pmt-drift-1",
            payload=payload,
            node_id="mon-0",
            pid=16,
        )
        rule = _rule("DIA-PMT-PID-DRIFT")
        assert len(rule.matches([record])) == 1
        for rule_id in MVP_RULE_IDS:
            assert _rule(rule_id).matches([record]) == ()
