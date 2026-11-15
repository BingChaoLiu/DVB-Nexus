"""Frozen-table routes whose backing use-cases arrive with M4 (SPEC-500
§4.1/§4.4/§4.7, ticket #48).

Route-table freeze discipline (REQ-API-500-001): the §4 inventory is the
authority, so these routes are **mounted now** and answer **501 Not
Implemented** through the unified envelope until their M3/M4 backends land:

- §4.1 Topology: creation/list/read/modify are SPEC-502 persistence
  (revision-row appends) — the topology tables are not in the M3 storage
  slice; ``POST .../validate`` needs the stored graph, so it waits too.
- §4.4 Diagnosis/Recovery: SPEC-306 evaluate + SPEC-206 three-state
  verification are the M4 diagnosis chain.
- §4.7 Scenario: SPEC-205 experiment packages have no M3 registry.

Each stub documents exactly which spec owns the future semantics so the
additive-only evolution (SPEC-500 §3) can replace the handler in place
without touching the path inventory.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.exceptions import HTTPException

__all__ = ["build_pending_router"]

_501 = 501

_TOPOLOGY_DETAIL = (
    "topology persistence (SPEC-502 revision rows) lands with M4; the "
    "route is mounted per the SPEC-500 §4.1 freeze"
)
_DIAGNOSIS_DETAIL = (
    "diagnosis evaluation (SPEC-306) / verification (SPEC-206) lands with "
    "the M4 diagnosis chain; the route is mounted per the SPEC-500 §4.4 "
    "freeze"
)
_SCENARIO_DETAIL = (
    "the scenario registry (SPEC-205 experiment packages) lands with M4; "
    "the route is mounted per the SPEC-500 §4.7 freeze"
)


def build_pending_router() -> APIRouter:
    """Build the §4.1/§4.4/§4.7 501 mount points (frozen table presence)."""
    router = APIRouter()

    # --- §4.1 Topology -----------------------------------------------------

    @router.post("/topologies")
    async def create_topology() -> dict:
        raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)

    @router.get("/topologies")
    async def list_topologies() -> dict:
        raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)

    @router.get("/topologies/{topology_id}")
    async def get_topology(topology_id: str) -> dict:
        raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)

    @router.put("/topologies/{topology_id}")
    async def update_topology(topology_id: str) -> dict:
        # Modify = a new immutable revision row (SPEC-502), never in-place.
        raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)

    @router.post("/topologies/{topology_id}/validate")
    async def validate_topology(topology_id: str) -> dict:
        # SPEC-202 path-addressed structured errors once stored graphs exist.
        raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)

    # --- §4.4 Diagnosis / Recovery ------------------------------------------

    @router.get("/sessions/{session_id}/diagnoses")
    async def list_diagnoses(session_id: str) -> dict:
        raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)

    @router.post("/sessions/{session_id}/runs/{run_id}/diagnose")
    async def diagnose_run(session_id: str, run_id: str) -> dict:
        # Idempotent re-evaluation (SPEC-306 evaluate) once the M4 chain lands.
        raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)

    @router.post("/sessions/{session_id}/runs/{run_id}/verify")
    async def verify_run(session_id: str, run_id: str) -> dict:
        # Three-state PASS/FAIL/INCONCLUSIVE (SPEC-206).
        raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)

    # --- §4.7 Scenario -------------------------------------------------------

    @router.get("/scenarios")
    async def list_scenarios() -> dict:
        raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)

    @router.get("/scenarios/{scenario_id}")
    async def get_scenario(scenario_id: str) -> dict:
        raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)

    return router
