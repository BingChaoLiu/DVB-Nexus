"""DIA-T2MI-PLP-MISMATCH builtin-rule declaration tests (ticket #130,
SPEC-307 §Phase2 candidate 1 — 「PLP 映射错位」).

The rule consumes the B1 candidate event ``t2mi.plp_mismatch`` (SPEC-602
§5; the payload key set is the #124 producer contract frozen by #129's
strict registry validation) and mirrors the ``T2MI_PLP_MISMATCH``
primitive's ``expected_observations`` — the ADR-0007 item 5 互证, now
against the Phase 2 primitives.

Mechanical honesty (候选 ≠ 事实 discipline, asserted not hidden): the
engine's SPEC-306 §6 evidence gate demands the ``artifact_id`` /
``pid`` / ``packet_index`` anchor triple in the record payload, and the
registered ``t2mi.plp_mismatch`` key set is strict — the rule therefore
stays loadable but unfired until a Phase 2 evidence-anchor path lands
(the ruling follow-up recorded on #130). The declaration itself is the
deliverable: it pins WHICH event and WHICH locator keys constitute the
candidate.

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import T2MI_EVENT_TYPES, validate_payload
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

from tests._support.diagnosis_fixtures import (
    FIXTURE_FAULT_TYPES,
    fault_observation_program,
)

RULE_ID = "DIA-T2MI-PLP-MISMATCH"

#: The registered ``t2mi.plp_mismatch`` payload shape (the #124 producer
#: contract: expected/actual PLP + the Inner TS business-absence locator
#: block). Mirrors the strict #129 registry key set; the integration
#: suite proves the REAL emitted payloads satisfy it.
PLP_MISMATCH_PAYLOAD = {
    "expected_plp": 0,
    "actual_plp": 1,
    "business_absent_evidence": {
        "plps_seen": [1],
        "bbframe_packet_count": 12,
        "filtered_packet_count": 0,
        "total_packet_count": 12,
    },
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real T2MI_PLP_MISMATCH FaultDefinition whose expected_observations
    are the paired rule's expected_evidence (the 互证 under test)."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-00000000f006",
        fault_type=FAULT_TYPE_T2MI_PLP_MISMATCH,
        target_id="enc-0",
        parameters={"expected_plp": 0, "actual_plp": 1},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_T2MI_PLP_MISMATCH],
    )


class TestDeclarationIdentity:
    """The SPEC-307 §Phase2 candidate lands as a registered builtin rule
    with its static SPEC-307 §3 declaration values."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_T2MI_PLP_MISMATCH"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 50
        assert rule.severity.value == "error"
        # Static THREE-tier declaration (Q3-ii): the B1 evidence is a
        # purpose-built pipeline candidate face — structured and
        # contract-frozen, but not an L1-confirmed artifact observation.
        assert rule.confidence.value == "medium"
        assert rule.enabled is True

    def test_suppression_is_the_mvp_fixed_declaration(self):
        rule = _rule()
        assert rule.suppression.key == ("code", "node_id")
        assert rule.suppression.window == "per_run"


class TestPrimitiveInterlock:
    """expected_evidence ↔ the primitive's expected_observations (ADR-0007
    item 5 互证, SPEC-307 §Phase2), validated by the genuine faults
    registry."""

    def test_expected_evidence_names_the_b1_candidate_event(self):
        assert _rule().expected_evidence == ("t2mi.plp_mismatch",)
        assert "t2mi.plp_mismatch" in T2MI_EVENT_TYPES

    def test_fault_definition_interlocks_with_the_rule(self):
        fault = _primitive()
        assert fault.expected_observations == _rule().expected_evidence
        assert fault.fault_type == FAULT_TYPE_T2MI_PLP_MISMATCH
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_T2MI_PLP_MISMATCH] == "T2MI"


class TestMatchShape:
    """The declarative match pins the registered candidate event and its
    locator keys (SPEC-307 §Phase2: 证据 = t2mi.plp_mismatch 事件 +
    Inner TS 业务缺失定位)."""

    def test_match_consumes_the_registered_event(self):
        assert _rule().match.event_type == "t2mi.plp_mismatch"

    def test_predicates_pin_exactly_the_registered_payload_keys(self):
        """Every predicate addresses a payload key the producer actually
        emits — verified against the registry's own payload validation,
        so the match can never reference a phantom key."""
        rule = _rule()
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        payload = dict(PLP_MISMATCH_PAYLOAD)
        validate_payload(rule.match.event_type, payload)
        assert predicate_fields == {
            f"payload.{key}" for key in payload
        }

    def test_predicates_are_existence_checks_on_the_locator_face(self):
        """候选 ≠ 事实: the rule fires on the presence of the candidate
        payload and its business-absence locator — the declarative
        exists-op set, never a fabricated fact predicate."""
        ops = {
            (predicate.field, predicate.op)
            for predicate in _rule().match.predicates
        }
        assert ("payload.expected_plp", "exists") in ops
        assert ("payload.business_absent_evidence", "exists") in ops

    def test_grouping_and_window_shape(self):
        match = _rule().match
        assert match.group_by == ("node_id",)
        assert match.window is None


class TestCandidateNotFactDiscipline:
    """The anchor-gate honesty and the single-attributable-symptom
    discipline (SPEC-307 §6 / ADR-0007 item 5)."""

    def test_registry_conformant_record_without_anchor_yields_no_hit(self):
        """The registered key set carries no diagnosis anchor triple
        (SPEC-306 §6: no anchor, no candidate) — the honest inert-today
        posture of the frozen engine, asserted so a silent gate change
        cannot pass unnoticed."""
        from domain.diagnosis.engine import ObservationRecord

        record = ObservationRecord(
            journal_seq=1,
            event_type="t2mi.plp_mismatch",
            event_id="obs-plp-mismatch-1",
            payload=dict(PLP_MISMATCH_PAYLOAD),
            node_id="demux-0",
        )
        assert _rule().matches([record]) == ()

    def test_mvp_fault_programs_do_not_trigger_the_rule(self):
        """Single attributable symptom: the MVP four's observation
        programs never produce a PLP-mismatch hit."""
        others = tuple(
            record
            for fault_type in FIXTURE_FAULT_TYPES
            for record in fault_observation_program(fault_type)
        )
        assert _rule().matches(others) == ()

    def test_summary_template_places_no_phantom_keys(self):
        """Every template placeholder is a plain payload key the producer
        emits (the declarative red line — no attribute access, no
        invented vocabulary)."""
        from string import Formatter

        rule = _rule()
        placeholders = {
            field_name
            for _, field_name, _, _ in Formatter().parse(
                rule.summary_template
            )
            if field_name is not None
        }
        assert placeholders <= set(PLP_MISMATCH_PAYLOAD)


@pytest.mark.parametrize(
    "other_rule_id",
    [
        "DIA-PAT-MISSING",
        "DIA-PMT-CRC-BAD",
        "DIA-CC-DISCONTINUITY",
        "DIA-PMT-PID-MISMATCH",
    ],
)
def test_mvp_rules_do_not_share_the_candidate_identity(other_rule_id):
    """The Phase 2 code namespace is additive: no MVP rule may collide
    with the new candidate's rule_id/code identity."""
    rules = {rule.rule_id: rule for rule in load_builtin_rules()}
    assert other_rule_id in rules
    assert rules[other_rule_id].code != "DIAG_T2MI_PLP_MISMATCH"
