"""SPEC-302 §8 query contract (ticket #50) — REQ-OBS-302-004/006.

Seam: ``MetricsService.query(MetricQueryRequest) -> MetricQueryResult`` (the
SPEC-300 §12 required interface name). Pinned here:

- the flat-scalar request baseline (#12 ruling: integer ns + top-level
  clock_domain) and the full §8 rejection matrix with registered codes;
- the response shape: per-series unit/value_type/aggregation/clock_domain/
  points/provenance summary + the declared bucket convention (§6.1);
- gap discipline (§6.3): missing buckets answer null + ``missing`` — 缺失
  ≠ 零 — unless the metric's quality policy declares zero-fill;
- per-type default aggregation and the aggregation_override legality;
- wall-clock operational series and virtual-time series answer to disjoint
  queries (§9: 墙钟操作指标是独立序列).

Unit layer: pure in-memory; no I/O.
"""

import pytest

from application.errors import BadRequestError, REQUEST_BODY_INVALID
from application.observation.gateway import GatewayMetrics
from application.observation.metrics.engine import MetricsEngine
from application.observation.metrics.errors import (
    OBS_METRIC_CARDINALITY_EXCEEDED,
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    OBS_QUERY_RANGE_TOO_LARGE,
    MetricError,
)
from application.observation.metrics.registry import MetricRegistry
from application.observation.metrics.service import (
    BUCKET_CONVENTION,
    MAX_POINTS_HARD_CAP,
    MetricQueryRequest,
    MetricsService,
)
from domain.observation import (
    AggregationOperation,
    MetricDefinition,
    MetricValueType,
    MetricTemporality,
    QualityPolicy,
)

from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    record,
    ts_payload,
)

DOMAIN = "sim:sess-1"


def _engine(*records) -> MetricsEngine:
    engine = MetricsEngine()
    for index, (event_type, source_ns, payload, seq) in enumerate(records):
        engine.handle_record(
            record(
                raw_envelope(
                    event_type=event_type, source_ns=source_ns, payload=payload
                ),
                journal_seq=seq,
            )
        )
    return engine


def _service(engine: MetricsEngine) -> MetricsService:
    return MetricsService(engine)


def _request(**overrides) -> MetricQueryRequest:
    fields = {
        "metric_names": ("simulation.virtual_time_ns",),
        "start_ns": 0,
        "end_ns": 400,
        "step_ns": 100,
        "clock_domain": DOMAIN,
    }
    fields.update(overrides)
    return MetricQueryRequest(**fields)


# --- happy path + response shape (REQ-OBS-302-006) ------------------------------


def test_query_returns_series_metadata_points_and_provenance() -> None:
    engine = _engine(("simulation.run_started", 120, {}, 3))
    result = _service(engine).query(_request())

    assert result.clock_domain == DOMAIN
    assert result.bucket_convention == BUCKET_CONVENTION
    assert len(result.series) == 1
    view = result.series[0]
    assert view.metric_name == "simulation.virtual_time_ns"
    assert view.unit == "ns"
    assert view.value_type is MetricValueType.GAUGE
    assert view.aggregation is AggregationOperation.LAST
    assert view.clock_domain == DOMAIN
    assert view.dimensions == {"session_id": "sess-1"}
    assert view.provenance.journal_watermark == 3
    assert len(view.points) == 4  # [0,100) [100,200) [200,300) [300,400)
    bucket1 = view.points[1]  # [100,200) holds the t=120 sample
    assert bucket1.start_ns == 100 and bucket1.end_ns == 200
    assert bucket1.value == 120
    assert bucket1.quality == ("good",)
    assert bucket1.revision == 1
    assert bucket1.is_final is False  # watermark 120 < bucket end 200


def test_query_provenance_carries_source_event_ids() -> None:
    engine = _engine(("simulation.run_started", 120, {}, 3))
    result = _service(engine).query(_request(start_ns=100, end_ns=200, step_ns=100))
    ids = result.series[0].provenance.source_event_ids
    assert ids and all(isinstance(i, str) for i in ids)


def test_sample_at_the_step_boundary_lands_in_the_next_half_open_bucket() -> None:
    # [start, end) is half-open (§6.1): t=100 with step 100 belongs to
    # [100,200), never to [0,100).
    engine = _engine(("simulation.run_started", 100, {}, 1))
    view = _service(engine).query(_request(end_ns=200)).series[0]
    assert view.points[0].value is None
    assert view.points[0].quality == ("missing",)
    assert view.points[1].value == 100


# --- gap discipline (REQ-OBS-302-004, SPEC-302 §6.3) ----------------------------


def test_missing_buckets_answer_null_plus_missing_never_zero() -> None:
    engine = _engine(("simulation.run_started", 350, {}, 1))
    view = _service(engine).query(_request()).series[0]
    gap = view.points[0]  # no sample in [0,100)
    assert gap.value is None
    assert gap.quality == ("missing",)


def test_zero_fill_policy_is_explicit_per_metric_definition() -> None:
    definition = MetricDefinition(
        metric_name="sandbox.zero_fill_gauge",
        value_type=MetricValueType.GAUGE,
        unit="units",
        description="test metric with an explicit zero-fill policy",
        allowed_dimensions=("session_id",),
        snapshot_source="test fixture",
        aggregation=(AggregationOperation.LAST,),
        temporality=MetricTemporality.INSTANT,
        quality_policy=QualityPolicy(zero_fill=True),
    )
    engine = MetricsEngine(registry=MetricRegistry((definition,)))
    result = MetricsService(engine).query(
        MetricQueryRequest(
            metric_names=("sandbox.zero_fill_gauge",),
            start_ns=0,
            end_ns=100,
            step_ns=100,
            clock_domain=DOMAIN,
        )
    )
    gap = result.series[0].points[0]
    assert gap.value == 0  # the ONLY sanctioned zero: explicit zero-fill
    assert gap.quality == ("good",)


# --- aggregation resolution (REQ-OBS-302-002 via the query seam) ----------------


def test_counter_query_defaults_to_reset_detecting_increase() -> None:
    engine = _engine(
        ("ts.continuity_error", 100, ts_payload(pid=256, source="internal_parser", confidence="parsed"), 1),
        ("ts.continuity_error", 250, ts_payload(pid=256, source="internal_parser", confidence="parsed"), 2),
    )
    view = _service(engine).query(
        _request(
            metric_names=("ts.continuity_error_total",),
            end_ns=300,
            filters={"pid": 256},
        )
    ).series[0]
    assert view.aggregation is AggregationOperation.INCREASE
    # Bucket [0,100): no samples → missing (§6.3, never a fabricated 0).
    assert view.points[0].value is None
    assert view.points[0].quality == ("missing",)
    # Bucket [100,200): the first sample is the baseline → increase 0.
    assert view.points[1].value == 0
    # Bucket [200,300): 1 → 2 with the anchor from t=100 → increase 1.
    assert view.points[2].value == 1


def test_aggregation_override_within_allowed_ops_changes_the_answer() -> None:
    engine = _engine(
        ("ts.continuity_error", 100, ts_payload(pid=256, source="internal_parser", confidence="parsed"), 1),
        ("ts.continuity_error", 150, ts_payload(pid=256, source="internal_parser", confidence="parsed"), 2),
    )
    view = _service(engine).query(
        _request(
            metric_names=("ts.continuity_error_total",),
            end_ns=200,
            filters={"pid": 256},
            aggregation_override=AggregationOperation.RATE,
        )
    ).series[0]
    assert view.aggregation is AggregationOperation.RATE
    # Bucket [100,200): increase 1 over a 100 ns window → 1e7 per second.
    assert view.points[1].value == pytest.approx(10_000_000.0)


def test_histogram_query_counts_and_quantiles_per_bucket() -> None:
    payload = ts_payload(pid=8, jitter_ns=150_000, source="tsduck", confidence="parsed")
    engine = _engine(("ts.pcr_jitter_observed", 100, payload, 1))
    service = _service(engine)
    count_view = service.query(
        _request(metric_names=("ts.pcr_jitter_ns",), end_ns=200, filters={"pid": 8})
    ).series[0]
    assert count_view.aggregation is AggregationOperation.COUNT
    assert count_view.points[1].value == 1

    quantile_view = service.query(
        _request(
            metric_names=("ts.pcr_jitter_ns",),
            end_ns=200,
            step_ns=100,
            clock_domain=DOMAIN,
            filters={"pid": 8},
            aggregation_override=AggregationOperation.QUANTILE,
        )
    ).series[0]
    q50 = quantile_view.points[1].value
    assert isinstance(q50, dict) and "0.5" in q50


# --- §8 rejection matrix ----------------------------------------------------------


def test_start_after_end_is_refused_with_range_code() -> None:
    with pytest.raises(MetricError) as excinfo:
        _service(_engine()).query(_request(start_ns=400, end_ns=400))
    assert excinfo.value.error_code == OBS_QUERY_RANGE_TOO_LARGE


def test_non_positive_step_is_a_request_shape_violation() -> None:
    with pytest.raises(BadRequestError) as excinfo:
        _service(_engine()).query(_request(step_ns=0))
    assert excinfo.value.error_code == REQUEST_BODY_INVALID


def test_missing_clock_domain_is_a_request_shape_violation() -> None:
    with pytest.raises(BadRequestError):
        _service(_engine()).query(_request(clock_domain=""))


def test_point_count_overrun_is_refused_with_range_code() -> None:
    # 400 ns / 100 ns = 4 buckets; max_points 3 → overrun.
    with pytest.raises(MetricError) as excinfo:
        _service(_engine()).query(_request(max_points=3))
    assert excinfo.value.error_code == OBS_QUERY_RANGE_TOO_LARGE


def test_max_points_over_the_hard_cap_is_refused() -> None:
    with pytest.raises(MetricError) as excinfo:
        _service(_engine()).query(_request(max_points=MAX_POINTS_HARD_CAP + 1))
    assert excinfo.value.error_code == OBS_QUERY_RANGE_TOO_LARGE


def test_unknown_metric_is_refused_unless_allow_unknown() -> None:
    with pytest.raises(MetricError) as excinfo:
        _service(_engine()).query(_request(metric_names=("no.such_metric",)))
    assert excinfo.value.error_code == OBS_METRIC_NOT_FOUND
    # allow_unknown: the unknown name is skipped (no fabricated series),
    # the known name still answers.
    result = _service(_engine(("simulation.run_started", 120, {}, 1))).query(
        _request(metric_names=("no.such_metric", "simulation.virtual_time_ns"), allow_unknown=True)
    )
    assert [s.metric_name for s in result.series] == ["simulation.virtual_time_ns"]


def test_filter_on_a_non_allowed_dimension_is_rejected() -> None:
    with pytest.raises(MetricError) as excinfo:
        _service(_engine()).query(
            _request(
                metric_names=("simulation.virtual_time_ns",),
                filters={"pid": 256},  # virtual_time allows only session_id
            )
        )
    assert excinfo.value.error_code == OBS_METRIC_DIMENSION_REJECTED


def test_aggregation_override_outside_allowed_ops_is_refused() -> None:
    with pytest.raises(BadRequestError):
        _service(_engine()).query(
            _request(aggregation_override=AggregationOperation.QUANTILE)
        )


# --- §9 wall vs sim separation through the query seam -----------------------------


def test_wall_operational_series_answer_only_wall_domain_queries() -> None:
    engine = _engine(("simulation.run_started", 120, {}, 1))
    gateway_metrics = GatewayMetrics(
        queue_depth=0, accepted=7, duplicate=0, rejected=0, coalesced=0,
        journal_duplicates=0, subscriber_errors=0, storage_failures=0,
        unhealthy=False,
    )
    engine.poll_operational(
        "sess-1", gateway_metrics=gateway_metrics, consumer_lag=2, wall_ns=1_000
    )
    service = _service(engine)
    # Cumulative counter readings surface via the `last` override; the
    # wall stamp t=1000 lands in bucket [1000,2000).
    wall = service.query(
        MetricQueryRequest(
            metric_names=("observation.ingest_events_total",),
            start_ns=0,
            end_ns=2000,
            step_ns=1000,
            clock_domain="wall:utc",
            aggregation_override=AggregationOperation.LAST,
        )
    )
    assert len(wall.series) == 1
    assert wall.series[0].points[1].value == 7

    # A second poll advances the counter; the later bucket's increase is
    # reset-detecting over the anchor from the first poll.
    later = GatewayMetrics(
        queue_depth=0, accepted=9, duplicate=0, rejected=0, coalesced=0,
        journal_duplicates=0, subscriber_errors=0, storage_failures=0,
        unhealthy=False,
    )
    engine.poll_operational(
        "sess-1", gateway_metrics=later, consumer_lag=1, wall_ns=3_000
    )
    increase = service.query(
        MetricQueryRequest(
            metric_names=("observation.ingest_events_total",),
            start_ns=0,
            end_ns=4000,
            step_ns=2000,
            clock_domain="wall:utc",
        )
    ).series[0]
    assert increase.points[0].value == 0  # first sample is the baseline
    assert increase.points[1].value == 2  # 7 → 9

    # The same metric asked on the sim domain has no series — the wall
    # series never leaks into virtual-time queries (SPEC-302 §9).
    sim = service.query(
        _request(metric_names=("observation.ingest_events_total",))
    )
    assert sim.series == ()
    # And the virtual-time metric never appears on the wall domain.
    wall_sim = service.query(
        _request(metric_names=("simulation.virtual_time_ns",), clock_domain="wall:utc")
    )
    assert wall_sim.series == ()
