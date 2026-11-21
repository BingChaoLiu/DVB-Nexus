"""Declarative health-rule model (SPEC-304 §4, ticket #52).

REQ-OBS-304-001: rules are declarative and validated; NO arbitrary Python
expression or eval exists anywhere in the model surface — the condition is a
finite operator/threshold pair with an EXPLICIT unit, and thresholds are
profile-specific (the rule set carries the profile name), never hardcoded
universal DVB compliance limits.

Fail-fast posture: a rule that fails validation raises
``AlertError(OBS_RULE_INVALID)`` (SPEC-304 §10 per-code registration) with a
path-addressed detail — the same startup-rejection discipline the diagnostic
rules (#55, SPEC-307 §8) apply.
"""

import math

import pytest

from application.observation.alerts.errors import AlertError, OBS_RULE_INVALID
from application.observation.alerts.rules import (
    ComparisonOperator,
    Condition,
    HealthRule,
    HealthRuleSet,
    MissingDataPolicy,
    RuleAggregation,
    default_rule_set,
    validate_health_rule,
)
from domain.observation import AlertSeverity, HealthDimension

_NANOSECOND = "ns"


def _open_condition(**overrides) -> Condition:
    fields = {
        "operator": ComparisonOperator.GT,
        "threshold": 50_000_000.0,
        "unit": _NANOSECOND,
    }
    fields.update(overrides)
    return Condition(**fields)


def _rule(**overrides) -> HealthRule:
    fields = {
        "rule_id": "PCR_JITTER_HIGH",
        "version": "1.0.0",
        "name": "PCR jitter p95 high",
        "description": "p95 PCR jitter stayed above the profile threshold",
        "dimension": HealthDimension.TIMING,
        "severity": AlertSeverity.WARNING,
        "input_metric": "ts.pcr_jitter_ns",
        "aggregation": RuleAggregation.P95,
        "window_ns": 10_000_000_000,
        "min_samples": 1,
        "freshness_ns": 5_000_000_000,
        "for_duration_ns": 2_000_000_000,
        "resolve_duration_ns": 5_000_000_000,
        "reopen_window_ns": 60_000_000_000,
        "open_condition": _open_condition(),
        "close_condition": Condition(
            operator=ComparisonOperator.LTE,
            threshold=30_000_000.0,
            unit=_NANOSECOND,
        ),
    }
    fields.update(overrides)
    return HealthRule(**fields)


class TestDeclarativeSurface:
    """REQ-OBS-304-001: 禁 eval/任意表达式 — the surface cannot express one."""

    def test_condition_has_no_expression_field(self) -> None:
        # The only knobs are a finite operator + threshold + unit.
        assert set(Condition.__dataclass_fields__) == {
            "operator",
            "threshold",
            "unit",
        }

    def test_operator_enum_is_finite(self) -> None:
        assert {op.value for op in ComparisonOperator} == {"gt", "gte", "lt", "lte"}

    def test_expression_strings_cannot_become_operators(self) -> None:
        with pytest.raises(ValueError):
            ComparisonOperator("eval('__import__(\"os\")')")

    def test_aggregation_enum_is_finite(self) -> None:
        assert {op.value for op in RuleAggregation} == {
            "last",
            "max",
            "avg",
            "p95",
            "increase",
        }

    def test_missing_data_policy_is_finite(self) -> None:
        assert {policy.value for policy in MissingDataPolicy} == {
            "unknown",
            "ignore",
        }


class TestRuleValidation:
    """REQ-OBS-304-001: 经校验 — OBS_RULE_INVALID per-code registrations."""

    def test_valid_rule_passes(self) -> None:
        validate_health_rule(_rule())

    def test_missing_threshold_unit_is_rejected(self) -> None:
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(
                _rule(open_condition=_open_condition(unit=""))
            )
        assert excinfo.value.error_code == OBS_RULE_INVALID
        assert excinfo.value.details["field"] == "open_condition.unit"

    def test_non_finite_threshold_is_rejected(self) -> None:
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(
                _rule(open_condition=_open_condition(threshold=math.nan))
            )
        assert excinfo.value.error_code == OBS_RULE_INVALID

    def test_zero_window_is_rejected(self) -> None:
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(_rule(window_ns=0))
        assert excinfo.value.details["field"] == "window_ns"

    def test_zero_min_samples_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(min_samples=0))

    def test_zero_freshness_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(freshness_ns=0))

    def test_unknown_dimension_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(dimension="traffic"))

    def test_unknown_severity_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(severity="blocker"))

    def test_non_dotted_metric_name_is_rejected(self) -> None:
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(_rule(input_metric="pcr_jitter"))
        assert excinfo.value.details["field"] == "input_metric"

    def test_volatile_group_dimension_is_rejected(self) -> None:
        # Fingerprint grouping accepts ONLY the stable baseline dimensions
        # (REQ-OBS-304-004: 不含易变值).
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(_rule(group_dimensions=("payload_text",)))
        assert excinfo.value.details["field"] == "group_dimensions"

    def test_session_id_is_implicit_in_group_dimensions(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(group_dimensions=("session_id",)))

    def test_inverted_hysteresis_band_is_rejected(self) -> None:
        # gt opens above 50 but closes only above 80: any value above 80
        # satisfies both conditions — the pair overlaps, rejected at
        # declaration time.
        with pytest.raises(AlertError) as excinfo:
            validate_health_rule(
                _rule(
                    close_condition=Condition(
                        operator=ComparisonOperator.GTE,
                        threshold=80_000_000.0,
                        unit=_NANOSECOND,
                    )
                )
            )
        assert excinfo.value.details["field"] == "close_condition"

    def test_same_family_close_condition_is_rejected(self) -> None:
        # A high-side rule closing on gt/gte never stops firing: the close
        # condition must be the opposite family (lt/lte).
        with pytest.raises(AlertError):
            validate_health_rule(
                _rule(
                    close_condition=Condition(
                        operator=ComparisonOperator.GTE,
                        threshold=10.0,
                        unit=_NANOSECOND,
                    )
                )
            )

    def test_touching_strict_pair_is_valid_hysteresis(self) -> None:
        # gt 500 open / lte 500 close: no value satisfies both, the pair is
        # a valid zero-width band (PSI_STALE shape).
        validate_health_rule(
            _rule(
                open_condition=_open_condition(threshold=500.0),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE,
                    threshold=500.0,
                    unit=_NANOSECOND,
                ),
            )
        )

    def test_inclusive_pair_touching_is_rejected(self) -> None:
        # gte 500 open / lte 500 close: value 500 satisfies BOTH — rejected.
        with pytest.raises(AlertError):
            validate_health_rule(
                _rule(
                    open_condition=_open_condition(
                        operator=ComparisonOperator.GTE, threshold=500.0
                    ),
                    close_condition=Condition(
                        operator=ComparisonOperator.LTE,
                        threshold=500.0,
                        unit=_NANOSECOND,
                    ),
                )
            )

    def test_empty_rule_id_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(rule_id=""))

    def test_blank_description_is_rejected(self) -> None:
        with pytest.raises(AlertError):
            validate_health_rule(_rule(description="  "))


class TestRuleSet:
    """Rule-set container: fail-fast, unique ids, declared profile."""

    def test_set_requires_a_profile_name(self) -> None:
        # REQ-OBS-304-001: thresholds are profile-specific — the set carries
        # the profile so a threshold can never masquerade as a universal
        # DVB compliance limit.
        with pytest.raises(AlertError):
            HealthRuleSet(ruleset_id="mvp", version="1.0.0", profile="", rules=(_rule(),))

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        with pytest.raises(AlertError) as excinfo:
            HealthRuleSet(
                ruleset_id="mvp",
                version="1.0.0",
                profile="mvp-sandbox",
                rules=(_rule(), _rule()),
            )
        assert excinfo.value.error_code == OBS_RULE_INVALID

    def test_set_lookup_by_id(self) -> None:
        rule_set = HealthRuleSet(
            ruleset_id="mvp", version="1.0.0", profile="mvp-sandbox", rules=(_rule(),)
        )
        assert rule_set.rule("PCR_JITTER_HIGH") is not None
        assert rule_set.rule("NOPE") is None


class TestDefaultRuleSet:
    """SPEC-304 §8: the six default rules ship declaratively, plus the two
    Phase 3 alert registrations (SPEC-304 §Phase3, ticket #166)."""

    def test_default_set_has_exactly_the_six_spec_rules(self) -> None:
        rule_set = default_rule_set()
        assert rule_set.profile == "mvp-sandbox"
        assert tuple(sorted(rule.rule_id for rule in rule_set.rules)) == (
            "BER_SEVERE",
            "OBS_CONSUMER_LAG_HIGH",
            "OBS_STORAGE_WRITE_FAILURE",
            "PCR_JITTER_HIGH",
            "PSI_STALE",
            "TOPOLOGY_PATH_DOWN",
            "TS_CC_ERROR_RATE_HIGH",
            "TUNER_UNLOCKED",
        )

    def test_every_default_rule_covers_one_dimension(self) -> None:
        rule_set = default_rule_set()
        dimensions = {rule.rule_id: rule.dimension for rule in rule_set.rules}
        assert dimensions == {
            "TS_CC_ERROR_RATE_HIGH": HealthDimension.TRANSPORT,
            "PCR_JITTER_HIGH": HealthDimension.TIMING,
            "PSI_STALE": HealthDimension.SERVICE,
            "TOPOLOGY_PATH_DOWN": HealthDimension.TOPOLOGY,
            "OBS_CONSUMER_LAG_HIGH": HealthDimension.OBSERVATION,
            "OBS_STORAGE_WRITE_FAILURE": HealthDimension.OBSERVATION,
            "TUNER_UNLOCKED": HealthDimension.TOPOLOGY,
            "BER_SEVERE": HealthDimension.TOPOLOGY,
        }

    def test_every_default_rule_validates(self) -> None:
        for rule in default_rule_set().rules:
            validate_health_rule(rule)

    def test_every_default_rule_declares_a_threshold_unit(self) -> None:
        for rule in default_rule_set().rules:
            assert rule.open_condition.unit, rule.rule_id
            if rule.close_condition is not None:
                assert rule.close_condition.unit, rule.rule_id


class TestPhase3AlertRules:
    """SPEC-304 §Phase3 registrations (ticket #166): TUNER_UNLOCKED (warning)
    and BER_SEVERE (error) read the state_evaluator tuner-state gauges
    (``tuner.lock_state``/``tuner.ber_state``) through the unchanged metric
    input face — the ``elevated`` tier deliberately declares NO rule (the
    SPEC-307 combination judgement owns it, SPEC-304 §Phase3 elevated 不告警).

    Comparison semantics ride the frozen discrete-state codes (catalog
    Phase 3 note): lock_state locked=0/unlocked=1, ber_state
    normal=0/elevated=1/severe=2.  Per-node grouping (SPEC-304 §6) — the
    fingerprint dedups per (rule, node).
    """

    def test_tuner_unlocked_registration_is_pinned(self) -> None:
        rule = default_rule_set().rule("TUNER_UNLOCKED")
        assert rule is not None
        assert rule.version == "1.0.0"
        assert rule.severity is AlertSeverity.WARNING
        assert rule.input_metric == "tuner.lock_state"
        assert rule.aggregation is RuleAggregation.LAST
        assert rule.group_dimensions == ("node_id",)
        # Alarm=1 code: unlocked (1) opens, locked (0) closes.
        assert rule.open_condition == Condition(
            operator=ComparisonOperator.GT, threshold=0, unit="1"
        )
        assert rule.close_condition == Condition(
            operator=ComparisonOperator.LTE, threshold=0, unit="1"
        )

    def test_ber_severe_registration_is_pinned(self) -> None:
        rule = default_rule_set().rule("BER_SEVERE")
        assert rule is not None
        assert rule.version == "1.0.0"
        assert rule.severity is AlertSeverity.ERROR
        assert rule.input_metric == "tuner.ber_state"
        assert rule.aggregation is RuleAggregation.LAST
        assert rule.group_dimensions == ("node_id",)
        # Ordinal ladder: severe (2) opens, elevated (1) closes — elevated
        # (1) therefore satisfies NEITHER condition (不告警) and a measured
        # close rides the same band.
        assert rule.open_condition == Condition(
            operator=ComparisonOperator.GTE, threshold=2, unit="1"
        )
        assert rule.close_condition == Condition(
            operator=ComparisonOperator.LTE, threshold=1, unit="1"
        )

    def test_state_rules_are_additive_observations_not_required_inputs(self) -> None:
        # A TS-only session has no tuner snapshots: the state rules must not
        # force the roll-up unknown (§7 required-input semantics).
        for rule_id in ("TUNER_UNLOCKED", "BER_SEVERE"):
            assert default_rule_set().rule(rule_id).required is False

    def test_no_rule_declares_the_elevated_tier(self) -> None:
        # SPEC-304 §Phase3: elevated 不告警 — the tier stays an honest gap
        # until the SPEC-307 combination judgement lands.
        assert default_rule_set().rule("BER_ELEVATED") is None

    def test_state_rules_target_registered_catalog_metrics(self) -> None:
        from application.observation.metrics.catalog import CATALOG_METRIC_NAMES

        for rule_id in ("TUNER_UNLOCKED", "BER_SEVERE"):
            assert default_rule_set().rule(rule_id).input_metric in CATALOG_METRIC_NAMES

    def test_state_rules_validate_and_stay_declarative(self) -> None:
        for rule_id in ("TUNER_UNLOCKED", "BER_SEVERE"):
            validate_health_rule(default_rule_set().rule(rule_id))
