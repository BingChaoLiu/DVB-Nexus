"""Journal → metrics → alerts full chain (ticket #52).

The SPEC-300 §7 data flow end-to-end over REAL file-backed SQLite (WAL, the
``journal`` fixture): producers → gateway accept/drain → stamped journal →
``JournalTailingConsumer`` (``metrics-engine``, ticket #50) → derived
samples → ``MetricsWindowReader`` (additive public-face consumption) →
``AlertService`` lifecycle evaluation → the ``alerts`` table (record
authority) → hint emission through the injected port.

Pinned here (beyond the unit slices):

- REQ-OBS-304-006: every emitted evidence ref RESOLVES through the
  ``MetricsService.query`` public face — the bucket window contains the
  immutable derived samples (fact chain, no fabrication);
- REQ-OBS-304-003: after the whole flow the journal contains ZERO
  ``observation.*`` events (the namespace is withdrawn, SPEC-301 §4) and
  every journal event type stays registered;
- Ruling H (optional wiring): ``AlertService.active_count`` feeds
  ``MetricsEngine.poll_operational(alerts_active=...)`` — the
  ``observation.alerts_active`` series becomes queryable on the wall domain;
- store restart: a fresh ``SqliteAlertStore`` connection over the same
  database file sees the persisted record (durable authority).

The ``ts.*`` observations ride the documented G3 fixture contract
(catalog module docstring) — journal-derived, never fabricated by the
alert engine.
"""

import pytest

from domain.observation import AlertState, parse_envelope

from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.alerts.engine import AlertEngine, AlertEngineConfig
from application.observation.alerts.inputs import MetricsWindowReader
from application.observation.alerts.rules import default_rule_set
from application.observation.alerts.service import AlertListRequest, AlertService
from application.observation.gateway import EventGateway, GatewayMetrics, IngestOutcome
from application.observation.metrics.engine import (
    MetricsEngine,
    build_metrics_consumer,
)
from application.observation.metrics.service import (
    MetricQueryRequest,
    MetricsService,
)
from application.observation.alerts.store import LIST_LIMIT_DEFAULT

from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.application.observation.alerts._alerts_fixtures import (
    RecordingHintEmitter,
)
from tests.unit.application.observation.metrics._metrics_fixtures import (
    raw_envelope,
    ts_payload,
)

SESSION_ID = "sess-alerts"
DOMAIN = f"sim:{SESSION_ID}"
PID = 100
#: Above the PCR_JITTER_HIGH open threshold (p95 > 50 ms, mvp-sandbox).
HIGH_JITTER_NS = 60_000_000
WINDOW_NS = 10_000_000_000  # the rule's evaluation window
FIRST_EVAL_NS = 12_000_000_000  # bucket start = 2 s (positive anchors)
SECOND_EVAL_NS = 14_000_000_000  # for_duration 2 s elapsed → firing

MIGRATIONS_DIR = None  # resolved lazily (default_migrations_dir())


def _events():
    """Four high-jitter observations inside [2 s, 12 s)."""
    stamps = (3_000_000_000, 5_000_000_000, 7_000_000_000, 9_000_000_000)
    return [
        raw_envelope(
            event_type="ts.pcr_jitter_observed",
            session_id=SESSION_ID,
            source_ns=stamp,
            pid=PID,
            payload=ts_payload(pid=PID, jitter_ns=HIGH_JITTER_NS, gap_ns=1_000_000),
        )
        for stamp in stamps
    ]


def _ingest(db_path) -> EventGateway:
    journal = SqliteEventJournal(connect(db_path))
    gateway = EventGateway(journal=journal)
    for envelope in _events():
        result = gateway.accept(envelope)
        assert result.outcome is IngestOutcome.ACCEPTED, (
            result.error_code,
            gateway.failures(),
        )
    gateway.drain()
    return gateway


def _consume(db_path) -> MetricsEngine:
    engine = MetricsEngine()
    cursor_connection = connect(":memory:")
    migrations_dir = default_migrations_dir()
    if migrations_dir is not None:
        apply_sql_migrations(cursor_connection, migrations_dir)
    consumer = build_metrics_consumer(
        journal=SqliteEventJournal(connect(db_path)),
        checkpoints=SqliteCheckpointStore(cursor_connection),
        session_id=SESSION_ID,
        engine=engine,
    )
    assert consumer.catch_up() == len(_events())
    return engine


def _alert_store(db_path) -> SqliteAlertStore:
    connection = connect(db_path)
    migrations_dir = default_migrations_dir()
    if migrations_dir is not None:
        apply_sql_migrations(connection, migrations_dir)
    return SqliteAlertStore(connection)


def _service(db_path, emitter) -> AlertService:
    return AlertService(
        _alert_store(db_path),
        default_rule_set(),
        engine=AlertEngine(
            default_rule_set(),
            config=AlertEngineConfig(alert_id_factory=lambda: f"alert-{len(emitter.hints):04d}"),
        ),
        hint_emitter=emitter,
    )


def _jitter_query(bucket_start_ns: int) -> MetricQueryRequest:
    return MetricQueryRequest(
        metric_names=("ts.pcr_jitter_ns",),
        start_ns=bucket_start_ns,
        end_ns=bucket_start_ns + WINDOW_NS,
        step_ns=WINDOW_NS,
        clock_domain=DOMAIN,
        filters={"pid": PID},
    )


@pytest.fixture
def db_path(journal):
    return journal.db_path


class TestAlertsJournalChain:
    def test_full_chain_persists_firing_with_resolvable_evidence(
        self, db_path
    ) -> None:
        gateway = _ingest(db_path)
        engine = _consume(db_path)
        emitter = RecordingHintEmitter()
        service = _service(db_path, emitter)
        reader = MetricsWindowReader(engine)

        # Tick 1: breach measured → pending (bucket start = 2 s).
        first = service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN
        )
        assert [t.to_state for t in first.evaluation.transitions] == [
            AlertState.PENDING
        ]
        pending_refs = first.records[0].evidence_refs
        # Tick 2: for_duration elapsed → firing.
        second = service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        assert [t.to_state for t in second.evaluation.transitions] == [
            AlertState.FIRING
        ]

        # Record authority: the alerts table holds the firing record.
        page = service.list(
            AlertListRequest(
                session_id=SESSION_ID, limit=LIST_LIMIT_DEFAULT
            )
        )
        assert page.total == 1
        record = page.items[0]
        assert record.state is AlertState.FIRING
        assert record.rule_id == "PCR_JITTER_HIGH"
        assert str(HIGH_JITTER_NS) in record.summary  # the measured fact
        assert len(emitter.hints) == 2  # pending + firing hints emitted

        # REQ-304-006: evidence refs resolve through the metrics face. The
        # pending tick's window [2 s, 12 s) covers all four derived samples;
        # the firing migration rewrites the record evidence to its own
        # window ([4 s, 12 s) → three samples) — each bucket non-empty.
        metrics_service = MetricsService(engine)

        def _resolve(ref: str) -> int:
            assert ref.startswith("metric:ts.pcr_jitter_ns:bucket-")
            bucket_start_ns = int(ref.rsplit("bucket-", 1)[1])
            result = metrics_service.query(_jitter_query(bucket_start_ns))
            assert result.series, f"unresolvable evidence ref {ref}"
            counts = [
                point.value
                for point in result.series[0].points
                if point.value is not None
            ]
            assert counts, f"empty evidence bucket for {ref}"
            return int(sum(counts))

        assert sum(_resolve(ref) for ref in pending_refs) >= len(_events())
        assert record.evidence_refs
        for ref in record.evidence_refs:
            assert _resolve(ref) >= 1

        # Restart: a fresh store connection sees the durable record.
        reopened = _alert_store(db_path)
        assert reopened.get(record.alert_id).state is AlertState.FIRING
        assert gateway.metrics().storage_failures == 0

    def test_journal_stays_zero_observation_events(self, db_path) -> None:
        """REQ-304-003: MVP 零 observation.* 信封事件 (SPEC-301 §4)."""
        _ingest(db_path)
        engine = _consume(db_path)
        service = _service(db_path, RecordingHintEmitter())
        reader = MetricsWindowReader(engine)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN)

        journal = SqliteEventJournal(connect(db_path))
        rows = journal.query(SESSION_ID, after_seq=0, limit=1000)
        assert rows, "the chain must have produced journal events"
        for row in rows:
            # Every journal event type is a REGISTERED type...
            assert row.event_type in {
                "ts.pcr_jitter_observed",
            }
            # ...and nothing observation.* ever entered the journal (the
            # alert plane produced records + hints, not envelope events).
            assert not row.event_type.startswith("observation.")
            parse_envelope(row.envelope)  # revalidates the contract

    def test_ruling_h_alerts_active_feeds_poll_operational(self, db_path) -> None:
        _ingest(db_path)
        engine = _consume(db_path)
        service = _service(db_path, RecordingHintEmitter())
        reader = MetricsWindowReader(engine)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN)
        active = service.active_count(SESSION_ID)
        assert active == 1

        # Ruling H: the composition feeds the count into the #50 operational
        # family (wall domain — never merged into virtual-time series).
        metrics_service = MetricsService(engine)
        gateway_metrics = GatewayMetrics(
            queue_depth=0,
            accepted=len(_events()),
            duplicate=0,
            rejected=0,
            coalesced=0,
            journal_duplicates=0,
            subscriber_errors=0,
            storage_failures=0,
            unhealthy=False,
        )
        samples = engine.poll_operational(
            SESSION_ID,
            gateway_metrics=gateway_metrics,
            consumer_lag=0,
            wall_ns=1_000,
            alerts_active=active,
        )
        assert samples[-1].metric_name == "observation.alerts_active"
        result = metrics_service.query(
            MetricQueryRequest(
                metric_names=("observation.alerts_active",),
                start_ns=0,
                end_ns=10_000,
                step_ns=10_000,
                clock_domain="wall:utc",
            )
        )
        assert result.series[0].points[-1].value == active

    def test_health_rollup_over_real_inputs(self, db_path) -> None:
        _ingest(db_path)
        engine = _consume(db_path)
        service = _service(db_path, RecordingHintEmitter())
        reader = MetricsWindowReader(engine)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN)
        service.evaluate_session(SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN)
        health = service.health(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        # A firing warning rule with no critical → degraded (§7 branch 2).
        assert health.overall.value == "degraded"
        timing = [
            entry
            for entry in health.dimensions
            if entry.dimension.value == "timing"
        ]
        assert timing and timing[0].status.value == "degraded"
        assert health.rule_set_version == default_rule_set().version
