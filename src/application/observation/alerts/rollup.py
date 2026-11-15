"""Deterministic health roll-up (SPEC-304 §7, ticket #52).

Pure reduction over one :class:`~application.observation.alerts.engine.
AlertEvaluation`'s contributions — no clock, no randomness, so the same
evaluation always reduces to the same :class:`HealthResult` (REQ-304-005).

§7 branches, applied per dimension and overall in THIS order:

1. any required CRITICAL-severity rule firing ⇒ ``critical``
   (reason ``critical_firing``);
2. any other firing rule (degraded severities) with no critical ⇒
   ``degraded`` (reason ``degraded_firing``);
3. no firing and every required input fresh ⇒ ``healthy``
   (reason ``all_clear``);
4. any required input missing or stale ⇒ ``unknown`` — never a false
   healthy (缺失 ≠ 干净). The stale reason code IS the SPEC-304 §10
   registered ``OBS_RULE_INPUT_STALE`` (this module is its raise point);
   missing uses the module-local ``input_missing`` reason.

Firing outranks degraded input completeness: a held firing on a stale input
is still a real signal — the roll-up never converts a firing alert into
``healthy`` just because the input went quiet (SPEC-304 §11 缺数据不误报
applies to recovery too).

Reason codes are informational payloads (SPEC-300 §13 shape is reserved for
errors); they ride the response next to the roll-up policy name/version and
the rule-set id/version, both mandatory on the result (§7 响应必含 roll-up
策略与规则集版本).
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.observation import (
    AlertSeverity,
    HealthDimension,
    HealthStatus,
    MetricSampleTimepoint,
    SampleSemantics,
)

from application.observation.alerts.engine import AlertEvaluation, RuleContribution
from application.observation.alerts.errors import OBS_RULE_INPUT_STALE
from application.observation.alerts.rules import HealthRuleSet


@dataclass(frozen=True)
class RollupPolicy:
    """The declared §7 reduction policy (name/version ride every response)."""

    name: str = "required-critical-first-v1"
    version: str = "1.0.0"


#: The frozen policy of this implementation (§7 响应必含).
ROLLUP_POLICY = RollupPolicy()

#: Module-local reason code: required input absent (no samples at all).
INPUT_MISSING_REASON = "input_missing"

_REASON_CRITICAL_FIRING = "critical_firing"
_REASON_DEGRADED_FIRING = "degraded_firing"
_REASON_ALL_CLEAR = "all_clear"


@dataclass(frozen=True)
class DimensionHealth:
    """One dimension's roll-up outcome (§3 健康结果必含项)."""

    dimension: HealthDimension
    status: HealthStatus
    contributing_rule_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class HealthResult:
    """The §7 roll-up response."""

    session_id: str
    clock_domain: str
    evaluated_at: MetricSampleTimepoint
    rule_set_id: str
    rule_set_version: str
    profile: str
    policy: RollupPolicy
    overall: HealthStatus
    dimensions: tuple[DimensionHealth, ...]


def roll_up(rule_set: HealthRuleSet, evaluation: AlertEvaluation) -> HealthResult:
    """Reduce one evaluation tick to the deterministic health result."""
    by_dimension: dict[HealthDimension, list[RuleContribution]] = {}
    for contribution in evaluation.contributions:
        by_dimension.setdefault(contribution.dimension, []).append(contribution)

    dimensions = tuple(
        _reduce_dimension(dimension, by_dimension[dimension])
        for dimension in sorted(by_dimension)
    )
    overall = _reduce_contributions(evaluation.contributions)
    return HealthResult(
        session_id=evaluation.session_id,
        clock_domain=evaluation.clock_domain,
        evaluated_at=MetricSampleTimepoint(
            value_ns=evaluation.now_ns,
            clock_domain=evaluation.clock_domain,
            clock_epoch=evaluation.clock_epoch,
            semantics=SampleSemantics.DERIVED,
        ),
        rule_set_id=rule_set.ruleset_id,
        rule_set_version=rule_set.version,
        profile=rule_set.profile,
        policy=ROLLUP_POLICY,
        overall=overall,
        dimensions=dimensions,
    )


def _reduce_dimension(
    dimension: HealthDimension, contributions: list[RuleContribution]
) -> DimensionHealth:
    status, reasons = _reduce_contributions(contributions), _reasons(contributions)
    firing = [c for c in contributions if c.firing]
    evidence = tuple(
        ref
        for contribution in (
            firing if firing else [c for c in contributions if c.input_status == "fresh"]
        )
        for ref in contribution.evidence_refs
    )
    contributing = tuple(
        sorted(
            {
                contribution.rule_id
                for contribution in (
                    firing
                    if firing
                    else [c for c in contributions if c.input_status != "fresh"]
                    or contributions
                )
            }
        )
    )
    return DimensionHealth(
        dimension=dimension,
        status=status,
        contributing_rule_ids=contributing,
        evidence_refs=evidence,
        reason_codes=reasons,
    )


def _reduce_contributions(contributions) -> HealthStatus:
    """§7 order: critical firing → degraded firing → unknown → healthy."""
    if any(
        c.firing and c.severity is AlertSeverity.CRITICAL for c in contributions
    ):
        return HealthStatus.CRITICAL
    if any(c.firing for c in contributions):
        return HealthStatus.DEGRADED
    if any(
        c.required
        and c.input_status != "fresh"
        for c in contributions
    ):
        return HealthStatus.UNKNOWN
    return HealthStatus.HEALTHY


def _reasons(contributions) -> tuple[str, ...]:
    reasons: list[str] = []
    if any(
        c.firing and c.severity is AlertSeverity.CRITICAL for c in contributions
    ):
        reasons.append(_REASON_CRITICAL_FIRING)
    elif any(c.firing for c in contributions):
        reasons.append(_REASON_DEGRADED_FIRING)
    for contribution in contributions:
        if not contribution.required or contribution.input_status == "fresh":
            continue
        code = (
            OBS_RULE_INPUT_STALE
            if contribution.input_status == "stale"
            else INPUT_MISSING_REASON
        )
        if code not in reasons:
            reasons.append(code)
    if not reasons:
        reasons.append(_REASON_ALL_CLEAR)
    return tuple(reasons)


__all__ = [
    "INPUT_MISSING_REASON",
    "ROLLUP_POLICY",
    "DimensionHealth",
    "HealthResult",
    "RollupPolicy",
    "roll_up",
]
