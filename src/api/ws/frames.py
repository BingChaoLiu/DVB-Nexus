"""WebSocket transport frames — SPEC-501 §4 (ticket #49, REQ-WS-501-002/005).

The transport layer adds exactly one wrapper field (``type``) around its
payloads and never modifies the envelope itself (ADR-0006 decision 4:
信封松负载紧 — the transport is not allowed to invent a fourth envelope):

- **journal frame**: ``{"type": "journal", "envelope": <SPEC-301 envelope>}``
  — the full stamped envelope (``journal_seq`` included) verbatim; a frame
  without the stamp is refused because the stamp is the replay cursor's
  anchor and the transport never fabricates order (CONTEXT.md 流水号).
- **hint frame**: ``{"type": "hint", "topic": ..., "data": ...}`` — a
  pointer to REST pull for record-type state (alert/metric/health/export,
  SPEC-305 §8 five topics). Topics are transport vocabulary per SPEC-501
  §4.1; they are deliberately NOT envelope event types (the MVP
  ``observation.*`` envelope namespace is empty and withdrawn,
  SPEC-301 §4 / SPEC-304 §5).
- **upstream**: ``subscribe`` (session + optional ``last_journal_seq``
  cursor) and ``ping``; server replies ``ready`` / ``pong``.

Close codes (SPEC-501 §8 matrix) live here as the single vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# --- close-code matrix (SPEC-501 §8) -----------------------------------------

#: session 不存在 / 已 DISPOSED (SPEC-501 §8).
CLOSE_SESSION_UNKNOWN = 4404
#: subscribe 的 session_id 与路由不一致 (SPEC-501 §8).
CLOSE_SUBSCRIBE_MISMATCH = 4400
#: 队列溢出持续慢消费 — reason 携带续传 cursor (SPEC-501 §8).
CLOSE_SLOW_CONSUMER = 1013
#: 服务端存储不可用 — 恢复重连后重放兜底 (SPEC-501 §8).
CLOSE_STORAGE_UNAVAILABLE = 1011
#: Heartbeat pong timeout (SPEC-501 §3). Not enumerated in §8; the transport
#: uses 1008 (policy violation) — deviation recorded in ticket #49's report.
CLOSE_PONG_TIMEOUT = 1008

#: Slow-consumer close reason carrying the continuation cursor. Parseable
#: ``journal_seq=<n>`` (SPEC-501 §6: 主动断开 close 1013 + 自定义 reason
#: 带 journal_seq). Client reconnects with ``last_journal_seq=<n>``.
SLOW_CONSUMER_REASON_PREFIX = "slow-consumer;journal_seq="


def slow_consumer_reason(last_sent_seq: int) -> str:
    """Build the 1013 close reason carrying the continuation cursor."""
    return f"{SLOW_CONSUMER_REASON_PREFIX}{last_sent_seq}"


def parse_slow_consumer_cursor(reason: str) -> int | None:
    """Extract the continuation cursor from a 1013 close reason (client side).

    Returns ``None`` when the reason is not a slow-consumer reason.
    """
    if not reason.startswith(SLOW_CONSUMER_REASON_PREFIX):
        return None
    try:
        return int(reason[len(SLOW_CONSUMER_REASON_PREFIX):])
    except ValueError:
        return None


# --- hint topics (SPEC-501 §4.1 = SPEC-305 §8 five topics) --------------------

#: The five record-state notification topics. Record-type state (alert/
#: metric/health/export progress) never enters the event stream (SPEC-304 §5
#: alert record is authoritative; SPEC-301 §4) — WS only hints to pull.
HINT_TOPICS = frozenset(
    {
        "observation.event_appended",
        "observation.metric_updated",
        "observation.alert_changed",
        "observation.health_changed",
        "observation.export_progress",
    }
)


class WsFrameError(ValueError):
    """A transport-frame contract violation (malformed frame or topic)."""


# --- downstream encoders -------------------------------------------------------


def encode_journal_frame(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap one stamped SPEC-301 envelope into a journal frame.

    The envelope is copied (deep) into the frame verbatim — no field is
    added, stripped or rewritten (REQ-WS-501-005). Refuses an envelope
    without ``journal_seq``: the transport never fabricates the total order.
    """
    if not isinstance(envelope, Mapping) or "journal_seq" not in envelope:
        raise WsFrameError(
            "journal frame requires a stamped SPEC-301 envelope "
            "(journal_seq present, ADR-0006 decision 2)"
        )
    return {"type": "journal", "envelope": _copy_value(envelope)}


def encode_hint_frame(topic: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap one record-state pointer into a hint frame (SPEC-501 §4.1).

    ``topic`` must be one of the SPEC-305 §8 five topics; anything else is a
    transport contract violation (envelope event types do not ride hints).
    """
    if topic not in HINT_TOPICS:
        raise WsFrameError(
            f"hint topic {topic!r} is not one of the SPEC-305 §8 five topics"
        )
    return {
        "type": "hint",
        "topic": topic,
        "data": _copy_value(data),
    }


def encode_ready(replayed_from: int) -> dict[str, Any]:
    """``ready`` — replay caught up; ``replayed_from`` is the first live seq.

    Per SPEC-501 §4.2: subscribe with ``last_journal_seq=1234`` answers
    ``{"type": "ready", "replayed_from": 1235}``.
    """
    return {"type": "ready", "replayed_from": int(replayed_from)}


def encode_pong() -> dict[str, Any]:
    """``pong`` — reply to the upstream application-level ``ping`` (§4.2)."""
    return {"type": "pong"}


# --- upstream parsing -----------------------------------------------------------


@dataclass(frozen=True)
class UpstreamMessage:
    """One validated upstream message (SPEC-501 §4.2).

    ``last_journal_seq`` is ``None`` when omitted — "从当前起，不重放"
    (SPEC-501 §5: default = live from now, no replay).
    """

    type: str
    session_id: str | None = None
    last_journal_seq: int | None = None


def parse_upstream(raw: Any) -> UpstreamMessage:
    """Validate one upstream JSON object into an :class:`UpstreamMessage`.

    Raises :class:`WsFrameError` for anything not exactly the §4.2 shapes:
    unknown ``type`` values, missing ``session_id`` on subscribe, non-int or
    negative cursors, and non-object payloads.
    """
    if not isinstance(raw, Mapping):
        raise WsFrameError("upstream message must be a JSON object")
    msg_type = raw.get("type")
    if msg_type == "subscribe":
        session_id = raw.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise WsFrameError("subscribe requires a non-empty session_id")
        cursor = raw.get("last_journal_seq")
        if cursor is not None:
            if isinstance(cursor, bool) or not isinstance(cursor, int):
                raise WsFrameError("last_journal_seq must be an integer")
            if cursor < 0:
                raise WsFrameError("last_journal_seq must be >= 0")
        return UpstreamMessage(
            type="subscribe", session_id=session_id, last_journal_seq=cursor
        )
    if msg_type == "ping":
        return UpstreamMessage(type="ping")
    raise WsFrameError(f"unknown upstream message type: {msg_type!r}")


def _copy_value(value: Any) -> Any:
    """Deep-copy helper keeping JSON-shaped structures frame-local.

    The WebSocket JSON boundary re-serializes everything anyway; the copy
    guarantees the caller's envelope dict can never be mutated through a
    frame (transport is a passthrough, not an owner).
    """
    import copy

    return copy.deepcopy(dict(value))
