"""Diagnosis domain: maps Observations to root-cause candidates and suggestions.

Consumes only ``domain.observation`` (plus static reference data from
``knowledge``); never touches TSDuck processes, never parses raw TS and never
starts processes (ADR-0005 decision 4).

Public API: SPEC-003 section 2.6 diagnosis models, plus — since ticket #54 —
the SPEC-306 batch evaluation core (pure evaluator, value objects, envelope
builders), and — since ticket #55 — the SPEC-307 declarative rule model,
registration loader and the builtin four-rule set (the engine consumes rules
structurally through :class:`EvaluationRule` without importing the rules
package — the rules side implements that face on
:class:`~domain.diagnosis.rules.DiagnosticRule`). The journal reading half
of the engine face (SPEC-306 §5 ``DiagnosisEngine.evaluate``) is the
application orchestration — the domain receives already-parsed observation
records only.
"""

from domain.diagnosis.engine import (
    DiagnosisEvaluator,
    EvaluationOutcome,
    EvaluationRule,
    GroupedCandidate,
    ObservationRecord,
    RuleMatch,
    suppression_node_key,
)
from domain.diagnosis.events import (
    PRODUCER_ID as DIAGNOSIS_PRODUCER_ID,
    cleared_envelope,
    raised_envelope,
    updated_envelope,
)
from domain.diagnosis.model import Diagnosis, DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.report import (
    DiagnosisCandidate,
    DiagnosisReport,
    EvidenceRef,
    ObservationRef,
    sort_candidates,
)
from domain.diagnosis.rules import (
    BuiltinRuleSet,
    DiagnosticRule,
    FieldPredicate,
    MatchSpec,
    RuleDefinitionError,
    SuppressionSpec,
    WindowAggregate,
    builtin_rules_provider,
    load_builtin_rules,
    parse_rule,
    python_builtin_rules,
    validate_ruleset,
)

__all__ = [
    "BuiltinRuleSet",
    "DIAGNOSIS_PRODUCER_ID",
    "DiagnosticRule",
    "Diagnosis",
    "DiagnosisCandidate",
    "DiagnosisConfidence",
    "DiagnosisEvaluator",
    "DiagnosisReport",
    "DiagnosisSeverity",
    "EvaluationOutcome",
    "EvaluationRule",
    "EvidenceRef",
    "FieldPredicate",
    "GroupedCandidate",
    "MatchSpec",
    "ObservationRecord",
    "ObservationRef",
    "RuleDefinitionError",
    "RuleMatch",
    "SuppressionSpec",
    "WindowAggregate",
    "builtin_rules_provider",
    "cleared_envelope",
    "load_builtin_rules",
    "parse_rule",
    "python_builtin_rules",
    "raised_envelope",
    "sort_candidates",
    "suppression_node_key",
    "updated_envelope",
    "validate_ruleset",
]
