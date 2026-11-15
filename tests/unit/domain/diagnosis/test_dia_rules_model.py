"""SPEC-307 §3/§4 diagnostic rule model unit tests (ticket #55,
REQ-DIA-307-001).

The declarative red line (SPEC-307 §4): MatchSpec is a FINITE primitive
set — ``event_type`` selector, ``eq/gt/lt/exists`` field predicates over
payload and correlation fields, ``count/rate`` window aggregates,
``pid``/``node_id`` grouping keys. Anything executable (expression
strings, attribute access in templates, unknown operators, open field
sets) is an implementation defect and must be refused at construction.

The ``matches()`` interpreter semantics pinned here mirror the sanctioned
shared-fixture contract (``tests._support.diagnosis_fixtures``): payload
keys ``artifact_id``/``pid``/``packet_index`` anchor the SPEC-306 §6
evidence chain — a hit without the full triple produces no match, because
a candidate without an artifact anchor cannot exist.

Pure logic: in-memory records only, no I/O, no wall clock (tests/README
§1/§4).
"""

import pytest
from pydantic import ValidationError

from domain.diagnosis.engine import ObservationRecord
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.rules import (
    DiagnosticRule,
    FieldPredicate,
    MatchSpec,
    RuleDefinitionError,
    SuppressionSpec,
    WindowAggregate,
)
from tests._support.diagnosis_fixtures import observation_record


def _psi_record(**overrides) -> ObservationRecord:
    payload = {
        "source": "internal_parser",
        "confidence": "parsed",
        "pid": 0,
        "section": "PAT",
        "present": False,
        "artifact_id": "a-0001",
        "packet_index": 12_000,
    }
    payload.update(overrides.pop("payload", {}))
    return observation_record(
        journal_seq=overrides.pop("journal_seq", 42),
        event_type=overrides.pop("event_type", "ts.psi_section_observed"),
        payload=payload,
        node_id=overrides.pop("node_id", "mux-0"),
        pid=overrides.pop("pid", 0),
        **overrides,
    )


def _spec(**overrides) -> MatchSpec:
    values = dict(
        event_type="ts.psi_section_observed",
        predicates=(
            FieldPredicate(field="payload.section", op="eq", value="PAT"),
            FieldPredicate(field="payload.present", op="eq", value=False),
        ),
    )
    values.update(overrides)
    return MatchSpec(**values)


def _rule(**overrides) -> DiagnosticRule:
    values = dict(
        rule_id="DIA-TEST",
        rule_version="1.0.0",
        code="DIAG_TEST",
        priority=10,
        severity="error",
        confidence="high",
        title="Test rule",
        summary_template="PAT gap at packet {packet_index}",
        match=_spec(),
        suggested_actions=("Act",),
        expected_evidence=("ts.psi_section_observed",),
    )
    values.update(overrides)
    return DiagnosticRule(**values)


class TestFieldPredicateContract:
    """The predicate vocabulary is closed (SPEC-307 §4)."""

    def test_eq_predicate_on_payload_field_constructs(self):
        predicate = FieldPredicate(field="payload.section", op="eq", value="PAT")
        assert predicate.op == "eq"

    def test_correlation_field_predicate_constructs(self):
        predicate = FieldPredicate(field="correlation.pid", op="eq", value=0)
        assert predicate.field == "correlation.pid"

    def test_unknown_op_is_refused(self):
        with pytest.raises(ValidationError):
            FieldPredicate(field="payload.section", op="regex", value="P.*")

    def test_exists_requires_no_value(self):
        with pytest.raises(RuleDefinitionError):
            FieldPredicate(field="payload.expected_cc", op="exists", value=5)

    def test_eq_requires_a_value_field(self):
        with pytest.raises(RuleDefinitionError):
            FieldPredicate(field="payload.section", op="eq")

    def test_gt_requires_numeric_value(self):
        with pytest.raises(RuleDefinitionError):
            FieldPredicate(field="payload.count_total", op="gt", value="many")

    def test_gt_rejects_bool_value(self):
        # bool is an int subclass but not a number in the predicate sense.
        with pytest.raises(RuleDefinitionError):
            FieldPredicate(field="payload.count_total", op="gt", value=True)

    def test_field_path_must_be_payload_or_correlation(self):
        for bad in ("events[0].pid", "header.pid", "payload.", "correlation."):
            with pytest.raises(RuleDefinitionError):
                FieldPredicate(field=bad, op="exists")

    def test_correlation_predicate_keys_are_the_addressing_dual_form(self):
        """MVP predicates resolve the ADR-0006 decision-3 addressing hops
        (node_id/pid) — the only correlation fields the engine's
        ObservationRecord carries; the wider correlation block stays
        additive (SPEC-307 §4 review clause)."""
        for bad in (
            "correlation.not_a_correlation_key",
            "correlation.trace_id",
            "correlation.fault_id",
            "correlation.service_id",
        ):
            with pytest.raises(RuleDefinitionError):
                FieldPredicate(field=bad, op="exists")

    def test_correlation_node_id_predicate_constructs(self):
        assert FieldPredicate(field="correlation.node_id", op="exists")


class TestMatchSpecContract:
    def test_event_type_must_be_registered(self):
        with pytest.raises(RuleDefinitionError):
            _spec(event_type="ts.made_up_event")

    def test_registered_ts_event_type_is_accepted(self):
        assert _spec().event_type == "ts.psi_section_observed"

    def test_group_by_vocabulary_is_pid_node_id(self):
        assert _spec(group_by=("pid", "node_id")).group_by == ("pid", "node_id")
        with pytest.raises(ValidationError):
            _spec(group_by=("payload.pid",))
        with pytest.raises(RuleDefinitionError):
            _spec(group_by=("node_id", "node_id"))

    def test_group_by_cannot_be_empty(self):
        with pytest.raises(RuleDefinitionError):
            _spec(group_by=())

    def test_default_group_by_is_node_id(self):
        assert _spec().group_by == ("node_id",)

    def test_window_scope_mvp_is_run(self):
        with pytest.raises(ValidationError):
            _spec(window=WindowAggregate(aggregation="count", scope="interval", min_count=2))

    def test_window_count_shape(self):
        window = WindowAggregate(aggregation="count", scope="run", min_count=2)
        assert window.min_count == 2
        with pytest.raises(ValidationError):
            WindowAggregate(aggregation="count", scope="run", min_count=0)

    def test_window_rate_shape(self):
        window = WindowAggregate(aggregation="rate", scope="run", min_rate=0.5)
        assert window.min_rate == 0.5
        for bad_rate in (0.0, 1.5, -0.1):
            with pytest.raises(RuleDefinitionError):
                WindowAggregate(aggregation="rate", scope="run", min_rate=bad_rate)

    def test_window_count_and_rate_are_mutually_exclusive(self):
        with pytest.raises(RuleDefinitionError):
            WindowAggregate(aggregation="count", min_count=2, min_rate=0.5)
        with pytest.raises(RuleDefinitionError):
            WindowAggregate(aggregation="rate", min_count=2, min_rate=0.5)
        with pytest.raises(RuleDefinitionError):
            WindowAggregate(aggregation="rate")
        with pytest.raises(RuleDefinitionError):
            WindowAggregate(aggregation="count")


class TestSuppressionSpecMvp:
    """SPEC-307 §5 MVP-fixed suppression declaration."""

    def test_default_is_the_fixed_mvp_values(self):
        suppression = SuppressionSpec()
        assert suppression.key == ("code", "node_id")
        assert suppression.window == "per_run"

    def test_other_keys_are_refused(self):
        # A type-valid but semantically deviant key shape hits the §5
        # fixed-value contract; an out-of-vocabulary member hits the
        # pydantic literal layer first.
        with pytest.raises(RuleDefinitionError):
            SuppressionSpec(key=("code",))
        with pytest.raises(ValidationError):
            SuppressionSpec(key=("code", "pid"))

    def test_other_windows_are_refused(self):
        with pytest.raises(ValidationError):
            SuppressionSpec(window="per_session")


class TestDiagnosticRuleShape:
    """SPEC-307 §3 field contract (identity, vocabularies, red line)."""

    def test_minimal_rule_constructs_with_defaults(self):
        rule = _rule()
        assert rule.rule_id == "DIA-TEST"
        assert rule.suppression == SuppressionSpec()
        assert rule.enabled is True

    def test_severity_and_confidence_are_the_static_vocabularies(self):
        rule = _rule(severity="warning", confidence="medium")
        assert rule.severity is DiagnosisSeverity.WARNING
        assert rule.confidence is DiagnosisConfidence.MEDIUM
        with pytest.raises(ValidationError):
            _rule(severity="severe")
        with pytest.raises(ValidationError):
            _rule(confidence="certain")

    def test_rule_id_is_a_semantic_slug(self):
        assert _rule(rule_id="DIA-CC-DISCONTINUITY").rule_id
        with pytest.raises(ValidationError):
            _rule(rule_id="dia-test")

    def test_rule_version_is_semver(self):
        assert _rule(rule_version="1.0.0").rule_version == "1.0.0"
        for bad in ("1.0", "v1.0.0", "one.two.three"):
            with pytest.raises(ValidationError):
                _rule(rule_version=bad)

    def test_code_is_uppercase_snake(self):
        assert _rule(code="DIAG_PAT_MISSING").code
        with pytest.raises(ValidationError):
            _rule(code="diag_pat_missing")

    def test_expected_evidence_entries_must_be_registered(self):
        with pytest.raises(RuleDefinitionError):
            _rule(expected_evidence=("ts.made_up_event",))

    def test_unknown_fields_are_refused_no_expression_escape_hatch(self):
        """The declarative red line: no field can smuggle executable
        semantics — an ``expression`` (or any unknown) key is refused."""
        document = _rule().model_dump(mode="json")
        document["match"]["expression"] = "payload.section == 'PAT'"
        with pytest.raises(ValidationError):
            MatchSpec.model_validate(document["match"])
        document_rule = _rule().model_dump(mode="json")
        document_rule["expression"] = "True"
        with pytest.raises(ValidationError):
            type(_rule()).model_validate(document_rule)

    def test_rules_are_frozen(self):
        rule = _rule()
        with pytest.raises(ValidationError):
            rule.priority = 99

    def test_summary_template_must_parse(self):
        with pytest.raises(RuleDefinitionError):
            _rule(summary_template="PAT gap at packet {packet_index")

    def test_summary_template_rejects_attribute_and_index_access(self):
        with pytest.raises(RuleDefinitionError):
            _rule(summary_template="leak {pid.__class__}")
        with pytest.raises(RuleDefinitionError):
            _rule(summary_template="leak {payload[0]}")


class TestInterpreterSemantics:
    """``matches()`` — the model→EvaluationRule adapter (the verdict
    method is deliberately NOT named ``match``: SPEC-307 §3 reserves
    ``match`` for the declarative field; ticket #54 protocol)."""

    def test_matches_on_payload_eq_predicates(self):
        rule = _rule()
        hits = rule.matches((_psi_record(),))
        assert len(hits) == 1
        assert hits[0].journal_seq == 42
        assert hits[0].event_type == "ts.psi_section_observed"

    def test_non_matching_payload_produces_no_hit(self):
        rule = _rule()
        assert rule.matches((_psi_record(payload={"present": True}),)) == ()

    def test_matches_on_correlation_eq_predicate(self):
        rule = _rule(
            match=_spec(
                predicates=(
                    FieldPredicate(field="correlation.pid", op="eq", value=256),
                )
            ),
            summary_template="CC hit at packet {packet_index}",
        )
        assert rule.matches((_psi_record(pid=256, node_id="mux-0"),))
        assert rule.matches((_psi_record(pid=0),)) == ()

    def test_matches_on_gt_and_lt_predicates(self):
        rule = _rule(
            match=_spec(
                predicates=(
                    FieldPredicate(field="payload.packet_index", op="gt", value=100),
                    FieldPredicate(field="payload.packet_index", op="lt", value=20_000),
                )
            )
        )
        assert rule.matches((_psi_record(),))
        assert rule.matches((_psi_record(payload={"packet_index": 50}),)) == ()

    def test_matches_on_exists_predicates(self):
        rule = _rule(
            match=_spec(
                predicates=(
                    FieldPredicate(field="payload.expected_cc", op="exists"),
                )
            ),
            summary_template="CC {expected_cc}->{actual_cc} at {packet_index}",
        )
        assert rule.matches((_psi_record(payload={"expected_cc": 5, "actual_cc": 8}),))
        assert rule.matches((_psi_record(),)) == ()

    def test_event_type_filters_records(self):
        rule = _rule()
        other = observation_record(
            journal_seq=7,
            event_type="ts.continuity_error",
            payload={
                "source": "internal_parser",
                "confidence": "parsed",
                "pid": 0,
                "section": "PAT",
                "present": False,
                "artifact_id": "a-0001",
                "packet_index": 1,
            },
        )
        assert rule.matches((other,)) == ()

    def test_hit_without_evidence_triple_produces_no_match(self):
        """A candidate cannot exist without an artifact anchor (SPEC-306
        §6): a record lacking artifact_id/packet_index never grounds a
        hit, even when the declarative predicates hold."""
        rule = _rule()
        anchorless = _psi_record(payload={"artifact_id": None, "packet_index": None})
        assert rule.matches((anchorless,)) == ()

    def test_matches_are_ordered_by_journal_seq(self):
        rule = _rule(
            match=MatchSpec(event_type="ts.psi_section_observed"),
            summary_template="hit {packet_index}",
        )
        records = (
            _psi_record(journal_seq=9, payload={"packet_index": 3}),
            _psi_record(journal_seq=2, payload={"packet_index": 1}),
            _psi_record(journal_seq=5, payload={"packet_index": 2}),
        )
        hits = rule.matches(records)
        assert [hit.journal_seq for hit in hits] == [2, 5, 9]

    def test_summary_is_rendered_from_the_payload(self):
        rule = _rule(summary_template="PAT gap at packet {packet_index}")
        hit = rule.matches((_psi_record(),))[0]
        assert "12000" in hit.summary

    def test_summary_with_unknown_key_falls_back_to_the_template(self):
        rule = _rule(summary_template="PAT gap with {no_such_key}")
        hit = rule.matches((_psi_record(),))[0]
        assert hit.summary == "PAT gap with {no_such_key}"

    def test_matches_are_deterministic(self):
        rule = _rule()
        records = (_psi_record(),)
        assert rule.matches(records) == rule.matches(records)

    def test_match_attribute_is_the_declarative_field(self):
        rule = _rule()
        assert isinstance(rule.match, MatchSpec)
        assert not hasattr(rule, "match_")
        # The verdict is a method named matches (EvaluationRule face).
        assert callable(rule.matches)


class TestWindowAggregatesInterpreter:
    """SPEC-307 §4 window aggregates: count/rate over a per-run window,
    computed per declared grouping key set."""

    def test_no_window_means_any_single_qualifying_hit_matches(self):
        rule = _rule(match=MatchSpec(event_type="ts.psi_section_observed"))
        assert len(rule.matches((_psi_record(),))) == 1

    def test_count_below_threshold_produces_no_hit(self):
        rule = _rule(
            match=_spec(
                window=WindowAggregate(aggregation="count", scope="run", min_count=2)
            )
        )
        assert rule.matches((_psi_record(),)) == ()

    def test_count_at_threshold_matches_all_qualifying_records(self):
        rule = _rule(
            match=_spec(
                window=WindowAggregate(aggregation="count", scope="run", min_count=2)
            )
        )
        records = (_psi_record(journal_seq=1), _psi_record(journal_seq=2))
        hits = rule.matches(records)
        assert [hit.journal_seq for hit in hits] == [1, 2]

    def test_count_is_grouped_by_the_declared_keys(self):
        """Two qualifying hits on DIFFERENT pids are two groups of one —
        the threshold is not met within either group."""
        rule = _rule(
            match=_spec(
                group_by=("node_id", "pid"),
                window=WindowAggregate(aggregation="count", scope="run", min_count=2),
            )
        )
        records = (
            _psi_record(journal_seq=1, pid=0),
            _psi_record(journal_seq=2, pid=100),
        )
        assert rule.matches(records) == ()

    def test_rate_at_threshold_matches(self):
        rule = _rule(
            match=_spec(
                window=WindowAggregate(aggregation="rate", scope="run", min_rate=0.5)
            )
        )
        qualifying = (_psi_record(journal_seq=1), _psi_record(journal_seq=2))
        non_qualifying = _psi_record(
            journal_seq=3, payload={"present": True}
        )
        hits = rule.matches((*qualifying, non_qualifying))
        assert [hit.journal_seq for hit in hits] == [1, 2]

    def test_rate_below_threshold_produces_no_hit(self):
        rule = _rule(
            match=_spec(
                window=WindowAggregate(aggregation="rate", scope="run", min_rate=0.5)
            )
        )
        qualifying = _psi_record(journal_seq=1)
        non_qualifying = (
            _psi_record(journal_seq=2, payload={"present": True}),
            _psi_record(journal_seq=3, payload={"present": True}),
        )
        assert rule.matches((qualifying, *non_qualifying)) == ()

    def test_rate_ignores_other_event_types_in_the_denominator(self):
        """The rate window is over records of the rule's event type only."""
        rule = _rule(
            match=_spec(
                window=WindowAggregate(aggregation="rate", scope="run", min_rate=0.5)
            )
        )
        qualifying = (_psi_record(journal_seq=1), _psi_record(journal_seq=2))
        other_type = observation_record(
            journal_seq=3,
            event_type="ts.continuity_error",
            payload={
                "source": "internal_parser",
                "confidence": "parsed",
                "pid": 0,
                "artifact_id": "a-0001",
                "packet_index": 2,
            },
        )
        hits = rule.matches((*qualifying, other_type))
        assert [hit.journal_seq for hit in hits] == [1, 2]


class TestVersionBumpSemantics:
    """SPEC-307 §7: a rule-set change is a NEW rule_version — the bump
    must not alter the existing semantics."""

    def test_bumping_rule_version_keeps_matching_semantics_identical(self):
        old = _rule(rule_version="1.0.0")
        new = _rule(rule_version="1.1.0")
        assert old.rule_version != new.rule_version
        assert old.model_dump(mode="json", exclude={"rule_version"}) == new.model_dump(
            mode="json", exclude={"rule_version"}
        )
        records = (_psi_record(),)
        assert old.matches(records) == new.matches(records)
