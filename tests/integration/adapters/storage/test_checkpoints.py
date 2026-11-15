"""SqliteCheckpointStore — consumer checkpoint persistence (SPEC-300 §7).

"消费者必须对其最后完整处理的 journal_seq 做检查点；重启恢复从该序号继续"
— the checkpoint is durable state in the SPEC-502 database (migration 002),
keyed per (consumer_id, session_id).

Integration layer: real file-backed SQLite via the ``journal`` fixture.
"""

import sqlite3

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore


@pytest.fixture
def store(journal) -> SqliteCheckpointStore:
    connection = journal.connect()
    return SqliteCheckpointStore(connection)


def test_get_defaults_to_zero_for_unknown_consumer(store) -> None:
    assert store.get("consumer-1", "sess-1") == 0


def test_set_then_get_roundtrip(store) -> None:
    store.set("consumer-1", "sess-1", 41)

    assert store.get("consumer-1", "sess-1") == 41


def test_checkpoints_are_isolated_per_consumer_and_session(store) -> None:
    store.set("consumer-1", "sess-1", 10)
    store.set("consumer-1", "sess-2", 20)
    store.set("consumer-2", "sess-1", 30)

    assert store.get("consumer-1", "sess-1") == 10
    assert store.get("consumer-1", "sess-2") == 20
    assert store.get("consumer-2", "sess-1") == 30


def test_set_is_an_upsert_on_the_latest_seq(store) -> None:
    store.set("consumer-1", "sess-1", 10)
    store.set("consumer-1", "sess-1", 12)

    assert store.get("consumer-1", "sess-1") == 12


def test_checkpoints_survive_a_reconnect(journal) -> None:
    first = SqliteCheckpointStore(journal.connect())
    first.set("consumer-1", "sess-1", 33)

    # "Restart": a brand-new connection/store over the same database file.
    second = SqliteCheckpointStore(journal.connect())

    assert second.get("consumer-1", "sess-1") == 33


def test_migration_002_is_registered_in_the_schema(journal) -> None:
    connection: sqlite3.Connection = journal.connect()

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert version >= 2
    assert "consumer_checkpoints" in tables
