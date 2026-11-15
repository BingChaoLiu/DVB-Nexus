"""SPEC-307 §6/§7/§8 rule registration loader unit tests (ticket #55,
REQ-DIA-307-004).

Fail-fast matrix: a rule JSON that fails validation and a match
referencing an unregistered event type fail the load (startup) — never a
silent skip. Uniqueness (rule_id/code) is enforced on the ruleset. The
builtin set loads from ``rules/builtin/*.json`` and is cross-checked
against its Python dual form (§7: Python definition + JSON declaration,
load-time consistency check). No hot reload: the provider loads once.

Structural JSON-shape refusals (unknown keys, bad literals, bad patterns)
surface as pydantic ValidationError at direct construction; the
REGISTRATION face (``parse_rule``) unifies everything into
:class:`RuleDefinitionError` — that is the face composition code (and
these tests) pins.

Layer note: reading the builtin package JSONs happens inside the
PRODUCTION loader (importlib.resources); the one direct file read here is
the in-repo schema document, waived per the #52 precedent (the schema
document IS the artifact under test).
"""

import json

import pytest

from domain.diagnosis.engine import EvaluationRule
from domain.diagnosis.rules import (
    DiagnosticRule,
    RuleDefinitionError,
    load_builtin_rules,
    parse_rule,
    python_builtin_rules,
    validate_ruleset,
)
from domain.observation.registry import TS_EVENT_TYPES
from tests._support.paths import repo_root

SCHEMA_RELPATH = ("docs", "schemas", "diagnostic-rule.schema.json")


def _valid_document() -> dict:
    return DiagnosticRule(
        rule_id="DIA-DOC",
        rule_version="1.0.0",
        code="DIAG_DOC",
        priority=10,
        severity="error",
        confidence="high",
        title="Doc rule",
        summary_template="gap at packet {packet_index}",
        match={
            "event_type": "ts.psi_section_observed",
            "predicates": [
                {"field": "payload.section", "op": "eq", "value": "PAT"}
            ],
        },
        suggested_actions=("Act",),
        expected_evidence=("ts.psi_section_observed",),
    ).model_dump(mode="json")


class TestParseRule:
    """The JSON registration face: strict, fail-fast (SPEC-307 §8)."""

    def test_valid_document_parses(self):
        rule = parse_rule(_valid_document())
        assert rule.rule_id == "DIA-DOC"
        assert rule.match.event_type == "ts.psi_section_observed"

    def test_canonical_json_round_trip(self):
        document = _valid_document()
        assert parse_rule(document).model_dump(mode="json") == document

    def test_non_mapping_input_fails_fast(self):
        with pytest.raises(RuleDefinitionError):
            parse_rule(["not", "a", "mapping"])

    def test_missing_required_field_fails_fast(self):
        document = _valid_document()
        del document["rule_id"]
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_unknown_field_fails_fast(self):
        document = _valid_document()
        document["expression"] = "payload.section == 'PAT'"
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_bad_severity_fails_fast(self):
        document = _valid_document()
        document["severity"] = "severe"
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_bad_confidence_fails_fast(self):
        document = _valid_document()
        document["confidence"] = "certain"
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_non_semver_version_fails_fast(self):
        document = _valid_document()
        document["rule_version"] = "1"
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_match_referencing_unregistered_event_type_fails_startup(self):
        """SPEC-307 §8 row 2: the failure names the spec row."""
        document = _valid_document()
        document["match"]["event_type"] = "ts.made_up_event"
        with pytest.raises(RuleDefinitionError) as excinfo:
            parse_rule(document)
        assert "SPEC-307 §8" in str(excinfo.value)

    def test_unregistered_expected_evidence_fails_fast(self):
        document = _valid_document()
        document["expected_evidence"] = ["made.up.event"]
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_bad_predicate_shape_fails_fast(self):
        document = _valid_document()
        document["match"]["predicates"] = [{"field": "payload.x", "op": "regex"}]
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)

    def test_bad_summary_template_fails_fast(self):
        document = _valid_document()
        document["summary_template"] = "leak {pid.__class__}"
        with pytest.raises(RuleDefinitionError):
            parse_rule(document)


class TestRulesetUniqueness:
    """SPEC-307 §7: rule_id/code uniqueness on the registered set."""

    def _rule(self, *, rule_id="DIA-A", code="DIAG_A"):
        return DiagnosticRule(
            rule_id=rule_id,
            rule_version="1.0.0",
            code=code,
            priority=10,
            severity="error",
            confidence="high",
            title="t",
            summary_template="s {packet_index}",
            match={"event_type": "ts.continuity_error"},
        )

    def test_unique_set_passes(self):
        validate_ruleset((self._rule(), self._rule(rule_id="DIA-B", code="DIAG_B")))

    def test_duplicate_rule_id_fails_fast(self):
        with pytest.raises(RuleDefinitionError):
            validate_ruleset((self._rule(), self._rule()))

    def test_duplicate_code_fails_fast(self):
        with pytest.raises(RuleDefinitionError):
            validate_ruleset(
                (self._rule(), self._rule(rule_id="DIA-B", code="DIAG_A"))
            )


class TestBuiltinLoad:
    """SPEC-307 §6: the four-rule builtin set and its table values."""

    @pytest.fixture(scope="class")
    def builtin(self) -> tuple[DiagnosticRule, ...]:
        return load_builtin_rules()

    def test_loads_exactly_the_four_rules(self, builtin):
        assert [rule.rule_id for rule in builtin] == [
            "DIA-PAT-MISSING",
            "DIA-PMT-CRC-BAD",
            "DIA-CC-DISCONTINUITY",
            "DIA-PMT-PID-MISMATCH",
        ]

    def test_load_order_follows_the_spec5_ordering(self, builtin):
        """Registration order is the SPEC-307 §5 output ordering (the
        evaluator re-applies it; the static set is pre-sorted)."""
        priorities = [rule.priority for rule in builtin]
        assert priorities == sorted(priorities) == [10, 20, 30, 40]

    @pytest.mark.parametrize(
        ("rule_id", "code", "priority", "severity", "confidence"),
        [
            ("DIA-PAT-MISSING", "DIAG_PAT_MISSING", 10, "error", "high"),
            ("DIA-PMT-CRC-BAD", "DIAG_PMT_CRC_BAD", 20, "error", "high"),
            ("DIA-CC-DISCONTINUITY", "DIAG_CC_DISCONTINUITY", 30, "warning", "high"),
            ("DIA-PMT-PID-MISMATCH", "DIAG_PMT_PID_MISMATCH", 40, "error", "medium"),
        ],
    )
    def test_table_values_per_rule(
        self, builtin, rule_id, code, priority, severity, confidence
    ):
        rule = next(rule for rule in builtin if rule.rule_id == rule_id)
        assert rule.code == code
        assert rule.priority == priority
        assert rule.severity.value == severity
        assert rule.confidence.value == confidence
        assert rule.rule_version == "1.0.0"

    def test_match_event_types_are_observation_family(self, builtin):
        for rule in builtin:
            assert rule.match.event_type in TS_EVENT_TYPES

    def test_expected_evidence_is_nonempty_and_registered(self, builtin):
        for rule in builtin:
            assert rule.expected_evidence
            assert all(
                evidence.startswith("ts.") for evidence in rule.expected_evidence
            )

    def test_suppression_is_the_mvp_fixed_declaration(self, builtin):
        for rule in builtin:
            assert rule.suppression.key == ("code", "node_id")
            assert rule.suppression.window == "per_run"

    def test_dual_form_python_and_json_agree(self, builtin):
        """SPEC-307 §7: Python definition + JSON declaration are dual
        forms; the loader fails the startup on any divergence — so a
        green load IS the consistency proof, pinned here explicitly."""
        assert builtin == python_builtin_rules()


class TestDualFormConsistency:
    """The dual-form check itself (pure function, doctored input)."""

    def test_doctored_document_fails_the_load_check(self):
        documents = [
            rule.model_dump(mode="json") for rule in python_builtin_rules()
        ]
        doctored = [dict(document) for document in documents]
        doctored[0]["priority"] = 99  # JSON drifted from the Python form
        parsed = tuple(parse_rule(document) for document in doctored)
        with pytest.raises(RuleDefinitionError) as excinfo:
            validate_ruleset(parsed, documents=doctored)
        assert "dual form" in str(excinfo.value)

    def test_missing_python_counterpart_fails_the_check(self):
        documents = [
            rule.model_dump(mode="json") for rule in python_builtin_rules()
        ]
        documents.append(documents[0] | {"rule_id": "DIA-EXTRA", "code": "DIAG_EXTRA"})
        parsed = tuple(parse_rule(document) for document in documents)
        with pytest.raises(RuleDefinitionError):
            validate_ruleset(parsed, documents=documents)

    def test_non_canonical_json_document_fails_the_check(self):
        """The JSON declaration must be the canonical dump — equivalent
        but non-canonical shapes (added suppression default) are refused
        so the shipped files stay the declaration of record."""
        documents = [
            rule.model_dump(mode="json") for rule in python_builtin_rules()
        ]
        # Dropping an explicit-null optional key keeps the document
        # semantically equivalent but NOT the canonical dump.
        del documents[0]["match"]["window"]
        parsed = tuple(parse_rule(document) for document in documents)
        with pytest.raises(RuleDefinitionError):
            validate_ruleset(parsed, documents=documents)


class TestSchemaDocument:
    """The rule declaration JSON schema (SPEC-307 §12 deliverable)."""

    def test_schema_document_declares_the_closed_shape(self):
        schema = json.loads(
            repo_root().joinpath(*SCHEMA_RELPATH).read_text(encoding="utf-8")
        )  # io-ok: the in-repo authoritative schema document is the artifact under test (SPEC-307 §12)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["title"] == "Diagnostic Rule Declaration"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) >= {
            "rule_id",
            "rule_version",
            "code",
            "priority",
            "severity",
            "confidence",
            "title",
            "summary_template",
            "match",
            "suppression",
            "suggested_actions",
            "expected_evidence",
        }
        assert schema["properties"]["severity"]["enum"] == [
            "info",
            "warning",
            "error",
            "critical",
        ]
        assert schema["properties"]["confidence"]["enum"] == ["low", "medium", "high"]
        defs = schema["$defs"]
        match_schema = defs["match_spec"]
        assert match_schema["properties"]["event_type"]["type"] == "string"
        predicate_schema = defs["field_predicate"]
        assert predicate_schema["properties"]["op"]["enum"] == ["eq", "gt", "lt", "exists"]
        assert predicate_schema["additionalProperties"] is False
        window_schema = defs["window_aggregate"]
        assert window_schema["properties"]["aggregation"]["enum"] == ["count", "rate"]
        assert window_schema["properties"]["scope"]["enum"] == ["run"]
        suppression_schema = defs["suppression_spec"]
        assert suppression_schema["properties"]["key"]["const"] == ["code", "node_id"]
        assert suppression_schema["properties"]["window"]["const"] == "per_run"

    def test_builtin_rules_match_the_schema_required_shape(self):
        schema = json.loads(
            repo_root().joinpath(*SCHEMA_RELPATH).read_text(encoding="utf-8")
        )  # io-ok: schema document under test (SPEC-307 §12)
        for rule in load_builtin_rules():
            dump = rule.model_dump(mode="json")
            assert set(dump) <= set(schema["properties"])
            for field in schema["required"]:
                assert field in dump, field
            assert dump["severity"] in schema["properties"]["severity"]["enum"]
            assert dump["confidence"] in schema["properties"]["confidence"]["enum"]
            assert (
                dump["suppression"]["key"]
                == schema["$defs"]["suppression_spec"]["properties"]["key"]["const"]
            )


class TestBuiltinRuleSet:
    """SPEC-307 §7: runtime disable switch over the static ruleset."""

    def test_default_ruleset_is_all_enabled(self):
        from domain.diagnosis.rules import BuiltinRuleSet

        rules = BuiltinRuleSet().rules()
        assert len(rules) == 4
        assert all(rule.enabled for rule in rules)

    def test_disabled_rule_is_flagged_not_removed(self):
        from domain.diagnosis.rules import BuiltinRuleSet

        rules = BuiltinRuleSet(
            disabled_rule_ids=["DIA-CC-DISCONTINUITY"]
        ).rules()
        by_id = {rule.rule_id: rule for rule in rules}
        assert len(rules) == 4  # the set keeps the rule visible
        assert by_id["DIA-CC-DISCONTINUITY"].enabled is False
        assert by_id["DIA-PAT-MISSING"].enabled is True
        # Everything except the switch stays byte-identical.
        original = {r.rule_id: r for r in BuiltinRuleSet().rules()}
        for rule_id, rule in by_id.items():
            assert rule.model_dump(mode="json", exclude={"enabled"}) == original[
                rule_id
            ].model_dump(mode="json", exclude={"enabled"})

    def test_unknown_disabled_id_fails_fast(self):
        from domain.diagnosis.rules import BuiltinRuleSet

        with pytest.raises(RuleDefinitionError):
            BuiltinRuleSet(disabled_rule_ids=["DIA-NOT-THERE"])


class TestRulesProvider:
    """The DiagnosisService ``rules_provider`` seam (no hot reload, §7)."""

    def test_provider_returns_the_builtin_ruleset(self):
        from domain.diagnosis.rules import builtin_rules_provider

        rules = builtin_rules_provider()
        assert len(rules) == 4
        for rule in rules:
            # Structural conformance with the #54 EvaluationRule face.
            for attribute in (
                "rule_id",
                "rule_version",
                "code",
                "priority",
                "severity",
                "confidence",
                "title",
                "suggested_actions",
                "expected_evidence",
                "matches",
            ):
                assert hasattr(rule, attribute), attribute

    def test_provider_loads_once_no_hot_reload(self):
        from domain.diagnosis.rules import builtin_rules_provider

        first = builtin_rules_provider()
        second = builtin_rules_provider()
        assert first == second
        assert all(a is b for a, b in zip(first, second))
