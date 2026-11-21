"""``rf.state_observed`` journal chain → alert firing (ticket #166).

The SPEC-300 §7 data flow for the Phase 3 alert inputs, over REAL file-backed
SQLite (WAL, the ``journal`` fixture): state_evaluator tuner snapshots →
gateway accept (payload registry strict validation, SPEC-303 §Phase3) →
stamped journal → ``JournalTailingConsumer`` (``metrics-engine``) → the
additive ``tuner.lock_state``/``tuner.ber_state`` gauges →
``MetricsWindowReader`` → ``AlertService`` over the shipped default rule set
→ the ``alerts`` table (record authority).

Pinned here (beyond the unit slices):

- TUNER_UNLOCKED (warning) and BER_SEVERE (error) fire end-to-end from
  state_evaluator observations (simulated confidence — the constant pairing
  rides inside the payloads, never re-labelled);
- the elevated tier stays alert-silent on the real chain (SPEC-304 §Phase3
  elevated 不告警): an elevated-only tuner slot never migrates;
- REQ-304-006: every emitted evidence ref resolves through the metrics
  query face (``metric:tuner.<state>:bucket-<start>`` → non-empty points);
- REQ-OBS-304-003: zero ``observation.*`` envelope events in the journal —
  the alert plane produces records + REST pulls, never envelope events;
- the composition wiring needs NO changes: the bootstrap already binds
  ``default_rule_set()`` + ``MetricsWindowReader(MetricsEngine)`` (ruling
  A6 — the additive catalog entries ride the existing ingestion face).
"""

import pytest

from domain.observation import AlertState, parse_envelope

from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.alerts.inputs import MetricsWindowReader
from application.observation.alerts.rules import default_rule_set
from application.observation.alerts.service import AlertListRequest, AlertService
from application.observation.alerts.store import LIST_LIMIT_DEFAULT
from application.observation.gateway import EventGateway, IngestOutcome
from application.observation.metrics.engine import (
    MetricsEngine,
    build_metrics_consumer,
)
from application.observation.metrics.service import MetricQueryRequest, MetricsService

from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.application.observation.metrics._metrics_fixtures import raw_envelope

SESSION_ID = "sess-rf-alerts"
DOMAIN = f"sim:{SESSION_ID}"
UNLOCKED_NODE = "tuner-a"  # UB-conflict style: unlocked, keeps no BER grade
SEVERE_NODE = "tuner-b"  # tone-residue style: mislocked onto a neighbour slot
ELEVATED_NODE = "tuner-c"  # guard-band style: elevated — never alerts

#: Snapshots land at 3 s / 4 s / 5 s; the rule window is the sandbox
#: standard 10 s, so both evaluation ticks still see every snapshot.
SNAP_A_NS = 3_000_000_000
SNAP_B_NS = 4_000_000_000
SNAP_C_NS = 5_000_000_000
FIRST_EVAL_NS = 11_000_000_000  # tick 1: both breach slots arm → pending
SECOND_EVAL_NS = 12_000_000_000  # tick 2: for_duration 0 elapsed → firing

UNLOCKED_PAYLOAD = {
    "node_id": UNLOCKED_NODE,
    "health": "error",
    "causes": [{"node_id": "lnb-0"}],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "unlocked",
    "if_frequency_khz": None,
    "ber_state": None,  # unlocked keeps no grade (the #164 registry face)
    "locked_transponder_id": None,
    "stale": True,
}
SEVERE_PAYLOAD = {
    "node_id": SEVERE_NODE,
    "health": "error",
    "causes": [],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "locked",  # mislocked onto a neighbour transponder slot
    "if_frequency_khz": 1_150_000,
    "ber_state": "severe",
    "locked_transponder_id": "tp-neighbour",
    "stale": False,
}
ELEVATED_PAYLOAD = {
    "node_id": ELEVATED_NODE,
    "health": "warn",
    "causes": [],
    "source": "state_evaluator",
    "confidence": "simulated",
    "lock_state": "locked",
    "if_frequency_khz": 1_230_000,
    "ber_state": "elevated",  # guard band — the SPEC-307 tier, no alert
    "locked_transponder_id": "tp-1",
    "stale": False,
}


def _snapshots():
    return [
        raw_envelope(
            event_type="rf.state_observed",
            session_id=SESSION_ID,
            source_ns=stamp,
            payload=payload,
        )
        for stamp, payload in (
            (SNAP_A_NS, UNLOCKED_PAYLOAD),
            (SNAP_B_NS, SEVERE_PAYLOAD),
            (SNAP_C_NS, ELEVATED_PAYLOAD),
        )
    ]


def _ingest(db_path) -> EventGateway:
    journal = SqliteEventJournal(connect(db_path))
    gateway = EventGateway(journal=journal)
    for document in _snapshots():
        parse_envelope(document)  # the payload registry validates the snapshot
        result = gateway.accept(document)
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
    assert consumer.catch_up() == len(_snapshots())
    return engine


def _alert_service(db_path) -> AlertService:
    connection = connect(db_path)
    migrations_dir = default_migrations_dir()
    if migrations_dir is not None:
        apply_sql_migrations(connection, migrations_dir)
    return AlertService(SqliteAlertStore(connection), default_rule_set())


@pytest.fixture
def db_path(journal):
    return journal.db_path


class TestRfAlertsChain:
    def test_unlocked_and_severe_fire_end_to_end_with_resolvable_evidence(
        self, db_path
    ) -> None:
        _ingest(db_path)
        engine = _consume(db_path)
        service = _alert_service(db_path)
        reader = MetricsWindowReader(engine)

        first = service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN
        )
        assert sorted(t.to_state.value for t in first.evaluation.transitions) == [
            "pending",
            "pending",
        ]
        second = service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        firing = [
            t for t in second.evaluation.transitions if t.to_state is AlertState.FIRING
        ]
        assert sorted((t.rule_id, t.severity.value) for t in firing) == [
            ("BER_SEVERE", "error"),
            ("TUNER_UNLOCKED", "warning"),
        ]

        # Record authority: both firing records persist with per-node grouping
        # (distinct fingerprint slots — one (rule, node) each).
        page = service.list(
            AlertListRequest(session_id=SESSION_ID, limit=LIST_LIMIT_DEFAULT)
        )
        assert page.total == 2
        by_rule = {record.rule_id: record for record in page.items}
        assert by_rule["TUNER_UNLOCKED"].state is AlertState.FIRING
        assert by_rule["BER_SEVERE"].state is AlertState.FIRING
        assert by_rule["BER_SEVERE"].severity.value == "error"
        assert "tuner.ber_state last = 2" in by_rule["BER_SEVERE"].summary
        assert (
            by_rule["TUNER_UNLOCKED"].fingerprint
            != by_rule["BER_SEVERE"].fingerprint
        )

        # REQ-304-006: the evidence refs resolve through the metrics face.
        metrics_service = MetricsService(engine)
        for rule_id, metric_name in (
            ("TUNER_UNLOCKED", "tuner.lock_state"),
            ("BER_SEVERE", "tuner.ber_state"),
        ):
            for ref in by_rule[rule_id].evidence_refs:
                assert ref.startswith(f"metric:{metric_name}:bucket-")
                bucket_start_ns = int(ref.rsplit("bucket-", 1)[1])
                result = metrics_service.query(
                    MetricQueryRequest(
                        metric_names=(metric_name,),
                        start_ns=bucket_start_ns,
                        end_ns=bucket_start_ns + 10_000_000_000,
                        step_ns=10_000_000_000,
                        clock_domain=DOMAIN,
                    )
                )
                points = [
                    point.value
                    for series in result.series
                    for point in series.points
                    if point.value is not None
                ]
                assert points, f"empty evidence bucket for {ref}"

        # Restart: a fresh store connection sees the durable records.
        reopened = SqliteAlertStore(connect(db_path))
        for record in page.items:
            assert reopened.get(record.alert_id).state is AlertState.FIRING

    def test_elevated_tuner_slot_stays_alert_silent(self, db_path) -> None:
        """SPEC-304 §Phase3: elevated 不告警 — the elevated-only slot never
        migrates while the two breach slots fire beside it."""
        _ingest(db_path)
        engine = _consume(db_path)
        service = _alert_service(db_path)
        reader = MetricsWindowReader(engine)
        service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN
        )
        second = service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        assert all(
            t.group_key != (("node_id", ELEVATED_NODE),)
            for t in second.evaluation.transitions
        )
        page = service.list(
            AlertListRequest(session_id=SESSION_ID, limit=LIST_LIMIT_DEFAULT)
        )
        assert page.total == 2  # the two breach slots only

    def test_journal_stays_zero_observation_events(self, db_path) -> None:
        """REQ-304-003: the alert plane produces records, never envelopes."""
        _ingest(db_path)
        engine = _consume(db_path)
        service = _alert_service(db_path)
        reader = MetricsWindowReader(engine)
        service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN
        )
        service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )

        journal = SqliteEventJournal(connect(db_path))
        rows = journal.query(SESSION_ID, after_seq=0, limit=1000)
        assert rows, "the chain must have produced journal events"
        for row in rows:
            assert row.event_type in {"rf.state_observed"}
            assert not row.event_type.startswith("observation.")
            parse_envelope(row.envelope)  # revalidates the contract

    def test_health_rollup_degrades_on_the_two_firings(self, db_path) -> None:
        _ingest(db_path)
        engine = _consume(db_path)
        service = _alert_service(db_path)
        reader = MetricsWindowReader(engine)
        service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=FIRST_EVAL_NS, clock_domain=DOMAIN
        )
        service.evaluate_session(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        health = service.health(
            SESSION_ID, reader=reader, now_ns=SECOND_EVAL_NS, clock_domain=DOMAIN
        )
        # A warning + an error firing, no critical → degraded (§7 branch 2).
        assert health.overall.value == "degraded"
        topology = [
            entry
            for entry in health.dimensions
            if entry.dimension.value == "topology"
        ]
        assert topology and topology[0].status.value == "degraded"
        assert set(topology[0].contributing_rule_ids) == {
            "BER_SEVERE",
            "TUNER_UNLOCKED",
        }
