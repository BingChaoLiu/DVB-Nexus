"""Topology-dimension DTOs (SPEC-500 §4.1, ticket #80).

The spec payload mirrors the SPEC-202 §4 state-engine graph contract
field-for-field in snake_case (``simulation.state.graph`` is the frozen
domain shape; the ``domain.topology`` correspondence is drift-guarded by
``tests/unit/simulation/state/test_graph.py``). Vocabulary is pinned as
``Literal`` so a bad direction/plane string is a 400 REQUEST_BODY_INVALID
at the envelope gate (the ``ClockConfigDTO`` Literal precedent) — the
SPEC-202 §5 semantic rule set stays with the validator and the
``POST /topologies/{id}/validate`` report.

Structural per-item gates here (min-length identifiers, ``ports``
min_length=1, ``max_connections`` ≥ 1) keep graph rehydration total: any
spec that entered through POST/PUT constructs a ``TopologyGraph`` without
raising, so the REST face never needs a construction-error code.

``topology_id`` / ``revision`` are server-assigned identity (SPEC-500
§4.1 row 1: "创建拓扑（新 topology_id，revision=1）") — request DTOs do
not carry them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.dto.sessions import TopologyViolationDTO

__all__ = [
    "TopologyConnectionDTO",
    "TopologyCreateRequest",
    "TopologyDTO",
    "TopologyNodeDTO",
    "TopologyPortDTO",
    "TopologySpecDTO",
    "TopologySummaryDTO",
    "TopologyValidationDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class TopologyPortDTO(_StrictDTO):
    """One named port (SPEC-202 §4 ``PortSpec`` mirror)."""

    port_id: str = Field(min_length=1)
    direction: Literal["input", "output", "bidirectional"]
    plane: Literal["RF", "SEC_CONTROL", "MPEG_TS", "T2MI", "IP"]
    max_connections: int | None = Field(default=None, ge=1)


class TopologyNodeDTO(_StrictDTO):
    """One node (SPEC-202 §4 ``NodeConfig`` mirror; ``config`` is opaque)."""

    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    ports: list[TopologyPortDTO] = Field(min_length=1)


class TopologyConnectionDTO(_StrictDTO):
    """One port-level four-tuple link (SPEC-202 §4 ``Connection`` mirror,
    ADR-0005 decision 5)."""

    connection_id: str = Field(min_length=1)
    from_node: str = Field(min_length=1)
    from_port: str = Field(min_length=1)
    to_node: str = Field(min_length=1)
    to_port: str = Field(min_length=1)
    plane: Literal["RF", "SEC_CONTROL", "MPEG_TS", "T2MI", "IP"]


class TopologySpecDTO(_StrictDTO):
    """The SPEC-003 §2.1 configuration model (graph content; identity
    excluded — server-assigned)."""

    nodes: list[TopologyNodeDTO] = Field(default_factory=list)
    connections: list[TopologyConnectionDTO] = Field(default_factory=list)


class TopologyCreateRequest(_StrictDTO):
    """``POST /topologies`` / ``PUT /topologies/{id}`` request body.

    PUT semantics = a NEW immutable revision row (SPEC-502); the revision
    is never client-chosen (防旧配置覆盖 is the server's composite key).
    """

    nodes: list[TopologyNodeDTO] = Field(default_factory=list)
    connections: list[TopologyConnectionDTO] = Field(default_factory=list)


class TopologyDTO(_StrictDTO):
    """The full topology answer (identity + stored spec)."""

    topology_id: str
    revision: int = Field(ge=1)
    nodes: list[TopologyNodeDTO] = Field(default_factory=list)
    connections: list[TopologyConnectionDTO] = Field(default_factory=list)


class TopologySummaryDTO(_StrictDTO):
    """One ``GET /topologies`` row: identity + latest revision."""

    topology_id: str
    revision: int = Field(ge=1)


class TopologyValidationDTO(_StrictDTO):
    """``POST /topologies/{id}/validate`` answer (SPEC-202 §5
    path-addressed report; ok=false reports, session VALIDATING rejects —
    the SPEC-200 §6 posture). Violations reuse the session-dimension
    violation DTO: the same ``{code, path, message}`` triple."""

    ok: bool
    violations: list[TopologyViolationDTO] = Field(default_factory=list)
