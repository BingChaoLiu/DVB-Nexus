"""SPEC-302 metrics engine ingestion derivations (ticket #50).

Seam: ``MetricsEngine.handle_record`` (the JournalTailingConsumer handler
face, consumer_id ``metrics-engine``) and ``MetricsEngine.poll_operational``
(the operational snapshot face for the ``observation.*`` family).

Coverage pinned here:

- ``simulation.virtual_time_ns`` derived from every simulation-family
  event's ``time.source`` (semantics ``source``, sim domain only —
  SPEC-302 §9: wall-clock series never merge into virtual time series);
- the ``ts.*``/``psi.*`` derivation contract (G3: fixture contract until the
  analysis bridge lands — see ``application.observation.metrics.catalog``);
  cumulative counter state; payload-key misses skip the metric without
  fabricating samples;
- journal watermark tracking (provenance, SPEC-302 §1);
- the operational family read directly from ``EventGateway.metrics()`` /
  consumer lag (watermark − checkpoint), stamped ``wall:utc`` — an
  independent series universe (SPEC-302 §9).

Unit layer: pure in-memory; envelopes schema-validated by the fixture.
"""

from application.observation.gateway import GatewayMetrics
from application.observation.metrics.engine import MetricsEngine

from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    record,
    ts_payload,
)


def _engine() -> MetricsEngine:
    return MetricsEngine()


def _sim_record(event_type: str, source_ns: int, journal_seq: int = 1, session_id="sess-1", **kwargs):
    return record(
        raw_envelope(
            event_type=event_type,
            session_id=session_id,
            source_ns=source_ns,
            **kwargs,
        ),
        journal_seq=journal_seq,
    )


# --- simulation.virtual_time_ns (SPEC-302 §4: 虚拟时钟) -------------------------


def test_run_event_derives_the_virtual_time_gauge() -> None:
    engine = _engine()
    engine.handle_record(_sim_record("simulation.run_started", source_ns=5_000))

    samples = engine.samples(
        "simulation.virtual_time_ns", clock_domain="sim:sess-1"
    )
    assert len(samples) == 1
    sample = samples[0]
    assert sample.value == 5_000
    assert sample.time.clock_domain == "sim:sess-1"
    assert sample.time.semantics.value == "source"
    assert sample.dimensions == {"session_id": "sess-1"}


def test_session_and_clock_family_events_also_carry_the_virtual_clock() -> None:
    engine = _engine()
    engine.handle_record(_sim_record("simulation.session_created", 100, 1))
    engine.handle_record(_sim_record("simulation.clock_advanced", 200, 2))
    values = [
        s.value
        for s in engine.samples(
            "simulation.virtual_time_ns", clock_domain="sim:sess-1"
        )
    ]
    assert values == [100, 200]


def test_non_simulation_events_do_not_fabricate_virtual_time_samples() -> None:
    engine = _engine()
    engine.handle_record(
        record(
            raw_envelope(
                event_type="fault.injected",
                payload={
                    "fault_id": "f-1",
                    "fault_type": "PAT_MISSING",
                    "injection_index": 0,
                    "expected_observations": ["ts.psi_section_observed"],
                },  # SPEC-204 §9 shape (ticket #56 registry branch)
            ),
            journal_seq=1,
        )
    )
    assert engine.samples(
        "simulation.virtual_time_ns", clock_domain="sim:sess-1"
    ) == ()


# --- ts.* derivation contract (G3 fixture contract, SPEC-302 §4) ----------------


def test_continuity_errors_accumulate_per_series_with_pid_dimension() -> None:
    engine = _engine()
    engine.handle_record(
        _sim_record(
            "ts.continuity_error",
            1_000,
            1,
            payload=ts_payload(pid=256),
            pid=256,
        )
    )
    engine.handle_record(
        _sim_record(
            "ts.continuity_error", 2_000, 2, payload=ts_payload(pid=256), pid=256
        )
    )
    engine.handle_record(
        _sim_record(
            "ts.continuity_error", 3_000, 3, payload=ts_payload(pid=512), pid=512
        )
    )
    pid_256 = engine.samples(
        "ts.continuity_error_total",
        clock_domain="sim:sess-1",
        dimensions={"session_id": "sess-1", "pid": 256},
    )
    assert [s.value for s in pid_256] == [1, 2]  # cumulative per series
    pid_512 = engine.samples(
        "ts.continuity_error_total",
        clock_domain="sim:sess-1",
        dimensions={"session_id": "sess-1", "pid": 512},
    )
    assert [s.value for s in pid_512] == [1]


def test_pcr_jitter_event_yields_histogram_and_repetition_gap_samples() -> None:
    engine = _engine()
    engine.handle_record(
        _sim_record(
            "ts.pcr_jitter_observed",
            4_000,
            1,
            payload=ts_payload(pid=256, jitter_ns=250_000, gap_ns=12_000_000),
            pid=256,
        )
    )
    jitter = engine.samples(
        "ts.pcr_jitter_ns", clock_domain="sim:sess-1"
    )
    assert [s.value for s in jitter] == [250_000]
    gaps = engine.samples(
        "ts.pcr_repetition_gap_ns", clock_domain="sim:sess-1"
    )
    assert [s.value for s in gaps] == [12_000_000]


def test_pcr_event_without_jitter_value_skips_the_histogram_without_error() -> None:
    # G3 contract: a payload missing the derivation key skips the metric —
    # the engine never fabricates a value (缺失 ≠ 零, SPEC-302 §6.3).
    engine = _engine()
    engine.handle_record(
        _sim_record(
            "ts.pcr_jitter_observed", 4_000, 1, payload=ts_payload(pid=256), pid=256
        )
    )
    assert engine.samples("ts.pcr_jitter_ns", clock_domain="sim:sess-1") == ()


def test_packet_batch_derives_rate_bitrate_and_ratio_series() -> None:
    engine = _engine()
    # 1000 packets (100 null, 50 scrambled), 188000 bytes over exactly 1 s.
    engine.handle_record(
        _sim_record(
            "ts.packet_batch_observed",
            5_000,
            1,
            payload=ts_payload(
                packet_count=1000,
                byte_count=188_000,
                duration_ns=1_000_000_000,
                null_packet_count=100,
                scrambled_packet_count=50,
                stream_id="svc-main",
            ),
        )
    )
    domain = "sim:sess-1"
    assert [
        s.value
        for s in engine.samples("ts.packet_rate", clock_domain=domain)
    ] == [1000.0]
    assert [
        s.value for s in engine.samples("ts.bitrate", clock_domain=domain)
    ] == [1_504_000.0]
    assert [
        s.value for s in engine.samples("ts.null_packet_ratio", clock_domain=domain)
    ] == [0.1]
    assert [
        s.value
        for s in engine.samples("ts.scrambled_packet_ratio", clock_domain=domain)
    ] == [0.05]


def test_psi_section_gap_derives_the_millisecond_gauge() -> None:
    engine = _engine()
    engine.handle_record(
        _sim_record(
            "ts.psi_section_observed",
            6_000,
            1,
            payload=ts_payload(gap_ms=3.5, service_id="service-100"),
            service_id="service-100",
        )
    )
    samples = engine.samples(
        "psi.section_repetition_gap_ms", clock_domain="sim:sess-1"
    )
    assert [s.value for s in samples] == [3.5]
    assert samples[0].dimensions["service_id"] == "service-100"


def test_topology_event_derives_the_degraded_node_gauge() -> None:
    engine = _engine()
    engine.handle_record(
        _sim_record(
            "topology.state_changed",
            7_000,
            1,
            payload={"degraded_node_count": 2},
        )
    )
    samples = engine.samples(
        "topology.degraded_node_count", clock_domain="sim:sess-1"
    )
    assert [s.value for s in samples] == [2]


# --- watermark and defensive paths -----------------------------------------------


def test_journal_watermark_tracks_the_consumed_records() -> None:
    engine = _engine()
    engine.handle_record(_sim_record("simulation.run_started", 1, 3))
    engine.handle_record(_sim_record("simulation.run_progress", 2, 7))
    assert engine.journal_watermark == 7


def test_record_without_session_id_is_recorded_as_rejection() -> None:
    # Session-domain metrics carry session in dimensions (SPEC-302 §5) —
    # a system-level record (session null, journal-side impossible per G4
    # but defended here) is refused visibly, never attributed to "" scope.
    engine = _engine()
    engine.handle_record(
        record(
            raw_envelope(
                event_type="simulation.run_started", session_id=None
            ),
            journal_seq=1,
        )
    )
    assert len(engine.rejections) == 1
    assert engine.journal_watermark == 1


# --- operational family (SPEC-302 §4 observation.*; §9 wall independence) -------


def test_poll_operational_maps_the_gateway_counters_one_to_one() -> None:
    engine = _engine()
    samples = engine.poll_operational(
        "sess-1",
        gateway_metrics=GatewayMetrics(
            queue_depth=0,
            accepted=5,
            duplicate=2,
            rejected=0,
            coalesced=0,
            journal_duplicates=1,
            subscriber_errors=0,
            storage_failures=0,
            unhealthy=False,
        ),
        consumer_lag=4,
        wall_ns=1_000_000,
    )
    by_name = {s.metric_name: s for s in samples}
    assert by_name["observation.ingest_events_total"].value == 5
    # Total duplicates across BOTH dedup layers (gateway cache + journal).
    assert by_name["observation.duplicate_events_total"].value == 3
    assert by_name["observation.consumer_lag_events"].value == 4
    assert set(by_name) == {
        "observation.ingest_events_total",
        "observation.duplicate_events_total",
        "observation.consumer_lag_events",
    }
    for sample in samples:
        assert sample.time.clock_domain == "wall:utc"
        assert sample.time.semantics.value == "observed"


def test_poll_operational_includes_alerts_active_only_when_measured() -> None:
    engine = _engine()
    gateway_metrics = GatewayMetrics(
        queue_depth=0, accepted=0, duplicate=0, rejected=0, coalesced=0,
        journal_duplicates=0, subscriber_errors=0, storage_failures=0,
        unhealthy=False,
    )
    assert not any(
        s.metric_name == "observation.alerts_active"
        for s in engine.poll_operational(
            "sess-1", gateway_metrics=gateway_metrics,
            consumer_lag=0, wall_ns=1,
        )
    )
    alerted = engine.poll_operational(
        "sess-1", gateway_metrics=gateway_metrics,
        consumer_lag=0, wall_ns=2, alerts_active=2,
    )
    active = [s for s in alerted if s.metric_name == "observation.alerts_active"]
    assert [s.value for s in active] == [2]


def test_operational_series_live_in_the_wall_domain_not_the_sim_domain() -> None:
    # SPEC-302 §9: 墙钟操作指标是独立序列，不得并入虚拟时间序列。
    engine = _engine()
    engine.handle_record(_sim_record("simulation.run_started", 9_000, 1))
    gateway_metrics = GatewayMetrics(
        queue_depth=0, accepted=1, duplicate=0, rejected=0, coalesced=0,
        journal_duplicates=0, subscriber_errors=0, storage_failures=0,
        unhealthy=False,
    )
    engine.poll_operational(
        "sess-1", gateway_metrics=gateway_metrics, consumer_lag=0, wall_ns=50
    )
    assert engine.samples(
        "observation.ingest_events_total", clock_domain="wall:utc"
    )
    assert engine.samples(
        "observation.ingest_events_total", clock_domain="sim:sess-1"
    ) == ()
    assert engine.samples(
        "simulation.virtual_time_ns", clock_domain="wall:utc"
    ) == ()
