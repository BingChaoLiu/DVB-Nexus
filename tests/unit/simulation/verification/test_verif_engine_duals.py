"""§6 四对偶观测语义区分 — each dual is a distinct evaluation outcome (#56).

混淆即实现缺陷 (SPEC-206 §6): these four tests are the acceptance gate for
the observation-side criteria. The pairs:

1. 无观测 vs 干净观测   — zero observations ⇒ NOT_EVALUATED (mandatory ⇒
   INCONCLUSIVE); clean observations ⇒ PASS. Never "no news = clean".
2. 分析器不支持 vs 协议违规 — records that lack the capability field are
   NOT_EVALUATED (the analyzer could not check); records with an explicit
   violating value are FAIL.
3. 缺失值 vs 零值       — a missing field is unknown (NOT_EVALUATED); an
   explicit 0 is a fact (here: program_map_pid == 0 is an INVALID mapping —
   PAT cannot declare itself — so zero FAILS while absence does not).
4. 预期不连续 vs 意外 CC 错误 — a continuity error covered by the declared
   fault expectations passes ``no_unexpected_cc_error`` while failing
   ``cc_continuous``; an uncovered error fails both.

Unit layer: pure evaluation over the builder records.
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


def criterion_result(outcome, criterion_id: str):
    return next(
        entry
        for entry in outcome.criteria
        if entry.criterion_id == criterion_id
    )


class TestDualOneNoObservationVsClean:
    """无观测 ≠ 干净观测: mandatory + no observations ⇒ INCONCLUSIVE."""

    @pytest.mark.parametrize(
        "kind",
        ["psi_pat_valid", "psi_pmt_valid", "cc_continuous", "no_unexpected_cc_error"],
    )
    def test_no_observations_is_not_a_pass(self, kind):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind=kind)], recovery_observations=[]
            )
        )
        entry = criterion_result(outcome, "sc-01")
        assert entry.result == RESULT_NOT_EVALUATED
        assert outcome.verdict == VERDICT_INCONCLUSIVE

    def test_clean_observations_confirm_validity(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [
                    v.criterion("sc-01", kind="psi_pat_valid"),
                    v.criterion("sc-02", kind="psi_pmt_valid"),
                    v.criterion("sc-03", kind="cc_continuous"),
                ]
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS
        assert criterion_result(outcome, "sc-02").result == RESULT_PASS
        assert criterion_result(outcome, "sc-03").result == RESULT_PASS
        assert outcome.verdict == VERDICT_PASS

    def test_pmt_family_clean_via_mapping_program(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="psi_pmt_valid")],
                recovery_observations=v.clean_mapping_program(),
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS


class TestDualTwoUnsupportedVsViolation:
    """分析器不支持 ≠ 协议违规: capability-less records never fail."""

    def test_psi_record_without_present_field_is_not_a_violation(self):
        # The analyzer saw a PAT but could not evaluate presence — that is
        # an analyzer gap, not a protocol violation.
        blind = v.observation(
            "ts.psi_section_observed",
            {
                "source": "tsduck",
                "confidence": "parsed",
                "section": "PAT",
                "packet_index": 100,
                # no 'present', no 'crc_valid'
            },
            journal_seq=210,
            pid=v.PSI_PID,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="psi_pat_valid")],
                recovery_observations=[blind],
            )
        )
        entry = criterion_result(outcome, "sc-01")
        assert entry.result == RESULT_NOT_EVALUATED
        assert outcome.verdict == VERDICT_INCONCLUSIVE

    def test_explicit_violation_is_a_fail(self):
        broken = v.observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PAT",
                "present": False,
                "packet_index": 100,
            },
            journal_seq=211,
            pid=v.PSI_PID,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="psi_pat_valid")],
                recovery_observations=[broken],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL
        assert outcome.verdict == VERDICT_FAIL

    def test_batch_record_without_count_field_is_unknown_not_clean(self):
        # Coverage without an error count: the analyzer did not report
        # counts — unknown, distinct from an explicit zero.
        coverage_unknown = v.observation(
            "ts.packet_batch_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "packet_count": 500,
                # no continuity_error_count
            },
            journal_seq=302,
            pid=None,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="cc_continuous")],
                recovery_observations=[coverage_unknown],
            )
        )
        # With coverage and zero per-error records the stream is confirmed
        # continuous — the UNKNOWN count does not fabricate a violation,
        # and the per-error stream stays the authority.
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS

    def test_batch_record_with_nonzero_count_fails_even_without_details(self):
        counted = v.observation(
            "ts.packet_batch_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "packet_count": 500,
                "continuity_error_count": 2,
            },
            journal_seq=303,
            pid=None,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="cc_continuous")],
                recovery_observations=[counted],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL


class TestDualThreeMissingValueVsZero:
    """缺失值 ≠ 零值: absent ⇒ unknown; explicit zero is a FACT."""

    def test_missing_program_map_pid_is_unknown(self):
        pat_without_mapping = v.observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PAT",
                "present": True,
                "crc_valid": True,
                "packet_index": 100,
                # no actual_program_map_pid
            },
            journal_seq=220,
            pid=v.PSI_PID,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="pat_pmt_mapping_valid")],
                recovery_observations=[pat_without_mapping],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_NOT_EVALUATED

    def test_explicit_zero_program_map_pid_is_an_invalid_mapping(self):
        pat_zero = v.observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PAT",
                "present": True,
                "crc_valid": True,
                "actual_program_map_pid": 0,  # PAT cannot declare itself
                "packet_index": 100,
            },
            journal_seq=221,
            pid=v.PSI_PID,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="pat_pmt_mapping_valid")],
                recovery_observations=[pat_zero],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL
        assert outcome.verdict == VERDICT_FAIL


class TestDualFourExpectedVsUnexpectedCc:
    """预期不连续（expected_observations 覆盖）≠ 意外 CC 错误."""

    def test_declared_error_tolerated_by_no_unexpected_but_not_by_continuous(
        self,
    ):
        # The baseline plan declared ts.continuity_error for this fault —
        # a recovery CC error covered by that declaration does not violate
        # no_unexpected_cc_error, but it IS a discontinuity.
        criteria = [
            v.criterion("sc-01", kind="cc_continuous", mandatory=False),
            v.criterion("sc-02", kind="no_unexpected_cc_error", mandatory=False),
        ]
        # The builders' baseline plan declares ts.continuity_error.
        outcome = evaluate(
            v.baseline_verified_input(
                criteria,
                recovery_observations=[v.clean_coverage()] + [v.cc_error()],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL
        assert criterion_result(outcome, "sc-02").result == RESULT_PASS

    def test_unexpected_error_fails_both(self):
        # Baseline declared NO continuity expectation (different fault
        # family) — a recovery CC error is unexpected for both criteria.
        baseline = [
            v.fault_event(
                "fault.injected",
                journal_seq=10,
                expected_observations=("ts.psi_section_observed",),
            ),
            v.fault_event("fault.activated", journal_seq=11),
            v.fault_event("fault.cleared", journal_seq=13),
        ]
        criteria = [
            v.criterion("sc-01", kind="cc_continuous", mandatory=False),
            v.criterion("sc-02", kind="no_unexpected_cc_error", mandatory=False),
        ]
        outcome = evaluate(
            v.baseline_verified_input(
                criteria,
                baseline_fault_events=baseline,
                recovery_observations=[v.clean_coverage()] + [v.cc_error()],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL
        assert criterion_result(outcome, "sc-02").result == RESULT_FAIL

    def test_declared_expectation_requires_the_baseline_vocabulary(self):
        """The coverage set comes from the baseline plan declarations —
        an empty baseline means every recovery CC error is unexpected."""
        criteria = [
            v.criterion("sc-01", kind="no_unexpected_cc_error", mandatory=False)
        ]
        outcome = evaluate(
            v.baseline_verified_input(
                criteria,
                baseline_fault_events=[],
                recovery_observations=[v.clean_coverage()] + [v.cc_error()],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL


class TestMappingValidityEdges:
    """pat_pmt_mapping_valid: the PAT→PMT contract around the duals."""

    def test_declared_pmt_present_mapping_passes(self):
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="pat_pmt_mapping_valid")]
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_PASS

    def test_declared_pmt_absent_with_other_pmt_observed_fails(self):
        # PAT declares 0x1000 but the only PMT observed sits on 0x1002 —
        # the observed mapping contradicts the declaration (mismatch
        # symptom, ADR-0007 item 5 single-symptom family).
        pat = v.clean_mapping_program()[0]
        wrong_pmt = v.observation(
            "ts.psi_section_observed",
            {
                "source": "internal_parser",
                "confidence": "parsed",
                "section": "PMT",
                "present": True,
                "crc_valid": True,
                "packet_index": 140,
            },
            journal_seq=203,
            pid=0x1002,
        )
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="pat_pmt_mapping_valid")],
                recovery_observations=[pat, wrong_pmt],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_FAIL

    def test_no_pmt_observations_at_all_is_not_evaluated(self):
        """无观测 ≠ 干净: PAT declares 0x1000 but the analyzer never
        observed any PMT — unknown, not a violation."""
        pat_only = v.clean_mapping_program()[0]
        outcome = evaluate(
            v.baseline_verified_input(
                [v.criterion("sc-01", kind="pat_pmt_mapping_valid")],
                recovery_observations=[pat_only],
            )
        )
        assert criterion_result(outcome, "sc-01").result == RESULT_NOT_EVALUATED
