"""SPEC-500 §4.1 Topology routes — the frozen table, wired (ticket #80).

The five endpoints landed verbatim in M3 (#48) as 501 mount points in
``pending.py``; ticket #80 moves them behind the ``TopologyPort`` over the
SPEC-502 topologies-table persistence (same paths, same methods, same
order — additive-only evolution, SPEC-500 §3). An unbound port keeps the
501 freeze answers (the #48 mount-point contract, exercised by the
unbound rest_stack); the composition root binds the real backends, which
flips the wiring gate (``ALLOWED_501`` shrink).

Accepted semantics (REQ-API-500-001, SPEC-502 §4/§5):

- POST = a NEW topology (server-assigned uuid4 id, revision 1, 201);
- PUT = the NEXT immutable revision row (never in-place; the composite
  key ``(topology_id, revision)`` is the append authority);
- GET = the requested revision (default latest); 404 unknown;
- validate = the SPEC-202 §5 path-addressed report over the STORED graph
  (ok=false reports with 200 — session VALIDATING is where rejection
  happens, SPEC-200 §6 posture).

The port is structural (import-linter C6 pins ``api`` to
``application``-only imports); implementations raise the application
error categories and ``api.errors`` renders the SPEC-500 §6 rows
(404 ``SIM_TOPOLOGY_NOT_FOUND``, 503 storage unavailable).
"""

from __future__ import annotations

from typing import Optional, Protocol, Sequence

from fastapi import APIRouter, Query
from starlette.exceptions import HTTPException

from api.dto.topologies import (
    TopologyCreateRequest,
    TopologyDTO,
    TopologySummaryDTO,
    TopologyValidationDTO,
)
from api.errors import OPENAPI_ERROR_RESPONSES

__all__ = [
    "TopologyPort",
    "build_topology_router",
]

_501 = 501

_TOPOLOGY_DETAIL = (
    "topology persistence (SPEC-502 revision rows) lands with M4; the "
    "route is mounted per the SPEC-500 §4.1 freeze"
)


class TopologyPort(Protocol):
    """The §4.1 topology face as seen from the REST layer (structural —
    import-linter C6 pins the api layer to ``application``-only imports).
    Implementations return the api-owned DTOs and raise the application
    error categories; ``api.errors`` renders the SPEC-500 §6 rows (404
    unknown topology/revision, 503 storage unavailable). Unknown ids raise
    ``NotFoundError("SIM_TOPOLOGY_NOT_FOUND", ...)`` from the port — the
    raiser-owned §6 404 row."""

    def create(self, request: TopologyCreateRequest) -> TopologyDTO: ...

    def list_topologies(
        self, *, limit: int
    ) -> Sequence[TopologySummaryDTO]: ...

    def get(
        self, topology_id: str, revision: Optional[int]
    ) -> TopologyDTO: ...

    def save_revision(
        self, topology_id: str, request: TopologyCreateRequest
    ) -> TopologyDTO: ...

    def validate(
        self, topology_id: str, revision: Optional[int]
    ) -> TopologyValidationDTO: ...


def build_topology_router(
    topology_port: TopologyPort | None = None,
) -> APIRouter:
    """Build the §4.1 topology router (frozen table presence).

    ``topology_port=None`` keeps the five routes on the 501 freeze answer
    (the unbound composition); binding a port switches the handlers to
    the SPEC-502 persistence in place — the path inventory never changes.
    """
    router = APIRouter()

    # --- §4.1 Topology -----------------------------------------------------

    @router.post(
        "/topologies",
        status_code=201,
        responses=OPENAPI_ERROR_RESPONSES,
    )
    async def create_topology(
        request: TopologyCreateRequest | None = None,
    ) -> TopologyDTO:
        # The port check precedes body validation: an UNBOUND composition
        # keeps the frozen 501 answer even for bare requests (the #48
        # mount-point contract).
        if topology_port is None:
            raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)
        if request is None:
            request = TopologyCreateRequest()
        return topology_port.create(request)

    @router.get("/topologies", responses=OPENAPI_ERROR_RESPONSES)
    async def list_topologies(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[TopologySummaryDTO]:
        if topology_port is None:
            raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)
        return list(topology_port.list_topologies(limit=limit))

    @router.get(
        "/topologies/{topology_id}", responses=OPENAPI_ERROR_RESPONSES
    )
    async def get_topology(
        topology_id: str,
        revision: Optional[int] = Query(default=None, ge=1),
    ) -> TopologyDTO:
        if topology_port is None:
            raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)
        return topology_port.get(topology_id, revision)

    @router.put(
        "/topologies/{topology_id}", responses=OPENAPI_ERROR_RESPONSES
    )
    async def update_topology(
        topology_id: str,
        request: TopologyCreateRequest | None = None,
    ) -> TopologyDTO:
        # Modify = a new immutable revision row (SPEC-502), never in-place.
        if topology_port is None:
            raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)
        if request is None:
            request = TopologyCreateRequest()
        return topology_port.save_revision(topology_id, request)

    @router.post(
        "/topologies/{topology_id}/validate", responses=OPENAPI_ERROR_RESPONSES
    )
    async def validate_topology(
        topology_id: str,
        revision: Optional[int] = Query(default=None, ge=1),
    ) -> TopologyValidationDTO:
        # SPEC-202 path-addressed structured errors over stored graphs.
        if topology_port is None:
            raise HTTPException(status_code=_501, detail=_TOPOLOGY_DETAIL)
        return topology_port.validate(topology_id, revision)

    return router
