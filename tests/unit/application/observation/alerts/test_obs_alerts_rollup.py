"""Health roll-up (SPEC-304 §7, ticket #52) — deterministic reduction.

The four §7 branches:

1. 任一 required critical 规则 firing ⇒ ``critical``;
2. 存在 degraded（非 critical severity）规则 firing 且无 critical ⇒
   ``degraded``;
3. 必需输入齐全且无规则 firing ⇒ ``healthy``;
4. 必需输入缺失或过期（超出配置新鲜度）⇒ ``unknown``（never a false
   healthy — 缺失 ≠ 干净）.

Application order is pinned: firing evidence outranks degraded input
completeness (a held firing on stale input is still a real signal), and the
stale reason code IS the SPEC-304 §10 registered code
``OBS_RULE_INPUT_STALE`` (per-code registration; the roll-up is its raise
point). The response carries the roll-up policy and the rule-set version
(REQ-304-005).
"""

import pytest

from application.observation.alerts.engine import AlertEvaluation, RuleContribution
from application.observation.alerts.errors import OBS_RULE_INPUT_STALE
from application.observation.alerts.rollup import (
    INPUT_MISSING_REASON,
    ROLLUP_POLICY,
    DimensionHealth,
    HealthResult,
    roll_up,
)
from application.observation.alerts.rules import default_rule_set
from domain.observation import (
    AlertSeverity,
    AlertState,
    HealthDimension,
    HealthStatus,
    MetricSampleTimepoint,
    SampleSemantics,
)

DOMAIN = "sim:sess-1"


def contribution(
    rule_id: str,
    *,
    dimension: HealthDimension = HealthDimension.TIMING,
    severity: AlertSeverity = AlertSeverity.WARNING,
    state: AlertState = AlertState.INACTIVE,
    input_status: str = "fresh",
    evidence: tuple[str, ...] = (),
    required: bool = True,
    version: str = "1.0.0",
) -> RuleContribution:
    return RuleContribution(
        rule_id=rule_id,
        fingerprint=f"fp-{rule_id}",
        rule_version=version,
        severity=severity,
        dimension=dimension,
        group_key=(),
        state=state,
        firing=state is AlertState.FIRING,
        observed_value=1.0 if input_status == "fresh" else None,
        sample_count=1 if input_status == "fresh" else 0,
        input_status=input_status,
        evidence_refs=evidence,
        required=required,
    )


def evaluation(*contributions: RuleContribution) -> AlertEvaluation:
    return AlertEvaluation(
        session_id="sess-1",
        now_ns=8_000_000_000,
        clock_domain=DOMAIN,
        clock_epoch=0,
        transitions=(),
        contributions=tuple(contributions),
    )


class TestFourBranches:
    def test_required_critical_firing_is_critical(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(
                contribution(
                    "CRIT",
                    severity=AlertSeverity.CRITICAL,
                    state=AlertState.FIRING,
                    evidence=("metric:m:bucket-0",),
                )
            ),
        )
        assert result.overall is HealthStatus.CRITICAL
        dimension = result.dimensions[0]
        assert dimension.status is HealthStatus.CRITICAL
        assert dimension.reason_codes == ("critical_firing",)
        assert "metric:m:bucket-0" in dimension.evidence_refs

    def test_degraded_firing_without_critical_is_degraded(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(
                contribution("WARN", state=AlertState.FIRING, evidence=("e1",))
            ),
        )
        assert result.overall is HealthStatus.DEGRADED
        assert result.dimensions[0].reason_codes == ("degraded_firing",)

    def test_complete_inputs_without_firing_is_healthy(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(contribution("OK1"), contribution("OK2")),
        )
        assert result.overall is HealthStatus.HEALTHY
        assert result.dimensions[0].reason_codes == ("all_clear",)

    def test_missing_required_input_is_unknown(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(contribution("GONE", input_status="missing")),
        )
        assert result.overall is HealthStatus.UNKNOWN
        assert result.dimensions[0].reason_codes == (INPUT_MISSING_REASON,)

    def test_stale_required_input_is_unknown_with_the_registered_code(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(contribution("OLD", input_status="stale")),
        )
        assert result.overall is HealthStatus.UNKNOWN
        # Per-code registration: the roll-up is OBS_RULE_INPUT_STALE's raise
        # point (SPEC-304 §10 输入超出新鲜度 → roll-up 入 unknown).
        assert result.dimensions[0].reason_codes == (OBS_RULE_INPUT_STALE,)

    def test_firing_outranks_degraded_input_completeness(self) -> None:
        # A held firing on a stale input is a real signal: firing first.
        result = roll_up(
            default_rule_set(),
            evaluation(
                contribution("CRIT", severity=AlertSeverity.CRITICAL, state=AlertState.FIRING),
                contribution("OLD", input_status="stale"),
            ),
        )
        assert result.overall is HealthStatus.CRITICAL

    def test_non_required_rule_input_gap_does_not_force_unknown(self) -> None:
        result = roll_up(
            default_rule_set(),
            evaluation(
                contribution("GONE", input_status="missing", required=False)
            ),
        )
        assert result.overall is HealthStatus.HEALTHY


class TestResponseShape:
    """REQ-304-005: policy + rule-set version + explicit timepoint."""

    def test_result_carries_policy_and_rule_set_version(self) -> None:
        rule_set = default_rule_set()
        result = roll_up(rule_set, evaluation(contribution("OK")))
        assert result.rule_set_id == rule_set.ruleset_id
        assert result.rule_set_version == rule_set.version
        assert result.policy.name == ROLLUP_POLICY.name
        assert result.policy.version == ROLLUP_POLICY.version
        assert result.profile == rule_set.profile

    def test_evaluated_at_has_explicit_clock_semantics(self) -> None:
        result = roll_up(default_rule_set(), evaluation(contribution("OK")))
        assert result.evaluated_at.clock_domain == DOMAIN
        assert result.evaluated_at.value_ns == 8_000_000_000
        assert result.evaluated_at.semantics is SampleSemantics.DERIVED

    def test_dimensions_are_sorted_deterministically(self) -> None:
        rule_set = default_rule_set()
        result = roll_up(
            rule_set,
            evaluation(
                contribution(
                    "A",
                    dimension=HealthDimension.TRANSPORT,
                    state=AlertState.FIRING,
                ),
                contribution("B", dimension=HealthDimension.OBSERVATION, input_status="stale"),
                contribution("C", dimension=HealthDimension.TIMING),
            ),
        )
        names = [entry.dimension for entry in result.dimensions]
        assert names == sorted(names)
        by_dimension = {entry.dimension: entry for entry in result.dimensions}
        assert by_dimension[HealthDimension.TRANSPORT].status is HealthStatus.DEGRADED
        assert by_dimension[HealthDimension.OBSERVATION].status is HealthStatus.UNKNOWN
        assert by_dimension[HealthDimension.TIMING].status is HealthStatus.HEALTHY
        # Overall: critical absent, degraded firing present → degraded.
        assert result.overall is HealthStatus.DEGRADED


class TestDeterminism:
    def test_same_evaluation_reduces_identically(self) -> None:
        def run() -> HealthResult:
            return roll_up(
                default_rule_set(),
                evaluation(
                    contribution("A", state=AlertState.FIRING),
                    contribution("B", input_status="stale"),
                ),
            )

        assert run() == run()

    def test_empty_rule_set_is_healthy(self) -> None:
        from application.observation.alerts.rules import HealthRuleSet

        empty = HealthRuleSet(
            ruleset_id="empty", version="1.0.0", profile="p", rules=()
        )
        result = roll_up(empty, evaluation())
        assert result.overall is HealthStatus.HEALTHY
        assert result.dimensions == ()
