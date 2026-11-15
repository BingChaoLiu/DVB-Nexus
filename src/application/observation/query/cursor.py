"""Opaque events cursor tokens — filter-hash + scope bound (ticket #53,
SPEC-305 §5 cursor; REQ-OBS-305-003 过期语义).

The token binds the pagination position to the query that produced it:
scope (session), the §5 whitelist filter fingerprint, the sort and the
resume anchor (seq for journal sorts, position+anchor-seq for the
position-stable time sorts). Any replay under a different binding — or an
undecodable token — is ``OBS_CURSOR_EXPIRED`` on the 409 row (cursor/
过滤器冲突, SPEC-305 §7), the same semantics the #51 timeline cursor
established.

Tokens are opaque to clients: base64url over a compact JSON payload.
No confidentiality claim is made (no secrets inside) — opacity is for
contract stability, not security.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from application.errors import ConflictError

from application.observation.query.errors import OBS_CURSOR_EXPIRED

_CURSOR_VERSION = 1


class CursorExpiredError(ConflictError):
    """The cursor token is malformed, foreign, or replayed under a changed
    binding — the client restarts iteration from page one (non-retryable
    as-is; §9)."""


@dataclass(frozen=True)
class CursorState:
    """Decoded cursor payload (position anchor + binding fingerprint)."""

    session_id: str
    filter_hash: str
    sort: str
    #: Journal sorts: the last journal_seq served (resume strictly after/
    #: before it). Time sorts: the anchor seq at the resume position.
    anchor_seq: int
    #: Time sorts only: the resume position in the materialized order.
    position: Optional[int] = None


def filter_fingerprint(request: Any) -> str:
    """Stable hash of the §5 whitelist filter binding (scope + filters +
    sort + time bounds + domain). Changing ANY of them invalidates the
    cursor."""
    material = {
        "session_id": request.session_id,
        "sort": request.sort,
        "event_types": list(request.event_types),
        "severities": list(request.severities),
        "producer_ids": list(request.producer_ids),
        "run_id": request.run_id,
        "clock_domain": request.clock_domain,
        "clock_epoch": request.clock_epoch,
        "start_ns": request.start_ns,
        "end_ns": request.end_ns,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def encode_cursor(state: CursorState) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "sid": state.session_id,
        "fh": state.filter_hash,
        "sort": state.sort,
        "a": state.anchor_seq,
        "p": state.position,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> CursorState:
    """Decode one opaque token; ANY failure is :class:`CursorExpiredError`
    (``OBS_CURSOR_EXPIRED``) — never a crash, never a partial state."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token is malformed or undecodable "
            "(SPEC-305 §5: opaque token)",
            details={"reason": f"decode failure: {exc}"},
        ) from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token version is unknown",
            details={"reason": "version mismatch"},
        )
    anchor_seq = payload.get("a")
    position = payload.get("p")
    if not isinstance(anchor_seq, int) or isinstance(anchor_seq, bool):
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token anchor is malformed",
            details={"reason": "anchor type"},
        )
    if position is not None and (
        not isinstance(position, int) or isinstance(position, bool)
    ):
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token position is malformed",
            details={"reason": "position type"},
        )
    return CursorState(
        session_id=payload.get("sid", ""),
        filter_hash=payload.get("fh", ""),
        sort=payload.get("sort", ""),
        anchor_seq=anchor_seq,
        position=position,
    )


@dataclass(frozen=True)
class OffsetCursorState:
    """Decoded offset-cursor payload (alerts list face: deterministic store
    order + offset window; binding = session + filter fingerprint)."""

    session_id: str
    filter_hash: str
    offset: int


def encode_offset_cursor(state: OffsetCursorState) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "sid": state.session_id,
        "fh": state.filter_hash,
        "off": state.offset,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_offset_cursor(token: str) -> OffsetCursorState:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token is malformed or undecodable "
            "(SPEC-305 §5: opaque token)",
            details={"reason": f"decode failure: {exc}"},
        ) from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token version is unknown",
            details={"reason": "version mismatch"},
        )
    offset = payload.get("off")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise CursorExpiredError(
            OBS_CURSOR_EXPIRED,
            "cursor token offset is malformed",
            details={"reason": "offset type"},
        )
    return OffsetCursorState(
        session_id=payload.get("sid", ""),
        filter_hash=payload.get("fh", ""),
        offset=offset,
    )


__all__ = [
    "CursorExpiredError",
    "CursorState",
    "OffsetCursorState",
    "decode_cursor",
    "decode_offset_cursor",
    "encode_cursor",
    "encode_offset_cursor",
    "filter_fingerprint",
]
