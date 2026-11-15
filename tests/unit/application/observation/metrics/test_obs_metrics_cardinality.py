"""SPEC-302 §7 cardinality enforcement — reject and quarantine (ticket #50).

REQ-OBS-302-001/§7: per-metric active-series limits are enforced, and
samples over the policy are either rejected (with the SPEC-302 §10 code
``OBS_METRIC_CARDINALITY_EXCEEDED``, never silently dropped) or quarantined
(isolated but observable). The consumer-handler face never raises on policy
violations — a raising handler would crash-loop the journal consumer; it
records the rejection in the engine's observable rejection stream instead.

Unit layer: pure in-memory, injection-construction samples only.
"""

import pytest

from application.observation.metrics.engine import MetricsEngine, MetricsEngineConfig
from application.observation.metrics.errors import (
    OBS_METRIC_CARDINALITY_EXCEEDED,
    MetricError,
)
from domain.observation import (
    MetricSample,
    MetricSampleTimepoint,
    SeriesQuality,
)

from tests.unit.application.observation.metrics._metrics_fixtures import record, raw_envelope, ts_payload


def _sample(
    session_id: str = "sess-1",
    *,
    metric_name: str = "ts.packet_rate",
    t_ns: int = 1_000,
) -> MetricSample:
    return MetricSample(
        metric_name=metric_name,
        time=MetricSampleTimepoint(
            value_ns=t_ns,
            clock_domain=f"sim:{session_id}",
            clock_epoch=0,
            semantics="source",
        ),
        value=42,
        dimensions={"session_id": session_id},
        quality=(SeriesQuality.GOOD,),
    )


def _engine(limit: int, mode: str) -> MetricsEngine:
    return MetricsEngine(
        config=MetricsEngineConfig(
            default_max_series_per_metric=limit,
            cardinality_mode=mode,
        )
    )


# --- reject mode ----------------------------------------------------------------


def test_reject_mode_refuses_series_over_the_limit_with_the_canonical_code() -> None:
    engine = _engine(limit=2, mode="reject")
    engine.ingest_sample(_sample("sess-1"))
    engine.ingest_sample(_sample("sess-2"))
    with pytest.raises(MetricError) as excinfo:
        engine.ingest_sample(_sample("sess-3"))
    assert excinfo.value.error_code == OBS_METRIC_CARDINALITY_EXCEEDED
    assert excinfo.value.retryable is False


def test_reject_mode_records_consumer_path_rejections_without_raising() -> None:
    # The JournalTailingConsumer handler must not raise on policy violations:
    # a raising handler crashes the batch and loops the redelivery. The
    # third series is refused AND visibly recorded (never a silent drop).
    engine = _engine(limit=1, mode="reject")
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", session_id="sess-1"
            ),
            journal_seq=1,
        )
    )
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", session_id="sess-2"
            ),
            journal_seq=2,
        )
    )
    assert len(engine.rejections) == 1
    assert (
        engine.rejections[0].code == OBS_METRIC_CARDINALITY_EXCEEDED
    )
    assert engine.samples(
        "simulation.virtual_time_ns", clock_domain="sim:sess-2"
    ) == ()


def test_series_limit_counts_distinct_dimension_sets_not_samples() -> None:
    engine = _engine(limit=2, mode="reject")
    engine.ingest_sample(_sample("sess-1", t_ns=1))
    engine.ingest_sample(_sample("sess-1", t_ns=2))  # same series: fine
    engine.ingest_sample(_sample("sess-2", t_ns=3))  # second series: fine
    with pytest.raises(MetricError):
        engine.ingest_sample(_sample("sess-3", t_ns=4))


def test_limits_are_per_metric_not_global() -> None:
    engine = _engine(limit=1, mode="reject")
    engine.ingest_sample(_sample("sess-1", metric_name="ts.packet_rate"))
    # A different metric has its own active-series budget.
    engine.ingest_sample(
        _sample("sess-1", metric_name="ts.bitrate", t_ns=5)
    )


# --- quarantine mode ------------------------------------------------------------


def test_quarantine_mode_isolates_the_sample_but_keeps_it_observable() -> None:
    engine = _engine(limit=1, mode="quarantine")
    engine.ingest_sample(_sample("sess-1"))
    engine.ingest_sample(_sample("sess-2", t_ns=2))

    quarantined = engine.quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].code == OBS_METRIC_CARDINALITY_EXCEEDED
    assert quarantined[0].sample.dimensions["session_id"] == "sess-2"
    # The quarantined sample never entered the series.
    assert engine.samples("ts.packet_rate", clock_domain="sim:sess-2") == ()


def test_quarantine_mode_consumer_path_isolates_without_raising() -> None:
    engine = _engine(limit=1, mode="quarantine")
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", session_id="sess-1"
            ),
            journal_seq=1,
        )
    )
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", session_id="sess-2"
            ),
            journal_seq=2,
        )
    )
    assert len(engine.quarantined()) == 1
    assert engine.rejections == ()


# --- dimension whitelist at ingest (SPEC-302 §5/§10) ----------------------------


def test_ingest_refuses_dimensions_outside_the_definition_whitelist() -> None:
    from application.observation.metrics.errors import (
        OBS_METRIC_DIMENSION_REJECTED,
    )

    engine = MetricsEngine()
    # simulation.virtual_time_ns allows exactly {session_id} — a stream_id
    # dimension is outside the whitelist and is strictly rejected (SPEC-302
    # §5 default) with the §10 code, never silently dropped.
    sample = _sample("sess-1", metric_name="simulation.virtual_time_ns")
    bad = sample.model_copy(
        update={"dimensions": {"session_id": "sess-1", "stream_id": "x"}}
    )
    with pytest.raises(MetricError) as excinfo:
        engine.ingest_sample(bad)
    assert excinfo.value.error_code == OBS_METRIC_DIMENSION_REJECTED
