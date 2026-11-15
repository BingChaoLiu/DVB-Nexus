"""ObservationQueryService — the SPEC-300 §12 required query interface
(ticket #53) and the read-side orchestrator behind the eight SPEC-305 §4
endpoints.

Composition (all injected, this package owns no storage):
- ``journal`` — the #47 ``EventJournal`` protocol face (``query``/``max_seq``);
  the durable authority every read serves from (SPEC-300 §7 step 7).
- ``session_exists`` — optional session-existence predicate bound by the
  composition root; an unknown session (no journal rows AND the predicate
  says no) is the 404 family with ``SIM_SESSION_NOT_FOUND`` (the #54
  precedent — journal-retained sessions stay queryable after restart).

Error discipline: every service-plane structured error passes through
:func:`application.observation.query.errors.translate_service_error`, so
the REST router raises frozen application categories whose ``error_code``
keeps the SPEC-300 §13 registry string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from application.errors import (
    BadRequestError,
    NotFoundError,
    REQUEST_BODY_INVALID,
    SemanticValidationError,
)
from application.observation.query.cursor import (
    CursorExpiredError,
    CursorState,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from application.observation.query.errors import (
    OBS_CURSOR_EXPIRED,
    OBS_QUERY_RANGE_TOO_LARGE,
    translate_service_error,
)
from application.observation.query.events import (
    MAX_EVENTS_SCAN_ROWS,
    QUERY_LIMIT_DEFAULT,
    QUERY_LIMIT_HARD_CAP,
    SORT_JOURNAL_DESC,
    SORT_TIME_ASC,
    SORT_TIME_DESC,
    VALID_SORTS,
    EventsPage,
    EventsQueryRequest,
    enforce_single_shape,
    require_clock_domain_for_time_query,
    validate_limit,
)

#: The session-scope 404 code (the simulation plane's registry string,
#: reused per the #54 diagnosis-route precedent — no new code invented).
SIM_SESSION_NOT_FOUND = "SIM_SESSION_NOT_FOUND"

#: The SPEC-305 §8 hint topic for health roll-up changes.
HEALTH_CHANGED_TOPIC = "observation.health_changed"


@dataclass(frozen=True)
class SessionObservationSummary:
    """``get_session_summary`` answer (SPEC-300 §12; fields MVP-scoped to
    what the durable faces expose without new storage reads)."""

    tenant_id: str
    session_id: str
    journal_seq_watermark: int
    event_count: int
    active_alert_count: int = 0
    schema_version: str = "1.0"


@dataclass(frozen=True)
class _AlertsPageView:
    """Alerts page + the service-issued continuation cursor (the store face
    answers offset windows; the cursor wrapper is SPEC-305 §3's opaque
    token discipline)."""

    items: tuple
    total: int
    truncated: bool
    next_cursor: Optional[str]


def _alerts_filter_fingerprint(
    session_id: str,
    rule_id: Optional[str],
    state: Optional[str],
    severity: Optional[str],
    suppressed: Optional[bool],
) -> str:
    import hashlib
    import json

    material = {
        "session_id": session_id,
        "rule_id": rule_id,
        "state": str(getattr(state, "value", state)),
        "severity": str(getattr(severity, "value", severity)),
        "suppressed": suppressed,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class ObservationQueryService:
    """The §12 query face (frozen name) — scope-forced and read-only."""

    def __init__(
        self,
        *,
        journal,
        session_exists: Optional[Callable[[str], bool]] = None,
        tenant_id: str = "local",
        max_scan_rows: int = MAX_EVENTS_SCAN_ROWS,
        metrics=None,
        timeline=None,
        alerts=None,
        reader=None,
        hint_publisher=None,
        exports=None,
    ) -> None:
        self._journal = journal
        self._session_exists = session_exists
        self._tenant_id = tenant_id
        self._max_scan_rows = max_scan_rows
        self._metrics = metrics
        self._timeline = timeline
        self._alerts = alerts
        self._reader = reader
        self._hints = hint_publisher
        self._exports = exports
        self._last_health_overall: dict[tuple[str, str], str] = {}

    # --- SPEC-300 §12 face ------------------------------------------------------

    def get_session_summary(self, session_id: str) -> SessionObservationSummary:
        """The frozen §12 name: one session's observation summary."""
        self.require_session(session_id)
        watermark = self._max_seq(session_id)
        count = self._count_events(session_id)
        return SessionObservationSummary(
            tenant_id=self._tenant_id,
            session_id=session_id,
            journal_seq_watermark=watermark,
            event_count=count,
        )

    # --- events face (SPEC-305 §4 events row) -----------------------------------

    def query_events(
        self, request: Optional[EventsQueryRequest] = None, **kwargs
    ) -> EventsPage:
        """Query the session's committed events (journal-sourced page).

        Accepts either an :class:`EventsQueryRequest` or the flat keyword
        form (the wire-face posture — the api layer passes primitives and
        imports nothing from this package: the C6 transitive closure).
        Request-shape validation (limit/sort/filters/time bounds) runs
        BEFORE the scope gate — the 400/422 contract is journal-state
        independent.
        """
        if request is None:
            request = EventsQueryRequest(**kwargs)
        elif kwargs:  # pragma: no cover — defensive API misuse
            raise TypeError(
                "query_events takes an EventsQueryRequest or keyword "
                "arguments, not both"
            )
        limit = validate_limit(
            request.limit, default=QUERY_LIMIT_DEFAULT, hard_cap=QUERY_LIMIT_HARD_CAP
        )
        _validate_sort(request.sort)
        _validate_filter_values(request)
        require_clock_domain_for_time_query(
            request.clock_domain, request.start_ns, request.end_ns
        )
        start_ns, end_ns = enforce_single_shape(
            request.start_ns, request.end_ns, request.clock_domain
        )
        self.require_session(request.session_id)

        fingerprint = filter_fingerprint(request)
        resume = self._resume_state(request, fingerprint)

        rows = self._scan(
            request,
            start_ns=start_ns,
            end_ns=end_ns,
        )

        if resume is not None and resume.position is not None:
            # Time sorts: position-stable resume over the re-materialized
            # order; the anchor seq must still sit at that position.
            position = resume.position
            if position >= len(rows) or rows[position]["journal_seq"] != resume.anchor_seq:
                raise CursorExpiredError(
                    OBS_CURSOR_EXPIRED,
                    "cursor anchor drifted from the materialized order "
                    "(records moved or were deleted)",
                    details={"position": position},
                )
            window = rows[position:]
        elif resume is not None:
            # Journal sorts: resume strictly after (asc) / before (desc) the
            # anchor seq.
            if request.sort == SORT_JOURNAL_DESC:
                window = [
                    envelope
                    for envelope in rows
                    if envelope["journal_seq"] < resume.anchor_seq
                ]
            else:
                window = [
                    envelope
                    for envelope in rows
                    if envelope["journal_seq"] > resume.anchor_seq
                ]
        else:
            window = rows

        page_items = tuple(window[:limit])
        next_cursor: Optional[str] = None
        truncated = len(window) > limit
        if truncated and page_items:
            next_position = len(rows) - len(window) + len(page_items)
            if request.sort in (SORT_TIME_ASC, SORT_TIME_DESC):
                # The anchor is the seq AT the resume position (the first
                # record of the next window) — drift-checkable.
                next_anchor = rows[next_position]["journal_seq"]
                next_cursor = encode_cursor(
                    CursorState(
                        session_id=request.session_id,
                        filter_hash=fingerprint,
                        sort=request.sort,
                        anchor_seq=next_anchor,
                        position=next_position,
                    )
                )
            else:
                next_cursor = encode_cursor(
                    CursorState(
                        session_id=request.session_id,
                        filter_hash=fingerprint,
                        sort=request.sort,
                        anchor_seq=page_items[-1]["journal_seq"],
                    )
                )
        return EventsPage(
            session_id=request.session_id,
            sort=request.sort,
            clock_domain=request.clock_domain,
            items=page_items,
            next_cursor=next_cursor,
            truncated=truncated,
        )

    def _resume_state(
        self, request: EventsQueryRequest, fingerprint: str
    ) -> Optional[CursorState]:
        """Decode + rebind the cursor (binding mismatch = expired)."""
        if request.cursor is None:
            return None
        state = decode_cursor(request.cursor)
        if state.session_id != request.session_id or state.filter_hash != fingerprint:
            raise CursorExpiredError(
                OBS_CURSOR_EXPIRED,
                "cursor was issued for a different scope or filter binding "
                "(SPEC-305 §5: cursor 绑定过滤器哈希与 scope)",
                details={"reason": "binding mismatch"},
            )
        if state.sort != request.sort:
            raise CursorExpiredError(
                OBS_CURSOR_EXPIRED,
                "cursor sort does not match the request sort",
                details={"reason": "sort mismatch"},
            )
        return state

    # --- timeline / metrics / alerts / health delegation -------------------------

    def query_timeline(self, session_id: str, *, page_size: int = 500, cursor: Optional[str] = None, **filter_kwargs):
        """Delegate to the #51 ``TimelineService`` face (errors translated).

        ``start_ns``/``end_ns``/``clock_domain`` are extracted from the
        filter kwargs: the flat time bounds parse HERE (the §5 shape rules
        — the api layer passes the raw wire values), then the pinned ints
        ride the #51 filter.
        """
        from application.observation.timeline.service import TimelineFilter

        start_raw = filter_kwargs.pop("start_ns", None)
        end_raw = filter_kwargs.pop("end_ns", None)
        clock_domain = filter_kwargs.get("clock_domain")
        start_ns, end_ns = enforce_single_shape(start_raw, end_raw, clock_domain)
        self.require_session(session_id)
        timeline_filter = TimelineFilter(
            session_id=session_id,
            start_ns=start_ns,
            end_ns=end_ns,
            **filter_kwargs,
        )
        try:
            return self._timeline.query(
                timeline_filter, page_size=page_size, cursor=cursor
            )
        except Exception as exc:
            raise translate_service_error(exc) from exc

    def query_metrics(self, session_id: str, *, metric_names, start_ns, end_ns, step_ns, clock_domain, filters=None, max_points=None, aggregation_override=None, allow_unknown=False):
        """Delegate to the #50 ``MetricsService.query`` face."""
        from application.observation.metrics.service import MetricQueryRequest

        self.require_session(session_id)
        request = MetricQueryRequest(
            metric_names=tuple(metric_names),
            start_ns=start_ns,
            end_ns=end_ns,
            step_ns=step_ns,
            clock_domain=clock_domain,
            filters=dict(filters or {}),
            max_points=max_points,
            aggregation_override=aggregation_override,
            allow_unknown=allow_unknown,
        )
        try:
            return self._metrics.query(request)
        except Exception as exc:
            raise translate_service_error(exc) from exc

    def list_alerts(
        self,
        session_id: str,
        *,
        rule_id: Optional[str] = None,
        state: Optional[str] = None,
        severity: Optional[str] = None,
        suppressed: Optional[bool] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ):
        """Delegate to the #52 ``AlertService.list`` face; the store's
        deterministic order + offset windows are exposed as a filter-bound
        opaque cursor (SPEC-305 §3: 告警集合用 cursor 分页)."""
        from application.observation.alerts.store import AlertListRequest
        from application.observation.query.cursor import (
            OffsetCursorState,
            decode_offset_cursor,
            encode_offset_cursor,
        )

        self.require_session(session_id)
        fingerprint = _alerts_filter_fingerprint(
            session_id, rule_id, state, severity, suppressed
        )
        offset = 0
        if cursor is not None:
            decoded = decode_offset_cursor(cursor)
            if decoded.session_id != session_id or decoded.filter_hash != fingerprint:
                raise CursorExpiredError(
                    OBS_CURSOR_EXPIRED,
                    "alerts cursor was issued for a different scope or "
                    "filter binding",
                    details={"reason": "binding mismatch"},
                )
            offset = decoded.offset
        request = AlertListRequest(
            session_id=session_id,
            rule_id=rule_id,
            state=state,
            severity=severity,
            suppressed=suppressed,
            limit=limit,
            offset=offset,
        )
        try:
            page = self._alerts.list(request)
        except Exception as exc:
            raise translate_service_error(exc) from exc
        next_offset = offset + len(page.items)
        next_cursor = None
        if page.truncated and page.items:
            next_cursor = encode_offset_cursor(
                OffsetCursorState(
                    session_id=session_id,
                    filter_hash=fingerprint,
                    offset=next_offset,
                )
            )
        return _AlertsPageView(
            items=page.items,
            total=page.total,
            truncated=page.truncated,
            next_cursor=next_cursor,
        )

    def health(self, session_id: str, *, clock_domain: str, now_ns: int, clock_epoch: int = 0, reader=None):
        """Delegate to the #52 roll-up face; a changed overall status emits
        one ``observation.health_changed`` hint (SPEC-305 §8)."""
        from application.observation.alerts.rollup import roll_up as _roll_up

        self.require_session(session_id)
        effective_reader = reader if reader is not None else self._reader
        result = self._alerts.health(
            session_id,
            reader=effective_reader,
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
        )
        self._emit_health_change(session_id, clock_domain, result)
        return result

    # --- export task face (SPEC-305 §4 export rows) -------------------------------

    def create_export(self, request=None, **kwargs):
        """Create one Observation export task (read-only discipline: never
        a simulation mutation). The registry owns 限流/scope/errors; the
        keyword form is the wire-face posture (C6-safe for the api layer).
        """
        if request is None:
            from application.observation.query.exports import ExportTaskRequest

            request = ExportTaskRequest(**kwargs)
        elif kwargs:  # pragma: no cover — defensive API misuse
            raise TypeError(
                "create_export takes an ExportTaskRequest or keyword "
                "arguments, not both"
            )
        self.require_session(request.session_id)
        return self._exports.create(request)

    def get_export(self, session_id: str, export_id: str):
        """Read one export task (the registry raises the 404/403 rows)."""
        self.require_session(session_id)
        return self._exports.get(session_id, export_id)

    # --- internals ----------------------------------------------------------------

    def require_session(self, session_id: str) -> None:
        """Scope gate: unknown session (no journal rows and the existence
        predicate — when bound — denies) is the 404 family."""
        if self._journal_rows_known(session_id):
            return
        if self._session_exists is not None and self._session_exists(session_id):
            return
        raise NotFoundError(
            SIM_SESSION_NOT_FOUND,
            f"unknown session {session_id!r}: no journal events and no live "
            "session record (SPEC-305 §7 row 404)",
        )

    def _journal_rows_known(self, session_id: str) -> bool:
        try:
            return self._max_seq(session_id) > 0
        except Exception as exc:  # storage failure is the 503 row, not 404
            raise translate_service_error(exc) from exc

    def _emit_health_change(self, session_id: str, clock_domain: str, result) -> None:
        """Emit ``observation.health_changed`` when the overall status moves
        (one hint per transition; best-effort — publisher failures are
        swallowed, SPEC-305 §8)."""
        if self._hints is None or self._alerts is None:
            return
        overall = str(getattr(result.overall, "value", result.overall))
        key = (session_id, clock_domain)
        previous = self._last_health_overall.get(key)
        if previous == overall:
            return
        self._last_health_overall[key] = overall
        try:
            self._hints.publish(
                session_id,
                HEALTH_CHANGED_TOPIC,
                {
                    "session_id": session_id,
                    "clock_domain": clock_domain,
                    "overall": overall,
                    "previous": previous,
                },
            )
        except Exception:
            pass

    def _max_seq(self, session_id: str) -> int:
        return int(self._journal.max_seq(session_id))

    def _count_events(self, session_id: str) -> int:
        """Count rows by scanning in journal-limit batches (the protocol
        read face has no COUNT; MVP sessions are bounded — ADR-0008)."""
        total = 0
        after_seq = 0
        while True:
            rows = self._journal.query(
                session_id, after_seq=after_seq, limit=QUERY_LIMIT_HARD_CAP
            )
            total += len(rows)
            if len(rows) < QUERY_LIMIT_HARD_CAP:
                return total
            after_seq = rows[-1].journal_seq

    def _scan(
        self,
        request: EventsQueryRequest,
        *,
        start_ns: Optional[int],
        end_ns: Optional[int],
    ) -> list[dict]:
        """Scan the session journal into filtered, ordered envelope docs."""
        envelopes: list[dict] = []
        after_seq = 0
        scanned = 0
        while True:
            rows = self._journal.query(
                request.session_id, after_seq=after_seq, limit=QUERY_LIMIT_HARD_CAP
            )
            if not rows:
                break
            for row in rows:
                envelopes.append(row.envelope)
            scanned += len(rows)
            if scanned > self._max_scan_rows:
                raise SemanticValidationError(
                    OBS_QUERY_RANGE_TOO_LARGE,
                    f"events scan exceeded the {self._max_scan_rows}-row "
                    "budget (SPEC-305 §9 范围上限)",
                    details={"scanned": scanned, "cap": self._max_scan_rows},
                )
            after_seq = rows[-1].journal_seq
            if len(rows) < QUERY_LIMIT_HARD_CAP:
                break
        selected = [
            envelope
            for envelope in envelopes
            if _matches_filters(envelope, request, start_ns, end_ns)
        ]
        if request.sort in (SORT_TIME_ASC, SORT_TIME_DESC):
            selected.sort(key=_time_sort_key)
        elif request.sort == SORT_JOURNAL_DESC:
            selected.reverse()
        return selected


def _validate_sort(sort: str) -> None:
    """The four §5 sort values — anything else is the 400 row."""
    if sort not in VALID_SORTS:
        raise BadRequestError(
            REQUEST_BODY_INVALID,
            f"sort must be one of {VALID_SORTS}, got {sort!r}",
            details={"param": "sort", "allowed": list(VALID_SORTS)},
        )


def _validate_filter_values(request: EventsQueryRequest) -> None:
    """Whitelist filters accept flat scalar/list values only (§5 过滤器按
    端点白名单; no expression strings, no object shapes)."""
    for name, value in (
        ("event_types", request.event_types),
        ("severities", request.severities),
        ("producer_ids", request.producer_ids),
    ):
        if not isinstance(value, tuple) or not all(
            isinstance(item, str) for item in value
        ):
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                f"{name} must be a list of strings",
                details={"param": name},
            )


def _time_sort_key(envelope: dict) -> tuple:
    """Single-domain time order key over ``time.source`` (SPEC-303 §4
    posture; the caller pinned the domain, epoch ties broken by seq)."""
    source = envelope["time"]["source"]
    return (source["clock_epoch"], source["value_ns"], envelope["journal_seq"])


def _matches_filters(
    envelope: dict,
    request: EventsQueryRequest,
    start_ns: Optional[int],
    end_ns: Optional[int],
) -> bool:
    """SPEC-305 §5 whitelist filters, applied BEFORE pagination (§3)."""
    source = envelope["time"]["source"]
    if request.clock_domain is not None and source["clock_domain"] != request.clock_domain:
        return False
    if start_ns is not None and source["value_ns"] < start_ns:
        return False
    if end_ns is not None and source["value_ns"] >= end_ns:
        return False
    if request.event_types and envelope["event_type"] not in request.event_types:
        return False
    if request.severities and envelope["severity"] not in request.severities:
        return False
    if (
        request.producer_ids
        and envelope["producer"]["producer_id"] not in request.producer_ids
    ):
        return False
    if request.run_id is not None and envelope["scope"].get("run_id") != request.run_id:
        return False
    return True
