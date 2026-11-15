"""Metrics query service — SPEC-300 §12 ``MetricsService.query`` face and
the SPEC-302 §8 query contract (ticket #50).

Request shape = the SPEC-305 §4 flat-scalar baseline (缝合批准 #12): integer
nanoseconds + a top-level ``clock_domain``; timepoint objects are record
shapes, never query parameters (SPEC-302 §8). The service refuses the §8
rejection matrix with the codes registered in :mod:`.errors` and answers
with per-series points carrying unit, aggregation, clock domain,
``revision``, provenance summary and quality flags (SPEC-300 §12
REQ-OBS-300-005).

Bucket convention (declared in every response, §6.1 响应必须标识实际桶边界
约定): half-open ``[start_ns + k*step_ns, start_ns + (k+1)*step_ns)`` over
the request's ``start_ns``. Gaps answer ``null`` + quality ``missing``
unless the metric's quality policy declares zero-fill (§6.3 缺失 ≠ 零).

Late-sample materialization (§6.2): the per-(step, bucket) ledger freezes a
finalized aggregate (无静默改写 — frozen values stand no matter which late
samples arrive afterwards when backfill is disabled); with backfill enabled
a rewrite increments ``revision`` and stays ``is_final=false`` until a later
materialization re-finalizes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from application.errors import BadRequestError, REQUEST_BODY_INVALID
from domain.observation import (
    AggregationOperation,
    MetricDefinition,
    MetricProvenance,
    MetricValueType,
    SeriesQuality,
    ensure_same_time_domain,
)

from application.observation.metrics.aggregator import (
    aggregate_scalar,
    bucket_bounds,
    bucket_count,
    counter_increase,
    counter_rate,
    histogram_counts,
    histogram_quantile,
)
from application.observation.metrics.engine import MetricsEngine
from application.observation.metrics.errors import (
    OBS_QUERY_RANGE_TOO_LARGE,
    MetricError,
)
from application.observation.metrics.store import BucketLedger

Number = Union[int, float]

#: Default/hard point limits (SPEC-302 §8 范围或点数超限; the SPEC-305 plane
#: maps the overrun onto the frozen HTTP table via OBS_QUERY_RANGE_TOO_LARGE).
MAX_POINTS_DEFAULT = 1000
MAX_POINTS_HARD_CAP = 10_000

#: Bucket-boundary convention label returned in every response (§6.1).
BUCKET_CONVENTION = (
    "half-open [start_ns + k*step_ns, start_ns + (k+1)*step_ns)"
)

#: Provenance summary cap per series (§8 摘要 — a summary, not the full log).
_PROVENANCE_SAMPLE_CAP = 100


@dataclass(frozen=True)
class MetricPoint:
    """One materialized bucket (§8 response point column)."""

    start_ns: int
    end_ns: int
    value: Optional[Union[Number, dict]]
    quality: tuple[SeriesQuality, ...]
    revision: int
    is_final: bool


@dataclass(frozen=True)
class MetricSeriesView:
    """One returned series: metadata + points + provenance summary."""

    metric_name: str
    unit: str
    value_type: MetricValueType
    aggregation: AggregationOperation
    clock_domain: str
    dimensions: dict
    points: tuple[MetricPoint, ...]
    provenance: MetricProvenance


@dataclass(frozen=True)
class MetricQueryRequest:
    """SPEC-302 §8 / SPEC-305 §4 flat query request."""

    metric_names: tuple[str, ...]
    start_ns: int
    end_ns: int
    step_ns: int
    clock_domain: str
    filters: dict = field(default_factory=dict)
    max_points: Optional[int] = None
    aggregation_override: Optional[AggregationOperation] = None
    allow_unknown: bool = False


@dataclass(frozen=True)
class MetricQueryResult:
    """SPEC-302 §8 response: series + the declared bucket convention."""

    series: tuple[MetricSeriesView, ...]
    clock_domain: str
    bucket_convention: str = BUCKET_CONVENTION


class MetricsService:
    """The §12 required ``MetricsService.query`` interface (frozen name)."""

    def __init__(self, engine: MetricsEngine) -> None:
        self._engine = engine

    def query(self, request: MetricQueryRequest) -> MetricQueryResult:
        """Validate the §8 contract and materialize the series points."""
        self._validate_request_shape(request)
        registry = self._engine.registry()
        max_points = request.max_points or MAX_POINTS_DEFAULT
        if max_points > MAX_POINTS_HARD_CAP:
            raise _range_error(
                f"max_points {max_points} exceeds the hard cap "
                f"{MAX_POINTS_HARD_CAP} (SPEC-302 §8)",
                {"max_points": max_points, "cap": MAX_POINTS_HARD_CAP},
            )
        total_buckets = bucket_count(
            request.start_ns, request.end_ns, request.step_ns
        )
        if total_buckets > max_points:
            raise _range_error(
                f"query spans {total_buckets} buckets over max_points="
                f"{max_points} (SPEC-302 §8)",
                {"buckets": total_buckets, "max_points": max_points},
            )

        views: list[MetricSeriesView] = []
        for name in request.metric_names:
            definition = registry.require(
                name, allow_unknown=request.allow_unknown
            )
            if definition is None:
                continue  # allow_unknown: skip unknown names, never fabricate
            registry.validate_dimension_filters(definition, request.filters)
            op = self._resolve_operation(definition, request)
            states = self._engine.store.series_matching(
                definition.metric_name, request.clock_domain, request.filters
            )
            if not states:
                if definition.quality_policy.zero_fill and not request.filters:
                    # §6.3 zero-fill contract: an explicitly zero-filling
                    # metric answers a full bucket column even with no
                    # series yet — the one sanctioned "0".
                    views.append(
                        self._empty_zero_fill_view(
                            definition, request, op, total_buckets
                        )
                    )
                continue
            for state in states:
                views.append(
                    self._materialize_series(
                        definition, state, request, op, total_buckets
                    )
                )
        return MetricQueryResult(
            series=tuple(views), clock_domain=request.clock_domain
        )

    def _empty_zero_fill_view(
        self,
        definition: MetricDefinition,
        request: MetricQueryRequest,
        op: AggregationOperation,
        total_buckets: int,
    ) -> MetricSeriesView:
        points = []
        for index in range(total_buckets):
            start, end = bucket_bounds(request.start_ns, request.step_ns, index)
            points.append(
                MetricPoint(
                    start_ns=start,
                    end_ns=end,
                    value=0,
                    quality=(SeriesQuality.GOOD,),
                    revision=1,
                    is_final=False,
                )
            )
        return MetricSeriesView(
            metric_name=definition.metric_name,
            unit=definition.unit,
            value_type=definition.value_type,
            aggregation=op,
            clock_domain=request.clock_domain,
            dimensions={},
            points=tuple(points),
            provenance=MetricProvenance(
                journal_watermark=self._engine.journal_watermark
            ),
        )

    # --- validation ------------------------------------------------------------

    @staticmethod
    def _validate_request_shape(request: MetricQueryRequest) -> None:
        if not isinstance(request.clock_domain, str) or not request.clock_domain:
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                "clock_domain is required for metrics queries "
                "(SPEC-302 §8: 时钟域缺失)",
                details={"field": "clock_domain"},
            )
        if request.step_ns < 1:
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                f"step_ns must be >= 1, got {request.step_ns} (SPEC-302 §8)",
                details={"field": "step_ns", "value": request.step_ns},
            )
        if request.start_ns >= request.end_ns:
            raise _range_error(
                f"start_ns >= end_ns ({request.start_ns} >= "
                f"{request.end_ns}) is refused (SPEC-302 §8)",
                {"start_ns": request.start_ns, "end_ns": request.end_ns},
            )

    @staticmethod
    def _resolve_operation(
        definition: MetricDefinition, request: MetricQueryRequest
    ) -> AggregationOperation:
        if request.aggregation_override is None:
            # Per-type defaults: counters answer increase (reset-detecting),
            # histograms answer count, gauges answer last.
            if definition.value_type is MetricValueType.COUNTER:
                return AggregationOperation.INCREASE
            if definition.value_type is MetricValueType.HISTOGRAM:
                return AggregationOperation.COUNT
            return AggregationOperation.LAST
        if request.aggregation_override not in definition.aggregation:
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                f"aggregation_override "
                f"{request.aggregation_override.value!r} is not an allowed "
                f"operation of {definition.metric_name!r} "
                f"(allowed: {[op.value for op in definition.aggregation]}; "
                "SPEC-302 §8 仅限允许操作)",
                details={
                    "metric_name": definition.metric_name,
                    "aggregation_override": request.aggregation_override.value,
                    "allowed": [op.value for op in definition.aggregation],
                },
            )
        return request.aggregation_override

    # --- materialization ---------------------------------------------------------

    def _materialize_series(
        self,
        definition: MetricDefinition,
        state,
        request: MetricQueryRequest,
        op: AggregationOperation,
        total_buckets: int,
    ) -> MetricSeriesView:
        points = []
        for index in range(total_buckets):
            start, end = bucket_bounds(request.start_ns, request.step_ns, index)
            points.append(
                self._materialize_point(
                    definition, state, request, op, start, end
                )
            )
        source_ids = sorted(
            {
                event_id
                for sample in state.samples
                for event_id in sample.provenance.source_event_ids
            }
        )
        return MetricSeriesView(
            metric_name=definition.metric_name,
            unit=definition.unit,
            value_type=definition.value_type,
            aggregation=op,
            clock_domain=request.clock_domain,
            dimensions=dict(state.key[3]),
            points=tuple(points),
            provenance=MetricProvenance(
                source_event_ids=tuple(source_ids[:_PROVENANCE_SAMPLE_CAP]),
                journal_watermark=self._engine.journal_watermark,
            ),
        )

    def _materialize_point(
        self,
        definition: MetricDefinition,
        state,
        request: MetricQueryRequest,
        op: AggregationOperation,
        bucket_start: int,
        bucket_end: int,
    ) -> MetricPoint:
        """§6.2/§6.3 materialization: late/revision/gap semantics."""
        in_bucket: list[tuple[int, MetricSampleLike]] = []
        for position, sample in enumerate(state.samples):
            t = sample.time.value_ns
            if bucket_start <= t < bucket_end:
                in_bucket.append((position, sample))

        lateness = definition.quality_policy.lateness_window_ns
        watermark = state.high_ns
        final_by_watermark = (
            watermark is not None and watermark >= bucket_end + lateness
        )

        if not in_bucket:
            if definition.quality_policy.zero_fill:
                return MetricPoint(
                    start_ns=bucket_start,
                    end_ns=bucket_end,
                    value=0,
                    quality=(SeriesQuality.GOOD,),
                    revision=1,
                    is_final=final_by_watermark,
                )
            # §6.3: 缺失 ≠ 零 — null + missing, never a fabricated zero.
            return MetricPoint(
                start_ns=bucket_start,
                end_ns=bucket_end,
                value=None,
                quality=(SeriesQuality.MISSING,),
                revision=1,
                is_final=False,
            )

        positions = tuple(position for position, _ in in_bucket)
        # The ledger is per (step, bucket, op): different aggregations are
        # independent materializations of the same raw bucket.
        ledger_key = (request.step_ns, bucket_start, op)
        ledger: Optional[BucketLedger] = state.ledgers.get(ledger_key)
        window_ns = bucket_end - bucket_start

        if ledger is None:
            value, quality = self._aggregate(
                definition, state, in_bucket, op, bucket_start, window_ns
            )
            ledger = BucketLedger(
                revision=1,
                is_final=final_by_watermark,
                sample_positions=positions,
            )
            if final_by_watermark:
                ledger.frozen_value = value
                ledger.frozen_quality = quality
            state.ledgers[ledger_key] = ledger
            return _point(bucket_start, bucket_end, value, quality, ledger)

        changed = ledger.sample_positions != positions
        if ledger.is_final and not changed:
            return _point(
                bucket_start,
                bucket_end,
                ledger.frozen_value,
                ledger.frozen_quality,
                ledger,
            )
        if ledger.is_final and changed:
            if not self._engine.config.backfill_enabled:
                # §6.2: 定稿后到达的样本保留在原始 journal，但不得静默改写
                # 已定稿聚合 — the frozen value stands; late samples stay
                # in the raw store only.
                return _point(
                    bucket_start,
                    bucket_end,
                    ledger.frozen_value,
                    ledger.frozen_quality,
                    ledger,
                )
            value, quality = self._aggregate(
                definition, state, in_bucket, op, bucket_start, window_ns
            )
            ledger.revision += 1
            ledger.sample_positions = positions
            ledger.is_final = False  # stays unfinal 直至重新定稿
            return _point(
                bucket_start,
                bucket_end,
                value,
                _mark_revised(quality),
                ledger,
            )
        # Still open (never finalized): accumulate at the same revision.
        value, quality = self._aggregate(
            definition, state, in_bucket, op, bucket_start, window_ns
        )
        ledger.sample_positions = positions
        if final_by_watermark:
            ledger.is_final = True
            ledger.frozen_value = value
            ledger.frozen_quality = quality
        return _point(bucket_start, bucket_end, value, quality, ledger)

    def _aggregate(
        self,
        definition: MetricDefinition,
        state,
        in_bucket,
        op: AggregationOperation,
        bucket_start: int,
        window_ns: int,
    ) -> tuple[Optional[Union[Number, dict]], tuple[SeriesQuality, ...]]:
        samples = [sample for _, sample in in_bucket]
        # Time-domain binding: every comparison inside the bucket runs on one
        # (clock_domain, clock_epoch) base (SPEC-300 §6 rules 1/3/5).
        if len(samples) >= 2:
            ensure_same_time_domain(*[sample.time for sample in samples])
        quality = _union_quality(samples)
        if op is AggregationOperation.COUNT:
            return len(samples), quality
        if op is AggregationOperation.QUANTILE:
            spec = definition.histogram
            if spec is None:  # pragma: no cover — registry-validated away
                raise ValueError(
                    f"{definition.metric_name!r} has no histogram spec"
                )
            values = [sample.value for sample in samples]
            counts = histogram_counts(spec, values)
            quantiles = {
                str(q): histogram_quantile(spec, counts, q)
                for q in spec.quantiles
            }
            return quantiles, quality
        if op is AggregationOperation.INCREASE:
            anchor = self._anchor_value(state, bucket_start)
            increase = counter_increase(
                anchor, [sample.value for sample in samples]
            )
            return increase, quality
        if op is AggregationOperation.RATE:
            anchor = self._anchor_value(state, bucket_start)
            increase = counter_increase(
                anchor, [sample.value for sample in samples]
            )
            if increase is None:
                return None, quality
            return counter_rate(increase, window_ns), quality
        values = [sample.value for sample in samples]
        return aggregate_scalar(op, values), quality

    @staticmethod
    def _anchor_value(state, bucket_start: int) -> Optional[Number]:
        """Last cumulative value strictly before the bucket (increase/rate)."""
        anchor = None
        for sample in state.samples:
            if sample.time.value_ns >= bucket_start:
                break
            anchor = sample.value
        return anchor


def _point(
    bucket_start: int,
    bucket_end: int,
    value,
    quality: tuple[SeriesQuality, ...],
    ledger: BucketLedger,
) -> MetricPoint:
    return MetricPoint(
        start_ns=bucket_start,
        end_ns=bucket_end,
        value=value,
        quality=quality,
        revision=ledger.revision,
        is_final=ledger.is_final,
    )


def _mark_revised(
    quality: tuple[SeriesQuality, ...],
) -> tuple[SeriesQuality, ...]:
    if SeriesQuality.REVISED in quality:
        return quality
    return tuple(quality) + (SeriesQuality.REVISED,)


def _union_quality(samples) -> tuple[SeriesQuality, ...]:
    seen: dict[SeriesQuality, None] = {}
    for sample in samples:
        for flag in sample.quality:
            seen.setdefault(flag, None)
    return tuple(seen)


def _range_error(message: str, details: dict) -> MetricError:
    return MetricError(OBS_QUERY_RANGE_TOO_LARGE, message, details=details)


__all__ = [
    "BUCKET_CONVENTION",
    "MAX_POINTS_DEFAULT",
    "MAX_POINTS_HARD_CAP",
    "MetricPoint",
    "MetricQueryRequest",
    "MetricQueryResult",
    "MetricSeriesView",
    "MetricsService",
]
