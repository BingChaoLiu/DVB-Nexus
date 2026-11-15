"""Timeline query service — filters, §4 ordering, lanes, cursor pagination
(SPEC-303 §4/§6, REQ-OBS-303-002/004; SPEC-300 §12 ``TimelineService.query``).

Ordering (SPEC-303 §4): journal-sourced records order by ``journal_seq``;
cross-source records order by ``(clock_domain, timestamp, source_id,
source_seq)``; the page labels its sort descriptor; and a mixed-domain
single time order is NEVER claimed — the caller either pins a clock domain
(single-order page over that domain only) or requests lanes (per
``(clock_domain, clock_epoch)`` partition, each lane labeled). Requests
that do neither are refused with ``OBS_INVALID_TIME_DOMAIN``, and time
ranges REQUIRE a pinned domain + epoch because a range comparison is a
time comparison (bound to
:func:`domain.observation.ensure_same_time_domain`).

Pagination (SPEC-303 §6): opaque cursor tokens bound to the filter hash +
scope (see :mod:`application.observation.timeline.cursor`); page size
default 500, hard cap 2000 (invalid, not clamped — same posture as the
SPEC-502 journal limit); any binding/expiry failure answers
``OBS_CURSOR_EXPIRED``.

Filters (SPEC-303 §6 whitelist): session, scenario, event type, severity,
producer, node, service, PID, fault ID, time range, tags — tag filters are
set membership, never free-text search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from application.observation.timeline.cursor import (
    TimelineCursorState,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from application.observation.timeline.errors import (
    OBS_CURSOR_EXPIRED,
    OBS_QUERY_RANGE_TOO_LARGE,
    TimelineError,
)
from application.observation.timeline.recorder import TimelineRecorder
from domain.observation import (
    DEFAULT_SORT_DESCRIPTOR,
    EnvelopeErrorCode,
    TimelineRecord,
    TimelineTimepoint,
    TimepointSemantics,
    ensure_same_time_domain,
    timeline_record_sort_key,
)

#: SPEC-303 §6: page size default 500, hard cap 2000.
PAGE_SIZE_DEFAULT = 500
PAGE_SIZE_HARD_CAP = 2000


@dataclass(frozen=True)
class TimelineFilter:
    """SPEC-303 §6 filter whitelist (session scope + flat fields).

    ``clock_domain``/``clock_epoch`` pin the single-order time base;
    ``lanes=True`` requests the per-time-base partition instead. ``tags``
    is all-tag membership (无文本 tags 过滤).
    """

    session_id: str
    record_kinds: Tuple[str, ...] = ()
    scenario_id: Optional[str] = None
    event_types: Tuple[str, ...] = ()
    severities: Tuple[str, ...] = ()
    producer_ids: Tuple[str, ...] = ()
    node_id: Optional[str] = None
    service_id: Optional[str] = None
    pid: Optional[int] = None
    fault_id: Optional[str] = None
    tags: Tuple[str, ...] = ()
    clock_domain: Optional[str] = None
    clock_epoch: Optional[int] = None
    start_ns: Optional[int] = None
    end_ns: Optional[int] = None
    lanes: bool = False


@dataclass(frozen=True)
class TimelineServiceConfig:
    """Service bounds. ``max_range_ns`` guards export/query IO peaks
    (SPEC-303 §12: 导出大区间 IO 峰值风险) — None = unbounded (the journal
    remains the range authority in MVP)."""

    max_range_ns: Optional[int] = None


@dataclass(frozen=True)
class TimelineLane:
    """One ``(clock_domain, clock_epoch)`` lane — records of compatible time
    bases only, ordering labeled (SPEC-303 §4: 分道 lanes)."""

    clock_domain: str
    clock_epoch: int
    sort_descriptor: str
    records: Tuple[TimelineRecord, ...]


@dataclass(frozen=True)
class TimelinePage:
    """One query result page (single-order mode fills ``records``; lanes mode
    fills ``lanes`` and leaves ``records`` empty)."""

    session_id: str
    sort_descriptor: str
    records: Tuple[TimelineRecord, ...]
    next_cursor: Optional[str]
    truncated: bool
    lanes: Tuple[TimelineLane, ...] = ()
    schema_version: str = "1.0"


class TimelineService:
    """SPEC-300 §12 required timeline query face over a recorder store."""

    def __init__(
        self,
        recorder: TimelineRecorder,
        config: TimelineServiceConfig | None = None,
    ) -> None:
        self._recorder = recorder
        self._config = config or TimelineServiceConfig()

    def query(
        self,
        filter_obj: TimelineFilter,
        *,
        page_size: int = PAGE_SIZE_DEFAULT,
        cursor: Optional[str] = None,
    ) -> TimelinePage:
        """Query the timeline (SPEC-303 §6).

        Raises :class:`TimelineError` with ``OBS_CURSOR_EXPIRED`` for any
        cursor binding/expiry failure, ``OBS_INVALID_TIME_DOMAIN`` (shared
        domain vocabulary) for mixed-domain single-order refusals and
        range-shape violations, ``OBS_QUERY_RANGE_TOO_LARGE`` for over-limit
        ranges, and plain ``ValueError`` for invalid page sizes / inverted
        ranges (request-shape errors the API layer maps to 400).
        """
        _validate_page_size(page_size)
        self._validate_time_base_request(filter_obj)

        ordered = self._filtered_and_ordered(filter_obj)

        if filter_obj.lanes:
            return self._laned_page(filter_obj, ordered)

        if cursor is not None:
            start = self._resume_position(filter_obj, cursor, ordered)
        else:
            start = 0
        page_records = tuple(ordered[start : start + page_size])
        end = start + len(page_records)
        next_cursor = None
        if end < len(ordered):
            next_cursor = encode_cursor(
                TimelineCursorState(
                    session_id=filter_obj.session_id,
                    filter_hash=filter_fingerprint(filter_obj),
                    position=end,
                    anchor_record_id=ordered[end].record_id,
                )
            )
        return TimelinePage(
            session_id=filter_obj.session_id,
            sort_descriptor=DEFAULT_SORT_DESCRIPTOR,
            records=page_records,
            next_cursor=next_cursor,
            truncated=next_cursor is not None,
        )

    # --- internals -------------------------------------------------------------

    def _filtered_and_ordered(
        self, filter_obj: TimelineFilter
    ) -> list[TimelineRecord]:
        candidates = [
            record
            for record in self._recorder.records(filter_obj.session_id)
            if _matches_filter(record, filter_obj)
        ]
        candidates = self._apply_time_range(filter_obj, candidates)
        candidates.sort(key=timeline_record_sort_key)
        return candidates

    def _validate_time_base_request(self, filter_obj: TimelineFilter) -> None:
        has_range = filter_obj.start_ns is not None or filter_obj.end_ns is not None
        if has_range and filter_obj.lanes:
            raise _time_domain_error(
                "a time range needs one pinned time base; lanes span "
                "multiple (SPEC-303 §4)"
            )
        if not filter_obj.lanes and filter_obj.clock_domain is None:
            raise _time_domain_error(
                "timeline query must pin clock_domain or request lanes=true "
                "— a mixed-domain single time order is never claimed "
                "(SPEC-303 §4)"
            )
        if has_range:
            start = filter_obj.start_ns
            end = filter_obj.end_ns
            if start is not None and end is not None and start >= end:
                raise ValueError("start_ns must be < end_ns (SPEC-305 §5 posture)")
            if filter_obj.clock_epoch is None:
                raise _time_domain_error(
                    "a time range requires a pinned clock_epoch: values "
                    "across epochs of one domain are different time bases "
                    "(SPEC-300 §6 rule 5)"
                )
            if (
                self._config.max_range_ns is not None
                and start is not None
                and end is not None
                and end - start > self._config.max_range_ns
            ):
                raise TimelineError(
                    OBS_QUERY_RANGE_TOO_LARGE,
                    f"time range {end - start} ns exceeds the configured "
                    f"maximum {self._config.max_range_ns} ns",
                    details={"max_range_ns": self._config.max_range_ns},
                )

    def _apply_time_range(
        self, filter_obj: TimelineFilter, records: list[TimelineRecord]
    ) -> list[TimelineRecord]:
        if filter_obj.start_ns is None and filter_obj.end_ns is None:
            return records
        epoch = filter_obj.clock_epoch
        assert filter_obj.clock_domain is not None and epoch is not None
        # Range bounds are derived timepoints of the pinned time base.
        lower = TimelineTimepoint(
            value_ns=filter_obj.start_ns if filter_obj.start_ns is not None else 0,
            clock_domain=filter_obj.clock_domain,
            clock_epoch=epoch,
            semantics=TimepointSemantics.DERIVED,
        )
        upper = TimelineTimepoint(
            value_ns=filter_obj.end_ns if filter_obj.end_ns is not None else 0,
            clock_domain=filter_obj.clock_domain,
            clock_epoch=epoch,
            semantics=TimepointSemantics.DERIVED,
        )
        kept: list[TimelineRecord] = []
        for record in records:
            timepoint = record.timepoint
            # Binding discipline (brief §1.5): every time comparison goes
            # through the cross-domain guard — a mismatch here is an
            # invariant breach, not a filter miss (epoch mismatch is already
            # excluded by the filter).
            ensure_same_time_domain(timepoint, lower, upper)
            if filter_obj.start_ns is not None and timepoint.value_ns < lower.value_ns:
                continue
            if filter_obj.end_ns is not None and timepoint.value_ns > upper.value_ns:
                continue
            kept.append(record)
        return kept

    def _laned_page(
        self, filter_obj: TimelineFilter, ordered: list[TimelineRecord]
    ) -> TimelinePage:
        grouped: dict[tuple[str, int], list[TimelineRecord]] = {}
        for record in ordered:
            grouped.setdefault(
                (record.timepoint.clock_domain, record.timepoint.clock_epoch), []
            ).append(record)
        lanes = tuple(
            TimelineLane(
                clock_domain=domain,
                clock_epoch=epoch,
                sort_descriptor=DEFAULT_SORT_DESCRIPTOR,
                records=tuple(grouped[(domain, epoch)]),
            )
            for domain, epoch in sorted(grouped)
        )
        return TimelinePage(
            session_id=filter_obj.session_id,
            sort_descriptor=DEFAULT_SORT_DESCRIPTOR,
            records=(),
            next_cursor=None,
            truncated=False,
            lanes=lanes,
        )

    def _resume_position(
        self,
        filter_obj: TimelineFilter,
        cursor_token: str,
        ordered: list[TimelineRecord],
    ) -> int:
        state = decode_cursor(cursor_token)
        expected_hash = filter_fingerprint(filter_obj)
        expired = TimelineError(
            OBS_CURSOR_EXPIRED,
            "cursor does not match this query's scope or filter, or its "
            "anchor record no longer sits at the recorded position "
            "(SPEC-303 §6/§10)",
            details={"reason": "binding_mismatch"},
        )
        if state.session_id != filter_obj.session_id:
            raise expired
        if state.filter_hash != expected_hash:
            raise expired
        if state.position < 0 or state.position > len(ordered):
            raise expired
        if ordered[state.position].record_id != state.anchor_record_id:
            raise expired
        return state.position


def _matches_filter(record: TimelineRecord, filter_obj: TimelineFilter) -> bool:
    if filter_obj.record_kinds and record.record_kind.value not in filter_obj.record_kinds:
        return False
    if filter_obj.scenario_id is not None and record.scenario_id != filter_obj.scenario_id:
        return False
    if filter_obj.event_types and record.event_type not in filter_obj.event_types:
        return False
    if filter_obj.severities:
        severity_value = record.severity.value if record.severity else None
        if severity_value not in filter_obj.severities:
            return False
    if filter_obj.producer_ids and record.producer_id not in filter_obj.producer_ids:
        return False
    if filter_obj.node_id is not None and record.node_id != filter_obj.node_id:
        return False
    if filter_obj.service_id is not None and record.service_id != filter_obj.service_id:
        return False
    if filter_obj.pid is not None and record.pid != filter_obj.pid:
        return False
    if filter_obj.fault_id is not None and record.fault_id != filter_obj.fault_id:
        return False
    if filter_obj.tags and not set(filter_obj.tags).issubset(set(record.tags)):
        return False
    if (
        filter_obj.clock_domain is not None
        and record.timepoint.clock_domain != filter_obj.clock_domain
    ):
        return False
    if (
        filter_obj.clock_epoch is not None
        and record.timepoint.clock_epoch != filter_obj.clock_epoch
    ):
        return False
    return True


def _validate_page_size(page_size: int) -> None:
    if (
        not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= PAGE_SIZE_HARD_CAP
    ):
        raise ValueError(
            f"page_size must be an int within 1..{PAGE_SIZE_HARD_CAP}, "
            f"got {page_size!r} (SPEC-303 §6: default {PAGE_SIZE_DEFAULT}, "
            "hard cap not clamped)"
        )


def _time_domain_error(message: str) -> TimelineError:
    return TimelineError(
        EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN.value,
        message,
        details={"canonical_code": EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN.value},
    )


__all__ = [
    "PAGE_SIZE_DEFAULT",
    "PAGE_SIZE_HARD_CAP",
    "TimelineFilter",
    "TimelineLane",
    "TimelinePage",
    "TimelineService",
    "TimelineServiceConfig",
]
