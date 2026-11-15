"""Alert record persistence (SPEC-304 §5 记录权威, ticket #52) — SQLite
adapter.

The ``alerts`` table (SPEC-502 §4, migration 0001, ticket #23 R8) holds the
11 frozen columns of the repository-authoritative schema
``docs/schemas/alert-record.schema.json``. The store is deliberately tiny —
upsert/get/find/list/count — exactly like its checkpoint sibling
(:mod:`adapters.storage.checkpoints`); all lifecycle semantics live in the
application alerts engine/service, not here (the journal/store family
carries rows, the SPEC-304 §5 state machine carries meaning).

JSON-object columns (``scope``/``time``/``suppression``/``evidence_refs``)
serialize canonically (sorted keys, tight separators) so equal content
always yields equal bytes — the mutation-log determinism posture applied to
row payloads. ``suppression_json`` NULL ⇔ the record is not suppressed
(the modifier rides the row, SPEC-304 §9: suppressed records stay
query-visible).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    AlertSuppression,
    MetricSampleTimepoint,
)

from application.observation.alerts.store import (
    ACTIVE_STATES,
    LIST_LIMIT_HARD_CAP,
    AlertListRequest,
    AlertPage,
)

_UPSERT_SQL = (
    "INSERT INTO alerts ("
    " alert_id, fingerprint, rule_id, rule_version, state, severity,"
    " scope, time, summary, evidence_refs_json, suppression_json)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (alert_id) DO UPDATE SET"
    " fingerprint = excluded.fingerprint,"
    " rule_id = excluded.rule_id,"
    " rule_version = excluded.rule_version,"
    " state = excluded.state,"
    " severity = excluded.severity,"
    " scope = excluded.scope,"
    " time = excluded.time,"
    " summary = excluded.summary,"
    " evidence_refs_json = excluded.evidence_refs_json,"
    " suppression_json = excluded.suppression_json"
)

_SELECT_SQL = (
    "SELECT alert_id, fingerprint, rule_id, rule_version, state, severity,"
    " scope, time, summary, evidence_refs_json, suppression_json"
    " FROM alerts"
)

_ORDER_SQL = " ORDER BY rule_id, fingerprint, alert_id LIMIT ? OFFSET ?"


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _row_to_record(row) -> AlertRecord:
    (
        alert_id,
        fingerprint,
        rule_id,
        rule_version,
        state,
        severity,
        scope_json,
        time_json,
        summary,
        evidence_json,
        suppression_json,
    ) = row
    suppression = None
    if suppression_json is not None:
        suppression = AlertSuppression.model_validate(json.loads(suppression_json))
    return AlertRecord(
        alert_id=alert_id,
        fingerprint=fingerprint,
        rule_id=rule_id,
        rule_version=rule_version,
        state=AlertState(state),
        severity=AlertSeverity(severity),
        scope=AlertScope.model_validate(json.loads(scope_json)),
        time=MetricSampleTimepoint.model_validate(json.loads(time_json)),
        summary=summary,
        evidence_refs=tuple(json.loads(evidence_json)),
        suppression=suppression,
    )


class SqliteAlertStore:
    """SQLite implementation of :class:`AlertStore` (migration 0001).

    Connection discipline follows the journal family: the caller owns the
    autocommit connection (``adapters.storage.db.connect``), each write is
    one statement inside the caller's transaction envelope.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, record: AlertRecord) -> None:
        """Upsert the record (the record is the authority; the last write
        wins deterministically)."""
        suppression = (
            _canonical(record.suppression.model_dump(mode="json"))
            if record.suppression is not None
            else None
        )
        self._conn.execute(
            _UPSERT_SQL,
            (
                record.alert_id,
                record.fingerprint,
                record.rule_id,
                record.rule_version,
                record.state.value,
                record.severity.value,
                _canonical(record.scope.model_dump(mode="json")),
                _canonical(record.time.model_dump(mode="json")),
                record.summary,
                _canonical(list(record.evidence_refs)),
                suppression,
            ),
        )

    def get(self, alert_id: str) -> Optional[AlertRecord]:
        row = self._conn.execute(
            f"{_SELECT_SQL} WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        return None if row is None else _row_to_record(row)

    def find_by_fingerprint(
        self, session_id: str, fingerprint: str, *, active_only: bool = False
    ) -> Optional[AlertRecord]:
        """Dedup lookup scoped by session (SPEC-304 §6 分组守 scope).

        The scope column is canonical JSON TEXT, so the session match rides
        the same quote-delimited LIKE shape the list face uses (the closing
        quote makes ``sess-1`` never match ``sess-11``).
        """
        rows = self._conn.execute(
            f"{_SELECT_SQL} WHERE fingerprint = ? AND scope LIKE ?{_ORDER_SQL}",
            (fingerprint, f'%"session_id":"{session_id}"%', -1, 0),
        ).fetchall()
        for row in rows:
            record = _row_to_record(row)
            if active_only and record.state not in ACTIVE_STATES:
                continue
            return record
        return None

    def list(self, request: AlertListRequest) -> AlertPage:
        clauses: list[str] = []
        params: list[object] = []
        if request.session_id is not None:
            clauses.append("scope LIKE ?")
            params.append(f'%"session_id":"{request.session_id}"%')
        if request.rule_id is not None:
            clauses.append("rule_id = ?")
            params.append(request.rule_id)
        if request.state is not None:
            clauses.append("state = ?")
            params.append(request.state.value)
        if request.severity is not None:
            clauses.append("severity = ?")
            params.append(request.severity.value)
        if request.suppressed is True:
            clauses.append("suppression_json IS NOT NULL")
        elif request.suppressed is False:
            clauses.append("suppression_json IS NULL")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        total_rows = self._conn.execute(
            f"SELECT COUNT(*) FROM alerts{where}", tuple(params)
        ).fetchone()
        total = int(total_rows[0])

        limit = max(0, min(int(request.limit), LIST_LIMIT_HARD_CAP))
        offset = max(0, int(request.offset))
        rows = self._conn.execute(
            f"{_SELECT_SQL}{where}{_ORDER_SQL}", tuple(params) + (limit, offset)
        ).fetchall()
        items = tuple(_row_to_record(row) for row in rows)
        return AlertPage(
            items=items,
            total=total,
            truncated=(offset + len(items)) < total,
        )

    def count_active(self, session_id: str) -> int:
        """Active (pending/firing/resolving) record count for one session —
        the SPEC-302 ``observation.alerts_active`` metric input (Ruling H)."""
        rows = self._conn.execute("SELECT scope, state FROM alerts").fetchall()
        count = 0
        for scope_json, state in rows:
            if json.loads(scope_json).get("session_id") != session_id:
                continue
            if state in {item.value for item in ACTIVE_STATES}:
                count += 1
        return count


__all__ = ["SqliteAlertStore"]
