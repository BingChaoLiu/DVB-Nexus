"""``fault_inactive`` — the #59 three-segment structured evidence chain (#56).

Traceability (SPEC-206 §7/§8/§9 + issue #59 Resolution):

- REQ-SIM-206-002 / SIM_VERIF_EVIDENCE_MISSING boundary: for THIS criterion
  evidence can only be missing on the BASELINE side (the recovery side's
  prepared-plan and journal facts are always available — absence of events
  there is a constructive fact, not a missing observation);
- segment 1 (baseline anchor): ``fault.injected``/``fault.activated``/
  ``fault.cleared`` all seen on the faulted run — incomplete lifecycle ⇒
  NOT_EVALUATED ⇒ INCONCLUSIVE;
- segment 2 (recovery prepared plan, 主承重件): the recovery run carries NO
  ``fault.injected`` for the fault — the prepare-validated plan binding
  makes every planned fault observable at run open, so the absence is the
  plan-exclusion declaration (structural, NOT observation absence);
- segment 3 (recovery no-recurrence audit): no ``fault.activated``/
  ``fault.applied`` for the fault on the recovery run — one appearing means
  an undeclared recurrence (engine violation) ⇒ FAIL;
- 换新 fault_id 重投: this criterion PASSES while the symptom criteria
  (mandatory) FAIL — symptom semantics are NOT duplicated here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from simulation.verification.engine import (
    RESULT_FAIL,
    RESULT_NOT_EVALUATED,
    RESULT_PASS,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    evaluate,
)

from tests.unit.simulation.verification import _verif_builders as v


def criterion_result(outcome, criterion_id: str = "sc-01"):
    return next(
        entry
        for entry in outcome.criteria
        if entry.criterion_id == criterion_id
    )


def fault_inactive_only() -> list[dict]:
    return [v.criterion("sc-01", kind="fault_inactive")]


class TestSegmentOneBaselineAnchor:
    """The lifecycle closure on the baseline run anchors the chain."""

    def test_closed_baseline_lifecycle_passes_segment_one(self):
        outcome = evaluate(v.baseline_verified_input(fault_inactive_only()))
        assert criterion_result(outcome).result == RESULT_PASS

    @pytest.mark.parametrize(
        "drop_event_type",
        ["fault.injected", "fault.activated", "fault.cleared"],
    )
    def test_missing_lifecycle_state_is_not_evaluated(self, drop_event_type):
        baseline = [
            event
            for event in v.closed_baseline_lifecycle()
            if event.event_type != drop_event_type
        ]
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(), baseline_fault_events=baseline
            )
        )
        entry = criterion_result(outcome)
        assert entry.result == RESULT_NOT_EVALUATED
        assert entry.reason_code == "SIM_VERIF_EVIDENCE_MISSING"
        assert drop_event_type in (entry.reason or "")
        assert outcome.verdict == VERDICT_INCONCLUSIVE

    def test_baseline_side_missing_is_the_only_missing_case(self):
        """SIM_VERIF_EVIDENCE_MISSING 适用边界 (#59): 恢复侧恒可得.

        A recovery run with zero fault events evaluates to PASS (the
        constructive absence), never NOT_EVALUATED.
        """
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(), recovery_fault_events=[]
            )
        )
        assert criterion_result(outcome).result == RESULT_PASS

    def test_empty_baseline_journal_is_missing_not_failing(self):
        """A wholly unknown baseline run anchors nothing — INCONCLUSIVE,
        never FAIL (排除空判：没有证据证明 F 曾被植入)."""
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(), baseline_fault_events=[]
            )
        )
        assert outcome.verdict == VERDICT_INCONCLUSIVE
        assert criterion_result(outcome).result == RESULT_NOT_EVALUATED

    def test_applied_is_not_required_on_the_baseline_anchor(self):
        """L1-only ``fault.applied`` may be omitted (state-level scenarios,
        SPEC-204 §8.1) — the anchor needs injected/activated/cleared."""
        baseline = [
            event
            for event in v.closed_baseline_lifecycle()
            if event.event_type != "fault.applied"
        ]
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(), baseline_fault_events=baseline
            )
        )
        assert criterion_result(outcome).result == RESULT_PASS


class TestSegmentTwoRecoveryPlanDeclaration:
    """主承重件: the recovery prepared plan must not declare the fault."""

    def test_recovery_still_declaring_the_fault_fails(self):
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(),
                recovery_fault_events=[
                    v.fault_event(
                        "fault.injected", journal_seq=110, run_id=v.RECOVERY
                    )
                ],
            )
        )
        entry = criterion_result(outcome)
        assert entry.result == RESULT_FAIL
        assert outcome.verdict == VERDICT_FAIL
        assert "plan" in (entry.reason or "").lower() or (
            "declared" in (entry.reason or "").lower()
        )

    def test_no_recovery_injection_is_the_structural_positive(self):
        """构造性无事件 ≠ 观测缺失（§6 指针句 / #59 裁决）: an empty
        recovery event list is the plan-exclusion declaration — PASS."""
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(), recovery_fault_events=[]
            )
        )
        assert criterion_result(outcome).result == RESULT_PASS
        # The evidence records the audited absence explicitly.
        kinds = {ref["kind"] for ref in criterion_result(outcome).evidence_refs}
        assert "journal_absence" in kinds


class TestSegmentThreeRecurrenceAudit:
    """未声明却出现 = 引擎违约 ⇒ FAIL."""

    @pytest.mark.parametrize("event_type", ["fault.activated", "fault.applied"])
    def test_undeclared_recurrence_fails(self, event_type):
        outcome = evaluate(
            v.baseline_verified_input(
                fault_inactive_only(),
                recovery_fault_events=[
                    v.fault_event(event_type, journal_seq=120, run_id=v.RECOVERY)
                ],
            )
        )
        entry = criterion_result(outcome)
        assert entry.result == RESULT_FAIL
        assert outcome.verdict == VERDICT_FAIL

    def test_recovered_stream_with_no_events_passes_all_segments(self):
        outcome = evaluate(v.baseline_verified_input(fault_inactive_only()))
        assert outcome.verdict == VERDICT_PASS


class TestFaultIdentitySwap:
    """#59: learner 换新 fault_id 重投同种故障 — 本判据 PASS，症状兜底."""

    def test_new_fault_id_passes_this_criterion_but_symptom_fails(self):
        # The recovery stream still carries a continuity error (the
        # re-injected fault under a fresh identity), while this criterion's
        # original fault id never reappears.
        criteria = [
            v.criterion("sc-01", kind="fault_inactive"),
            v.criterion("sc-02", kind="cc_continuous"),
        ]
        outcome = evaluate(
            v.baseline_verified_input(
                criteria,
                recovery_observations=[v.clean_coverage()]
                + v.clean_mapping_program()
                + [v.cc_error(seq=402)],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS
        assert criterion_result(outcome, "sc-02").result == RESULT_FAIL
        assert outcome.verdict == VERDICT_FAIL
