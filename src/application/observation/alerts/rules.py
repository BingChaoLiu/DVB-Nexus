"""Declarative health-rule model (SPEC-304 §4, ticket #52).

REQ-OBS-304-001 — the model is DECLARATIVE ONLY: a condition is a finite
operator (``gt/gte/lt/lte``) over an aggregated scalar with an explicit
threshold unit; there is no expression string, no callable field and no
eval anywhere on the surface (the enums make expression strings
unrepresentable). Thresholds are PROFILE-specific: every
:class:`HealthRuleSet` declares its profile name, and the shipped default
set is ``mvp-sandbox`` — none of its thresholds is a universal DVB
compliance limit (SPEC-304 §4 / #6 标准核查纪律).

Rule fields (SPEC-304 §4): rule_id / version / name / description / input
metric (+ aggregation) / condition + threshold with explicit unit /
evaluation window + minimum sample count / severity + target health
dimension / open-close hysteresis / missing-data behaviour / evidence
capture policy / enabled flag / input freshness (§7: 输入缺失或过期) /
reopen window (§5: resolved 后再触发) / stable grouping dimensions (§6).

Validation is fail-fast (:func:`validate_health_rule` raises
``AlertError(OBS_RULE_INVALID)`` with a path-addressed ``field`` detail),
applied by :class:`HealthRuleSet` at registration time — the #55 startup
posture. This module owns no evaluation (that is :mod:`.engine`) and no
diagnosis semantics (brief §6 axis discipline: a firing alert is an
evidence-backed signal, never a root-cause conclusion).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from application.observation.alerts.errors import AlertError, OBS_RULE_INVALID
from domain.observation import (
    AlertSeverity,
    BASELINE_DIMENSIONS,
    HealthDimension,
)

#: Stable dotted metric identifier (same shape as the SPEC-302 catalog).
_METRIC_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: Stable rule identifier: letters/digits/underscore/dash, no dots (a rule id
#: never collides with a metric-name segment).
_RULE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")


class ComparisonOperator(str, Enum):
    """Finite declarative comparison operators (no expression escape hatch)."""

    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"

    @property
    def is_lower_bound(self) -> bool:
        """True when larger values satisfy the operator (gt/gte family)."""
        return self in (ComparisonOperator.GT, ComparisonOperator.GTE)


class RuleAggregation(str, Enum):
    """Window aggregation over the input series' samples (deterministic)."""

    LAST = "last"
    MAX = "max"
    AVG = "avg"
    P95 = "p95"
    INCREASE = "increase"


class MissingDataPolicy(str, Enum):
    """缺数据行为 (SPEC-304 §4/§11): missing/stale inputs never false-fire."""

    #: Contribute ``unknown`` to the roll-up (default; §7 必需输入缺失或过期
    #: ⇒ unknown).
    UNKNOWN = "unknown"
    #: Skip the rule for this evaluation (rule contributes nothing; if the
    #: rule is required its missing input still forces dimension unknown —
    #: the roll-up, not the rule, owns that verdict).
    IGNORE = "ignore"


class EvidencePolicy(str, Enum):
    """证据捕获策略 (SPEC-304 §4, REQ-OBS-304-006)."""

    #: Emit ``metric:<name>:bucket-<start_ns>`` refs resolvable through the
    #: metrics query face (the MVP engine's capture).
    METRIC_BUCKET = "metric_bucket"
    #: Capture no evidence refs (transient evaluation only — never used for
    #: a rule allowed to reach firing).
    NONE = "none"


@dataclass(frozen=True)
class Condition:
    """One declarative threshold: operator + finite threshold + explicit unit.

    REQ-OBS-304-001: the unit is mandatory — a unitless threshold cannot be
    declared (SPEC-304 §4 阈值显式单位).
    """

    operator: ComparisonOperator
    threshold: float
    unit: str

    def satisfied_by(self, value: float) -> bool:
        """Pure comparison; the only "execution" a condition can do."""
        if self.operator is ComparisonOperator.GT:
            return value > self.threshold
        if self.operator is ComparisonOperator.GTE:
            return value >= self.threshold
        if self.operator is ComparisonOperator.LT:
            return value < self.threshold
        return value <= self.threshold


@dataclass(frozen=True)
class HealthRule:
    """One declarative health rule (SPEC-304 §4 field list)."""

    rule_id: str
    version: str
    name: str
    #: The DECLARED interpretation (static text; the engine never generates
    #: interpretive content — REQ-OBS-304-006 keeps measured facts and
    #: inferred interpretation distinguishable).
    description: str
    dimension: HealthDimension
    severity: AlertSeverity
    input_metric: str
    aggregation: RuleAggregation
    window_ns: int
    min_samples: int
    #: Input freshness bound (SPEC-304 §7: beyond this the input is stale).
    freshness_ns: int
    #: pending → firing dwell (SPEC-304 §5 for_duration).
    for_duration_ns: int
    #: resolving → resolved hold (SPEC-304 §5 解除保持期).
    resolve_duration_ns: int
    #: resolved instances reopen only within this span after resolving
    #: (0 = never reopen; a later trigger creates a new instance, §5).
    reopen_window_ns: int = 0
    open_condition: Condition = field(default_factory=lambda: Condition(
        operator=ComparisonOperator.GT, threshold=0.0, unit="1"
    ))
    #: Open/close hysteresis (§4). ``None`` = close as soon as the open
    #: condition stops holding. Same operator family, threshold on the safe
    #: side of the open threshold.
    close_condition: Optional[Condition] = None
    missing_data: MissingDataPolicy = MissingDataPolicy.UNKNOWN
    evidence: EvidencePolicy = EvidencePolicy.METRIC_BUCKET
    #: Stable grouping dimensions BEYOND the implicit session scope (§6);
    #: must be a subset of the SPEC-302 baseline whitelist.
    group_dimensions: tuple[str, ...] = ()
    #: Required input for the roll-up (§7: missing required input ⇒ unknown).
    required: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class HealthRuleSet:
    """A validated, versioned, profile-scoped rule set (SPEC-304 §3/§4).

    Construction is fail-fast: every rule is validated and rule ids must be
    unique. ``profile`` documents that the thresholds belong to a specific
    deployment profile (REQ-OBS-304-001) and rides on every roll-up
    response (§7 响应必含 roll-up 策略与规则集版本).
    """

    ruleset_id: str
    version: str
    profile: str
    rules: tuple[HealthRule, ...]

    def __post_init__(self) -> None:
        if not self.profile:
            raise AlertError(
                OBS_RULE_INVALID,
                "rule set must declare its threshold profile "
                "(REQ-OBS-304-001: 阈值是 profile 特定的)",
                details={"field": "profile"},
            )
        seen: set[str] = set()
        for rule in self.rules:
            validate_health_rule(rule)
            if rule.rule_id in seen:
                raise AlertError(
                    OBS_RULE_INVALID,
                    f"duplicate rule_id {rule.rule_id!r} in rule set",
                    details={"field": "rule_id", "rule_id": rule.rule_id},
                )
            seen.add(rule.rule_id)

    def rule(self, rule_id: str) -> Optional[HealthRule]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self.rules)


def validate_health_rule(rule: HealthRule) -> None:
    """Fail-fast declaration validation — raises ``OBS_RULE_INVALID``.

    Every rejection carries a ``field`` detail so the declaration surface
    (loader/API plane) can path-address the defect (house error shape).
    """
    if not _RULE_ID_PATTERN.match(rule.rule_id):
        raise _invalid(
            "rule_id",
            rule.rule_id,
            "must match ^[A-Za-z][A-Za-z0-9_-]{2,63}$",
        )
    if not rule.version:
        raise _invalid("version", rule.version, "must be a non-empty version")
    if not rule.name.strip():
        raise _invalid("name", rule.name, "must be a non-empty name")
    if not rule.description.strip():
        # The declared interpretation is mandatory: facts vs interpretation
        # stays distinguishable (REQ-OBS-304-006).
        raise _invalid(
            "description", rule.description, "must declare the interpretation text"
        )
    if not isinstance(rule.dimension, HealthDimension):
        raise _invalid(
            "dimension", rule.dimension, f"must be a HealthDimension, got {rule.dimension!r}"
        )
    if not isinstance(rule.severity, AlertSeverity):
        raise _invalid(
            "severity", rule.severity, f"must be an AlertSeverity, got {rule.severity!r}"
        )
    if not _METRIC_NAME_PATTERN.match(rule.input_metric):
        raise _invalid(
            "input_metric", rule.input_metric, "must be a stable dotted metric name"
        )
    if not isinstance(rule.aggregation, RuleAggregation):
        raise _invalid(
            "aggregation",
            rule.aggregation,
            f"must be a RuleAggregation, got {rule.aggregation!r}",
        )
    if rule.window_ns < 1:
        raise _invalid("window_ns", rule.window_ns, "must be >= 1 ns")
    if rule.min_samples < 1:
        raise _invalid("min_samples", rule.min_samples, "must be >= 1 sample")
    if rule.freshness_ns < 1:
        raise _invalid("freshness_ns", rule.freshness_ns, "must be >= 1 ns")
    if rule.for_duration_ns < 0:
        raise _invalid("for_duration_ns", rule.for_duration_ns, "must be >= 0 ns")
    if rule.resolve_duration_ns < 0:
        raise _invalid("resolve_duration_ns", rule.resolve_duration_ns, "must be >= 0 ns")
    if rule.reopen_window_ns < 0:
        raise _invalid("reopen_window_ns", rule.reopen_window_ns, "must be >= 0 ns")
    _validate_condition(rule.open_condition, "open_condition")
    if rule.close_condition is not None:
        _validate_condition(rule.close_condition, "close_condition")
        _validate_hysteresis(rule.open_condition, rule.close_condition)
    if not isinstance(rule.missing_data, MissingDataPolicy):
        raise _invalid(
            "missing_data",
            rule.missing_data,
            f"must be a MissingDataPolicy, got {rule.missing_data!r}",
        )
    if not isinstance(rule.evidence, EvidencePolicy):
        raise _invalid(
            "evidence", rule.evidence, f"must be an EvidencePolicy, got {rule.evidence!r}"
        )
    if len(rule.group_dimensions) != len(set(rule.group_dimensions)):
        raise _invalid(
            "group_dimensions", rule.group_dimensions, "must not contain duplicates"
        )
    for dimension in rule.group_dimensions:
        if dimension not in BASELINE_DIMENSIONS:
            raise _invalid(
                "group_dimensions",
                dimension,
                "must stay inside the SPEC-302 baseline dimension whitelist "
                "(REQ-OBS-304-004: 不含易变值)",
            )
        if dimension == "session_id":
            raise _invalid(
                "group_dimensions",
                dimension,
                "session scope is implicit (SPEC-304 §6 分组守 scope)",
            )


def _validate_condition(condition: Condition, field_name: str) -> None:
    if not isinstance(condition.operator, ComparisonOperator):
        raise _invalid(
            f"{field_name}.operator",
            condition.operator,
            f"must be a ComparisonOperator, got {condition.operator!r}",
        )
    if not isinstance(condition.threshold, (int, float)) or isinstance(
        condition.threshold, bool
    ):
        raise _invalid(
            f"{field_name}.threshold",
            condition.threshold,
            "must be a real number",
        )
    if not math.isfinite(condition.threshold):
        raise _invalid(
            f"{field_name}.threshold", condition.threshold, "must be finite"
        )
    if not condition.unit or not condition.unit.strip():
        raise _invalid(
            f"{field_name}.unit",
            condition.unit,
            "must declare an explicit unit (REQ-OBS-304-001)",
        )


def _validate_hysteresis(open_condition: Condition, close_condition: Condition) -> None:
    """Open/close band sanity (SPEC-304 §4 hysteresis).

    The close condition must be the OPPOSITE family of the open condition
    (a high-side rule opens on ``gt/gte`` and closes on ``lt/lte``) and the
    two satisfied-sets must never overlap — an overlapping pair could hold
    open and closed simultaneously, which oscillates. A neutral band between
    the thresholds is the hysteresis margin and is expected.
    """
    same_family = open_condition.operator.is_lower_bound == (
        close_condition.operator.is_lower_bound
    )
    if same_family:
        raise _invalid(
            "close_condition",
            close_condition.operator.value,
            "must be the opposite operator family of the open condition "
            "(high-side rules open on gt/gte and close on lt/lte)",
        )
    open_inclusive = open_condition.operator in (
        ComparisonOperator.GTE,
        ComparisonOperator.LTE,
    )
    close_inclusive = close_condition.operator in (
        ComparisonOperator.GTE,
        ComparisonOperator.LTE,
    )
    if open_condition.operator.is_lower_bound:
        # open (T,∞)/[T,∞) vs close (-∞,C]/(-∞,C): reject when a value can
        # satisfy both — i.e. when C reaches T (strictly, for the inclusive
        # pair).
        valid = (
            close_condition.threshold < open_condition.threshold
            if open_inclusive and close_inclusive
            else close_condition.threshold <= open_condition.threshold
        )
    else:
        valid = (
            close_condition.threshold > open_condition.threshold
            if open_inclusive and close_inclusive
            else close_condition.threshold >= open_condition.threshold
        )
    if not valid:
        raise _invalid(
            "close_condition",
            close_condition.threshold,
            "threshold overlaps the open threshold — the conditions could "
            "hold simultaneously",
        )


def _invalid(field: str, value, reason: str) -> AlertError:
    return AlertError(
        OBS_RULE_INVALID,
        f"invalid health rule: field {field!r} ({reason}); got {value!r}",
        details={"field": field},
    )


def default_rule_set() -> HealthRuleSet:
    """The six SPEC-304 §8 default rules, ``mvp-sandbox`` profile.

    The thresholds are sandbox-profile values chosen for the MVP teaching
    loop — explicitly NOT DVB compliance limits (REQ-OBS-304-001). Input
    bindings use the SPEC-302 catalog metrics registered by ticket #50;
    ``OBS_STORAGE_WRITE_FAILURE`` targets
    ``observation.storage_write_failures_total``, which has NO registered
    producer yet (GatewayMetrics.failures is not a catalog metric — #50 face
    is NOT-TOUCH for #52): until that input exists the rule honestly
    contributes ``unknown`` (no false firing, SPEC-304 §11).
    """
    return HealthRuleSet(
        ruleset_id="mvp-default-health-rules",
        version="1.0.0",
        profile="mvp-sandbox",
        rules=(
            HealthRule(
                rule_id="TS_CC_ERROR_RATE_HIGH",
                version="1.0.0",
                name="Continuity error burst",
                description=(
                    "Transport signal: continuity errors appeared inside the "
                    "window (sandbox profile: any increase fires)"
                ),
                dimension=HealthDimension.TRANSPORT,
                severity=AlertSeverity.WARNING,
                input_metric="ts.continuity_error_total",
                aggregation=RuleAggregation.INCREASE,
                window_ns=10_000_000_000,
                min_samples=1,
                freshness_ns=5_000_000_000,
                for_duration_ns=0,
                resolve_duration_ns=5_000_000_000,
                reopen_window_ns=60_000_000_000,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=0, unit="errors"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=0, unit="errors"
                ),
                group_dimensions=("service_id", "pid"),
            ),
            HealthRule(
                rule_id="PCR_JITTER_HIGH",
                version="1.0.0",
                name="PCR jitter p95 high",
                description=(
                    "Timing signal: p95 PCR jitter above the sandbox profile "
                    "threshold (50 ms open / 30 ms close)"
                ),
                dimension=HealthDimension.TIMING,
                severity=AlertSeverity.WARNING,
                input_metric="ts.pcr_jitter_ns",
                aggregation=RuleAggregation.P95,
                window_ns=10_000_000_000,
                min_samples=1,
                freshness_ns=5_000_000_000,
                for_duration_ns=2_000_000_000,
                resolve_duration_ns=5_000_000_000,
                reopen_window_ns=60_000_000_000,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=50_000_000.0, unit="ns"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=30_000_000.0, unit="ns"
                ),
                group_dimensions=("pid",),
            ),
            HealthRule(
                rule_id="PSI_STALE",
                version="1.0.0",
                name="PSI sections stale",
                description=(
                    "Service signal: PSI repetition gap above the sandbox "
                    "profile interval (500 ms)"
                ),
                dimension=HealthDimension.SERVICE,
                severity=AlertSeverity.WARNING,
                input_metric="psi.section_repetition_gap_ms",
                aggregation=RuleAggregation.MAX,
                window_ns=30_000_000_000,
                min_samples=1,
                freshness_ns=10_000_000_000,
                for_duration_ns=5_000_000_000,
                resolve_duration_ns=10_000_000_000,
                reopen_window_ns=0,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=500.0, unit="ms"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=500.0, unit="ms"
                ),
            ),
            HealthRule(
                rule_id="TOPOLOGY_PATH_DOWN",
                version="1.0.0",
                name="Degraded topology nodes",
                description=(
                    "Topology signal: degraded node count above zero (MVP "
                    "proxy over topology.degraded_node_count until a path "
                    "snapshot input exists — declared assumption)"
                ),
                dimension=HealthDimension.TOPOLOGY,
                severity=AlertSeverity.ERROR,
                input_metric="topology.degraded_node_count",
                aggregation=RuleAggregation.LAST,
                window_ns=1,
                min_samples=1,
                freshness_ns=30_000_000_000,
                for_duration_ns=0,
                resolve_duration_ns=10_000_000_000,
                reopen_window_ns=0,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=0, unit="nodes"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=0, unit="nodes"
                ),
            ),
            HealthRule(
                rule_id="OBS_CONSUMER_LAG_HIGH",
                version="1.0.0",
                name="Consumer lag high",
                description=(
                    "Observation signal: journal consumer lag above the "
                    "sandbox profile bound (1000 events)"
                ),
                dimension=HealthDimension.OBSERVATION,
                severity=AlertSeverity.WARNING,
                input_metric="observation.consumer_lag_events",
                aggregation=RuleAggregation.LAST,
                window_ns=1,
                min_samples=1,
                freshness_ns=10_000_000_000,
                for_duration_ns=5_000_000_000,
                resolve_duration_ns=10_000_000_000,
                reopen_window_ns=0,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=1000, unit="events"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=100, unit="events"
                ),
            ),
            HealthRule(
                rule_id="OBS_STORAGE_WRITE_FAILURE",
                version="1.0.0",
                name="Storage write failures",
                description=(
                    "Observation signal: journal append failures inside the "
                    "window (input metric has no registered producer yet — "
                    "contributes unknown until one lands)"
                ),
                dimension=HealthDimension.OBSERVATION,
                severity=AlertSeverity.CRITICAL,
                input_metric="observation.storage_write_failures_total",
                aggregation=RuleAggregation.INCREASE,
                window_ns=10_000_000_000,
                min_samples=1,
                freshness_ns=5_000_000_000,
                for_duration_ns=0,
                resolve_duration_ns=30_000_000_000,
                reopen_window_ns=0,
                open_condition=Condition(
                    operator=ComparisonOperator.GT, threshold=0, unit="failures"
                ),
                close_condition=Condition(
                    operator=ComparisonOperator.LTE, threshold=0, unit="failures"
                ),
            ),
        ),
    )


__all__ = [
    "ComparisonOperator",
    "Condition",
    "EvidencePolicy",
    "HealthRule",
    "HealthRuleSet",
    "MissingDataPolicy",
    "RuleAggregation",
    "default_rule_set",
    "validate_health_rule",
]
