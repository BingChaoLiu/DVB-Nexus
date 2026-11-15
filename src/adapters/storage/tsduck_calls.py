"""``SqliteTSDuckCallStore`` — SPEC-308 §7 nine-field call-record storage
(ticket #80, REQ-API-500-008, migration ``0004_tsduck_calls.sql``).

Write face (:meth:`SqliteTSDuckCallStore.record`): one row per invocation.
There is deliberately no update/delete path — call records are append-only
facts. The production stack makes no real TSDuck calls (MVP, 裁定 E item
3); today the write face is exercised by contract-test fixture seeding and
is the seam future emission wiring binds.

Read face (:meth:`SqliteTSDuckCallStore.query`): the ``GET
/sessions/{id}/tsduck/calls`` projection — session-scoped, ordered by
``started_at_utc_ms`` ASC, optional ``run_id`` filter.

Field discipline (SPEC-308 §7): the nine mandatory fields + the optional
``run_id``; failure-path fields carry explicit ``None`` — never fabricated
values (the adapter's ``TSDuckCallRecord`` rule; the store mirrors it).
Timestamps are epoch-ms INTEGER (R8) — the adapter's epoch-second floats
convert at the caller's write seam. ``argv`` is JSON TEXT.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

__all__ = ["TSDuckCallRecord", "SqliteTSDuckCallStore"]


@dataclass(frozen=True)
class TSDuckCallRecord:
    """One stored ``tsduck_calls`` row (SPEC-308 §7 nine fields + run_id)."""

    record_id: str
    session_id: str
    run_id: Optional[str]
    version: Optional[str]
    executable_path: Optional[str]
    argv: tuple[str, ...]
    started_at_utc_ms: int
    finished_at_utc_ms: int
    exit_code: Optional[int]
    stdout_text: Optional[str]
    stderr_text: Optional[str]
    input_artifact_sha256: Optional[str]


class SqliteTSDuckCallStore:
    """SQLite storage for TSDuck invocation records (append-only)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, entry: TSDuckCallRecord) -> None:
        argv_json = json.dumps(list(entry.argv), ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO tsduck_calls (record_id, session_id, run_id, version,"
            " executable_path, argv_json, started_at_utc_ms, finished_at_utc_ms,"
            " exit_code, stdout_text, stderr_text, input_artifact_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.record_id,
                entry.session_id,
                entry.run_id,
                entry.version,
                entry.executable_path,
                argv_json,
                entry.started_at_utc_ms,
                entry.finished_at_utc_ms,
                entry.exit_code,
                entry.stdout_text,
                entry.stderr_text,
                entry.input_artifact_sha256,
            ),
        )

    def query(
        self, session_id: str, *, run_id: Optional[str] = None
    ) -> list[TSDuckCallRecord]:
        if run_id is None:
            rows = self._conn.execute(
                "SELECT * FROM tsduck_calls WHERE session_id = ?"
                " ORDER BY started_at_utc_ms ASC, record_id ASC",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tsduck_calls WHERE session_id = ? AND run_id = ?"
                " ORDER BY started_at_utc_ms ASC, record_id ASC",
                (session_id, run_id),
            ).fetchall()
        return [_call_record(row) for row in rows]


def _call_record(row: sqlite3.Row) -> TSDuckCallRecord:
    return TSDuckCallRecord(
        record_id=row["record_id"],
        session_id=row["session_id"],
        run_id=row["run_id"],
        version=row["version"],
        executable_path=row["executable_path"],
        argv=tuple(json.loads(row["argv_json"])),
        started_at_utc_ms=row["started_at_utc_ms"],
        finished_at_utc_ms=row["finished_at_utc_ms"],
        exit_code=row["exit_code"],
        stdout_text=row["stdout_text"],
        stderr_text=row["stderr_text"],
        input_artifact_sha256=row["input_artifact_sha256"],
    )
