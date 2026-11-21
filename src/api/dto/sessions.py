"""Session-dimension DTOs (SPEC-500 §4.2, ticket #48).

``POST /sessions`` body per the §4.2 row: ``topology_id`` + revision, seed,
``clock_config``, ``resource_limits``, optional ``scenario_id``. Clock
fields mirror SPEC-201 §4 ``SimulationClockConfig``; resource-limit fields
mirror the SPEC-200 §4 ``ResourceLimits`` shape (all optional — the value
ranges are pinned by OPEN-006/#16, so the DTO stays permissive and the
backend owns the semantic checks).

Response DTOs mirror the SPEC-200 §4 view shapes (``SessionView`` /
``SimulationSnapshot`` / SPEC-202 §5 ``TopologyViolation``) with the wire
vocabulary kept identical to the domain enums' string values (lifecycle
states are the SPEC-200 §5 nine-state table verbatim).

``journal_seq_cursor`` appears only as a snapshot **echo** (SPEC-200 §4
pull API): request DTOs never carry ``journal_seq`` (SPEC-500 §5 —
producers never fill it, ADR-0006 item 2).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ArtifactRefDTO",
    "ClockConfigDTO",
    "ConnectionDTO",
    "CreateSessionRequest",
    "FaultRefDTO",
    "NodeStateDTO",
    "PortStateDTO",
    "ResourceLimitsDTO",
    "SessionDetailDTO",
    "SessionListItemDTO",
    "SessionValidationDTO",
    "SnapshotDTO",
    "TopologyViolationDTO",
    "SessionViewDTO",
]


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation (400)."""

    model_config = ConfigDict(extra="forbid")


class ClockConfigDTO(_StrictDTO):
    """SPEC-201 §4 ``SimulationClockConfig`` (exact field set)."""

    mode: Literal["deterministic", "realtime"] = "deterministic"
    start_time_ns: int = Field(default=0, ge=0)
    speed_num: int = Field(default=1, ge=1)
    speed_den: int = Field(default=1, ge=1)
    tick_quantum_ns: int = Field(default=1_000_000, ge=1)


class ResourceLimitsDTO(_StrictDTO):
    """SPEC-200 §4 ``ResourceLimits`` (optional caps; ranges随 OPEN-006)."""

    bitrate_bps: int | None = Field(default=None, ge=1)
    memory_bytes: int | None = Field(default=None, ge=1)
    duration_ns: int | None = Field(default=None, ge=1)


class CreateSessionRequest(_StrictDTO):
    """``POST /sessions`` request body (SPEC-500 §4.2 row 1)."""

    topology_id: str
    topology_revision: int = Field(default=1, ge=1)
    seed: int = Field(ge=0)
    deterministic: bool = True
    clock_config: ClockConfigDTO = Field(default_factory=ClockConfigDTO)
    resource_limits: ResourceLimitsDTO | None = None
    scenario_id: str | None = None


class PortStateDTO(_StrictDTO):
    """One evaluated port state (SPEC-202 §6.1 / SPEC-003 §3)."""

    port_id: str
    health: str


class NodeStateDTO(_StrictDTO):
    """One node's snapshot-facing state (SPEC-003 §3 vocabulary)."""

    node_id: str
    health: str
    ports: list[PortStateDTO] = Field(default_factory=list)


class FaultRefDTO(_StrictDTO):
    """Active-fault reference (identity + state only; SPEC-204 seam)."""

    fault_id: str
    state: str


class ArtifactRefDTO(_StrictDTO):
    """Latest-artifact reference (identity only — #42/#43 seam)."""

    artifact_id: str
    kind: str
    status: str


class ConnectionDTO(_StrictDTO):
    """One connection's identity inside a snapshot (read-only mirror)."""

    connection_id: str
    from_node: str
    from_port: str
    to_node: str
    to_port: str


class SessionViewDTO(_StrictDTO):
    """The per-command session answer (SPEC-200 §4 ``SessionView``)."""

    session_id: str
    revision: int
    lifecycle: str
    virtual_time_ns: int
    topology_revision: int
    node_states: dict[str, NodeStateDTO] = Field(default_factory=dict)
    active_faults: list[FaultRefDTO] = Field(default_factory=list)
    latest_artifact_refs: list[ArtifactRefDTO] = Field(default_factory=list)
    #: The initial L0 evaluation's whole-graph aggregate (ticket #165,
    #: ADR-0012 decision 5 — the snapshot health-display data source is
    #: the TopologyEvalResult product; ``None`` when the composition
    #: layer has no evaluation record).
    graph_health: str | None = None


class SessionListItemDTO(_StrictDTO):
    """One ``GET /sessions`` row (SPEC-408 §6.1, ticket #94).

    The list answers newest-first (``created_at`` DESC, default limit 20,
    hard cap 100, no pagination). ``created_at_ms`` is newly collected
    wall clock — the runtime session spec carries none, so the composition
    layer records it at creation (bootstrap-level metadata, the frozen
    ``SimulationSessionSpec`` stays untouched). ``scenario_id`` closes the
    write-only provenance gap for the list annotation face.
    """

    session_id: str
    lifecycle: str
    created_at_ms: int
    scenario_id: str | None = None
    topology_revision: int


class SessionDetailDTO(SessionViewDTO):
    """``GET /sessions/{id}`` — the SPEC-408 §6.2 detail read-back
    (ticket #94): the existing ``SessionViewDTO`` wire shape additively
    extended with the provenance pair. ``scenario_id`` was write-only
    before (consumed at create, then dropped — the structural root of
    "data with unknown provenance"); ``created_at_ms`` is the wall clock
    at session creation, recorded by the composition layer."""

    scenario_id: str | None = None
    created_at_ms: int


class SnapshotDTO(SessionViewDTO):
    """Full replacement view + ``journal_seq_cursor`` echo (SPEC-200 §4).

    The cursor echoes the client-supplied pull cursor verbatim (``None``
    when the request omitted it) — it is never server-authored here.
    """

    connection_states: list[ConnectionDTO] = Field(default_factory=list)
    journal_seq_cursor: int | None = Field(default=None, ge=0)


class TopologyViolationDTO(_StrictDTO):
    """One path-addressed rejection (SPEC-202 §5: code + path + message)."""

    code: str
    path: str
    message: str


class SessionValidationDTO(_StrictDTO):
    """``POST /sessions/{id}/validate`` answer (SPEC-200 §6 report)."""

    ok: bool
    violations: list[TopologyViolationDTO] = Field(default_factory=list)
