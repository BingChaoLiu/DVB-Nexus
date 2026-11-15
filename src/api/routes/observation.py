"""SPEC-305 observation query routes — frozen table presence, M4 wiring
(SPEC-500 §4.5, ticket #48).

The eight SPEC-305 §4 logical endpoints land **verbatim** on the REST
surface (REQ-API-500-006): same methods, same paths, same order as the
frozen table. The *query processing* is deliberately not wired in M3 —
observation persistence + query semantics arrive with the M4 SPEC-305
implementation, so every endpoint here answers **501 Not Implemented**
rendered through the unified SPEC-305 §7 envelope (the framework-fallback
convention of ``api.errors``: code ``HTTP_501``).

This stub is a mount-point, not a license: when the M4 wiring lands, the
flat scalar query baseline (SPEC-305 §5: ``start_ns``/``end_ns``/``step_ns``
+ ``clock_domain``, ISO only for the wall domain, never mixed in one
request) and the read-only discipline must be implemented on these exact
paths (additive-only evolution, SPEC-500 §3).
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.exceptions import HTTPException

__all__ = ["build_observation_router"]

_501_DETAIL = (
    "observation query processing is not implemented yet (SPEC-305 wiring "
    "lands with M4); the route is mounted per the SPEC-500 §4.5 freeze"
)


def _not_implemented() -> None:
    raise HTTPException(status_code=501, detail=_501_DETAIL)


def build_observation_router() -> APIRouter:
    """Build the §4.5 observation router (eight 501 mount points)."""
    router = APIRouter()

    @router.get("/sessions/{session_id}/observation/summary")
    async def observation_summary(session_id: str) -> dict:
        _not_implemented()

    @router.get("/sessions/{session_id}/events")
    async def list_events(session_id: str) -> dict:
        _not_implemented()

    @router.get("/sessions/{session_id}/timeline")
    async def get_timeline(session_id: str) -> dict:
        _not_implemented()

    @router.post("/sessions/{session_id}/metrics/query")
    async def query_metrics(session_id: str) -> dict:
        _not_implemented()

    @router.get("/sessions/{session_id}/alerts")
    async def list_alerts(session_id: str) -> dict:
        _not_implemented()

    @router.get("/sessions/{session_id}/health")
    async def get_health(session_id: str) -> dict:
        _not_implemented()

    @router.get("/sessions/{session_id}/exports/{export_id}")
    async def get_export(session_id: str, export_id: str) -> dict:
        _not_implemented()

    @router.post("/sessions/{session_id}/exports")
    async def create_export(session_id: str) -> dict:
        # Export POST creates only an Observation export task — it never
        # creates or mutates a simulation session (SPEC-305 §4).
        _not_implemented()

    return router
