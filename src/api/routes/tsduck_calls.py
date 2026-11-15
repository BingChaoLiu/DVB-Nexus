"""SPEC-500 §4.8 TSDuck call-records route — the #80 additive read face
over the SPEC-308 §7 nine-field persistence.

Session-scoped list (the ``GET .../diagnoses`` house pattern), ordered by
``started_at_utc_ms`` ASC with an optional ``run_id`` filter. MVP carries
no pagination — single-user local posture, record volume bounded by
fixture seeding (the additive evolution keeps the path stable).

Existence semantics mirror ``DiagnosisService.list_diagnoses`` exactly:
no stored rows AND an empty journal → 404 ``SIM_SESSION_NOT_FOUND``;
otherwise 200 (possibly an empty list). An unbound port keeps the 501
freeze answer (the mount-point posture; the wiring gate demands the
production composition bind it).
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from fastapi import APIRouter, Query
from starlette.exceptions import HTTPException

from api.dto.tsduck_calls import TSDuckCallDTO
from api.errors import OPENAPI_ERROR_RESPONSES

__all__ = [
    "TSDuckCallsPort",
    "build_tsduck_calls_router",
]

_501 = 501

_CALLS_DETAIL = (
    "the TSDuck call-record store (SPEC-308 §7 nine fields, SPEC-500 §4.8 "
    "additive read face) is not bound in this composition"
)


class TSDuckCallsPort(Protocol):
    """The §4.8 face as seen from the REST layer (structural —
    import-linter C6 pins the api layer to ``application``-only imports).
    Implementations return the api-owned DTOs and raise the application
    error categories (404 unknown session, 503 storage unavailable)."""

    def list_calls(
        self, session_id: str, *, run_id: Optional[str]
    ) -> Sequence[TSDuckCallDTO]: ...


def build_tsduck_calls_router(
    tsduck_calls_port: TSDuckCallsPort | None = None,
) -> APIRouter:
    """Build the §4.8 router. ``tsduck_calls_port=None`` keeps the route
    on the 501 freeze answer (the unbound composition)."""
    router = APIRouter()

    @router.get(
        "/sessions/{session_id}/tsduck/calls",
        responses=OPENAPI_ERROR_RESPONSES,
    )
    async def list_tsduck_calls(
        session_id: str,
        run_id: Optional[str] = Query(default=None),
    ) -> list[TSDuckCallDTO]:
        if tsduck_calls_port is None:
            raise HTTPException(status_code=_501, detail=_CALLS_DETAIL)
        return list(tsduck_calls_port.list_calls(session_id, run_id=run_id))

    return router
