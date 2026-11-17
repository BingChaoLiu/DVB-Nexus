"""DIA-BBHEADER-SYNC-FAULT builtin-rule declaration tests (ticket #130,
SPEC-307 §Phase2 candidate 2 — 「BBHEADER 同步错位」).

The rule consumes the B2 recovery evidence event ``bbframe.recovery_failed``
(SPEC-601 §5; payload key set is the #123 producer contract frozen by
#129's strict registry validation) and mirrors the
``BBHEADER_SYNC_FAULT`` primitive's ``expected_observations`` — the
ADR-0007 item 5 互证 against the Phase 2 primitives.

Mechanical honesty (候选 ≠ 事实 discipline, asserted not hidden): the
registered ``bbframe.recovery_failed`` key set carries no diagnosis
anchor triple (SPEC-306 §6), so the rule stays loadable but unfired
under the frozen engine until a Phase 2 evidence-anchor path lands (the
ruling follow-up recorded on #130).

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import (
    BBFRAME_EVENT_TYPES,
    validate_payload,
)
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_BBHEADER_SYNC_FAULT,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

from tests._support.diagnosis_fixtures import (
    FIXTURE_FAULT_TYPES,
    fault_observation_program,
)

RULE_ID = "DIA-BBHEADER-SYNC-FAULT"

#: The registered ``bbframe.recovery_failed`` payload shape (the #123
#: producer contract: failure count + the first-failed-frame locator,
#: honestly nullable). Integration proves the REAL emitted payload.
RECOVERY_FAILED_PAYLOAD = {
    "failure_count": 2,
    "first_failed_frame_index": 1,
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real BBHEADER_SYNC_FAULT FaultDefinition interlocked with the
    rule (packet_index activation per the SPEC-204 §Phase2 table)."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-00000000f007",
        fault_type=FAULT_TYPE_BBHEADER_SYNC_FAULT,
        target_id="enc-0",
        parameters={"field": "SYNCD", "mode": "corrupt"},
        activation=FaultActivation(kind="packet_index", packet_index=10),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_BBHEADER_SYNC_FAULT],
    )


class TestDeclarationIdentity:
    """Static SPEC-307 §3 declaration values of the Phase 2 candidate."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_BBHEADER_SYNC_FAULT"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 60
        assert rule.severity.value == "error"
        # Pipeline candidate face (候选 ≠ 事实) — not an L1-confirmed
        # artifact observation.
        assert rule.confidence.value == "medium"
        assert rule.enabled is True

    def test_suppression_is_the_mvp_fixed_declaration(self):
        rule = _rule()
        assert rule.suppression.key == ("code", "node_id")
        assert rule.suppression.window == "per_run"


class TestPrimitiveInterlock:
    """expected_evidence ↔ the primitive's expected_observations,
    validated by the genuine faults registry."""

    def test_expected_evidence_names_the_recovery_evidence_event(self):
        assert _rule().expected_evidence == ("bbframe.recovery_failed",)
        assert "bbframe.recovery_failed" in BBFRAME_EVENT_TYPES

    def test_fault_definition_interlocks_with_the_rule(self):
        fault = _primitive()
        assert fault.expected_observations == _rule().expected_evidence
        assert fault.fault_type == FAULT_TYPE_BBHEADER_SYNC_FAULT
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_BBHEADER_SYNC_FAULT] == "BBFRAME"


class TestMatchShape:
    """The match pins the recovery evidence event and its locator keys
    (SPEC-307 §Phase2: 证据 = bbframe.recovery_failed + 首失败帧定位)."""

    def test_match_consumes_the_registered_event(self):
        assert _rule().match.event_type == "bbframe.recovery_failed"

    def test_predicates_pin_exactly_the_registered_payload_keys(self):
        rule = _rule()
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        payload = dict(RECOVERY_FAILED_PAYLOAD)
        validate_payload(rule.match.event_type, payload)
        assert predicate_fields == {
            f"payload.{key}" for key in payload
        }

    def test_symptom_predicate_demands_a_positive_failure_count(self):
        """The zero-failure face is not a symptom: the match gates on
        failure_count > 0 (the pipeline emits only positive counts —
        the rule keeps that honesty if the producer face ever widens)."""
        holds = {
            (predicate.field, predicate.op, predicate.value)
            for predicate in _rule().match.predicates
        }
        assert ("payload.failure_count", "gt", 0) in holds

    def test_grouping_and_window_shape(self):
        match = _rule().match
        assert match.group_by == ("node_id",)
        assert match.window is None


class TestCandidateNotFactDiscipline:
    """The anchor-gate honesty and the single-attributable-symptom
    discipline."""

    def test_registry_conformant_record_without_anchor_yields_no_hit(self):
        """SPEC-306 §6: no anchor triple, no candidate — the honest
        inert-today posture under the frozen engine."""
        from domain.diagnosis.engine import ObservationRecord

        record = ObservationRecord(
            journal_seq=1,
            event_type="bbframe.recovery_failed",
            event_id="obs-bbframe-recovery-1",
            payload=dict(RECOVERY_FAILED_PAYLOAD),
            node_id="enc-0",
        )
        assert _rule().matches([record]) == ()

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
        assert placeholders <= set(RECOVERY_FAILED_PAYLOAD)
