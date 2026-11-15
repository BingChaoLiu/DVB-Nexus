"""SPEC-306 batch evaluation core unit tests (ticket #54).

REQ-DIA-306-001/002 + the §8 error-handling rows: empty ruleset = empty
report (non-error), rule isolation, invalid-payload skip, SPEC-307 §5
ordering and MVP suppression semantics, ADR-0007 item 5 single-attributable
symptom via the shared fixture programs.

Pure logic: in-memory records only, injected ``now_utc_ms`` — no I/O, no
wall clock (tests/README §1/§4).
"""

import pytest

from domain.diagnosis.engine import DiagnosisEvaluator, ObservationRecord
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.report import EvidenceRef, sort_candidates
from faults.registry import validate_fault_definition

from tests._support.diagnosis_fixtures import (
    FIXTURE_FAULT_TYPES,
    RUN_ID,
    SESSION_ID,
    builtin_fixture_rules,
    fixture_fault_definition,
    fixture_rule_for_fault,
    fault_observation_program,
    observation_record,
)

EVALUATOR = DiagnosisEvaluator()
NOW_MS = 1_700_000_000_000


def _evaluate(records, rules=None, *, existing=None):
    return EVALUATOR.evaluate(
        SESSION_ID,
        RUN_ID,
        records,
        rules if rules is not None else builtin_fixture_rules(),
        existing=existing,
        now_utc_ms=NOW_MS,
    )


class TestEmptyRuleset:
    """SPEC-306 §8 row 1: no rules / no match = empty report, not an error."""

    def test_no_rules_yields_empty_report(self):
        outcome = EVALUATOR.evaluate(
            SESSION_ID,
            RUN_ID,
            fault_observation_program("PAT_MISSING"),
            None,
            now_utc_ms=NOW_MS,
        )
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()
        assert outcome.groups == ()

    def test_explicitly_empty_ruleset_yields_empty_report(self):
        outcome = _evaluate(fault_observation_program("PAT_MISSING"), rules=())
        assert outcome.report.candidates == ()

    def test_no_matching_records_yields_empty_report(self):
        clean = (
            observation_record(
                journal_seq=1,
                event_type="ts.psi_section_observed",
                payload={
                    "source": "internal_parser",
                    "confidence": "parsed",
                    "pid": 0,
                    "section": "PAT",
                    "present": True,
                    "artifact_id": "a-1",
                    "packet_index": 0,
                },
            ),
        )
        outcome = _evaluate(clean)
        assert outcome.report.candidates == ()


class TestSingleAttributableSymptom:
    """REQ-DIA-306-002: one MVP fault → one primary candidate, rule pairing
    per SPEC-307 §6; interlock with the real FaultDefinition fields."""

    @pytest.mark.parametrize("fault_type", FIXTURE_FAULT_TYPES)
    def test_one_fault_program_yields_exactly_one_candidate(self, fault_type):
        outcome = _evaluate(fault_observation_program(fault_type))
        rule = fixture_rule_for_fault(fault_type)
        assert len(outcome.report.candidates) == 1
        candidate = outcome.report.candidates[0]
        assert candidate.code == rule.code
        assert candidate.rule_id == rule.rule_id
        assert candidate.rule_version == rule.rule_version

    @pytest.mark.parametrize("fault_type", FIXTURE_FAULT_TYPES)
    def test_expected_evidence_interlocks_with_fault_definition(self, fault_type):
        """expected_evidence ↔ FaultDefinition.expected_observations
        (ADR-0007 item 5): the interlocked definition passes the real
        faults-registry validation."""
        rule = fixture_rule_for_fault(fault_type)
        fault = fixture_fault_definition(fault_type)
        assert fault.expected_observations == rule.expected_evidence
        assert validate_fault_definition(fault) == ()

    def test_confidence_is_static_passthrough_not_a_score(self):
        """The engine transmits the rule's declared tier verbatim — no
        scoring, no probability claim (brief §6)."""
        outcome = _evaluate(fault_observation_program("PMT_PID_MISMATCH"))
        candidate = outcome.report.candidates[0]
        assert candidate.confidence is DiagnosisConfidence.MEDIUM
        assert isinstance(candidate.confidence, DiagnosisConfidence)

    def test_severity_is_static_passthrough(self):
        outcome = _evaluate(fault_observation_program("CC_DISCONTINUITY"))
        assert outcome.report.candidates[0].severity is DiagnosisSeverity.WARNING


class TestOrdering:
    """SPEC-307 §5: priority asc → severity desc → code lexicographic."""

    def _rule(self, **overrides):
        base = dict(
            rule_id="R",
            rule_version="1.0.0",
            code="DIAG_R",
            priority=50,
            severity="warning",
            confidence="low",
            title="t",
            summary_template="s",
            suggested_actions=(),
            expected_evidence=(),
        )
        base.update(overrides)
        # Synthetic ordering probes — NOT the default ruleset (非默认规则
        # 集): ad-hoc REAL DiagnosticRule objects so the engine's §5 sort
        # matrix is exercised in isolation. All match the shared CC hit
        # shape through the production declarative interpreter (M4 review
        # fix F2: the fixture rule stand-ins are gone).
        from domain.diagnosis.rules import DiagnosticRule, FieldPredicate, MatchSpec

        return DiagnosticRule(
            rule_id=base["rule_id"],
            rule_version=base["rule_version"],
            code=base["code"],
            priority=base["priority"],
            severity=base["severity"],
            confidence=base["confidence"],
            title=base["title"],
            summary_template=base["summary_template"],
            match=MatchSpec(
                event_type="ts.continuity_error",
                predicates=(
                    FieldPredicate(field="payload.expected_cc", op="exists"),
                    FieldPredicate(field="payload.actual_cc", op="exists"),
                ),
            ),
            suggested_actions=base["suggested_actions"],
            expected_evidence=base["expected_evidence"],
        )

    def _hit(self, seq):
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

    def test_priority_ascending_severity_descending_code_lexicographic(self):
        rules = (
            self._rule(rule_id="R-A", code="DIAG_B", priority=30, severity="warning"),
            self._rule(rule_id="R-B", code="DIAG_A", priority=10, severity="info"),
            self._rule(rule_id="R-C", code="DIAG_C", priority=30, severity="critical"),
            self._rule(rule_id="R-D", code="DIAG_D", priority=30, severity="error"),
        )
        outcome = _evaluate((self._hit(1),), rules=rules)
        # priority ascending first: DIAG_A (priority 10) leads; the
        # priority-30 tie is severity-desc (critical > error > warning).
        assert [candidate.code for candidate in outcome.report.candidates] == [
            "DIAG_A",
            "DIAG_C",
            "DIAG_D",
            "DIAG_B",
        ]

    def test_no_preemption_every_candidate_present(self):
        rules = (
            self._rule(rule_id="R-A", code="DIAG_B", priority=10),
            self._rule(rule_id="R-B", code="DIAG_A", priority=99),
        )
        outcome = _evaluate((self._hit(1),), rules=rules)
        assert len(outcome.report.candidates) == 2

    def test_sort_candidates_helper_matches_report_order(self):
        from domain.diagnosis.report import (
            DiagnosisCandidate,
            ObservationRef,
        )

        def candidate(code, priority, severity):
            return DiagnosisCandidate(
                diagnosis_id=f"id-{code}",
                run_id=RUN_ID,
                rule_id="R",
                rule_version="1.0.0",
                code=code,
                priority=priority,
                severity=severity,
                confidence="high",
                title="t",
                summary="s",
                observation_refs=[ObservationRef(journal_seq=1, event_type="ts.continuity_error")],
                evidence=EvidenceRef(artifact_id="a", pid=0, packet_index=0),
            )

        ordered = sort_candidates(
            [
                candidate("DIAG_X", 5, "error"),
                candidate("DIAG_A", 5, "critical"),
                candidate("DIAG_B", 2, "info"),
                candidate("DIAG_C", 5, "error"),
            ]
        )
        assert [c.code for c in ordered] == ["DIAG_B", "DIAG_A", "DIAG_C", "DIAG_X"]


class TestRuleIsolation:
    """SPEC-306 §8 row 2: one raising rule warns and is skipped, the rest
    still evaluate."""

    def test_raising_rule_is_isolated_with_warning(self):
        class ExplodingRule:
            rule_id = "DIA-EXPLODE"
            rule_version = "1.0.0"
            code = "DIAG_EXPLODE"
            priority = 1
            severity = "critical"
            confidence = "high"
            title = "t"
            suggested_actions = ()
            expected_evidence = ()

            def matches(self, records):
                raise RuntimeError("rule bug")

        outcome = _evaluate(
            fault_observation_program("PAT_MISSING"),
            rules=(ExplodingRule(), *builtin_fixture_rules()),
        )
        codes = [candidate.code for candidate in outcome.report.candidates]
        assert "DIAG_PAT_MISSING" in codes
        assert "DIAG_EXPLODE" not in codes
        assert any("DIA-EXPLODE" in warning for warning in outcome.report.warnings)
        assert any("SPEC-306 §8" in warning for warning in outcome.report.warnings)


class TestInvalidPayloadSkip:
    """SPEC-306 §8 row 4: payload not satisfying the registered schema is
    skipped with a warning and produces no candidate."""

    def test_nonconforming_observation_payload_is_skipped(self):
        bad = ObservationRecord(
            journal_seq=5,
            event_type="ts.psi_section_observed",
            event_id="e-5",
            # Missing the mandatory observation axes (#13 Q3-i) — the
            # registry refuses it, so it can never ground a candidate.
            payload={"section": "PAT", "present": False},
            node_id="mux-0",
            pid=0,
        )
        outcome = _evaluate((bad,))
        assert outcome.report.candidates == ()
        assert len(outcome.report.warnings) == 1
        assert "journal_seq 5" in outcome.report.warnings[0]

    def test_unregistered_event_type_record_is_skipped(self):
        bad = ObservationRecord(
            journal_seq=6,
            event_type="made.up.event",
            event_id="e-6",
            payload={},
            node_id=None,
            pid=None,
        )
        outcome = _evaluate((bad,))
        assert outcome.report.candidates == ()
        assert len(outcome.report.warnings) == 1


class TestSuppressionSemantics:
    """SPEC-307 §5 MVP: per (code, node) per run one candidate; repeated
    hits accumulate refs under one identity; ``existing`` keeps the stored
    diagnosis_id across re-evaluations."""

    def test_repeated_hits_accumulate_one_candidate_group(self):
        outcome = _evaluate(fault_observation_program("PMT_INVALID_CRC"))
        assert len(outcome.report.candidates) == 1
        candidate = outcome.report.candidates[0]
        refs = candidate.observation_refs
        assert [ref.journal_seq for ref in refs] == [51, 52]
        # Per-hit emission facts: hit 0 anchors the raised, hit 1 the updated.
        assert len(outcome.groups) == 1
        assert len(outcome.groups[0].hit_refs) == 2
        assert outcome.groups[0].is_new is True
        assert outcome.groups[0].node_key == "mux-0"

    def test_same_node_different_codes_are_separate_groups(self):
        records = (
            *fault_observation_program("PMT_INVALID_CRC"),
            *fault_observation_program("PAT_MISSING"),
        )
        outcome = _evaluate(records)
        assert {candidate.code for candidate in outcome.report.candidates} == {
            "DIAG_PMT_CRC_BAD",
            "DIAG_PAT_MISSING",
        }

    def test_existing_map_preserves_diagnosis_identity(self):
        records = fault_observation_program("PAT_MISSING")
        first = _evaluate(records)
        stored_id = first.report.candidates[0].diagnosis_id
        existing = {("DIAG_PAT_MISSING", "mux-0"): stored_id}
        second = _evaluate(records, existing=existing)
        assert second.report.candidates[0].diagnosis_id == stored_id
        assert second.groups[0].is_new is False

    def test_without_existing_map_a_fresh_identity_is_minted(self):
        records = fault_observation_program("PAT_MISSING")
        first = _evaluate(records)
        second = _evaluate(records)
        assert (
            first.report.candidates[0].diagnosis_id
            != second.report.candidates[0].diagnosis_id
        )


class TestDisabledRules:
    """SPEC-307 §8 row 3: a disabled rule is skipped at evaluation (a
    non-error) — the structural ``enabled`` attribute."""

    def test_disabled_rule_produces_no_candidate(self):
        rule = fixture_rule_for_fault("PAT_MISSING")
        # The runtime disable switch mints the disabled view exactly the
        # way the production ruleset does (BuiltinRuleSet.rules()).
        disabled = rule.model_copy(update={"enabled": False})
        outcome = _evaluate(
            fault_observation_program("PAT_MISSING"), rules=(disabled,)
        )
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()  # skipping is not a warning


class TestReportShape:
    """The report carries injected evaluation time and stable identity."""

    def test_report_metadata(self):
        outcome = _evaluate(fault_observation_program("PAT_MISSING"))
        report = outcome.report
        assert report.session_id == SESSION_ID
        assert report.run_id == RUN_ID
        assert report.evaluated_at_utc_ms == NOW_MS
        candidate = report.candidates[0]
        assert candidate.run_id == RUN_ID
        assert candidate.evidence.artifact_id != ""
