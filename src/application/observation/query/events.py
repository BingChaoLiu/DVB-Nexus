"""Events journal query face — SPEC-305 §4 events row on the §5 flat
baseline (ticket #53).

The journal is the only read authority (SPEC-502 §8 ``query(after_seq,
limit)`` / ``max_seq``); this face scans it through the #47 ``EventJournal``
protocol, applies the §5 server-side filters BEFORE pagination (§3 服务端
过滤先于分页), orders by one of the four §5 sort values and pages with an
opaque cursor. Time sorts are single-domain by construction (SPEC-300 §6
rule 1/3: a mixed-domain time order is never claimed) — the request must
pin ``clock_domain`` and only events whose ``time.source`` lives in that
domain participate.

Flat-scalar baseline (SPEC-305 §5, 缝合批准 #12): ``start_ns``/``end_ns``
are integer nanoseconds; the ``wall:utc`` domain accepts ISO-8601 strings
in their place; the two shapes are NEVER mixed in one request (a mixed or
domain-misplaced shape is the OBS_INVALID_TIME_DOMAIN semantic row, the
#51 timeline precedent); a value that parses as neither is the 400
request-shape row. Timepoint OBJECT shapes are record/response bodies and
are refused as query parameters (SPEC-302 §8 同源裁决).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Union

from adapters.storage.journal import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HARD_CAP
from application.errors import (
    BadRequestError,
    REQUEST_BODY_INVALID,
    SemanticValidationError,
)
from application.observation.query.errors import OBS_INVALID_TIME_DOMAIN

#: The four SPEC-305 §5 sort values.
SORT_JOURNAL_ASC = "journal_asc"
SORT_JOURNAL_DESC = "journal_desc"
SORT_TIME_ASC = "time_asc"
SORT_TIME_DESC = "time_desc"
VALID_SORTS = (SORT_JOURNAL_ASC, SORT_JOURNAL_DESC, SORT_TIME_ASC, SORT_TIME_DESC)

WALL_CLOCK_DOMAIN = "wall:utc"

#: Bounded-scan budget for position-paginated sorts and deep filter scans
#: (§9 请求范围上限默认保守). The seq-cursor sorts never scan beyond their
#: page; time sorts and filtered journal walks stop at this row budget and
#: refuse with ``OBS_QUERY_RANGE_TOO_LARGE`` (REQ-OBS-305-004 范围限制).
MAX_EVENTS_SCAN_ROWS = 20_000


@dataclass(frozen=True)
class EventsQueryRequest:
    """One events query on the SPEC-305 §5 flat baseline (whitelist filters).

    ``start_ns``/``end_ns`` carry integer nanoseconds; ISO-8601 strings are
    legal ONLY for the ``wall:utc`` domain (§5: 同一请求绝不混用两种形状).
    """

    session_id: str
    limit: int = QUERY_LIMIT_DEFAULT
    cursor: Optional[str] = None
    sort: str = SORT_JOURNAL_ASC
    event_types: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    producer_ids: tuple[str, ...] = ()
    run_id: Optional[str] = None
    clock_domain: Optional[str] = None
    clock_epoch: Optional[int] = None
    start_ns: Optional[Union[int, str]] = None
    end_ns: Optional[Union[int, str]] = None


@dataclass(frozen=True)
class EventsPage:
    """One events page (SPEC-305 §6 data body for the events endpoint)."""

    session_id: str
    sort: str
    clock_domain: Optional[str]
    items: tuple[dict, ...] = field(default_factory=tuple)
    next_cursor: Optional[str] = None
    truncated: bool = False
    schema_version: str = "1.0"


def validate_limit(limit: int, *, default: int, hard_cap: int) -> int:
    """SPEC-305 §5: limit defaults to 100, hard cap 2000 — out-of-range
    values are INVALID, not clamped (the journal's own query posture)."""
    if limit is None:
        return default
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= hard_cap:
        raise BadRequestError(
            REQUEST_BODY_INVALID,
            f"limit must be an int within 1..{hard_cap}, got {limit!r}",
            details={"param": "limit", "hard_cap": hard_cap},
        )
    return limit


def parse_time_bound(
    name: str,
    value: Optional[Union[int, str]],
    clock_domain: Optional[str],
) -> Optional[int]:
    """Parse one flat time bound per the SPEC-305 §5 baseline.

    Integer nanoseconds parse directly; ISO-8601 strings parse ONLY in the
    ``wall:utc`` domain (UTC-anchored, ``Z``/offset aware). Violations:

    - a value that parses as neither shape is the 400 request-shape row
      (``REQUEST_BODY_INVALID``);
    - an ISO string under a declared non-wall domain is the 422 semantic
      row ``OBS_INVALID_TIME_DOMAIN`` (the domain was declared; the
      parameter shape contradicts it — SPEC-305 §5 禁混用).
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise BadRequestError(
            REQUEST_BODY_INVALID,
            f"{name} must be integer nanoseconds or an ISO-8601 string "
            "(wall:utc domain only)",
            details={"param": name},
        )
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    iso_bound = _parse_iso8601_ns(text)
    if iso_bound is None:
        raise BadRequestError(
            REQUEST_BODY_INVALID,
            f"{name} is neither integer nanoseconds nor a valid ISO-8601 instant",
            details={"param": name, "value_shape": "string"},
        )
    if clock_domain != WALL_CLOCK_DOMAIN:
        raise SemanticValidationError(
            OBS_INVALID_TIME_DOMAIN,
            f"{name} ISO-8601 strings are legal only for the wall:utc domain "
            f"(SPEC-305 §5); request declares clock_domain={clock_domain!r}",
            details={"param": name, "clock_domain": clock_domain},
        )
    return iso_bound


def require_clock_domain_for_time_query(
    clock_domain: Optional[str],
    start_ns: Optional[Union[int, str]],
    end_ns: Optional[Union[int, str]],
) -> Optional[str]:
    """SPEC-305 §5: ``clock_domain`` is REQUIRED for sim-time queries.

    A time-bounded query without a declared domain is a clock-domain
    semantic failure (SPEC-305 §10 第一条) — the 422 row, OBS_INVALID_TIME_DOMAIN
    (the request claims time semantics but names no time base).
    """
    if (start_ns is not None or end_ns is not None) and not clock_domain:
        raise SemanticValidationError(
            OBS_INVALID_TIME_DOMAIN,
            "a time-bounded query must declare clock_domain "
            "(SPEC-305 §5: 仿真时间查询必填)",
            details={"param": "clock_domain"},
        )
    return clock_domain


def enforce_single_shape(
    start_ns: Optional[Union[int, str]],
    end_ns: Optional[Union[int, str]],
    clock_domain: Optional[str],
) -> tuple[Optional[int], Optional[int]]:
    """Parse both bounds and refuse MIXED shapes in one request (§5).

    One integer + one ISO string never combine; the shape pair must be
    uniform (all-ns or all-ISO-in-wall). Parsed via :func:`parse_time_bound`
    (per-bound rows) plus the explicit mix check.
    """
    start = parse_time_bound("start_ns", start_ns, clock_domain)
    end = parse_time_bound("end_ns", end_ns, clock_domain)
    if isinstance(start_ns, str) != isinstance(end_ns, str) and (
        start_ns is not None and end_ns is not None
    ):
        raise SemanticValidationError(
            OBS_INVALID_TIME_DOMAIN,
            "start_ns/end_ns must not mix integer-nanosecond and ISO-8601 "
            "shapes in one request (SPEC-305 §5)",
            details={"param": "start_ns/end_ns"},
        )
    return start, end


def parse_iso8601_ns(text: str) -> Optional[int]:
    """Parse an ISO-8601 instant to epoch nanoseconds (UTC-anchored)."""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Naive instants are UTC by the wall:utc contract.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(round(parsed.timestamp() * 1_000_000_000))


# Backwards-internal alias kept private.
_parse_iso8601_ns = parse_iso8601_ns


def sort_key_factory(sort: str, clock_domain: Optional[str]) -> Callable[[dict], tuple]:
    """Build the record sort key for one §5 sort value.

    Time sorts key on ``time.source`` within the pinned domain (single
    order, SPEC-303 §4 posture); journal sorts key on the stamped seq.
    """
    if sort in (SORT_JOURNAL_ASC, SORT_JOURNAL_DESC):
        return lambda item: item["journal_seq"]
    if sort in (SORT_TIME_ASC, SORT_TIME_DESC):
        assert clock_domain, "time sorts require a pinned clock_domain"

        def time_key(item: dict) -> tuple:
            source = item["time"]["source"]
            return (source["clock_epoch"], source["value_ns"])

        return time_key
    raise BadRequestError(
        REQUEST_BODY_INVALID,
        f"sort must be one of {VALID_SORTS}, got {sort!r}",
        details={"param": "sort", "allowed": list(VALID_SORTS)},
    )
