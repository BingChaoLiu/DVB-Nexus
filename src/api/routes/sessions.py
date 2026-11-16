"""Session lifecycle routes (SPEC-500 §4.2, ticket #48).

The §4.2 table is the one-to-one mapping of the SPEC-200 §5/§6 lifecycle
exhaustive table onto REST:

- ``POST /sessions`` creates (topology_id + revision, seed, clock_config,
  resource_limits, optional scenario_id) → **201** with the SPEC-200 §4
  ``SessionView``;
- ``POST /sessions/{id}/validate`` → VALIDATING (SPEC-200 §6
  ``validate_session``); ``POST .../start|pause|resume|stop`` → the SPEC-200
  §5 edges (RUNNING→PAUSED shares the clock critical section behind the
  backend's per-session command lock); ``DELETE /sessions/{id}`` disposes
  (recovers tasks and TSDuck child processes); ``GET .../snapshot`` is the
  full-replacement pull API with the optional ``journal_seq_cursor`` echo
  (SPEC-200 §4);
- an illegal lifecycle transition is a **409** (``InvalidLifecycleTransition``,
  SPEC-500 §4.2/§6) — the backend raises
  ``application.errors.ConflictError`` with the ``SIM_INVALID_LIFECYCLE_TRANSITION``
  registry code and the current/target/allowed detail.

Backend seam: :class:`SessionsPort` is structural (import-linter C6: the
api layer imports only ``application``). The production composition root
binds it to the #41 ``simulation.runtime.SimulationRuntime``; the port
returns api-owned Pydantic DTOs (SPEC-108 §4 discipline: the api layer does
the JSON validation) and raises the application error categories, which
``api.errors`` maps onto the SPEC-500 §6 rows.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from api.dto.sessions import (
    CreateSessionRequest,
    SessionDetailDTO,
    SessionListItemDTO,
    SessionValidationDTO,
    SessionViewDTO,
    SnapshotDTO,
)
from api.errors import OPENAPI_ERROR_RESPONSES
from application.errors import NotFoundError

__all__ = ["SessionsPort", "build_sessions_router"]


class SessionsPort(Protocol):
    """The SPEC-200 §6 command face as seen from the REST layer.

    Implementations return the api-owned DTOs directly and raise the
    application error categories (``NotFoundError`` / ``ConflictError`` /
    ``SemanticValidationError``) — ``api.errors`` renders the SPEC-305 §7
    envelope with the SPEC-500 §6 status mapping.
    """

    async def create(self, request: CreateSessionRequest) -> SessionViewDTO: ...

    async def validate_session(self, session_id: str) -> SessionValidationDTO: ...

    async def start(self, session_id: str) -> SessionViewDTO: ...

    async def pause(self, session_id: str) -> SessionViewDTO: ...

    async def resume(self, session_id: str) -> SessionViewDTO: ...

    async def stop(self, session_id: str) -> SessionViewDTO: ...

    async def dispose(self, session_id: str) -> None: ...

    async def snapshot(
        self, session_id: str, *, journal_seq_cursor: int | None
    ) -> SnapshotDTO: ...

    async def list_sessions(self, *, limit: int) -> list[SessionListItemDTO]:
        """The SPEC-408 §6.1 read face (ticket #94): newest-first, capped."""
        ...

    async def get_session_detail(
        self, session_id: str
    ) -> SessionDetailDTO | None:
        """The SPEC-408 §6.2 read face (ticket #94): the view shape plus
        the provenance pair; ``None`` renders the uniform 404."""
        ...


def _require_found(view: BaseModel | None, what: str) -> BaseModel:
    """Port-returned ``None`` is a uniform 404 (SPEC-500 §6 row 404)."""
    if view is None:
        raise NotFoundError(
            "SIM_SESSION_NOT_FOUND", f"unknown {what} (SPEC-200 §6)"
        )
    return view


def build_sessions_router(port: SessionsPort) -> APIRouter:
    """Build the §4.2 session router (mounted under the frozen prefix)."""
    router = APIRouter()

    @router.post("/sessions", status_code=201, response_model=SessionViewDTO)
    async def create_session(request: CreateSessionRequest) -> SessionViewDTO:
        return await port.create(request)

    @router.post(
        "/sessions/{session_id}/validate", response_model=SessionValidationDTO
    )
    async def validate_session(session_id: str) -> SessionValidationDTO:
        return await port.validate_session(session_id)

    @router.post("/sessions/{session_id}/start", response_model=SessionViewDTO)
    async def start_session(session_id: str) -> SessionViewDTO:
        return await port.start(session_id)

    @router.post("/sessions/{session_id}/pause", response_model=SessionViewDTO)
    async def pause_session(session_id: str) -> SessionViewDTO:
        return await port.pause(session_id)

    @router.post("/sessions/{session_id}/resume", response_model=SessionViewDTO)
    async def resume_session(session_id: str) -> SessionViewDTO:
        return await port.resume(session_id)

    @router.post("/sessions/{session_id}/stop", response_model=SessionViewDTO)
    async def stop_session(session_id: str) -> SessionViewDTO:
        return await port.stop(session_id)

    @router.delete("/sessions/{session_id}", status_code=204)
    async def dispose_session(session_id: str) -> Response:
        await port.dispose(session_id)
        return Response(status_code=204)

    @router.get("/sessions/{session_id}/snapshot", response_model=SnapshotDTO)
    async def get_snapshot(
        session_id: str, journal_seq_cursor: int | None = None
    ) -> SnapshotDTO:
        # Cursor passthrough only: the pull API echoes the client cursor
        # (SPEC-200 §4); the route layer never authors a journal_seq.
        return _require_found(
            await port.snapshot(session_id, journal_seq_cursor=journal_seq_cursor),
            f"session {session_id!r}",
        )

    # --- SPEC-408 §6 read-only increments (ticket #94) ----------------------
    # Additive GET faces only: zero write paths, zero state migrations
    # (SPEC-408 §6); errors ride the unified envelope via the port.

    @router.get(
        "/sessions",
        response_model=list[SessionListItemDTO],
        responses=OPENAPI_ERROR_RESPONSES,
    )
    async def list_sessions(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[SessionListItemDTO]:
        # §6.1: newest-first, default 20, hard cap 100, no pagination —
        # the limit bounds are schema-enforced here so the rejection is
        # the SPEC-500 §6 row-400 envelope (REQUEST_BODY_INVALID).
        return await port.list_sessions(limit=limit)

    @router.get(
        "/sessions/{session_id}",
        response_model=SessionDetailDTO,
        responses=OPENAPI_ERROR_RESPONSES,
    )
    async def get_session_detail(session_id: str) -> SessionDetailDTO:
        # §6.2: the existing view shape + scenario_id?/created_at_ms.
        return _require_found(
            await port.get_session_detail(session_id),
            f"session {session_id!r}",
        )

    return router
