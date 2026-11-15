"""Frozen-table routes whose backing use-cases arrive with M4 (SPEC-500
§4.1/§4.4/§4.7, tickets #48/#54).

Route-table freeze discipline (REQ-API-500-001): the §4 inventory is the
authority, so these routes are **mounted now** and answer **501 Not
Implemented** through the unified envelope until their M3/M4 backends land:

- §4.1 Topology: creation/list/read/modify are SPEC-502 persistence
  (revision-row appends) — the topology tables are not in the M3 storage
  slice; ``POST .../validate`` needs the stored graph, so it waits too.
- §4.4 Diagnosis/Recovery: ticket #54 wires the TWO diagnosis endpoints
  (``GET .../diagnoses`` list, ``POST .../runs/{run_id}/diagnose``
  idempotent re-evaluation) behind the optional ``diagnosis_port`` — an
  unbound port (composition root has no service yet) keeps the 501
  freeze answer; ``POST .../verify`` stays a stub until SPEC-206
  (ticket #56).
- §4.7 Scenario: SPEC-205 experiment packages have no M3 registry.

Each stub documents exactly which spec owns the future semantics so the
additive-only evolution (SPEC-500 §3) can replace the handler in place
without touching the path inventory.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from fastapi import APIRouter
from starlette.exceptions import HTTPException

from api.dto.diagnosis import (
    DiagnosisDTO,
    DiagnosisReportDTO,
    diagnosis_dto_from_record,
    diagnosis_report_dto_from_report,
)

__all__ = [
    "DiagnosisPort",
    "ServiceDiagnosisPort",
    "build_pending_router",
]

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
_VERIFY_DETAIL = (
    "recovery verification (SPEC-206 three-state) lands with the M4 "
    "diagnosis chain; the route is mounted per the SPEC-500 §4.4 freeze"
)
_SCENARIO_DETAIL = (
    "the scenario registry (SPEC-205 experiment packages) lands with M4; "
    "the route is mounted per the SPEC-500 §4.7 freeze"
)


class DiagnosisPort(Protocol):
    """The §4.4 diagnosis face as seen from the REST layer (structural —
    import-linter C6 pins the api layer to ``application``-only imports).
    Implementations return the api-owned DTOs and raise the application
    error categories; ``api.errors`` renders the SPEC-500 §6 rows
    (404 unknown session/run, 503 storage unavailable)."""

    async def list_diagnoses(self, session_id: str) -> Sequence[DiagnosisDTO]: ...

    async def diagnose(self, session_id: str, run_id: str) -> DiagnosisReportDTO: ...


class ServiceDiagnosisPort:
    """Built-in port adapter: wraps an application diagnosis service into
    :class:`DiagnosisPort`. The mapping lives in the api layer (it owns
    the DTOs); the service object stays duck-typed so the adapter never
    imports ``domain`` (C6)."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def list_diagnoses(self, session_id: str) -> list[DiagnosisDTO]:
        return [
            diagnosis_dto_from_record(record)
            for record in self._service.list_diagnoses(session_id)
        ]

    async def diagnose(self, session_id: str, run_id: str) -> DiagnosisReportDTO:
        return diagnosis_report_dto_from_report(
            self._service.evaluate(session_id, run_id)
        )


def build_pending_router(
    *, diagnosis_port: DiagnosisPort | None = None
) -> APIRouter:
    """Build the §4.1/§4.4/§4.7 router (frozen table presence).

    ``diagnosis_port=None`` keeps the §4.4 diagnosis endpoints on the 501
    freeze answer; binding a port switches exactly those two handlers to
    the SPEC-306 service (additive wiring — the paths/methods never
    change, SPEC-500 §3).
    """
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
    async def list_diagnoses(session_id: str) -> list[DiagnosisDTO]:
        if diagnosis_port is None:
            raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)
        return list(await diagnosis_port.list_diagnoses(session_id))

    @router.post("/sessions/{session_id}/runs/{run_id}/diagnose")
    async def diagnose_run(session_id: str, run_id: str) -> DiagnosisReportDTO:
        # Idempotent re-evaluation (SPEC-306 §5 evaluate).
        if diagnosis_port is None:
            raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)
        return await diagnosis_port.diagnose(session_id, run_id)

    @router.post("/sessions/{session_id}/runs/{run_id}/verify")
    async def verify_run(session_id: str, run_id: str) -> dict:
        # Three-state PASS/FAIL/INCONCLUSIVE (SPEC-206, ticket #56).
        raise HTTPException(status_code=_501, detail=_VERIFY_DETAIL)

    # --- §4.7 Scenario -------------------------------------------------------

    @router.get("/scenarios")
    async def list_scenarios() -> dict:
        raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)

    @router.get("/scenarios/{scenario_id}")
    async def get_scenario(scenario_id: str) -> dict:
        raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)

    return router
