"""Run routes: the async-generation job surface (SPEC-500 §4.3, ticket #48).

Ticket #13 Q-C-① / ADR-0007 item 2: the fault plan rides **in the run
request body** and binds at the prepare stage — the chatgpt §9
``POST /sessions/{id}/faults`` runtime-injection shape is deprecated and
has no route here.

Async-job semantics (REQ-API-500-004): ``POST /sessions/{id}/runs`` is a
**202** acceptance, never a synchronous completion — the handler validates
(prepare) and schedules, then answers ``202 + run_id`` (the bound
``config_hash`` fingerprint rides in the body). Synchronous completion
masquerading as 202 is contract-forbidden; progress rides ``run_progress``
events (SPEC-301 §5 / SPEC-501 transport).

Prepare rejection (SPEC-204 §11 / SPEC-500 §4.3): fault-plan and generation
config validation complete synchronously at submission (AC-204-01) and map
to **422** semantic-invalidity with the registry codes
``SIM_TS_PLAN_INVALID`` / ``SIM_TS_CONFIG_INVALID`` and the per-element
detail list (schema path) — raised by the port as
``application.errors.SemanticValidationError``, rendered by ``api.errors``.

Backend seam: :class:`RunsPort` is structural (import-linter C6). The
composition root binds it to the #43 ``simulation.ts_runtime.TSRuntime``
(prepare + bounded-worker execution) over the #41 run face; the port owns
the job registry so ``GET .../runs/{run_id}`` can poll without touching the
session lifecycle.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter

from api.dto.runs import RunAcceptedDTO, RunStatusDTO, RunSubmitRequest
from application.errors import NotFoundError

__all__ = ["RunsPort", "build_runs_router"]


class RunsPort(Protocol):
    """The run job face as seen from the REST layer.

    ``submit`` validates + schedules and returns the 202 body; it raises
    ``NotFoundError`` (unknown session), ``ConflictError`` (lifecycle /
    concurrent-run conflicts) or ``SemanticValidationError`` (prepare
    rejection). ``get_run`` returns ``None`` for an unknown job — the route
    renders the uniform 404.
    """

    async def submit(
        self, session_id: str, request: RunSubmitRequest
    ) -> RunAcceptedDTO: ...

    async def get_run(self, session_id: str, run_id: str) -> RunStatusDTO | None: ...


def build_runs_router(port: RunsPort) -> APIRouter:
    """Build the §4.3 run router (mounted under the frozen prefix)."""
    router = APIRouter()

    @router.post(
        "/sessions/{session_id}/runs",
        status_code=202,
        response_model=RunAcceptedDTO,
    )
    async def submit_run(
        session_id: str, request: RunSubmitRequest
    ) -> RunAcceptedDTO:
        # 202 + run_id: asynchronous job acceptance (SPEC-500 §4.3). The
        # route performs no generation work itself — prepare/schedule is
        # the port's concern; progress is event-borne, never polled here.
        return await port.submit(session_id, request)

    @router.get(
        "/sessions/{session_id}/runs/{run_id}", response_model=RunStatusDTO
    )
    async def get_run(session_id: str, run_id: str) -> RunStatusDTO:
        view = await port.get_run(session_id, run_id)
        if view is None:
            raise NotFoundError(
                "SIM_RUN_NOT_FOUND",
                f"unknown run {run_id!r} in session {session_id!r} "
                "(SPEC-203 §5.2)",
            )
        return view

    return router
