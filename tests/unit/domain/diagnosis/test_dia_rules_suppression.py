"""SPEC-307 §5 MVP suppression semantics — ticket #55 dedicated tests
(REQ-DIA-307-002).

The engine (ticket #54) implements the suppression; these tests PIN it
through the REAL builtin rules (the #54 suite pins the same semantics
via fixture rules): per ``(code, node_id)`` per run exactly one
``diagnosis.raised``, each further hit accumulating one
``diagnosis.updated`` with cumulative refs; identity continuation across
re-evaluations via the ``existing`` map; disabled rules are skipped as a
non-error.

Pure logic: in-memory records, injected clock — no I/O, no wall clock.
"""

import pytest

from domain.diagnosis.engine import DiagnosisEvaluator
from domain.diagnosis.rules import BuiltinRuleSet, load_builtin_rules

from tests._support.diagnosis_fixtures import (
    NODE_ID,
    fault_observation_program,
    observation_record,
)

EVALUATOR = DiagnosisEvaluator()
NOW_MS = 1_700_000_000_000


def _evaluate(records, rules=None, *, existing=None):
    return EVALUATOR.evaluate(
        "sess-sup",
        "run-sup",
        records,
        rules if rules is not None else load_builtin_rules(),
        existing=existing,
        now_utc_ms=NOW_MS,
    )


class TestSuppressionWindow:
    """One raised + N updated per (code, node_id) per run (§5)."""

    def test_persistent_crc_hits_form_one_group(self):
        """Two CRC failures on the same (code, node) → ONE candidate,
        evidence accumulated in journal_seq order."""
        outcome = _evaluate(fault_observation_program("PMT_INVALID_CRC"))
        assert len(outcome.report.candidates) == 1
        candidate = outcome.report.candidates[0]
        assert candidate.code == "DIAG_PMT_CRC_BAD"
        assert [ref.journal_seq for ref in candidate.observation_refs] == [51, 52]

    def test_emission_facts_one_raised_then_updated_per_hit(self):
        """The engine's per-hit emission view: hit 0 anchors the raised,
        each further hit accumulates one updated (cumulative refs)."""
        outcome = _evaluate(fault_observation_program("PMT_INVALID_CRC"))
        assert len(outcome.groups) == 1
        group = outcome.groups[0]
        assert group.is_new is True
        assert group.node_key == NODE_ID
        assert [ref.journal_seq for ref in group.hit_refs] == [51, 52]

    def test_distinct_codes_never_share_a_group(self):
        records = (
            *fault_observation_program("PMT_INVALID_CRC"),
            *fault_observation_program("PAT_MISSING"),
        )
        outcome = _evaluate(records)
        assert {candidate.code for candidate in outcome.report.candidates} == {
            "DIAG_PMT_CRC_BAD",
            "DIAG_PAT_MISSING",
        }

    def test_window_scope_is_per_run_by_default(self):
        """A re-evaluation WITHOUT the stored identity is a new run
        window from the engine's viewpoint: a fresh identity is minted
        (the caller passes ``existing`` to continue one)."""
        records = fault_observation_program("PAT_MISSING")
        first = _evaluate(records)
        second = _evaluate(records)
        assert (
            first.report.candidates[0].diagnosis_id
            != second.report.candidates[0].diagnosis_id
        )


class TestIdentityContinuation:
    """Re-evaluation extends the SAME candidate (updated) instead of
    raising a twin."""

    def test_existing_map_preserves_the_diagnosis_identity(self):
        records = fault_observation_program("PAT_MISSING")
        first = _evaluate(records)
        stored_id = first.report.candidates[0].diagnosis_id
        second = _evaluate(
            records, existing={("DIAG_PAT_MISSING", NODE_ID): stored_id}
        )
        assert second.report.candidates[0].diagnosis_id == stored_id
        assert second.groups[0].is_new is False

    def test_accumulated_refs_survive_the_continuation(self):
        records = fault_observation_program("PMT_INVALID_CRC")
        first = _evaluate(records)
        stored_id = first.report.candidates[0].diagnosis_id
        second = _evaluate(
            records, existing={("DIAG_PMT_CRC_BAD", NODE_ID): stored_id}
        )
        refs = second.report.candidates[0].observation_refs
        assert [ref.journal_seq for ref in refs] == [51, 52]


class TestDisabledRuleEvaluation:
    """§8 row 3: a disabled rule is skipped at evaluation — not an
    error, not a warning."""

    def test_disabled_builtin_rule_produces_no_candidate(self):
        rules = BuiltinRuleSet(disabled_rule_ids=["DIA-PAT-MISSING"]).rules()
        outcome = _evaluate(fault_observation_program("PAT_MISSING"), rules)
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()

    def test_partially_disabled_ruleset_keeps_the_others(self):
        rules = BuiltinRuleSet(disabled_rule_ids=["DIA-PAT-MISSING"]).rules()
        records = (
            *fault_observation_program("PAT_MISSING"),
            *fault_observation_program("CC_DISCONTINUITY"),
        )
        outcome = _evaluate(records, rules)
        assert [candidate.code for candidate in outcome.report.candidates] == [
            "DIAG_CC_DISCONTINUITY"
        ]


class TestEvidenceAccumulationShape:
    """Every hit anchors its own evidence slot (SPEC-306 §6 chain)."""

    def test_each_hit_carries_its_own_evidence_anchor(self):
        """The two persistent-CRC hits sit 13 packets apart on the
        shared frame (fixture geometry) — each RuleMatch names its own
        slot; the group candidate anchors the FIRST hit."""
        rule = next(
            r
            for r in load_builtin_rules()
            if r.rule_id == "DIA-PMT-CRC-BAD"
        )
        hits = rule.matches(fault_observation_program("PMT_INVALID_CRC"))
        assert len(hits) == 2
        assert hits[0].evidence.packet_index != hits[1].evidence.packet_index
        outcome = _evaluate(fault_observation_program("PMT_INVALID_CRC"))
        group = outcome.groups[0]
        assert group.candidate.evidence.artifact_id
        assert group.candidate.evidence.pid == 0
        assert group.candidate.evidence == hits[0].evidence

    def test_no_match_records_produce_nothing(self):
        clean = observation_record(
            journal_seq=3,
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
        )
        outcome = _evaluate((clean,))
        assert outcome.report.candidates == ()
        assert outcome.report.warnings == ()
