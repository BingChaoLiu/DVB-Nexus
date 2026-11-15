"""``SqliteEventJournal.max_seq`` — the consumer-lag watermark (ticket #50).

Both consumption protocols already declared ``max_seq``
(``application.observation.gateway.EventJournal`` and
``application.observation.consumer.TailableJournal``); ticket #50's
``observation.consumer_lag_events`` metric (SPEC-302 §4: journal watermark
− checkpoint) is the first production consumer, so the additive
implementation gets its own pin: per-session watermark, 0 for unknown
sessions, and advance-after-append.

Unit layer: ``:memory:`` SQLite is the documented journal-slice posture.
"""

import pytest

from adapters.storage import db
from adapters.storage.journal import SqliteEventJournal
from application.observation.consumer import JournalTailingConsumer
from domain.observation import new_event_id


@pytest.fixture
def journal_conn():
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()


def _envelope(session_id: str, event_type: str = "simulation.run_started"):
    return {
        "schema_version": "1.0",
        "event_id": str(new_event_id()),
        "event_type": event_type,
        "producer": {
            "producer_id": "test-producer",
            "producer_version": "0.1.0",
            "instance_id": "inst-1",
        },
        "scope": {"tenant_id": "local", "session_id": session_id},
        "time": {
            "source": {
                "value_ns": 1,
                "clock_domain": f"sim:{session_id}",
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 2,
                "clock_domain": "wall:utc",
                "clock_epoch": 0,
            },
        },
        "severity": "info",
        "payload": {},
        "tags": [],
    }


def _append(journal: SqliteEventJournal, session_id: str) -> int:
    seq, duplicate = journal.append(_envelope(session_id))
    assert duplicate is False
    return seq


def test_max_seq_is_the_per_session_watermark(journal_conn) -> None:
    journal = SqliteEventJournal(journal_conn)
    _append(journal, "s-1")
    _append(journal, "s-1")
    _append(journal, "s-2")

    assert journal.max_seq("s-1") == 2
    assert journal.max_seq("s-2") == 1


def test_max_seq_is_zero_for_an_unknown_session(journal_conn) -> None:
    journal = SqliteEventJournal(journal_conn)
    assert journal.max_seq("never-ingested") == 0


def test_consumer_lag_runs_on_the_production_journal(journal_conn) -> None:
    # The consumer_lag_events data source: lag = watermark − checkpoint
    # (SPEC-300 §8 / SPEC-302 §4) — exercised over the real journal so the
    # declared protocol surface cannot silently rot again.
    journal = SqliteEventJournal(journal_conn)

    class _MemoryCheckpoints:
        def __init__(self) -> None:
            self._values: dict[tuple[str, str], int] = {}

        def get(self, consumer_id: str, session_id: str) -> int:
            return self._values.get((consumer_id, session_id), 0)

        def set(self, consumer_id: str, session_id: str, last_seq: int) -> None:
            self._values[(consumer_id, session_id)] = last_seq

    consumer = JournalTailingConsumer(
        journal=journal,
        checkpoints=_MemoryCheckpoints(),
        session_id="s-1",
        consumer_id="metrics-engine",
        handler=lambda record: None,
    )
    _append(journal, "s-1")
    assert consumer.lag() == 1
    consumer.catch_up()
    assert consumer.lag() == 0
