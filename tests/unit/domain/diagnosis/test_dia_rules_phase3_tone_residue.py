"""TONE_RESIDUE_SUSPECT builtin-rule declaration tests (ticket #168,
SPEC-307 §Phase3 candidate 1 — 「LNB tone 残留 / 供电异常」).

The rule consumes the tuner snapshot ``rf.state_observed`` (SPEC-303
§Phase3, registered by #164; the payload key set is the #164 producer
contract frozen by the strict registry validation) and mirrors the
``TONE_RESIDUE`` primitive's ``expected_observations`` symbol set —
the ADR-0007 item 5 互证, now against the state-layer primitives (#163).

Mechanical honesty (候选 ≠ 事实 discipline, asserted not hidden): the
engine's SPEC-306 §6 evidence gate demands an anchor state the
``rf.state_observed`` registered key set cannot carry (no MVP triple —
exact-key snapshot shape — and the state namespaces are not the Phase 2
evidence family), so the rule stays loadable but unfired until a Phase 3
evidence-anchor path lands (the #130 → #138 precedent posture; the
declaration itself is the deliverable: it pins WHICH event and WHICH
predicate faces constitute the candidate).

Predicate-face honesty (the frozen §4 op set is {eq, gt, lt, exists}):
the declarable faces are the constant observation axes
(``state_evaluator``/``simulated`` — the SPEC-303 §Phase3 恒定配对) and
the graded BER face.  The #161 frozen producer semantics put every
fault-chain tuner snapshot (tone mismatch / short / UB conflict /
anomalous feeder) at ``ber_state="severe"`` — the ``elevated`` arm of
the SPEC-307 §Phase3 "ber_state=elevated/severe" OR-face is the
no-fault protection-band grade (SPEC-620 §7 rule 3), unreachable for
the TONE_RESIDUE chain, and a string-valued OR is not expressible in
the frozen op set (ticket #168 REPORT deviation).  The CauseRef-array
face (``causes[*].node_id`` 指向 lnb) and the cross-event
``sec.state_observed`` faces (tone 双字段 / ``ub_assignments`` 表) are
likewise outside the finite predicate set — they ride the
``expected_evidence`` symbol set and the #171 判据互锁, not the
match predicates.

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.rules import load_builtin_rules
from domain.diagnosis.rules.model import DiagnosticRule
from domain.observation.registry import (
    RF_EVENT_TYPES,
    RF_TUNER_SNAPSHOT_KEYS,
    validate_payload,
)
from faults.definition import FaultActivation, FaultDefinition
from faults.registry import (
    FAULT_TYPE_TONE_RESIDUE,
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)

RULE_ID = "DIA-TONE-RESIDUE-SUSPECT"

#: The registered ``rf.state_observed`` payload shape at the TONE_RESIDUE
#: 失锁 face (the #164 producer contract; the 850 MHz offset arithmetic:
#: low-band request 11095000 kHz against the residue-stuck high LO
#: 10600000 kHz → delivered-arm IF 495000 kHz, ≫ LO drift ±3 MHz —
#: SPEC-621 附录 A 尾段).  The integration suite proves the REAL emitted
#: payloads satisfy the shape and that the predicates hold on the 错锁
#: face too.
TONE_RESIDUE_TUNER_SNAPSHOT = {
    "node_id": "tuner-0",
    "health": "error",
    "causes": [{"node_id": "lnb-0"}],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "unlocked",
    "if_frequency_khz": 495000,
    "ber_state": "severe",
    "locked_transponder_id": None,
    "stale": True,
}

#: The 错锁 face of the same chain (locked onto the delivered arm's
#: transponder, still severe — SPEC-620 §7 错锁组合事实, AC-620-03).
TONE_RESIDUE_WRONG_LOCK_SNAPSHOT = {
    "node_id": "tuner-0",
    "health": "error",
    "causes": [{"node_id": "lnb-0"}],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "locked",
    "if_frequency_khz": 1470000,
    "ber_state": "severe",
    "locked_transponder_id": "high@12070000",
    "stale": False,
}


def _rule() -> DiagnosticRule:
    return next(rule for rule in load_builtin_rules() if rule.rule_id == RULE_ID)


def _primitive() -> FaultDefinition:
    """A real TONE_RESIDUE FaultDefinition whose expected_observations
    are the paired rule's expected_evidence (the 互证 under test)."""
    return FaultDefinition(
        fault_id="fd000000-0000-4000-8000-000000000163",
        fault_type=FAULT_TYPE_TONE_RESIDUE,
        target_id="lnb-0",
        parameters={"tone_actual": "continuous"},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=_rule().expected_evidence,
        layer=LAYER_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE],
    )


class TestDeclarationIdentity:
    """The SPEC-307 §Phase3 candidate lands as a registered builtin rule
    with its static SPEC-307 §3 declaration values."""

    def test_rule_is_registered_by_the_production_loader(self):
        assert _rule() is not None

    def test_static_declaration_values(self):
        rule = _rule()
        assert rule.code == "DIAG_TONE_RESIDUE_SUSPECT"
        assert rule.rule_version == "1.0.0"
        assert rule.priority == 90
        assert rule.severity.value == "error"
        # Static THREE-tier declaration (Q3-ii): the state-snapshot
        # combination face is a declarative root-cause suspicion, never a
        # computed score.
        assert rule.confidence.value == "medium"
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
        assert fault.fault_type == FAULT_TYPE_TONE_RESIDUE
        assert validate_fault_definition(fault) == ()

    def test_declared_layer_interlocks_with_the_registry(self):
        assert LAYER_BY_FAULT_TYPE[FAULT_TYPE_TONE_RESIDUE] == "RF"


class TestMatchShape:
    """The declarative match pins the registered tuner snapshot event and
    exactly its payload keys (SPEC-307 §Phase3: 消费 rf.state_observed —
    tuner ber_state 升档 + CauseRef 指向 lnb)."""

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
        payload = dict(TONE_RESIDUE_TUNER_SNAPSHOT)
        validate_payload(rule.match.event_type, payload)
        assert predicate_fields == {f"payload.{key}" for key in payload}
        assert set(payload) == set(RF_TUNER_SNAPSHOT_KEYS)

    def test_predicates_hold_on_both_symptom_faces(self):
        """The eq face set (constant axes + the graded BER) holds on the
        失锁 AND the 错锁 face of the chain — the declaration does not
        bake in one lock outcome (SPEC-620 §7: 失锁或错锁)."""
        rule = _rule()
        for payload in (
            TONE_RESIDUE_TUNER_SNAPSHOT,
            TONE_RESIDUE_WRONG_LOCK_SNAPSHOT,
        ):
            validate_payload(rule.match.event_type, dict(payload))
            record = _record_of(payload)
            assert all(
                predicate.holds(record) for predicate in rule.match.predicates
            )

    def test_eq_predicates_are_the_invariant_candidate_faces(self):
        """The eq pins: the SPEC-303 §Phase3 恒定配对 (state_evaluator +
        simulated — registry-enforced constants) and the graded BER face
        (anomaly ⇒ severe per the #161 frozen vectors; see the module
        docstring for the elevated-arm deviation)."""
        ops = {
            (predicate.field, predicate.op, predicate.value)
            for predicate in _rule().match.predicates
        }
        assert ("payload.source", "eq", "state_evaluator") in ops
        assert ("payload.confidence", "eq", "simulated") in ops
        assert ("payload.ber_state", "eq", "severe") in ops

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
        from domain.diagnosis.engine import DiagnosisEvaluator, ObservationRecord

        record = _record_of(TONE_RESIDUE_TUNER_SNAPSHOT)
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
        record = _record_of(TONE_RESIDUE_TUNER_SNAPSHOT)
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
        assert placeholders <= set(TONE_RESIDUE_TUNER_SNAPSHOT)


def _record_of(payload: dict) -> "ObservationRecord":
    from domain.diagnosis.engine import ObservationRecord

    return ObservationRecord(
        journal_seq=1,
        event_type="rf.state_observed",
        event_id="obs-tone-residue-1",
        payload=dict(payload),
        node_id=str(payload["node_id"]),
    )
