"""UB_CONFLICT_SUSPECT builtin-rule declaration tests (ticket #168,
SPEC-307 §Phase3 candidate 2 — 「UB 槽位冲突 / SCR 堆叠互扰」).

The rule consumes the tuner snapshot ``rf.state_observed`` (SPEC-303
§Phase3, registered by #164) and mirrors the ``UB_SLOT_CONFLICT``
primitive's ``expected_observations`` symbol set — the ADR-0007 item 5
互证 against the state-layer primitives (#163).

Mechanical honesty (候选 ≠ 事实 discipline, asserted not hidden): the
engine's SPEC-306 §6 evidence gate demands an anchor state the
``rf.state_observed`` registered key set cannot carry (exact-key
snapshot shape, not the Phase 2 evidence family), so the rule stays
loadable but unfired until a Phase 3 evidence-anchor path lands (the
#130 → #138 precedent posture; the declaration itself is the
deliverable: it pins WHICH event and WHICH predicate faces constitute
the candidate).

Predicate-face honesty (the frozen §4 op set is {eq, gt, lt, exists}):
the declarable faces are the constant observation axes
(``state_evaluator``/``simulated``), the unlocked face
(``lock_state="unlocked"`` — the SPEC-307 §Phase3 discriminator) and
the graded BER face (the runtime conflict branch is anomaly ⇒ severe,
#161).  The CauseRef 冲突对 face (``causes[*].node_id`` — the conflict
peer pair) and the ``ub_assignments`` table (which lives on the lnb
snapshot ``sec.state_observed``, NOT on the matched tuner snapshot) are
outside the finite single-event predicate set — they ride the
``expected_evidence`` symbol set and the #171 判据互锁, not the match
predicates (ticket #168 REPORT deviation; no mechanism extension taken
under the 零改 discipline).

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import (
    RF_EVENT_TYPES,
    validate_payload,
)
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_UB_SLOT_CONFLICT,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

RULE_ID = "DIA-UB-CONFLICT-SUSPECT"

#: The registered ``rf.state_observed`` payload shape at the UB-conflict
#: face (the #164 producer contract): the conflict-claimed tuner sits
#: unlocked with the conflict peer in its cause chain and the effective
#: slot's carrier as the IF fact (the #161 runtime branch — the UB
#: carrier is the transponder slot centre, 1210 MHz → 1210000 kHz).
UB_CONFLICT_TUNER_SNAPSHOT = {
    "node_id": "tuner-b",
    "health": "error",
    "causes": [{"node_id": "tuner-a"}],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "unlocked",
    "if_frequency_khz": 1210000,
    "ber_state": "severe",
    "locked_transponder_id": None,
    "stale": True,
}

#: The non-anomaly unlocked face (polarization mismatch, no fault): the
#: unlocked state keeps NO BER grade (SPEC-620 §8) and carries no cause
#: chain — the eq pin set must NOT hold here (缺失 ≠ 候选).
UNGRADED_UNLOCKED_SNAPSHOT = {
    "node_id": "tuner-0",
    "health": "error",
    "causes": [],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "unlocked",
    "if_frequency_khz": 1345000,
    "ber_state": None,
    "locked_transponder_id": None,
    "stale": True,
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real UB_SLOT_CONFLICT FaultDefinition whose expected_observations
    are the paired rule's expected_evidence (the 互证 under test); the
    ``tuner-b:ub_slot`` target rides the #163/#A4 node-attr form."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000163",
        fault_type=FAULT_TYPE_UB_SLOT_CONFLICT,
        target_id="tuner-b:ub_slot",
        parameters={"conflicting_ub_slot": 0},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT],
    )


class TestDeclarationIdentity:
    """The SPEC-307 §Phase3 candidate lands as a registered builtin rule
    with its static SPEC-307 §3 declaration values."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_UB_CONFLICT_SUSPECT"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 100
        assert rule.severity.value == "error"
        # Static THREE-tier declaration (Q3-ii): the conflict-pair fact is
        # a deterministic combination, declared high — never a score.
        assert rule.confidence.value == "high"
        assert rule.enabled is True

    def test_suppression_is_the_mvp_fixed_declaration(self):
        rule = _rule()
        assert rule.suppression.key == ("code", "node_id")
        assert rule.suppression.window == "per_run"


class TestPrimitiveInterlock:
    """expected_evidence ↔ the primitive's expected_observations (ADR-0007
    item 5 互证, SPEC-307 §Phase3), validated by the genuine faults
    registry — the symbol SET is the interlock criterion (the #171
    lab-pack posture)."""

    def test_expected_evidence_names_the_state_observation_family(self):
        assert _rule().expected_evidence == (
            "rf.state_observed",
            "sec.state_observed",
        )
        assert set(_rule().expected_evidence) <= RF_EVENT_TYPES | {"sec.state_observed"}

    def test_fault_definition_interlocks_with_the_rule(self):
        fault = _primitive()
        assert fault.expected_observations == _rule().expected_evidence
        assert set(fault.expected_observations) == set(_rule().expected_evidence)
        assert fault.fault_type == FAULT_TYPE_UB_SLOT_CONFLICT
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_UB_SLOT_CONFLICT] == "SEC"


class TestMatchShape:
    """The declarative match pins the registered tuner snapshot event and
    exactly its payload keys (SPEC-307 §Phase3: tuner lock_state=unlocked
    + CauseRef 冲突对 + ub_assignments 表)."""

    def test_match_consumes_the_registered_tuner_snapshot(self):
        assert _rule().match.event_type == "rf.state_observed"
        assert _rule().match.event_type in RF_EVENT_TYPES

    def test_predicates_pin_exactly_the_registered_payload_keys(self):
        """Every predicate addresses a payload key the producer actually
        emits — verified against the registry's own payload validation,
        so the match can never reference a phantom key."""
        rule = _rule()
        predicate_fields = {
            predicate.field for predicate in rule.match.predicates
        }
        payload = dict(UB_CONFLICT_TUNER_SNAPSHOT)
        validate_payload(rule.match.event_type, payload)
        assert predicate_fields == {f"payload.{key}" for key in payload}

    def test_eq_predicates_pin_the_conflict_candidate_face(self):
        """The eq pins: the SPEC-303 §Phase3 恒定配对, the unlocked
        discriminator (SPEC-307 §Phase3) and the graded BER face (the
        runtime conflict branch is anomaly ⇒ severe — a plain unlocked
        face without a grade is NOT a conflict candidate)."""
        ops = {
            (predicate.field, predicate.op, predicate.value)
            for predicate in _rule().match.predicates
        }
        assert ("payload.source", "eq", "state_evaluator") in ops
        assert ("payload.confidence", "eq", "simulated") in ops
        assert ("payload.lock_state", "eq", "unlocked") in ops
        assert ("payload.ber_state", "eq", "severe") in ops

    def test_ungraded_unlocked_face_is_not_a_candidate(self):
        """缺失 ≠ 候选: the eq pin set holds on the conflict face and
        fails the ungraded unlocked face (no BER grade, no cause chain —
        e.g. the polarization-mismatch unlock, SPEC-620 §8)."""
        rule = _rule()
        conflict_record = _record_of(UB_CONFLICT_TUNER_SNAPSHOT)
        assert all(
            predicate.holds(conflict_record)
            for predicate in rule.match.predicates
        )
        ungraded_record = _record_of(UNGRADED_UNLOCKED_SNAPSHOT)
        validate_payload(rule.match.event_type, dict(UNGRADED_UNLOCKED_SNAPSHOT))
        assert not all(
            predicate.holds(ungraded_record)
            for predicate in rule.match.predicates
        )

    def test_grouping_and_window_shape(self):
        match = _rule().match
        assert match.group_by == ("node_id",)
        assert match.window is None


class TestCandidateNotFactDiscipline:
    """The anchor-gate honesty and the single-attributable-symptom
    discipline (SPEC-307 §6 / ADR-0007 item 5)."""

    def test_registry_conformant_record_without_anchor_yields_no_hit(self):
        """The registered tuner snapshot carries no diagnosis anchor state
        (SPEC-306 §6: no anchor, no candidate) — the honest inert-today
        posture of the frozen engine, asserted so a silent gate change
        cannot pass unnoticed (the #130 precedent face)."""
        from domain.diagnosis.engine import DiagnosisEvaluator

        record = _record_of(UB_CONFLICT_TUNER_SNAPSHOT)
        assert _rule().matches([record]) == ()
        outcome = DiagnosisEvaluator().evaluate(
            "sess-x",
            "run-x",
            (record,),
            load_builtin_rules(),
            now_utc_ms=1_700_000_000_000,
        )
        assert outcome.report.candidates == ()
        # The payload is registry-valid — the skip-with-warning face
        # stays silent too (no fabricated failure).
        assert outcome.report.warnings == ()

    def test_other_builtin_rules_stay_silent_on_the_tuner_snapshot(self):
        """Single attributable symptom across the additive boundary: no
        MVP/Phase 2 rule consumes the state-snapshot family."""
        record = _record_of(UB_CONFLICT_TUNER_SNAPSHOT)
        for rule in load_builtin_rules():
            if rule.rule_id == RULE_ID:
                continue
            assert rule.matches([record]) == ()

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
        assert placeholders <= set(UB_CONFLICT_TUNER_SNAPSHOT)


def _record_of(payload: dict) -> "ObservationRecord":
    from domain.diagnosis.engine import ObservationRecord

    return ObservationRecord(
        journal_seq=1,
        event_type="rf.state_observed",
        event_id="obs-ub-conflict-1",
        payload=dict(payload),
        node_id=str(payload["node_id"]),
    )
