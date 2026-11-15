"""Metric window input face (SPEC-302 → SPEC-304 seam, ticket #52).

The alerts engine consumes metric VALUES through one narrow protocol so the
rule evaluation stays pure and testable (canned readers in unit tests, the
ticket #50 metrics engine in composition — Ruling H wiring):

- :class:`MetricWindowReader` — the structural protocol the engine depends
  on (samples of one metric series family for one session/clock domain);
- :class:`MetricsWindowReader` — the production adapter over the #50 public
  face (``MetricsEngine.samples``), declared additive consumption (no
  metrics-package internals are touched).

The adapter NEVER fabricates samples: absence of input stays absence (缺失
≠ 零, SPEC-302 §6.3) — the engine's missing-data policy owns the verdict.
"""

from __future__ import annotations

from typing import Protocol

from domain.observation import MetricSample

from application.observation.metrics import MetricsEngine


class MetricWindowReader(Protocol):
    """Structural source of metric samples for one session/domain."""

    def samples_for(
        self,
        *,
        metric_name: str,
        session_id: str,
        clock_domain: str,
        clock_epoch: int,
    ) -> tuple[MetricSample, ...]: ...


class MetricsWindowReader:
    """Adapter over the #50 ``MetricsEngine`` public face.

    Filters the engine's recorded samples to the requested session and
    clock epoch (the engine keys series by domain; the session dimension is
    part of the sample's declared dimensions).
    """

    def __init__(self, engine: MetricsEngine) -> None:
        self._engine = engine

    def samples_for(
        self,
        *,
        metric_name: str,
        session_id: str,
        clock_domain: str,
        clock_epoch: int,
    ) -> tuple[MetricSample, ...]:
        matched = self._engine.samples(metric_name, clock_domain=clock_domain)
        return tuple(
            sample
            for sample in matched
            if sample.time.clock_epoch == clock_epoch
            and sample.dimensions.get("session_id") == session_id
        )


__all__ = ["MetricWindowReader", "MetricsWindowReader"]
