"""SPEC-307 §6/§7/§8 rule registration loader (ticket #55).

Static builtin registration with fail-fast semantics: a rule declaration
that fails validation, a match referencing an unregistered event type, a
duplicate ``rule_id``/``code`` and a divergence between the JSON and the
Python dual form ALL fail the load (startup) — never a silent skip (§8
rows 1-2). Runtime disable is a configuration switch over the loaded set
(``BuiltinRuleSet``); there is NO hot reload — the builtin set parses
once per process and the provider hands out the same instances (§7).

The JSON declarations live in the ``builtin`` data package and are read
through ``importlib.resources`` (the domain purity contract forbids
os/pathlib/glob). Every shipped document must be the canonical
``model_dump(mode="json")`` of its Python dual form — the shipped files
are the declaration of record.

The registration face is :func:`parse_rule`: structural JSON-shape
refusals (pydantic ``ValidationError`` at the model layer) are unified
into :class:`RuleDefinitionError` here, so composition code catches one
exception type for the whole fail-fast matrix.
"""

from __future__ import annotations

import importlib.resources
import json
from typing import Any, Mapping, Optional, Sequence

from pydantic import ValidationError

from domain.diagnosis.model import DiagnosisSeverity
from domain.diagnosis.rules.declarations import python_builtin_rules
from domain.diagnosis.rules.errors import RuleDefinitionError
from domain.diagnosis.rules.model import DiagnosticRule

__all__ = [
    "BuiltinRuleSet",
    "builtin_rules_provider",
    "load_builtin_rules",
    "parse_rule",
    "python_builtin_rules",
    "validate_ruleset",
]

_BUILTIN_PACKAGE = "domain.diagnosis.rules.builtin"

#: SPEC-307 §5 ordering (priority asc → severity desc → code lex).
_SEVERITY_RANK_DESC = {
    DiagnosisSeverity.CRITICAL: 0,
    DiagnosisSeverity.ERROR: 1,
    DiagnosisSeverity.WARNING: 2,
    DiagnosisSeverity.INFO: 3,
}


def _builtin_sort_key(rule: DiagnosticRule) -> tuple[int, int, str]:
    return (
        rule.priority,
        _SEVERITY_RANK_DESC[rule.severity],
        rule.code,
    )


def parse_rule(document: Mapping[str, Any]) -> DiagnosticRule:
    """Parse ONE rule declaration document (fail-fast, §8 rows 1-2)."""
    if not isinstance(document, Mapping):
        raise RuleDefinitionError(
            f"rule declaration must be a JSON object, got"
            f" {type(document).__name__}"
        )
    try:
        return DiagnosticRule.model_validate(dict(document))
    except ValidationError as exc:
        raise RuleDefinitionError(
            f"rule declaration fails validation (SPEC-307 §8 row 1"
            f" fail-fast): {exc}"
        ) from exc


def validate_ruleset(
    rules: Sequence[DiagnosticRule],
    *,
    documents: Optional[Sequence[Mapping[str, Any]]] = None,
) -> None:
    """Ruleset-level registration checks (§7): rule_id/code uniqueness
    and — when the JSON documents are supplied — the dual-form
    consistency against the Python declarations."""
    seen_ids: dict[str, str] = {}
    seen_codes: dict[str, str] = {}
    for rule in rules:
        if rule.rule_id in seen_ids:
            raise RuleDefinitionError(
                f"duplicate rule_id {rule.rule_id!r} (also on"
                f" {seen_ids[rule.rule_id]!r}) — registration fails fast"
                " (SPEC-307 §7)"
            )
        if rule.code in seen_codes:
            raise RuleDefinitionError(
                f"duplicate code {rule.code!r} (also on"
                f" {seen_codes[rule.code]!r}) — registration fails fast"
                " (SPEC-307 §7)"
            )
        seen_ids[rule.rule_id] = rule.code
        seen_codes[rule.code] = rule.rule_id
    if documents is not None:
        _ensure_dual_form(rules, documents)


def _ensure_dual_form(
    rules: Sequence[DiagnosticRule],
    documents: Sequence[Mapping[str, Any]],
) -> None:
    """SPEC-307 §7: Python definitions and JSON declarations are dual
    forms — every shipped JSON must be the canonical dump of its Python
    counterpart, and both sides must cover the same rule ids."""
    declarations = {rule.rule_id: rule for rule in python_builtin_rules()}
    declared: dict[str, Mapping[str, Any]] = {}
    for document in documents:
        rule_id = document.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            raise RuleDefinitionError(
                "rule declaration document lacks a rule_id — dual-form"
                " check cannot proceed (SPEC-307 §7)"
            )
        declared[rule_id] = document
    for rule_id in sorted(set(declared) | set(declarations)):
        if rule_id not in declarations:
            raise RuleDefinitionError(
                f"JSON declaration {rule_id!r} has no Python dual form"
                " (SPEC-307 §7 dual form check)"
            )
        if rule_id not in declared:
            raise RuleDefinitionError(
                f"Python declaration {rule_id!r} has no JSON dual form"
                " (SPEC-307 §7 dual form check)"
            )
    parsed_by_id = {rule.rule_id: rule for rule in rules}
    for rule_id, document in declared.items():
        parsed = parsed_by_id.get(rule_id)
        canonical = declarations[rule_id]
        if (
            parsed is None
            or parsed != canonical
            or parsed.model_dump(mode="json") != dict(document)
        ):
            raise RuleDefinitionError(
                f"rule {rule_id!r}: JSON declaration and Python dual form"
                " diverge — startup fails fast (SPEC-307 §7 dual form"
                " check; the shipped JSON must be the canonical dump)"
            )


#: Process-level cache — no hot reload (§7): the builtin set parses once.
_RULESET_CACHE: Optional[tuple[DiagnosticRule, ...]] = None


def load_builtin_rules() -> tuple[DiagnosticRule, ...]:
    """Load + validate the builtin four-rule set (SPEC-307 §6).

    Returns the rules in the §5 output ordering. Raises
    :class:`RuleDefinitionError` on any §8 fail-fast condition. The load
    runs once per process; later calls return the same instances.
    """
    global _RULESET_CACHE
    if _RULESET_CACHE is None:
        documents = _read_builtin_documents()
        parsed = [parse_rule(document) for document in documents]
        validate_ruleset(parsed, documents=documents)
        _RULESET_CACHE = tuple(sorted(parsed, key=_builtin_sort_key))
    return _RULESET_CACHE


def _read_builtin_documents() -> list[dict]:
    """Read the builtin JSON declarations (deterministic filename order;
    domain purity: importlib.resources, no os/pathlib/glob)."""
    package = importlib.resources.files(_BUILTIN_PACKAGE)
    documents: list[dict] = []
    for resource in sorted(package.iterdir(), key=lambda item: item.name):
        name = resource.name
        if not name.endswith(".json") or not resource.is_file():
            continue
        try:
            document = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuleDefinitionError(
                f"builtin rule file {name!r} is unreadable: {exc}"
            ) from exc
        documents.append(document)
    if not documents:
        raise RuleDefinitionError(
            "builtin ruleset is empty — no JSON declarations found"
            f" in {_BUILTIN_PACKAGE!r} (SPEC-307 §6)"
        )
    return documents


class BuiltinRuleSet:
    """The static builtin ruleset with the runtime disable switch (§7).

    Constructing one LOADS and validates the builtin set (fail-fast at
    composition time). ``rules()`` returns the registered rules in the
    §5 ordering with disabled members flagged ``enabled=False`` — the
    evaluator skips those (non-error, §8 row 3); the set keeps them
    visible so the configuration surface stays inspectable.
    """

    def __init__(self, *, disabled_rule_ids: Sequence[str] = ()) -> None:
        self._rules = load_builtin_rules()
        known = {rule.rule_id for rule in self._rules}
        unknown = sorted(set(disabled_rule_ids) - known)
        if unknown:
            raise RuleDefinitionError(
                f"unknown disabled rule_id(s) {unknown} — the disable"
                " switch names registered rules only (SPEC-307 §7)"
            )
        self._disabled = frozenset(disabled_rule_ids)

    def rules(self) -> tuple[DiagnosticRule, ...]:
        """The registered ruleset view for evaluation (stable order,
        disabled members flagged)."""
        if not self._disabled:
            return self._rules
        return tuple(
            (
                rule.model_copy(update={"enabled": False})
                if rule.rule_id in self._disabled
                else rule
            )
            for rule in self._rules
        )


_PROVIDER_RULESET: Optional[BuiltinRuleSet] = None


def builtin_rules_provider() -> tuple[DiagnosticRule, ...]:
    """The ``DiagnosisService(rules_provider=...)`` seam (SPEC-306 §5,
    ticket #54): resolves the SPEC-307 registered ruleset. Loads once
    per process — no hot reload (§7).
    """
    global _PROVIDER_RULESET
    if _PROVIDER_RULESET is None:
        _PROVIDER_RULESET = BuiltinRuleSet()
    return _PROVIDER_RULESET.rules()
