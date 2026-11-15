"""SPEC-206 三态判定 — the §4 verdict semantics and §9 triage matrix (#56).

Traceability:

- REQ-SIM-206-002  mandatory evidence missing ⇒ INCONCLUSIVE
- REQ-SIM-206-003  every criterion carries a result or an explicit
  NOT_EVALUATED reason (no silent skips)
- REQ-SIM-206-001  UI state without evidence can never PASS (AC-206-01)
- REQ-SIM-206-005  replay determinism: same input ⇒ same output, no wall
  clock, no randomness (the operational timestamp is injectable upstream)
- §9 matrix: all-PASS / single-FAIL / evidence-missing
- SIM_VERIF_CRITERION_INVALID: unknown kinds are refused (§8 row 1)

Unit layer: pure evaluation over the journal-read record shapes (see
``_verif_builders`` — the same faces the service feeds from the real
journal, which is what the replay-equivalence test rides).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_VERIF_CRITERION_INVALID,
    VerificationCriterionInvalidError,
)
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


def criterion_result(outcome, criterion_id: str):
    return next(
        entry
        for entry in outcome.criteria
        if entry.criterion_id == criterion_id
    )


class TestCriterionKindClosedEnum:
    """§7: the six MVP kinds are a closed enum; unknown kinds are refused."""

    @pytest.mark.parametrize(
        "kind",
        [
            "fault_inactive",
            "psi_pat_valid",
            "psi_pmt_valid",
            "pat_pmt_mapping_valid",
            "cc_continuous",
            "no_unexpected_cc_error",
        ],
    )
    def test_all_six_kinds_are_evaluable(self, kind):
        criteria = [v.criterion("sc-01", kind=kind)]
        outcome = evaluate(v.baseline_verified_input(criteria))
        assert criterion_result(outcome, "sc-01").result in {
            RESULT_PASS,
            RESULT_FAIL,
            RESULT_NOT_EVALUATED,
        }

    def test_unknown_kind_is_rejected_with_the_registered_code(self):
        outcome_input = v.baseline_verified_input(
            [v.criterion("sc-01", kind="ui_state_green")]
        )
        with pytest.raises(VerificationCriterionInvalidError) as excinfo:
            evaluate(outcome_input)
        assert excinfo.value.code == SIM_VERIF_CRITERION_INVALID

    def test_fault_inactive_without_fault_id_is_rejected(self):
        outcome_input = v.baseline_verified_input(
            [v.criterion("sc-01", kind="fault_inactive", fault_id=None)]
        )
        with pytest.raises(VerificationCriterionInvalidError):
            evaluate(outcome_input)


class TestTriageMatrix:
    """§9 三态矩阵：全 PASS / 单 mandatory FAIL / 证据缺失 INCONCLUSIVE."""

    def test_all_mandatory_pass_yields_pass(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="fault_inactive"),
                    v.criterion("sc-02", kind="cc_continuous"),
                    v.criterion("sc-03", kind="psi_pat_valid"),
                ]
            )
        )
        assert outcome.verdict == VERDICT_PASS
        assert all(entry.result == RESULT_PASS for entry in outcome.criteria)

    def test_single_mandatory_fail_yields_fail(self):
        # The recovery run still declares the fault (fault.injected present)
        # — fault_inactive fails outright (§9: 恢复 Run plan 含该 fault_id).
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="fault_inactive"),
                    v.criterion("sc-02", kind="cc_continuous"),
                ],
                recovery_fault_events=[
                    v.fault_event(
                        "fault.injected",
                        journal_seq=110,
                        run_id=v.RECOVERY,
                    )
                ],
            )
        )
        assert outcome.verdict == VERDICT_FAIL
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL
        assert criterion_result(outcome, "sc-02").result == RESULT_PASS

    def test_mandatory_evidence_missing_yields_inconclusive(self):
        # No recovery observations at all: the observation criteria are
        # honestly NOT_EVALUATED — "没证据" is a third conclusion (§4).
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="fault_inactive"),
                    v.criterion("sc-02", kind="cc_continuous"),
                ],
                recovery_observations=[],
            )
        )
        assert outcome.verdict == VERDICT_INCONCLUSIVE
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS
        missing = criterion_result(outcome, "sc-02")
        assert missing.result == RESULT_NOT_EVALUATED
        assert missing.reason_code == "SIM_VERIF_EVIDENCE_MISSING"

    def test_fail_takes_precedence_over_inconclusive(self):
        """§4: 任一 mandatory FAIL ⇒ 总体 FAIL（先于证据缺失）。"""
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="fault_inactive"),
                    v.criterion("sc-02", kind="cc_continuous"),
                ],
                recovery_fault_events=[
                    v.fault_event(
                        "fault.injected", journal_seq=110, run_id=v.RECOVERY
                    )
                ],
                recovery_observations=[],
            )
        )
        assert outcome.verdict == VERDICT_FAIL

    def test_non_mandatory_failure_does_not_gate_the_verdict(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="fault_inactive"),
                    v.criterion("sc-99", kind="cc_continuous", mandatory=False),
                ],
                # Unexpected CC error on the recovery stream (an
                # observation fact — the recovery plan declares nothing).
                recovery_observations=[v.clean_coverage(), v.cc_error()],
            )
        )
        assert criterion_result(outcome, "sc-99").result == RESULT_FAIL
        assert outcome.verdict == VERDICT_PASS

    def test_incomplete_recovery_run_is_upstream_incomplete(self):
        """§8: 候选恢复 Run 未完成走 §4 mandatory 证据缺失既有规则."""
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="fault_inactive")],
                recovery_run_completed=False,
            )
        )
        assert outcome.verdict == VERDICT_INCONCLUSIVE
        for entry in outcome.criteria:
            assert entry.result == RESULT_NOT_EVALUATED
            assert entry.reason_code == "SIM_VERIF_EVIDENCE_MISSING"


class TestCriterionAccountability:
    """REQ-SIM-206-003: results carry evidence refs or explicit reasons."""

    def test_every_pass_carries_evidence_refs(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="fault_inactive")]
            )
        )
        entry = criterion_result(outcome, "sc-01")
        assert entry.result == RESULT_PASS
        assert entry.evidence_refs, "a PASS verdict without evidence is empty"
        kinds = {ref["kind"] for ref in entry.evidence_refs}
        assert "journal" in kinds

    def test_not_evaluated_always_names_the_reason(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-02", kind="cc_continuous")],
                recovery_observations=[],
            )
        )
        entry = criterion_result(outcome, "sc-02")
        assert entry.result == RESULT_NOT_EVALUATED
        assert entry.reason_code
        assert entry.reason

    def test_evidence_refs_use_journal_seq_identities(self):
        """裁定：verdict evidence 按 journal_seq/ID 引用（经注入读脸）."""
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="fault_inactive")]
            )
        )
        refs = [
            ref
            for entry in outcome.criteria
            for ref in entry.evidence_refs
            if ref["kind"] == "journal"
        ]
        assert refs
        for ref in refs:
            assert isinstance(ref["journal_seq"], int)
            assert ref["journal_seq"] >= 1
            assert ref["event_type"].startswith("fault.")


class TestUiStateIsNeverEvidence:
    """REQ-SIM-206-001 (AC-206-01): UI state alone can never PASS."""

    def test_ui_state_with_no_evidence_is_inconclusive(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-02", kind="cc_continuous")],
                recovery_observations=[],
                ui_state={"verification_panel": "green", "score": 100},
            )
        )
        assert outcome.verdict == VERDICT_INCONCLUSIVE

    def test_ui_state_does_not_flip_a_failing_verdict(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="fault_inactive")],
                recovery_fault_events=[
                    v.fault_event(
                        "fault.injected", journal_seq=110, run_id=v.RECOVERY
                    )
                ],
                ui_state={"verification_panel": "green"},
            )
        )
        assert outcome.verdict == VERDICT_FAIL


class TestBaselineReuse:
    """REQ-SIM-206-004 (§5 item 4 / §8 row 4): verifying the baseline
    against itself is INCONCLUSIVE — a run cannot prove its own repair."""

    def test_candidate_equal_to_baseline_is_inconclusive_with_reason(self):
        from simulation.errors import SIM_VERIF_BASELINE_REUSED

        spec = v.baseline_verified_input(
            [v.criterion("sc-01", kind="fault_inactive")]
        )
        reused = type(spec)(
            **{
                **{field: getattr(spec, field) for field in spec.__dataclass_fields__},
                "recovery_run_id": spec.baseline_run_id,
            }
        )
        outcome = evaluate(reused)
        assert outcome.verdict == VERDICT_INCONCLUSIVE
        for entry in outcome.criteria:
            assert entry.result == RESULT_NOT_EVALUATED
            assert entry.reason_code == SIM_VERIF_BASELINE_REUSED


class TestDeterminism:
    """REQ-SIM-206-005: same input replays to the identical verdict."""

    def test_same_input_replays_identically(self):
        criteria = [
            v.criterion("sc-01", kind="fault_inactive"),
            v.criterion("sc-02", kind="cc_continuous"),
            v.criterion("sc-03", kind="pat_pmt_mapping_valid"),
        ]
        first = evaluate(v.baseline_verified_input(criteria))
        second = evaluate(v.baseline_verified_input(criteria))
        assert first.verdict == second.verdict
        assert first.criteria == second.criteria
        assert first.evidence_refs == second.evidence_refs
        assert first.summary == second.summary

    def test_engine_carries_no_wall_clock(self):
        """The outcome structure has no self-sourced timestamp: the only
        operational time in the pipeline is injected by the service
        (verified_at_utc_ms) — the engine result is replay-stable."""
        outcome = evaluate(
            v.baseline_verified_input([v.criterion("sc-01")])
        )
        dumped = repr(outcome)
        assert "utc_ms" not in dumped
