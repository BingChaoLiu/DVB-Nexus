"""SPEC-307 §6 builtin-rule interlock unit tests (ticket #55,
REQ-DIA-307-003 + the §5 ordering matrix on the static ruleset).

The four builtin rules run against the four shared-fixture fault
observation programs (ADR-0007 item 5 single-symptom signatures,
``tests._support.diagnosis_fixtures``) through the REAL #54 evaluator:
one fault → exactly one candidate from the paired rule, never a second
rule's (single attributable symptom). ``expected_evidence`` is
cross-checked against the real ``FaultDefinition.expected_observations``
(interlock, ADR-0007 item 5) with the genuine faults-registry
validation.

Pure logic: in-memory records only — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.engine import DiagnosisEvaluator
from domain.diagnosis.rules import (
    DiagnosticRule,
    MatchSpec,
    load_builtin_rules,
)
from faults.registry import validate_fault_definition

from tests._support.diagnosis_fixtures import (
    FIXTURE_FAULT_TYPES,
    builtin_fixture_rules,
    fault_observation_program,
    fixture_fault_definition,
    fixture_rule_for_fault,
)

EVALUATOR = DiagnosisEvaluator()

#: SPEC-307 §6 pairing: one rule per MVP fault type.
PAIRING = {
    "PAT_MISSING": "DIA-PAT-MISSING",
    "PMT_INVALID_CRC": "DIA-PMT-CRC-BAD",
    "CC_DISCONTINUITY": "DIA-CC-DISCONTINUITY",
    "PMT_PID_MISMATCH": "DIA-PMT-PID-MISMATCH",
}


def _rule_for_fault(fault_type: str) -> DiagnosticRule:
    rule_id = PAIRING[fault_type]
    return next(rule for rule in load_builtin_rules() if rule.rule_id == rule_id)


class TestFourRulesAgainstFourFaults:
    """SPEC-307 §9 row 4: rules × fault-injection vectors → the paired
    candidate (shared fixture with SPEC-306 §9)."""

    @pytest.mark.parametrize("fault_type", FIXTURE_FAULT_TYPES)
    def test_one_fault_program_yields_exactly_the_paired_candidate(
        self, fault_type
    ):
        rules = load_builtin_rules()
        outcome = EVALUATOR.evaluate(
            "sess-x", "run-x", fault_observation_program(fault_type), rules,
            now_utc_ms=1_700_000_000_000,
        )
        rule = _rule_for_fault(fault_type)
        assert len(outcome.report.candidates) == 1
        candidate = outcome.report.candidates[0]
        assert candidate.code == rule.code
        assert candidate.rule_id == rule.rule_id
        assert candidate.rule_version == rule.rule_version
        assert candidate.priority == rule.priority
        assert candidate.severity.value == rule.severity.value
        assert candidate.confidence.value == rule.confidence.value

    @pytest.mark.parametrize("fault_type", FIXTURE_FAULT_TYPES)
    def test_other_fault_programs_do_not_trigger_the_rule(self, fault_type):
        """Single attributable symptom: the paired rule fires on its own
        fault's program ONLY."""
        rule = _rule_for_fault(fault_type)
        others = tuple(
            record
            for other in FIXTURE_FAULT_TYPES
            if other != fault_type
            for record in fault_observation_program(other)
        )
        assert rule.matches(others) == ()

    def test_all_four_programs_together_yield_four_candidates(self):
        records = tuple(
            record
            for fault_type in FIXTURE_FAULT_TYPES
            for record in fault_observation_program(fault_type)
        )
        outcome = EVALUATOR.evaluate(
            "sess-x", "run-x", records, load_builtin_rules(),
            now_utc_ms=1_700_000_000_000,
        )
        assert [candidate.code for candidate in outcome.report.candidates] == [
            "DIAG_PAT_MISSING",
            "DIAG_PMT_CRC_BAD",
            "DIAG_CC_DISCONTINUITY",
            "DIAG_PMT_PID_MISMATCH",
        ]


class TestExpectedEvidenceInterlock:
    """SPEC-307 §6: expected_evidence ↔ FaultDefinition
    expected_observations (ADR-0007 item 5), validated by the genuine
    faults registry."""

    @pytest.mark.parametrize("fault_type", FIXTURE_FAULT_TYPES)
    def test_interlock_holds_for_every_pairing(self, fault_type):
        real_rule = _rule_for_fault(fault_type)
        fixture_rule = fixture_rule_for_fault(fault_type)
        fault = fixture_fault_definition(fault_type)
        assert real_rule.expected_evidence == fixture_rule.expected_evidence
        assert fault.expected_observations == real_rule.expected_evidence
        assert fault.fault_type == fault_type
        assert validate_fault_definition(fault) == ()

    def test_every_rule_declares_at_least_one_registered_evidence_code(self):
        for rule in load_builtin_rules():
            assert rule.expected_evidence
            assert all(code.startswith("ts.") for code in rule.expected_evidence)

    def test_signal_semantics_per_rule(self):
        """The declarative predicates pin the ADR-0007 item 5
        single-symptom signatures (SPEC-307 §6: 信号语义以 ADR-0007 §5
        为权威): PAT window missing; persistent CRC failure (count
        window); relative CC offset; PAT repointed at an orphan PMT."""
        rules = {rule.rule_id: rule for rule in load_builtin_rules()}
        pat = rules["DIA-PAT-MISSING"].match
        assert pat.event_type == "ts.psi_section_observed"
        assert ("payload.present", "eq", False) in _predicates(pat)
        crc = rules["DIA-PMT-CRC-BAD"].match
        assert crc.window is not None
        assert crc.window.aggregation == "count"
        assert crc.window.min_count == 2  # persistent mode: stable symptom
        assert ("payload.crc_valid", "eq", False) in _predicates(crc)
        cc = rules["DIA-CC-DISCONTINUITY"].match
        assert cc.event_type == "ts.continuity_error"
        assert ("payload.expected_cc", "exists", None) in _predicates(cc)
        assert ("payload.actual_cc", "exists", None) in _predicates(cc)
        mismatch = rules["DIA-PMT-PID-MISMATCH"].match
        assert (
            "payload.expected_program_map_pid",
            "exists",
            None,
        ) in _predicates(mismatch)
        assert (
            "payload.actual_program_map_pid",
            "exists",
            None,
        ) in _predicates(mismatch)


def _predicates(match: MatchSpec) -> tuple:
    return tuple(
        (predicate.field, predicate.op, predicate.value)
        for predicate in match.predicates
    )


class TestOrderingMatrix:
    """SPEC-307 §5: priority asc → severity desc → code lexicographic,
    no preemption — exercised with REAL DiagnosticRule objects (the #54
    suite pins the same matrix via fixture rules)."""

    def _rule(self, *, rule_id, code, priority, severity) -> DiagnosticRule:
        return DiagnosticRule(
            rule_id=rule_id,
            rule_version="1.0.0",
            code=code,
            priority=priority,
            severity=severity,
            confidence="high",
            title="t",
            summary_template="hit {packet_index}",
            match=MatchSpec(event_type="ts.continuity_error"),
        )

    def _cc_hit(self, seq: int):
        from tests._support.diagnosis_fixtures import observation_record

        return observation_record(
            journal_seq=seq,
            event_type="ts.continuity_error",
            payload={
                "source": "internal_parser",
                "confidence": "parsed",
                "pid": 256,
                "expected_cc": 1,
                "actual_cc": 2,
                "artifact_id": f"a-{seq}",
                "packet_index": seq,
            },
            pid=256,
        )

    def test_priority_tie_breaks_by_severity_then_code(self):
        rules = (
            self._rule(rule_id="R-A", code="DIAG_B", priority=5, severity="warning"),
            self._rule(rule_id="R-B", code="DIAG_D", priority=5, severity="critical"),
            self._rule(rule_id="R-C", code="DIAG_C", priority=5, severity="error"),
            self._rule(rule_id="R-E", code="DIAG_A", priority=5, severity="critical"),
        )
        outcome = EVALUATOR.evaluate(
            "sess-x", "run-x", (self._cc_hit(1),), rules,
            now_utc_ms=1_700_000_000_000,
        )
        # Critical pair first in code-lexicographic order, then error,
        # then warning. (Same-code rules would share the (code, node)
        # suppression group and collapse — distinct codes here.)
        assert [candidate.code for candidate in outcome.report.candidates] == [
            "DIAG_A",
            "DIAG_D",
            "DIAG_C",
            "DIAG_B",
        ]

    def test_no_preemption_every_rule_evaluates(self):
        rules = (
            self._rule(rule_id="R-A", code="DIAG_LOW_PRIO", priority=99, severity="info"),
            self._rule(rule_id="R-B", code="DIAG_HIGH_PRIO", priority=1, severity="critical"),
        )
        outcome = EVALUATOR.evaluate(
            "sess-x", "run-x", (self._cc_hit(1),), rules,
            now_utc_ms=1_700_000_000_000,
        )
        assert len(outcome.report.candidates) == 2

    def test_static_builtin_ruleset_is_in_spec5_order(self):
        rules = load_builtin_rules()
        keys = [(rule.priority, rule.severity.value, rule.code) for rule in rules]
        assert keys == sorted(keys, key=lambda k: (k[0], k[1], k[2]))
        assert [rule.priority for rule in rules] == [10, 20, 30, 40]

    def test_fixture_rules_and_real_rules_agree_on_the_pairing(self):
        """The #54 fixture pairing (used by the engine suite) and the
        real §6 pairing are the same table — the two suites cannot
        drift apart."""
        fixture_pairing = {
            fault: fixture_rule_for_fault(fault).rule_id
            for fault in FIXTURE_FAULT_TYPES
        }
        real_pairing = dict(PAIRING)
        assert fixture_pairing == real_pairing
        fixture_rules = {rule.rule_id: rule for rule in builtin_fixture_rules()}
        for rule in load_builtin_rules():
            fixture = fixture_rules[rule.rule_id]
            assert fixture.code == rule.code
            assert fixture.priority == rule.priority
            assert fixture.severity == rule.severity.value
            assert fixture.confidence == rule.confidence.value
