"""WebSocket transport (SPEC-501, ticket #49) — api layer's WS face.

Exports the assembly points only:

- :class:`api.ws.hub.SessionHub` / :class:`api.ws.hub.WsConfig` — the
  connection lifecycle, cursor replay and per-client backpressure hub;
- :func:`api.ws.router.build_ws_router` — the §3 route
  ``/ws/v1/sessions/{session_id}`` (mounted by ``api.app.create_ws_app``,
  the factory seam);
- :mod:`api.ws.frames` — the §4 frame vocabulary and §8 close codes;
- :mod:`api.ws.backpressure` — the §6 per-client coalesce/no-drop matrix.

Layer note (ADR-0005 decision 4): this package imports ``application``
only — the frozen event classification arrives as the registry's own
function object via the application seam, and the journal is consumed
through the application layer's structural ``EventJournal`` protocol; the
transport never imports domain or adapters directly.
"""

from api.ws.backpressure import ClientQueue, CoalesceKey, PendingItem
from api.ws.frames import (
    CLOSE_PONG_TIMEOUT,
    CLOSE_SESSION_UNKNOWN,
    CLOSE_SLOW_CONSUMER,
    CLOSE_STORAGE_UNAVAILABLE,
    CLOSE_SUBSCRIBE_MISMATCH,
    HINT_TOPICS,
    WsFrameError,
)
from api.ws.hub import SessionDirectory, SessionHub, WsConfig
from api.ws.router import WS_ROUTE, build_ws_router

__all__ = [
    "CLOSE_PONG_TIMEOUT",
    "CLOSE_SESSION_UNKNOWN",
    "CLOSE_SLOW_CONSUMER",
    "CLOSE_STORAGE_UNAVAILABLE",
    "CLOSE_SUBSCRIBE_MISMATCH",
    "CoalesceKey",
    "ClientQueue",
    "HINT_TOPICS",
    "PendingItem",
    "SessionDirectory",
    "SessionHub",
    "WS_ROUTE",
    "WsConfig",
    "WsFrameError",
    "build_ws_router",
]
