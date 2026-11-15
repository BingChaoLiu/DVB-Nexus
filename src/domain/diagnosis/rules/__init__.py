"""SPEC-307 diagnostic rules (ticket #55): the declarative rule model,
the registration loader and the builtin four-rule set.

The engine (``domain.diagnosis.engine``, ticket #54) consumes rules
structurally through :class:`EvaluationRule`; this package owns the REAL
declarative side — ``DiagnosticRule`` (SPEC-307 §3), the ``MatchSpec``
finite primitive set (§4), the MVP suppression declaration (§5), the
builtin rule set (§6) and its fail-fast registration loader (§7/§8).
Python declarations (``declarations.py``) and JSON declarations
(``builtin/*.json``) are dual forms, cross-checked at load.
"""

from domain.diagnosis.rules.errors import RuleDefinitionError
from domain.diagnosis.rules.loader import (
    BuiltinRuleSet,
    builtin_rules_provider,
    load_builtin_rules,
    parse_rule,
    python_builtin_rules,
    validate_ruleset,
)
from domain.diagnosis.rules.model import (
    DiagnosticRule,
    FieldPredicate,
    GroupKey,
    MatchSpec,
    PredicateOp,
    SuppressionSpec,
    WindowAggregate,
)

__all__ = [
    "BuiltinRuleSet",
    "DiagnosticRule",
    "FieldPredicate",
    "GroupKey",
    "MatchSpec",
    "PredicateOp",
    "RuleDefinitionError",
    "SuppressionSpec",
    "WindowAggregate",
    "builtin_rules_provider",
    "load_builtin_rules",
    "parse_rule",
    "python_builtin_rules",
    "validate_ruleset",
]
