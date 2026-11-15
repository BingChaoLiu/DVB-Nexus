"""Deterministic alert lifecycle engine (SPEC-304 §5, ticket #52).

Pure virtual-time evaluation: :meth:`AlertEngine.evaluate` advances every
fingerprint-slot state machine to an INJECTED integer ``now_ns`` (SPEC-201
discipline — no wall clock, no sleeping, no randomness except the injectable
alert-id factory). The same input sequence therefore replays to the same
transition list (SPEC-304 §11 重放下的确定性评估).

Lifecycle (§5)::

    inactive -> pending -> firing -> resolving -> resolved
                          \\-> inactive   (a MEASURED close before the pending
                                          for_duration threshold)

Semantics pinned here (and by tests):

- ``pending`` arms at the first measured breach; it FIRES when
  ``for_duration`` has elapsed since arming. A measured close
  (``close_condition`` satisfied; without hysteresis: the open condition no
  longer holding) returns it to ``inactive``; the neutral hysteresis band
  HOLDS the current state (the pending clock keeps running — a breach that
  was observed and never measurably retracted is a real signal).
- ``firing`` is idempotent: a fresh open reading produces no new migration.
- ``resolving`` re-arms to ``firing`` on a fresh open reading; it settles to
  ``resolved`` after the configured hold.
- ``resolved`` instances reopen (same alert id) only inside the configured
  reopen window; afterwards a NEW instance is created (§5).
- Missing/stale input NEVER moves a machine (缺数据行为, §11: 入 unknown 不
  误报 — a lost input is not a recovery; the roll-up degrades to unknown via
  the contribution's ``input_status``).

Every migration carries the measured fact (aggregated reading + threshold +
unit + window — REQ-OBS-304-006: facts vs interpretation are distinguishable;
the declared rule description never leaks into the summary), the rule
version, the explicit clock domain/epoch and evidence refs.

Time-domain discipline: each machine anchors its last evaluation timepoint;
a later evaluation on another ``(clock_domain, clock_epoch)`` is refused
through the shared guard :func:`ensure_same_time_domain` (SPEC-300 §6 rules
1/3/5 — ``OBS_INVALID_TIME_DOMAIN``), the #50/#51 seam binding.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Union

from domain.observation import (
    AlertSeverity,
    AlertState,
    HealthDimension,
    MetricSample,
    MetricSampleTimepoint,
    SampleSemantics,
    ensure_same_time_domain,
)

from application.observation.metrics import counter_increase

from application.observation.alerts.fingerprint import alert_fingerprint
from application.observation.alerts.inputs import MetricWindowReader
from application.observation.alerts.rules import (
    HealthRule,
    HealthRuleSet,
    MissingDataPolicy,
    RuleAggregation,
    validate_health_rule,
)

GroupKey = tuple[tuple[str, str], ...]

#: Evidence ref shape (REQ-OBS-304-006): resolvable through the metrics
#: query face — the bucket half-open window start rides inside the ref.
def metric_bucket_ref(metric_name: str, window_start_ns: int) -> str:
    return f"metric:{metric_name}:bucket-{window_start_ns}"


def _format_number(value: float) -> str:
    """Deterministic short numeric rendering for fact summaries."""
    return format(value, ".12g")


@dataclass(frozen=True)
class AlertEngineConfig:
    """Engine policies. The alert-id factory is injectable so deterministic
    replays (tests) can pin ids; production keeps opaque uuid4 ids."""

    alert_id_factory: Callable[[], str] = field(
        default_factory=lambda: lambda: f"alert-{uuid.uuid4()}"
    )


@dataclass(frozen=True)
class AlertTransition:
    """One lifecycle migration (SPEC-304 §5: 每次迁移持久化时间戳、规则版本、
    证据引用). ``summary`` is the measured fact — never an interpretation."""

    alert_id: str
    fingerprint: str
    rule_id: str
    rule_version: str
    severity: AlertSeverity
    dimension: HealthDimension
    session_id: str
    group_key: GroupKey
    from_state: AlertState
    to_state: AlertState
    at_ns: int
    clock_domain: str
    clock_epoch: int
    evidence_refs: tuple[str, ...]
    observed_value: Optional[float]
    summary: str


@dataclass(frozen=True)
class RuleContribution:
    """One rule/group outcome this tick — the roll-up's input (§7)."""

    rule_id: str
    fingerprint: str
    rule_version: str
    severity: AlertSeverity
    dimension: HealthDimension
    group_key: GroupKey
    state: AlertState
    firing: bool
    observed_value: Optional[float]
    sample_count: int
    #: ``fresh`` | ``stale`` | ``missing`` (SPEC-304 §7 input completeness).
    input_status: str
    #: The rule's required flag (§7: required-input gaps force unknown).
    required: bool
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class AlertEvaluation:
    """One evaluation tick over the whole rule set."""

    session_id: str
    now_ns: int
    clock_domain: str
    clock_epoch: int
    transitions: tuple[AlertTransition, ...]
    contributions: tuple[RuleContribution, ...]


@dataclass
class _Machine:
    """One fingerprint slot's lifecycle state (in-memory; persistence is the
    store's job via the service)."""

    state: AlertState = AlertState.INACTIVE
    alert_id: Optional[str] = None
    open_since_ns: Optional[int] = None
    resolve_since_ns: Optional[int] = None
    resolved_at_ns: Optional[int] = None
    anchor: Optional[MetricSampleTimepoint] = None


def _aggregate(aggregation: RuleAggregation, ordered_values: list[float]) -> float:
    if aggregation is RuleAggregation.LAST:
        return ordered_values[-1]
    if aggregation is RuleAggregation.MAX:
        return max(ordered_values)
    if aggregation is RuleAggregation.AVG:
        return math.fsum(ordered_values) / len(ordered_values)
    if aggregation is RuleAggregation.P95:
        ordered = sorted(ordered_values)
        rank = max(1, math.ceil(0.95 * len(ordered)))
        return ordered[rank - 1]
    if aggregation is RuleAggregation.INCREASE:
        increase = counter_increase(None, ordered_values)
        return float(increase) if increase is not None else 0.0
    raise ValueError(f"unsupported aggregation {aggregation!r}")  # pragma: no cover


def _close_measured(rule: HealthRule, observed: float) -> bool:
    """A MEASURED close: the close condition holds (with hysteresis), or —
    without one — the open condition no longer holds."""
    if rule.close_condition is not None:
        return rule.close_condition.satisfied_by(observed)
    return not rule.open_condition.satisfied_by(observed)


def _fact_summary(rule: HealthRule, observed: float, phase_condition, phase: str) -> str:
    """Measured-fact sentence (REQ-OBS-304-006): reading + threshold + unit +
    window + rule identity. The declared interpretation lives in
    ``rule.description`` and is deliberately NOT appended here."""
    return (
        f"{rule.input_metric} {rule.aggregation.value} = "
        f"{_format_number(observed)} {phase_condition.unit} satisfies {phase} "
        f"{phase_condition.operator.value} "
        f"{_format_number(phase_condition.threshold)} {phase_condition.unit} "
        f"over {rule.window_ns} ns window (rule {rule.rule_id} v{rule.version})"
    )


class AlertEngine:
    """The SPEC-304 §5 lifecycle evaluator over a validated rule set."""

    def __init__(
        self,
        rules: Union[HealthRule, HealthRuleSet],
        *,
        config: Optional[AlertEngineConfig] = None,
    ) -> None:
        if isinstance(rules, HealthRule):
            self._rules: tuple[HealthRule, ...] = (rules,)
        else:
            self._rules = tuple(rules.rules)
        for rule in self._rules:
            # Fail-fast posture (SPEC-304 §10): no unvalidated rule reaches
            # evaluation — declaration defects surface at construction.
            validate_health_rule(rule)
        self._config = config or AlertEngineConfig()
        self._machines: dict[tuple[str, str], _Machine] = {}

    # --- evaluation -----------------------------------------------------------

    def evaluate(
        self,
        session_id: str,
        *,
        reader: MetricWindowReader,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int = 0,
    ) -> AlertEvaluation:
        transitions: list[AlertTransition] = []
        contributions: list[RuleContribution] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            self._evaluate_rule(
                rule,
                session_id=session_id,
                reader=reader,
                now_ns=now_ns,
                clock_domain=clock_domain,
                clock_epoch=clock_epoch,
                transitions=transitions,
                contributions=contributions,
            )
        return AlertEvaluation(
            session_id=session_id,
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            transitions=tuple(transitions),
            contributions=tuple(contributions),
        )

    # --- per rule --------------------------------------------------------------

    def _evaluate_rule(
        self,
        rule: HealthRule,
        *,
        session_id: str,
        reader: MetricWindowReader,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int,
        transitions: list[AlertTransition],
        contributions: list[RuleContribution],
    ) -> None:
        samples = reader.samples_for(
            metric_name=rule.input_metric,
            session_id=session_id,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
        )
        measured = [s for s in samples if s.value is not None]  # 缺失 ≠ 零
        groups: dict[GroupKey, list[MetricSample]] = {}
        for sample in measured:
            key = tuple(
                (dim, str(sample.dimensions[dim]))
                for dim in rule.group_dimensions
                if dim in sample.dimensions
            )
            groups.setdefault(key, []).append(sample)
        if not groups:
            groups = {(): []}

        window_start_ns = now_ns - rule.window_ns
        for group_key in sorted(groups):
            fingerprint = alert_fingerprint(rule.rule_id, dict(group_key))
            machine = self._machine(rule.rule_id, fingerprint)
            self._tick_machine(
                rule,
                machine,
                fingerprint=fingerprint,
                group_key=group_key,
                session_id=session_id,
                now_ns=now_ns,
                clock_domain=clock_domain,
                clock_epoch=clock_epoch,
                group_samples=groups[group_key],
                window_start_ns=window_start_ns,
                transitions=transitions,
                contributions=contributions,
            )

    # --- one machine tick --------------------------------------------------------

    def _tick_machine(
        self,
        rule: HealthRule,
        machine: _Machine,
        *,
        fingerprint: str,
        group_key: GroupKey,
        session_id: str,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int,
        group_samples: list[MetricSample],
        window_start_ns: int,
        transitions: list[AlertTransition],
        contributions: list[RuleContribution],
    ) -> None:
        # Time-domain guard FIRST (SPEC-300 §6: the comparison entry point
        # refuses cross-(domain, epoch) evaluation).
        anchor = MetricSampleTimepoint(
            value_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            semantics=SampleSemantics.DERIVED,
        )
        if machine.anchor is not None:
            ensure_same_time_domain(machine.anchor, anchor)
        machine.anchor = anchor

        # --- input completeness (SPEC-304 §7/§11) -----------------------------
        ordered = sorted(group_samples, key=lambda s: s.time.value_ns)
        newest_ns = max((s.time.value_ns for s in ordered), default=None)
        in_window = [s for s in ordered if window_start_ns <= s.time.value_ns < now_ns]
        if not ordered:
            input_status = "missing"
        elif newest_ns < now_ns - rule.freshness_ns:
            input_status = "stale"
        elif len(in_window) < rule.min_samples:
            input_status = "missing"
        else:
            input_status = "fresh"

        if input_status != "fresh":
            if rule.missing_data is MissingDataPolicy.IGNORE:
                return  # IGNORE policy: the rule contributes nothing this tick
            self._hold(
                rule,
                machine,
                fingerprint=fingerprint,
                group_key=group_key,
                now_ns=now_ns,
                clock_domain=clock_domain,
                clock_epoch=clock_epoch,
                input_status=input_status,
                observed_value=None,
                sample_count=len(in_window),
                contributions=contributions,
            )
            return

        observed = _aggregate(rule.aggregation, [s.value for s in in_window])
        opened = rule.open_condition.satisfied_by(observed)
        closed = _close_measured(rule, observed)
        evidence = self._evidence_refs(rule, window_start_ns)
        fresh_transitions = self._advance(
            rule,
            machine,
            fingerprint=fingerprint,
            group_key=group_key,
            session_id=session_id,
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            opened=opened,
            closed=closed,
            observed=observed,
            evidence=evidence,
        )
        for index, transition in enumerate(fresh_transitions):
            # The measured fact sentence: the phase whose condition this
            # transition was driven by (the open breach or the measured
            # close). The declared interpretation stays in rule.description.
            if transition.to_state is AlertState.RESOLVING:
                phase = rule.close_condition or rule.open_condition
                band = "close" if rule.close_condition is not None else "close"
            else:
                phase = rule.open_condition
                band = "open"
            transitions.append(
                replace(transition, summary=_fact_summary(rule, observed, phase, band))
            )
        contributions.append(
            RuleContribution(
                rule_id=rule.rule_id,
                fingerprint=fingerprint,
                rule_version=rule.version,
                severity=rule.severity,
                dimension=rule.dimension,
                group_key=group_key,
                state=machine.state,
                firing=machine.state is AlertState.FIRING,
                observed_value=observed,
                sample_count=len(in_window),
                input_status=input_status,
                required=rule.required,
                evidence_refs=evidence,
            )
        )

    # --- state machine ------------------------------------------------------------

    def _advance(
        self,
        rule: HealthRule,
        machine: _Machine,
        *,
        fingerprint: str,
        group_key: GroupKey,
        session_id: str,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int,
        opened: bool,
        closed: bool,
        observed: float,
        evidence: tuple[str, ...],
    ) -> list[AlertTransition]:
        """Advance the machine one fresh tick; returns the migrations made
        (summaries are filled by the caller — the fact phase depends on the
        transition target)."""
        created: list[AlertTransition] = []

        def migrate(to_state: AlertState, *, fresh_alert_id: bool = False) -> None:
            if machine.alert_id is None or fresh_alert_id:
                machine.alert_id = self._config.alert_id_factory()
            created.append(
                AlertTransition(
                    alert_id=machine.alert_id,
                    fingerprint=fingerprint,
                    rule_id=rule.rule_id,
                    rule_version=rule.version,
                    severity=rule.severity,
                    dimension=rule.dimension,
                    session_id=session_id,
                    group_key=group_key,
                    from_state=machine.state,
                    to_state=to_state,
                    at_ns=now_ns,
                    clock_domain=clock_domain,
                    clock_epoch=clock_epoch,
                    evidence_refs=evidence,
                    observed_value=observed,
                    summary="",
                )
            )
            machine.state = to_state

        if machine.state is AlertState.INACTIVE:
            if opened:
                machine.open_since_ns = now_ns
                machine.resolve_since_ns = None
                machine.resolved_at_ns = None
                migrate(AlertState.PENDING)
        elif machine.state is AlertState.PENDING:
            if closed:
                machine.open_since_ns = None
                migrate(AlertState.INACTIVE)
            elif (
                machine.open_since_ns is not None
                and now_ns - machine.open_since_ns >= rule.for_duration_ns
            ):
                migrate(AlertState.FIRING)
        elif machine.state is AlertState.FIRING:
            if closed:
                machine.resolve_since_ns = now_ns
                migrate(AlertState.RESOLVING)
        elif machine.state is AlertState.RESOLVING:
            if opened:
                machine.resolve_since_ns = None
                migrate(AlertState.FIRING)
            elif (
                machine.resolve_since_ns is not None
                and now_ns - machine.resolve_since_ns >= rule.resolve_duration_ns
            ):
                machine.resolved_at_ns = now_ns
                migrate(AlertState.RESOLVED)
        elif machine.state is AlertState.RESOLVED:
            if opened:
                rearm = (
                    rule.reopen_window_ns > 0
                    and machine.resolved_at_ns is not None
                    and now_ns - machine.resolved_at_ns <= rule.reopen_window_ns
                )
                machine.open_since_ns = now_ns
                machine.resolve_since_ns = None
                machine.resolved_at_ns = None
                # §5: outside the reopen window this is a NEW instance —
                # a fresh alert id is minted for the re-armed slot.
                migrate(AlertState.PENDING, fresh_alert_id=not rearm)
        # FIRING + open / RESOLVED + not opened / neutral band: hold, no
        # migration (idempotent tick).
        return created

    # --- helpers ---------------------------------------------------------------

    def _hold(
        self,
        rule: HealthRule,
        machine: _Machine,
        *,
        fingerprint: str,
        group_key: GroupKey,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int,
        input_status: str,
        observed_value: Optional[float],
        sample_count: int,
        contributions: list[RuleContribution],
    ) -> None:
        """Missing/stale input: the machine HOLDS its state (a lost input is
        not a recovery, SPEC-304 §11) and the roll-up gets the degraded
        input status."""
        contributions.append(
            RuleContribution(
                rule_id=rule.rule_id,
                fingerprint=fingerprint,
                rule_version=rule.version,
                severity=rule.severity,
                dimension=rule.dimension,
                group_key=group_key,
                state=machine.state,
                firing=machine.state is AlertState.FIRING,
                observed_value=observed_value,
                sample_count=sample_count,
                input_status=input_status,
                required=rule.required,
                evidence_refs=(),
            )
        )

    def _evidence_refs(
        self, rule: HealthRule, window_start_ns: int
    ) -> tuple[str, ...]:
        from application.observation.alerts.rules import EvidencePolicy

        if rule.evidence is EvidencePolicy.NONE:
            return ()
        return (metric_bucket_ref(rule.input_metric, window_start_ns),)

    def _machine(self, rule_id: str, fingerprint: str) -> _Machine:
        key = (rule_id, fingerprint)
        machine = self._machines.get(key)
        if machine is None:
            machine = _Machine()
            self._machines[key] = machine
        return machine


__all__ = [
    "AlertEngine",
    "AlertEngineConfig",
    "AlertEvaluation",
    "AlertTransition",
    "RuleContribution",
    "metric_bucket_ref",
]
