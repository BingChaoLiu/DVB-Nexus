"""Shared fixtures for the SPEC-304 alerts tests (ticket #52).

The reader double is a structural ``MetricWindowReader`` (the engine's only
input seam); samples are built through the domain model so a non-conforming
fixture cannot reach the engine (the #50 ``_metrics_fixtures`` discipline).
The deterministic alert-id factory keeps virtual-time replays byte-stable
(SPEC-201 discipline: injected integers, no wall clock).
"""

from __future__ import annotations

from typing import Optional

from application.observation.alerts.rules import (
    ComparisonOperator,
    Condition,
    HealthRule,
    RuleAggregation,
)
from domain.observation import (
    AlertSeverity,
    HealthDimension,
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
    SampleSemantics,
    SeriesQuality,
)

DOMAIN = "sim:sess-1"
METRIC = "test.metric"


def make_rule(**overrides) -> HealthRule:
    """Simple deterministic rule: fire above 100, recover at/below 50."""
    fields = {
        "rule_id": "TEST_RULE",
        "version": "1.2.0",
        "name": "Test rule",
        "description": "Declared interpretation: the test signal is too high",
        "input_metric": METRIC,
        "aggregation": RuleAggregation.LAST,
        "window_ns": 5_000,
        "min_samples": 1,
        "freshness_ns": 1_000_000,
        "for_duration_ns": 1_000,
        "resolve_duration_ns": 500,
        "reopen_window_ns": 2_000,
        "dimension": HealthDimension.OBSERVATION,
        "severity": AlertSeverity.WARNING,
        "open_condition": Condition(
            operator=ComparisonOperator.GT, threshold=100.0, unit="u"
        ),
        "close_condition": Condition(
            operator=ComparisonOperator.LTE, threshold=50.0, unit="u"
        ),
    }
    fields.update(overrides)
    return HealthRule(**fields)


def sample_at(
    value_ns: int,
    value: Optional[float],
    pid: int = 1,
    *,
    session_id: str = "sess-1",
    metric: str = METRIC,
    clock_domain: str = DOMAIN,
    clock_epoch: int = 0,
) -> MetricSample:
    return MetricSample(
        metric_name=metric,
        time=MetricSampleTimepoint(
            value_ns=value_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            semantics=SampleSemantics.SOURCE,
        ),
        value=value,
        dimensions={"session_id": session_id, "pid": pid},
        quality=() if value is not None else (SeriesQuality.MISSING,),
        provenance=MetricProvenance(source_event_ids=("evt-1",)),
    )


class CannedReader:
    """Structural ``MetricWindowReader`` double over a canned sample list."""

    def __init__(self, samples: tuple[MetricSample, ...] = ()) -> None:
        self.samples = list(samples)

    def samples_for(self, *, metric_name, session_id, clock_domain, clock_epoch):
        return tuple(self.samples)

    def add(self, sample: MetricSample) -> None:
        self.samples.append(sample)


def deterministic_alert_id() -> str:
    """Factory whose sequence is deterministic across replays."""
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"alert-{counter['n']:04d}"

    return factory


class RecordingHintEmitter:
    """Structural ``AlertHintEmitter`` double capturing emitted hints."""

    def __init__(self) -> None:
        self.hints: list[object] = []
        self.fail_after: Optional[int] = None  # simulate emitter failure

    def emit(self, hint) -> None:
        if self.fail_after is not None and len(self.hints) >= self.fail_after:
            raise RuntimeError("hint transport down")
        self.hints.append(hint)
