"""SPEC-500 §4.7 Scenario routes — the frozen table + the #80 additive
solution-reveal gate.

The two GET endpoints landed verbatim in M3 (#48) as 501 mount points in
``pending.py``; ticket #80 moves them behind the ``ScenarioPort`` over the
SPEC-205 scenario registry (directory scan; same paths, same methods —
additive-only evolution, SPEC-500 §3) and appends the 裁定 F reveal face:

- ``GET /scenarios`` — the summary projection (filename-ASC determinism);
- ``GET /scenarios/{scenario_id}`` — the exported document with
  ``hidden_reference_solution`` stripped by construction
  (``export_scenario_document``; REQ-SIM-205-003 政策外不泄露);
- ``GET /scenarios/{scenario_id}/solution?session_id=`` — the backend
  reveal gate: the session+scenario pair must carry a verdict=PASS
  SPEC-206 row (read from the SPEC-502 ``verification_verdicts`` table)
  before the hidden reference solution leaves the server; anything else
  is 403 ``SIM_SCENARIO_SOLUTION_LEAK`` (SPEC-205 §7 row 6, refuse AND
  audit). Unknown scenario → 404 ``SIM_SCENARIO_NOT_FOUND``; missing
  ``session_id`` → 400 ``REQUEST_BODY_INVALID``.

An unbound port keeps the 501 freeze answers on ALL three routes (the #48
mount-point contract, exercised by the unbound rest_stack).
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from fastapi import APIRouter, Query
from starlette.exceptions import HTTPException

from api.dto.scenarios import (
    ScenarioDetailDTO,
    ScenarioSolutionDTO,
    ScenarioSummaryDTO,
)
from api.errors import OPENAPI_ERROR_RESPONSES, OPENAPI_SOLUTION_ERROR_RESPONSES

__all__ = [
    "ScenarioPort",
    "build_scenario_router",
]

_501 = 501

_SCENARIO_DETAIL = (
    "the scenario registry (SPEC-205 experiment packages) lands with M4; "
    "the route is mounted per the SPEC-500 §4.7 freeze"
)


class ScenarioPort(Protocol):
    """The §4.7 scenario face as seen from the REST layer (structural —
    import-linter C6 pins the api layer to ``application``-only imports).
    Implementations return the api-owned DTOs and raise the application
    error categories; ``api.errors`` renders the SPEC-500 §6 rows (400
    body invalid, 404 ``SIM_SCENARIO_NOT_FOUND``, 403
    ``SIM_SCENARIO_SOLUTION_LEAK``, 503 storage unavailable)."""

    def list_scenarios(self) -> Sequence[ScenarioSummaryDTO]: ...

    def get(self, scenario_id: str) -> ScenarioDetailDTO: ...

    def reveal(self, scenario_id: str, session_id: str) -> ScenarioSolutionDTO: ...


def build_scenario_router(
    scenario_port: ScenarioPort | None = None,
) -> APIRouter:
    """Build the §4.7 scenario router (frozen table presence + the #80
    additive reveal row).

    ``scenario_port=None`` keeps the routes on the 501 freeze answer (the
    unbound composition); binding a port switches the handlers to the
    SPEC-205 registry in place — the §4.7 path inventory never changes.
    """
    router = APIRouter()

    # --- §4.7 Scenario -------------------------------------------------------

    @router.get("/scenarios", responses=OPENAPI_ERROR_RESPONSES)
    async def list_scenarios() -> list[ScenarioSummaryDTO]:
        if scenario_port is None:
            raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)
        return list(scenario_port.list_scenarios())

    @router.get(
        "/scenarios/{scenario_id}", responses=OPENAPI_ERROR_RESPONSES
    )
    async def get_scenario(scenario_id: str) -> ScenarioDetailDTO:
        if scenario_port is None:
            raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)
        return scenario_port.get(scenario_id)

    @router.get(
        "/scenarios/{scenario_id}/solution",
        responses=OPENAPI_SOLUTION_ERROR_RESPONSES,
    )
    async def reveal_scenario_solution(
        scenario_id: str,
        session_id: Optional[str] = Query(default=None),
    ) -> ScenarioSolutionDTO:
        # The reveal gate (裁定 F): the backend, not the client, decides
        # whether the hidden reference solution leaves the server.
        if scenario_port is None:
            raise HTTPException(status_code=_501, detail=_SCENARIO_DETAIL)
        if not session_id:
            from application.errors import BadRequestError

            raise BadRequestError(
                "REQUEST_BODY_INVALID",
                "solution reveal requires the session_id query parameter "
                "(the PASS gate is per session+scenario; SPEC-205 §7 row 6)",
                details={"param": "session_id"},
            )
        return scenario_port.reveal(scenario_id, session_id)

    return router
