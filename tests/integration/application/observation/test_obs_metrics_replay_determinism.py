"""Metrics engine over the real journal — deterministic replay (ticket #50).

REQ-OBS-302-005 (SPEC-302 §9): replaying the SAME event journal with the
SAME metric definitions must produce identical metric values AND bucket
boundaries. The full SPEC-300 §7 data flow runs here: gateway accept →
drain → SQLite journal stamp → ``JournalTailingConsumer`` (consumer_id
``metrics-engine``) → engine derivations → ``MetricsService.query``.

The replay constructs a FRESH engine + a fresh checkpoint view over the
same journal file and re-consumes from seq 0 — finalization watermarks,
late flags, revisions and quality flags all derive from journal arrival
order only, so both passes must agree field for field.

Integration layer: real file-backed SQLite (WAL) via the ``journal``
fixture; the ts.* observations ride the documented G3 fixture contract
(catalog module docstring).
"""

import pytest

from domain.observation import AggregationOperation

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.gateway import EventGateway, IngestOutcome
from application.observation.metrics.engine import (
    MetricsEngine,
    build_metrics_consumer,
)
from application.observation.metrics.service import (
    MetricQueryRequest,
    MetricsService,
)
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir

from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    ts_payload,
)

SESSION_ID = "sess-replay"
DOMAIN = f"sim:{SESSION_ID}"


@pytest.fixture
def db_path(journal):
    """The ``journal`` fixture's migrated file database path."""
    return journal.db_path


def _memory_checkpoints() -> SqliteCheckpointStore:
    """A migrated empty cursor store (full from-scratch replay)."""
    connection = connect(":memory:")
    apply_sql_migrations(connection, default_migrations_dir())
    return SqliteCheckpointStore(connection)


def _events():
    """The fixed journal program: simulation clock + ts fixture observations.

    Times deliberately non-monotonic at the tail (a late arrival: 150 after
    300) so finalization/late-flag/revision logic is inside the replay
    equivalence, not just the happy path.
    """
    def envelope(**overrides):
        return raw_envelope(session_id=SESSION_ID, **overrides)

    return [
        envelope(
            event_type="simulation.run_started", source_ns=100, run_id="run-1"
        ),
        envelope(
            event_type="simulation.run_started", source_ns=300, run_id="run-1"
        ),
        envelope(
            event_type="ts.continuity_error",
            source_ns=120,
            run_id="run-1",
            pid=256,
            payload=ts_payload(pid=256),
        ),
        envelope(
            event_type="ts.continuity_error",
            source_ns=180,
            run_id="run-1",
            pid=256,
            payload=ts_payload(pid=256),
        ),
        envelope(
            event_type="ts.pcr_jitter_observed",
            source_ns=140,
            run_id="run-1",
            pid=256,
            payload=ts_payload(pid=256, jitter_ns=250_000, gap_ns=12_000_000),
        ),
        envelope(
            event_type="ts.packet_batch_observed",
            source_ns=150,
            run_id="run-1",
            payload=ts_payload(
                packet_count=1000,
                byte_count=188_000,
                duration_ns=1_000_000_000,
                null_packet_count=100,
                scrambled_packet_count=50,
                stream_id="svc-main",
            ),
        ),
        # Late relative to the 300 watermark: t=150 lands back in [100,200).
        envelope(
            event_type="simulation.run_progress", source_ns=150, run_id="run-1"
        ),
    ]


def _journal_on(db_path):
    return SqliteEventJournal(connect(db_path))


def _ingest(db_path) -> None:
    """Producers → gateway → dispatcher drain → stamped journal rows."""
    gateway = EventGateway(journal=_journal_on(db_path))
    for envelope in _events():
        result = gateway.accept(envelope)
        assert result.outcome is IngestOutcome.ACCEPTED, (
            result.error_code,
            gateway.failures(),
        )
    gateway.drain()
    assert gateway.metrics().queue_depth == 0


def _consume(db_path, *, checkpoints=None):
    """A fresh engine replaying the journal from seq 0 (metrics-engine).

    The replay's cursor store is ``:memory:`` by default: the durable
    per-session cursor is exactly what makes a RESTART resume mid-stream
    (the correct production behavior), so a full from-scratch replay needs
    an empty cursor — not a new connection to the already-stamped store.
    """
    engine = MetricsEngine()
    if checkpoints is None:
        checkpoints = _memory_checkpoints()
    consumer = build_metrics_consumer(
        journal=_journal_on(db_path),
        checkpoints=checkpoints,
        session_id=SESSION_ID,
        engine=engine,
    )
    processed = consumer.catch_up()
    assert processed == len(_events())
    return engine, consumer


def _request(**overrides) -> MetricQueryRequest:
    fields = {
        "start_ns": 0,
        "end_ns": 400,
        "step_ns": 100,
        "clock_domain": DOMAIN,
    }
    fields.update(overrides)
    return MetricQueryRequest(**fields)


def _snapshot(engine: MetricsEngine):
    """The query program held constant across replays."""
    service = MetricsService(engine)
    return {
        "virtual_time_last": service.query(
            _request(metric_names=("simulation.virtual_time_ns",))
        ),
        "virtual_time_max": service.query(
            _request(
                metric_names=("simulation.virtual_time_ns",),
                aggregation_override=AggregationOperation.MAX,
            )
        ),
        "continuity_increase": service.query(
            _request(
                metric_names=("ts.continuity_error_total",),
                filters={"pid": 256},
            )
        ),
        "jitter_count": service.query(
            _request(metric_names=("ts.pcr_jitter_ns",), filters={"pid": 256})
        ),
        "packet_rate_avg": service.query(
            _request(
                metric_names=("ts.packet_rate",),
                aggregation_override=AggregationOperation.AVG,
            )
        ),
        "psi_absent_on_sim_domain": service.query(
            _request(metric_names=("psi.section_repetition_gap_ms",))
        ),
    }


def test_replaying_the_same_journal_reproduces_identical_queries(db_path) -> None:
    _ingest(db_path)

    first, consumer_a = _consume(db_path)
    first_snapshot = _snapshot(first)

    # REPLAY: fresh engine, empty cursor, same journal file — identical
    # values AND bucket boundaries AND revisions (§9). The journal's max_seq
    # is the lag watermark; a fully caught-up consumer shows zero lag.
    assert consumer_a.lag() == 0
    second, _consumer_b = _consume(db_path)
    second_snapshot = _snapshot(second)

    assert first_snapshot == second_snapshot

    # Spot-check the substance behind the equality.
    continuity = first_snapshot["continuity_increase"].series[0]
    # [0,100) miss | [100,200) baseline+one delta = 1 | rest miss.
    assert [p.value for p in continuity.points] == [None, 1, None, None]
    assert continuity.provenance.journal_watermark == len(_events())

    virtual = first_snapshot["virtual_time_last"].series[0]
    bucket_100 = virtual.points[1]
    # The bucket materializes after both arrivals (nothing was published
    # earlier), so the on-time t=100 and late t=150 samples aggregate at
    # revision 1; the watermark 300 ≥ 200 freezes it.
    assert bucket_100.value == 150
    assert bucket_100.is_final is True
    assert bucket_100.revision == 1
    late_samples = [
        s
        for s in second.samples(
            "simulation.virtual_time_ns", clock_domain=DOMAIN
        )
        if s.time.value_ns == 150
    ]
    assert late_samples and late_samples[0].quality == ("good", "late")


def test_consumer_checkpoints_under_the_metrics_engine_consumer_id(db_path) -> None:
    _ingest(db_path)
    checkpoints = SqliteCheckpointStore(connect(db_path))
    _consume(db_path, checkpoints=checkpoints)
    # The ticket's consumption posture: consumer_id "metrics-engine"; the
    # durable cursor in the session database advances per full batch.
    assert checkpoints.get("metrics-engine", SESSION_ID) == len(_events())


def test_gateway_operational_metrics_flow_through_the_engine(db_path) -> None:
    _ingest(db_path)
    engine, consumer = _consume(db_path)

    # A live gateway on the same session: its counters feed the operational
    # family one-to-one (GatewayMetrics field mapping, brief §2.3).
    gateway = EventGateway(journal=_journal_on(db_path))
    for envelope in _events()[:3]:
        assert gateway.accept(envelope).outcome is IngestOutcome.ACCEPTED
    gateway.drain()

    # consumer_lag_events = watermark − checkpoint, straight from the
    # consumer face (SPEC-300 §8): 3 unprocessed rows right now.
    lag_before = consumer.lag()
    assert lag_before == 3
    engine.poll_operational(
        SESSION_ID,
        gateway_metrics=gateway.metrics(),
        consumer_lag=consumer.lag(),
        wall_ns=5_000,
    )
    samples = engine.samples(
        "observation.ingest_events_total", clock_domain="wall:utc"
    )
    assert [s.value for s in samples] == [3]
    lag_samples = engine.samples(
        "observation.consumer_lag_events", clock_domain="wall:utc"
    )
    assert [s.value for s in lag_samples] == [3]

    # After the consumer catches up, the next poll shows the lag drain.
    consumer.catch_up()
    engine.poll_operational(
        SESSION_ID,
        gateway_metrics=gateway.metrics(),
        consumer_lag=consumer.lag(),
        wall_ns=6_000,
    )
    lag_samples = engine.samples(
        "observation.consumer_lag_events", clock_domain="wall:utc"
    )
    assert [s.value for s in lag_samples] == [3, 0]
