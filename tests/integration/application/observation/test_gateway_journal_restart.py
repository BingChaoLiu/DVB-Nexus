"""Gateway + journal + consumer over the real SQLite store — the SPEC-300
§7 data flow end to end, including restart recovery (ticket #47 acceptance).

Integration layer: real file-backed SQLite (WAL) via the ``journal``
fixture; the gateway drain runs on a dedicated dispatcher thread over a
``check_same_thread=False`` connection (the documented single-writer
posture, SPEC-300 §8) — producers never touch storage I/O.
"""

import threading

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from application.observation.gateway import EventGateway, IngestOutcome
from tests.unit.application.observation.test_gateway_accept import _raw_envelope


@pytest.fixture
def db_path(journal):
    """The ``journal`` fixture's migrated file database path."""
    return journal.db_path


def _journal_on(db_path) -> SqliteEventJournal:
    """Journal over a fresh connection; dispatcher-thread safe (single writer)."""
    return SqliteEventJournal(connect(db_path, check_same_thread=False))


def _drain_in_thread(gateway: EventGateway, stop: threading.Event) -> threading.Thread:
    """Minimal dispatcher loop: the composition-root posture of SPEC-300 §8.

    The loop yields between drain slices so the test observes progress
    event-driven (bounded polling, no wall-clock waits on real work).
    """

    def _loop() -> None:
        while not stop.is_set():
            gateway.drain(limit=10)
            stop.wait(timeout=0.01)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread


# --- accept → queue → dispatcher thread → stamped journal rows ----------------


def test_gateway_stamps_through_real_journal_on_the_dispatcher_thread(
    db_path,
) -> None:
    gateway = EventGateway(journal=_journal_on(db_path))
    stop = threading.Event()
    thread = _drain_in_thread(gateway, stop)
    try:
        for index in range(5):
            result = gateway.accept(_raw_envelope(event_id=f"e2e-{index:07d}"))
            assert result.outcome is IngestOutcome.ACCEPTED, (
                result.error_code,
                gateway.failures(),
            )
        # Deterministic quiescence: wait until the queue is empty (bounded
        # event-driven polling).
        while gateway.metrics().queue_depth > 0:
            stop.wait(timeout=0.01)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not gateway.failures()

    journal = _journal_on(db_path)
    rows = journal.query("sess-1")
    assert [row.journal_seq for row in rows] == [1, 2, 3, 4, 5]
    assert [row.envelope["journal_seq"] for row in rows] == [1, 2, 3, 4, 5]


# --- restart: stamp continuity + consumer resume + dedup across restart -------


def test_restart_continues_stamp_and_consumer_resume(db_path) -> None:
    # First "process": ingest two events and commit them synchronously.
    first_gateway = EventGateway(journal=_journal_on(db_path))
    store = SqliteCheckpointStore(connect(db_path))
    seen: list[int] = []
    consumer = JournalTailingConsumer(
        journal=_journal_on(db_path),
        checkpoints=store,
        session_id="sess-1",
        consumer_id="metrics-engine",
        handler=lambda record: seen.append(record.journal_seq),
        config=ConsumerConfig(batch_size=2),
    )
    for index in range(2):
        assert first_gateway.accept(
            _raw_envelope(event_id=f"restart-{index:07d}")
        ).outcome is IngestOutcome.ACCEPTED
    first_gateway.drain()
    assert consumer.catch_up() == 2
    assert consumer.checkpoint_seq() == 2

    # RESTART: brand-new gateway + journal + consumer over the same database.
    restarted_gateway = EventGateway(journal=_journal_on(db_path))
    restarted_consumer = JournalTailingConsumer(
        journal=_journal_on(db_path),
        checkpoints=SqliteCheckpointStore(connect(db_path)),
        session_id="sess-1",
        consumer_id="metrics-engine",
        handler=lambda record: seen.append(record.journal_seq),
        config=ConsumerConfig(batch_size=2),
    )

    # The stamp continues from the durable max(journal_seq) — no reset to 1.
    assert restarted_gateway.accept(
        _raw_envelope(event_id="restart-0000002")
    ).outcome is IngestOutcome.ACCEPTED
    restarted_gateway.drain()

    # The restarted consumer resumes exactly after the durable checkpoint.
    assert restarted_consumer.catch_up() == 1
    assert seen == [1, 2, 3]
    assert restarted_consumer.checkpoint_seq() == 3

    # At-least-once replay ACROSS the restart: the journal's unique index is
    # the authority — no second row is created.
    replay = restarted_gateway.accept(_raw_envelope(event_id="restart-0000000"))
    assert replay.outcome is IngestOutcome.ACCEPTED  # cache is fresh after restart
    restarted_gateway.drain()
    journal = _journal_on(db_path)
    rows = journal.query("sess-1")
    assert len(rows) == 3
    assert restarted_consumer.catch_up() == 0  # deduped at the journal: no new row
