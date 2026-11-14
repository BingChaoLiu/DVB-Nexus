"""Event journal — the unique journal_seq stamp point (SPEC-502 sections 5-6).

``journal_seq`` is the platform's single total order (ADR-0006 decision 2,
SPEC-301 §5, CONTEXT.md「流水号」): it does not come from producers — it is
stamped HERE, inside the append transaction, as ``max(seq) + 1`` per session.
Delivery is at-least-once, so the ``(producer_id, event_id)`` pair is the
idempotency key: a replayed append returns the ORIGINAL seq with
``duplicate=True`` and creates no new row (SPEC-301 §5, REQ-PLT-502-003).

No batching/coalescing exists in this layer: every append is a direct
committed write, so the no-drop event classes (``fault.*`` / ``session_*`` /
terminal run / ``recovery.verification_completed``, SPEC-502 §6) are
trivially never silently dropped (REQ-PLT-502-004). Flush windows are an
application-layer queue concern (SPEC-502 §8, OPEN-006 / ticket #16).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from adapters.storage.errors import (
    InvalidEnvelopeError,
    StorageConflictError,
    StorageWriteFailure,
)

#: SPEC-502 §8 via SPEC-305 §5: query limit default 100, hard cap 2000.
QUERY_LIMIT_DEFAULT = 100
QUERY_LIMIT_HARD_CAP = 2000

_INSERT_SQL = (
    "INSERT INTO events"
    " (session_id, journal_seq, event_type, severity, producer_id, event_id, envelope_json)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True)
class EventRow:
    """One stored journal row (SPEC-502 §5 ``EventRow``)."""

    session_id: str
    journal_seq: int
    event_type: str
    severity: str
    producer_id: str
    event_id: str
    #: Parsed authoritative envelope (contains the stamped journal_seq).
    envelope: dict


class EventJournal(Protocol):
    """SPEC-502 §5 journal protocol."""

    def append(self, envelope: dict) -> tuple[int, bool]:
        """Stamp and store one envelope; returns ``(journal_seq, duplicate)``.

        The unique stamp entry point: the seq is allocated and the row
        inserted inside one transaction (``BEGIN IMMEDIATE``), so concurrent
        appenders on the same session see no holes and no duplicates.
        """
        ...

    def query(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> list[EventRow]:
        """Rows of one session in journal_seq order, seq > after_seq."""
        ...


class SqliteEventJournal(EventJournal):
    """SQLite implementation of :class:`EventJournal`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, envelope: dict) -> tuple[int, bool]:
        columns = _extract_columns(envelope)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise StorageWriteFailure("cannot begin the journal append transaction") from exc
        try:
            seq = self._next_seq(columns.session_id)
            stamped_json = _serialize_stamped(envelope, seq)
            try:
                self._conn.execute(
                    _INSERT_SQL,
                    (
                        columns.session_id,
                        seq,
                        columns.event_type,
                        columns.severity,
                        columns.producer_id,
                        columns.event_id,
                        stamped_json,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Constraint-first dedup (SPEC-502 §7: no app-layer
                # check-then-insert): the (producer_id, event_id) partial
                # unique index fired; resolve the original seq in this same
                # transaction. Any other conflict is the 409 path.
                original = self._original_seq(columns.producer_id, columns.event_id)
                self._rollback()
                if original is not None:
                    return (original, True)
                raise StorageConflictError(
                    f"event violates a uniqueness constraint"
                    f" (session {columns.session_id}, candidate seq {seq})"
                ) from exc
            self._conn.execute("COMMIT")
            return (seq, False)
        except sqlite3.OperationalError as exc:
            self._rollback()
            raise StorageWriteFailure(
                f"journal append failed (code {StorageWriteFailure.code})"
            ) from exc
        except InvalidEnvelopeError:
            self._rollback()
            raise
        except sqlite3.Error:
            self._rollback()
            raise

    def query(
        self, session_id: str, *, after_seq: int = 0, limit: int = QUERY_LIMIT_DEFAULT
    ) -> list[EventRow]:
        # SPEC-502 §8 via SPEC-305 §5: limit defaults to 100, hard cap 2000 —
        # requests beyond the cap are invalid, not silently clamped.
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= QUERY_LIMIT_HARD_CAP:
            raise ValueError(f"limit must be an int within 1..{QUERY_LIMIT_HARD_CAP}, got {limit!r}")
        rows = self._conn.execute(
            "SELECT session_id, journal_seq, event_type, severity, producer_id, event_id,"
            " envelope_json FROM events WHERE session_id = ? AND journal_seq > ?"
            " ORDER BY journal_seq ASC LIMIT ?",
            (session_id, after_seq, limit),
        ).fetchall()
        return [
            EventRow(
                session_id=row["session_id"],
                journal_seq=row["journal_seq"],
                event_type=row["event_type"],
                severity=row["severity"],
                producer_id=row["producer_id"],
                event_id=row["event_id"],
                envelope=json.loads(row["envelope_json"]),
            )
            for row in rows
        ]

    def _next_seq(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(journal_seq) FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()
        return (row[0] or 0) + 1

    def _original_seq(self, producer_id: str, event_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT journal_seq FROM events WHERE producer_id = ? AND event_id = ?",
            (producer_id, event_id),
        ).fetchone()
        return None if row is None else int(row[0])

    def _rollback(self) -> None:
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:  # pragma: no cover - rollback of a finished tx
            pass


class _EnvelopeColumns:
    __slots__ = ("session_id", "event_type", "severity", "producer_id", "event_id")

    def __init__(self, session_id: str, event_type: str, severity: str, producer_id: str, event_id: str) -> None:
        self.session_id = session_id
        self.event_type = event_type
        self.severity = severity
        self.producer_id = producer_id
        self.event_id = event_id


def _extract_columns(envelope: Any) -> _EnvelopeColumns:
    """Validate the fields the journal columns materialize (SPEC-301 §9:
    malformed events are rejected before journal commit)."""
    if not isinstance(envelope, dict):
        raise InvalidEnvelopeError("envelope must be a JSON object")
    event_id = _non_empty_str(envelope, "event_id")
    event_type = _non_empty_str(envelope, "event_type")
    severity = _non_empty_str(envelope, "severity")
    producer = envelope.get("producer")
    if not isinstance(producer, dict):
        raise InvalidEnvelopeError("envelope field producer must be an object")
    producer_id = _non_empty_str(producer, "producer_id")
    scope = envelope.get("scope")
    if not isinstance(scope, dict):
        raise InvalidEnvelopeError("envelope field scope must be an object")
    # R4 (implementation plan §7): the stamp key is a session and the events
    # PK is (session_id, journal_seq); SPEC-301 §3's null session_id
    # (system-level events) has no MVP registry entry, so it is rejected here.
    session_id = _non_empty_str(scope, "session_id")
    return _EnvelopeColumns(session_id, event_type, severity, producer_id, event_id)


def _non_empty_str(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidEnvelopeError(f"envelope field {key} must be a non-empty string")
    return value


def _serialize_stamped(envelope: dict, seq: int) -> str:
    """Return the canonical authoritative JSON with the stamp applied.

    The caller's dict is never mutated (the stamped copy is stored); a
    producer-supplied journal_seq is overwritten (R12).
    """
    stamped = dict(envelope)
    stamped["journal_seq"] = seq
    try:
        return json.dumps(stamped, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidEnvelopeError("envelope is not JSON-representable") from exc


__all__ = [
    "QUERY_LIMIT_DEFAULT",
    "QUERY_LIMIT_HARD_CAP",
    "EventJournal",
    "EventRow",
    "SqliteEventJournal",
]
