"""Python dual form of the builtin rule set (SPEC-307 §7, ticket #55).

The builtin four rules exist in TWO forms — Python definitions (this
module) and JSON declarations (``builtin/*.json``) — and the loader
fails the startup when the two diverge (§7 load-time consistency check;
``load_builtin_rules`` proves it on every start). Keep every value here
byte-identical to its JSON counterpart; a rule-set change is a NEW
``rule_version`` (§7), never an in-place semantic edit.

Predicate parameters pin the ADR-0007 item 5 single-symptom signatures
of the four MVP fault types at the signal level (SPEC-307 §6: 具体谓词
参数随实现细化，信号语义以 ADR-0007 §5 为权威).
"""

from __future__ import annotations

from domain.diagnosis.rules.model import (
    DiagnosticRule,
    FieldPredicate,
    MatchSpec,
    SuppressionSpec,
    WindowAggregate,
)

__all__ = ["python_builtin_rules"]


def python_builtin_rules() -> tuple[DiagnosticRule, ...]:
    """The four SPEC-307 §6 rules in the §5 output ordering."""
    return (
        DiagnosticRule(
            rule_id="DIA-PAT-MISSING",
            rule_version="1.0.0",
            code="DIAG_PAT_MISSING",
            priority=10,
            severity="error",
            confidence="high",
            title="PAT missing in window",
            summary_template=(
                "No PAT observed on PID {pid} (null substitution at packet"
                " {packet_index}); window artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="correlation.pid", op="eq", value=0),
                    FieldPredicate(field="payload.section", op="eq", value="PAT"),
                    FieldPredicate(field="payload.present", op="eq", value=False),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Restore PAT emission on PID 0",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        DiagnosticRule(
            rule_id="DIA-PMT-CRC-BAD",
            rule_version="1.0.0",
            code="DIAG_PMT_CRC_BAD",
            priority=20,
            severity="error",
            confidence="high",
            title="PMT CRC verification failed",
            summary_template=(
                "PMT CRC check failed (persistent symptom) at packet"
                " {packet_index}; window artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="payload.section", op="eq", value="PMT"),
                    FieldPredicate(field="payload.crc_valid", op="eq", value=False),
                ),
                group_by=("node_id", "pid"),
                window=WindowAggregate(
                    aggregation="count", scope="run", min_count=2
                ),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Re-mux the PMT with correct CRC",),
            expected_evidence=("ts.psi_section_observed",),
        ),
        DiagnosticRule(
            rule_id="DIA-CC-DISCONTINUITY",
            rule_version="1.0.0",
            code="DIAG_CC_DISCONTINUITY",
            priority=30,
            severity="warning",
            confidence="high",
            title="Continuity counter discontinuity",
            summary_template=(
                "CC discontinuity on PID {pid}: expected {expected_cc},"
                " got {actual_cc} at packet {packet_index} (relative"
                " offset persists); artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.continuity_error",
                predicates=(
                    FieldPredicate(field="payload.expected_cc", op="exists"),
                    FieldPredicate(field="payload.actual_cc", op="exists"),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=(
                "Inspect the upstream multiplex for packet loss",
            ),
            expected_evidence=("ts.continuity_error",),
        ),
        DiagnosticRule(
            rule_id="DIA-PMT-PID-MISMATCH",
            rule_version="1.0.0",
            code="DIAG_PMT_PID_MISMATCH",
            priority=40,
            severity="error",
            confidence="medium",
            title="PAT points at a PMT PID with no PMT",
            summary_template=(
                "PAT declares program_map_pid {actual_program_map_pid} but"
                " the PMT sits on {expected_program_map_pid} (orphan PMT)"
                " at packet {packet_index}; artefact {artifact_id}"
            ),
            match=MatchSpec(
                event_type="ts.psi_section_observed",
                predicates=(
                    FieldPredicate(field="payload.section", op="eq", value="PAT"),
                    FieldPredicate(
                        field="payload.expected_program_map_pid", op="exists"
                    ),
                    FieldPredicate(
                        field="payload.actual_program_map_pid", op="exists"
                    ),
                ),
                group_by=("node_id", "pid"),
            ),
            suppression=SuppressionSpec(),
            suggested_actions=("Correct the PAT program_map_pid entry",),
            expected_evidence=("ts.psi_section_observed",),
        ),
    )
