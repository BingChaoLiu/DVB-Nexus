"""Consumer checkpoint persistence (SPEC-300 §7) — SQLite adapter.

The journal is the platform's only SQLite writer family (SPEC-502); consumer
checkpoints live next to the journal they tail (migration 0002). The store is
deliberately tiny: get/set on ``(consumer_id, session_id)`` with an upsert —
all cursor semantics (batch-only checkpointing, redelivery tolerance) live in
the application-layer tailing consumer, not here.

Thread posture: checkpoint writes happen on the consumer's own thread with
the same connection discipline as the journal (explicit transactions via the
caller's autocommit connection).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Protocol

#: R6 (ticket #23 register): *_utc columns are ISO-8601 TEXT.
_UPDATED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

_UPSERT_SQL = (
    "INSERT INTO consumer_checkpoints"
    " (consumer_id, session_id, last_seq, updated_at_utc)"
    " VALUES (?, ?, ?, ?)"
    " ON CONFLICT (consumer_id, session_id)"
    " DO UPDATE SET last_seq = excluded.last_seq,"
    " updated_at_utc = excluded.updated_at_utc"
)


class CheckpointStore(Protocol):
    """SPEC-300 §7 checkpoint protocol (application consumers depend on this)."""

    def get(self, consumer_id: str, session_id: str) -> int: ...

    def set(self, consumer_id: str, session_id: str, last_seq: int) -> None: ...


class SqliteCheckpointStore(CheckpointStore):
    """SQLite implementation of :class:`CheckpointStore` (migration 0002)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, consumer_id: str, session_id: str) -> int:
        """Last durably checkpointed seq; 0 when the consumer never ran."""
        row = self._conn.execute(
            "SELECT last_seq FROM consumer_checkpoints"
            " WHERE consumer_id = ? AND session_id = ?",
            (consumer_id, session_id),
        ).fetchone()
        return 0 if row is None else int(row[0])

    def set(self, consumer_id: str, session_id: str, last_seq: int) -> None:
        """Upsert the last FULLY processed journal_seq (never a partial batch)."""
        updated_at = datetime.now(timezone.utc).strftime(_UPDATED_AT_FORMAT)
        self._conn.execute(_UPSERT_SQL, (consumer_id, session_id, int(last_seq), updated_at))


__all__ = ["CheckpointStore", "SqliteCheckpointStore"]
