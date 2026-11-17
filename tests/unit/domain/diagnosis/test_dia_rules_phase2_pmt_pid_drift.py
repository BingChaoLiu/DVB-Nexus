"""DIA-PMT-PID-DRIFT builtin-rule declaration tests (ticket #130,
SPEC-307 §Phase2 candidate 4 — 「PMT/Demux 过滤不同步」).

The rule consumes the ts.* observation face per ruling §10-16-③:
``"ts.pmt_pid_drift"`` is NOT a registered envelope event (SPEC-303
§Phase2 does not list it; the PMT_PID_DRIFT primitive stays a TS-layer
skeleton, ruling §10-15-④), so the evidence face is the existing ts.*
observation family — ``ts.psi_section_observed`` facts + the
``fault.applied`` confirmation. The expected_evidence mirrors exactly
that symbol set (the 互证 with the primitive's expected_observations).

The match follows the house contradiction-field style (the analyzer
emits the declared expectation ONLY on a contradiction, see the PAT
mapping facts): a PMT section whose observed ``pmt_version`` carries the
contradiction field ``expected_pmt_version``. Unlike the three
construction-candidate rules, THIS rule produces hits today — the ts.*
family tolerates additive payload keys and the records can legally
carry the SPEC-306 §6 anchor triple. Confidence is declared ``low``:
the MVP analyzer does not emit the version-contradiction fields yet, so
the rule is honestly inert on current analysis output (the
pcr_jitter registered-but-inert precedent) until the observation face
grows the drift projection.

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.engine import DiagnosisEvaluator, ObservationRecord
from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import TS_EVENT_TYPES
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_PMT_PID_DRIFT,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

from tests._support.diagnosis_fixtures import (
    ARTIFACT_ID,
    FIXTURE_FAULT_TYPES,
    fault_observation_program,
)

RULE_ID = "DIA-PMT-PID-DRIFT"
EVALUATOR = DiagnosisEvaluator()
NOW_MS = 1_700_000_000_000

#: The psi payload of a PMT observation carrying the version-contradiction
#: pair (the observed version + the declared expectation that rides ONLY
#: on a contradiction — the house style of expected_program_map_pid).
#: The ts.* family tolerates additive payload keys, so the anchor triple
#: rides legally and the SPEC-306 §6 chain resolves.
DRIFT_PSI_PAYLOAD = {
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

#: The same PMT observation WITHOUT the contradiction (a clean face —
#: the analyzer's current output shape).
CLEAN_PSI_PAYLOAD = {
    "source": "internal_parser",
    "confidence": "parsed",
    "artifact_id": ARTIFACT_ID,
    "pid": 16,
    "packet_index": 300,
    "section": "PMT",
    "present": True,
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real PMT_PID_DRIFT FaultDefinition interlocked with the rule
    (stream-level TS-layer target per SPEC-204 §Phase2 item 4)."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-00000000f009",
        fault_type=FAULT_TYPE_PMT_PID_DRIFT,
        target_id="mux-0:pid:0x0010",
        parameters={"new_pid_map": {1: 4100}, "pmt_version_bump": True},
        activation=FaultActivation(kind="packet_index", packet_index=100),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_PMT_PID_DRIFT],
    )


def _drift_record(seq: int = 1) -> ObservationRecord:
    return ObservationRecord(
        journal_seq=seq,
        event_type="ts.psi_section_observed",
        event_id=f"obs-pmt-drift-{seq}",
        payload=dict(DRIFT_PSI_PAYLOAD),
        node_id="mon-0",
        pid=16,
    )


class TestDeclarationIdentity:
    """Static SPEC-307 §3 declaration values of the Phase 2 candidate."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_PMT_PID_DRIFT"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 80
        assert rule.severity.value == "error"
        # Honest LOW: the version-contradiction fields are not emitted by
        # the MVP analyzer yet (registered-but-inert posture) — the rule
        # must not claim more than its evidence face supports.
        assert rule.confidence.value == "low"
        assert rule.enabled is True

    def test_suppression_is_the_mvp_fixed_declaration(self):
        rule = _rule()
        assert rule.suppression.key == ("code", "node_id")
        assert rule.suppression.window == "per_run"


class TestPrimitiveInterlock:
    """expected_evidence ↔ the primitive's expected_observations (ruling
    §10-16-③ symbol set), validated by the genuine faults registry."""

    def test_expected_evidence_names_the_ts_observation_family(self):
        """ts.pmt_pid_drift does NOT exist as an envelope event; the
        evidence face is ts.psi_section_observed + fault.applied."""
        assert _rule().expected_evidence == (
            "ts.psi_section_observed",
            "fault.applied",
        )

    def test_match_consumes_an_observation_family_event(self):
        assert _rule().match.event_type in TS_EVENT_TYPES
        assert _rule().match.event_type == "ts.psi_section_observed"

    def test_fault_definition_interlocks_with_the_rule(self):
        fault = _primitive()
        assert fault.expected_observations == _rule().expected_evidence
        assert fault.fault_type == FAULT_TYPE_PMT_PID_DRIFT
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_PMT_PID_DRIFT] == "TS"


class TestMatchShape:
    """The match pins the PSI version-contrast contradiction (SPEC-307
    §Phase2: 证据 = PSI 版本对比 + 声明 PID 无数据漂移 — the version
    pair is the drift signature; the declared-PID data-absence face
    rides the same contradiction fields as the observation face grows)."""

    def test_predicates_pin_the_contradiction_pair(self):
        holds = {
            (predicate.field, predicate.op, predicate.value)
            for predicate in _rule().match.predicates
        }
        assert ("payload.section", "eq", "PMT") in holds
        assert ("payload.pmt_version", "exists", None) in holds
        assert ("payload.expected_pmt_version", "exists", None) in holds

    def test_grouping_addresses_the_dual_form(self):
        assert _rule().match.group_by == ("node_id", "pid")


class TestCandidateProduction:
    """The one Phase 2 rule that produces candidates TODAY: anchored,
    registry-valid ts.* records drive the full evaluator path."""

    def test_contradiction_record_yields_the_paired_candidate(self):
        outcome = EVALUATOR.evaluate(
            "sess-x",
            "run-x",
            (_drift_record(),),
            load_builtin_rules(),
            now_utc_ms=NOW_MS,
        )
        codes = [candidate.code for candidate in outcome.report.candidates]
        assert codes == ["DIAG_PMT_PID_DRIFT"]
        candidate = outcome.report.candidates[0]
        assert candidate.confidence.value == "low"
        # The SPEC-306 §6 chain resolves to the artifact anchor.
        assert candidate.evidence.artifact_id == ARTIFACT_ID
        assert candidate.evidence.pid == 16
        assert candidate.summary.startswith("PMT version")

    def test_clean_pmt_observation_yields_no_candidate(self):
        record = ObservationRecord(
            journal_seq=1,
            event_type="ts.psi_section_observed",
            event_id="obs-pmt-clean-1",
            payload=dict(CLEAN_PSI_PAYLOAD),
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
        assert outcome.report.candidates == ()

    def test_mvp_fault_programs_do_not_trigger_the_rule(self):
        others = tuple(
            record
            for fault_type in FIXTURE_FAULT_TYPES
            for record in fault_observation_program(fault_type)
        )
        assert _rule().matches(others) == ()

    def test_summary_template_places_no_phantom_keys(self):
        from string import Formatter

        rule = _rule()
        placeholders = {
            field_name
            for _, field_name, _, _ in Formatter().parse(
                rule.summary_template
            )
            if field_name is not None
        }
        assert placeholders <= set(DRIFT_PSI_PAYLOAD)
