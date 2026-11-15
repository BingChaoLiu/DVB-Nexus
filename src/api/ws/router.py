"""WS router — mounts the SPEC-501 connection endpoint (ticket #49).

Factory-shaped (like the whole api layer): :func:`build_ws_router` closes
over the :class:`api.ws.hub.SessionHub` and exposes the §3 route
``/ws/v1/sessions/{session_id}`` — a single connection serves exactly one
session (ticket #13 Q4; no multi-session aggregation connection).

Path note: the WS transport namespace is ``/ws/v1``, deliberately outside
the frozen REST prefix ``/api/v1`` (SPEC-501 §3 names the route verbatim;
the /api/v1 additive-only policy governs REST routes — SPEC-500 §3).
``api.app.create_ws_app`` is the only place that mounts this router.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from api.ws.hub import SessionHub

WS_ROUTE = "/ws/v1/sessions/{session_id}"


def build_ws_router(hub: SessionHub) -> APIRouter:
    """Build the router serving ``hub`` at the SPEC-501 §3 route."""
    router = APIRouter()

    @router.websocket(WS_ROUTE)
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await hub.serve(websocket, session_id)

    return router


__all__ = ["WS_ROUTE", "build_ws_router"]
