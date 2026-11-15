"""Topology composition adapters (ticket #80, SPEC-502 §4/§5 × SPEC-500
§4.1).

Three faces, all composition-root concerns (they translate between the
storage rows / domain graphs and the api DTOs — the api layer never
imports ``simulation`` or ``adapters``, import-linter C6):

- :func:`wire_to_spec_payload` / :func:`spec_payload_to_wire` — the wire
  DTO view ↔ the stored ``spec_json`` TEXT (the stored payload keeps the
  identity-free content view the REST face posts, keyed ``nodes`` /
  ``connections``);
- :func:`graph_from_spec_payload` — payload → ``TopologyGraph`` (the
  provider/validate rehydration; DTO gates make this total for anything
  that entered through POST/PUT, so construction never raises on stored
  rows);
- :class:`RepositoryTopologyPort` — the ``TopologyPort`` backend over
  :class:`~adapters.storage.topologies.SqliteTopologyRepository` (create /
  list / get / save_revision / validate);
- :class:`RepositoryTopologyProvider` — the session topology resolver:
  saved rows resolve to the EXACT ``(topology_id, revision)`` graph
  (revision pinning, SPEC-502 §4 topologyRevision 防旧配置覆盖); a miss
  falls back to ``default_topology_provider`` (the MVP ``topo-1`` posture
  and its ``SIM_TOPOLOGY_NOT_FOUND`` semantics, byte-for-byte preserved).
"""

from __future__ import annotations

import json
import uuid
from typing import Callable, Optional

from simulation.state import (
    Connection,
    NodeConfig,
    PortSpec,
    TopologyGraph,
    validate_topology,
)

from adapters.storage.topologies import TopologyRepository

from api.dto.sessions import TopologyViolationDTO
from api.dto.topologies import (
    TopologyCreateRequest,
    TopologyDTO,
    TopologySummaryDTO,
    TopologyValidationDTO,
)
from application.errors import NotFoundError

__all__ = [
    "RepositoryTopologyPort",
    "RepositoryTopologyProvider",
    "graph_from_spec_payload",
    "spec_payload_to_wire",
    "wire_to_spec_payload",
]

_TOPOLOGY_NOT_FOUND_DETAIL = (
    "unknown topology {topology_id!r} (revision {revision!r}): no stored"
    " row and the MVP registry carries only 'topo-1'"
)


# --- payload ↔ wire (stored spec_json identity-free content view) ---------------


def wire_to_spec_payload(request: TopologyCreateRequest) -> str:
    """Wire DTO → the stored ``spec_json`` TEXT (content view verbatim)."""
    return json.dumps(request.model_dump(), ensure_ascii=False)


def spec_payload_to_wire(payload: str) -> dict:
    """Stored ``spec_json`` TEXT → the content mapping (DTO revalidation
    happened at the route boundary; here it is plain JSON)."""
    return json.loads(payload)


# --- payload → domain graph (provider/validate rehydration) ----------------------


def graph_from_spec_payload(
    payload: str, *, topology_id: str, revision: int
) -> TopologyGraph:
    """Stored spec payload → the SPEC-202 §4 graph contract.

    Total for anything that entered through the REST face: the DTO gates
    (Literal direction/plane, min-length ids, ``ports`` min_length=1,
    ``max_connections`` ≥ 1) are exactly the construction guards, so no
    construction error can reach this function from stored rows.
    """
    content = spec_payload_to_wire(payload)
    nodes = [
        NodeConfig(
            node_id=node["node_id"],
            node_type=node["node_type"],
            config=dict(node.get("config") or {}),
            ports=[
                PortSpec(
                    port_id=port["port_id"],
                    direction=port["direction"],
                    plane=port["plane"],
                    max_connections=port.get("max_connections"),
                )
                for port in node.get("ports", ())
            ],
        )
        for node in content.get("nodes", ())
    ]
    connections = [
        Connection(
            connection_id=connection["connection_id"],
            from_node=connection["from_node"],
            from_port=connection["from_port"],
            to_node=connection["to_node"],
            to_port=connection["to_port"],
            plane=connection["plane"],
        )
        for connection in content.get("connections", ())
    ]
    return TopologyGraph(
        topology_id=topology_id,
        revision=revision,
        nodes=nodes,
        connections=connections,
    )


# --- the §4.1 port backend --------------------------------------------------------


class RepositoryTopologyPort:
    """``TopologyPort`` over the SPEC-502 topologies table."""

    def __init__(self, repository: TopologyRepository) -> None:
        self._repository = repository

    def create(self, request: TopologyCreateRequest) -> TopologyDTO:
        topology_id = str(uuid.uuid4())
        return self._save_row(topology_id, 1, request)

    def save_revision(
        self, topology_id: str, request: TopologyCreateRequest
    ) -> TopologyDTO:
        latest = self._repository.get(topology_id)
        if latest is None:
            raise NotFoundError(
                "SIM_TOPOLOGY_NOT_FOUND",
                f"unknown topology {topology_id!r}: no stored row to append"
                " a revision to (SPEC-502 §4)",
            )
        return self._save_row(topology_id, latest.revision + 1, request)

    def list_topologies(self, *, limit: int) -> list[TopologySummaryDTO]:
        rows = self._repository.list_latest()[:limit]
        return [
            TopologySummaryDTO(topology_id=row.topology_id, revision=row.revision)
            for row in rows
        ]

    def get(self, topology_id: str, revision: Optional[int]) -> TopologyDTO:
        row = self._repository.get(topology_id, revision)
        if row is None:
            raise NotFoundError(
                "SIM_TOPOLOGY_NOT_FOUND",
                _TOPOLOGY_NOT_FOUND_DETAIL.format(
                    topology_id=topology_id, revision=revision
                ),
            )
        content = spec_payload_to_wire(row.spec_json)
        return TopologyDTO(
            topology_id=row.topology_id,
            revision=row.revision,
            nodes=content.get("nodes", []),
            connections=content.get("connections", []),
        )

    def validate(
        self, topology_id: str, revision: Optional[int]
    ) -> TopologyValidationDTO:
        row = self._repository.get(topology_id, revision)
        if row is None:
            raise NotFoundError(
                "SIM_TOPOLOGY_NOT_FOUND",
                _TOPOLOGY_NOT_FOUND_DETAIL.format(
                    topology_id=topology_id, revision=revision
                ),
            )
        graph = graph_from_spec_payload(
            row.spec_json, topology_id=row.topology_id, revision=row.revision
        )
        violations = [
            TopologyViolationDTO(
                code=str(violation.code),
                path=str(violation.path),
                message=str(violation.message),
            )
            for violation in validate_topology(graph)
        ]
        return TopologyValidationDTO(ok=not violations, violations=violations)

    def _save_row(
        self, topology_id: str, revision: int, request: TopologyCreateRequest
    ) -> TopologyDTO:
        self._repository.save(
            topology_id, revision, wire_to_spec_payload(request)
        )
        return TopologyDTO(
            topology_id=topology_id,
            revision=revision,
            nodes=request.nodes,
            connections=request.connections,
        )


# --- the session topology provider -------------------------------------------------


class RepositoryTopologyProvider:
    """Session topology resolver over the SPEC-502 table (the provider
    upgrade, ticket #80 scope item 1).

    Saved rows resolve to the EXACT ``(topology_id, revision)`` graph —
    revision pinning (a later PUT never re-binds a live session). A miss
    falls through to ``fallback`` (the MVP ``topo-1`` empty-graph posture
    and its ``SIM_TOPOLOGY_NOT_FOUND`` semantics, preserved verbatim).
    """

    def __init__(
        self,
        repository: TopologyRepository,
        fallback: Callable[[str, int], TopologyGraph] | None = None,
    ) -> None:
        self._repository = repository
        self._fallback = fallback

    def __call__(self, topology_id: str, revision: int) -> TopologyGraph:
        row = self._repository.get(topology_id, revision)
        if row is not None:
            return graph_from_spec_payload(
                row.spec_json, topology_id=row.topology_id, revision=row.revision
            )
        if self._fallback is not None:
            return self._fallback(topology_id, revision)
        raise NotFoundError(
            "SIM_TOPOLOGY_NOT_FOUND",
            _TOPOLOGY_NOT_FOUND_DETAIL.format(
                topology_id=topology_id, revision=revision
            ),
        )
