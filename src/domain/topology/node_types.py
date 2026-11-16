"""SPEC-003 §Phase2 — the backend NodeType registry and config schemas.

Phase 2 (ticket #121, ADR-0010 §3) adds ``t2mi_encapsulator`` and
``t2mi_demux`` to the node type registry — the single declaration point
for backend node types (the frontend mirror lives in
``frontend/src/features/topologies/nodeTypes.ts`` and is owned by #135).

Config schemas (wire snake_case, SPEC-600 §5 / SPEC-601 §5 /
SPEC-602 §5):

- ``T2miEncapsulatorConfigDTO`` = ``plp_assignment``
  (:class:`PlpAssignmentDTO`, SPEC-602 ``entries: [{plp_id, source_tag}]``)
  + ``bbframe_params`` (:class:`BBFrameBuildParamsDTO`, SPEC-601
  ``matype_value / upl / n_ups / issy_mode / npd_enabled``);
- ``T2miDemuxConfigDTO`` = ``plp_filter`` (:class:`PlpFilterConfigDTO`,
  SPEC-602 ``mode: expected | all`` + ``expected_plp``) + ``strict_crc``
  (SPEC-600 §5 demux config content ``expected_plp / plp_mode /
  strict_crc`` — the ``plp_filter.mode`` subsection carries the
  ``plp_mode`` semantics, see the #121 report's interface list).

Node ``config`` stays an opaque dict on the wire (``TopologyNodeDTO``);
these Pydantic models are the schema authority the topology validator and
the scenario loader (#128) validate against via
:func:`validate_node_config`.  No Pydantic DTO in ``src/api/dto/`` changes
shape → no OpenAPI/dto:check impact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from domain._base import DomainModel
from domain.topology.model import PortDirection, SignalPlane

__all__ = [
    "ALL_NODE_TYPES",
    "BBFrameBuildParamsDTO",
    "MVP_NODE_TYPES",
    "NODE_CONFIG_INVALID",
    "NODE_TYPE_T2MI_DEMUX",
    "NODE_TYPE_T2MI_ENCAPSULATOR",
    "NODE_TYPE_TS_DEMUX",
    "NODE_TYPE_TS_GENERATOR",
    "NODE_TYPE_TS_MONITOR",
    "NODE_TYPE_TS_MUX",
    "NODE_TYPE_UNKNOWN",
    "NodeTypePortSpec",
    "NodeTypeSpec",
    "PHASE2_NODE_TYPES",
    "PlpAssignmentDTO",
    "PlpAssignmentEntryDTO",
    "PlpFilterConfigDTO",
    "T2miDemuxConfigDTO",
    "T2miEncapsulatorConfigDTO",
    "get_node_type",
    "validate_node_config",
]

# --- node_type wire strings --------------------------------------------------------

NODE_TYPE_TS_GENERATOR = "ts_generator"
NODE_TYPE_TS_MUX = "ts_mux"
NODE_TYPE_TS_DEMUX = "ts_demux"
NODE_TYPE_TS_MONITOR = "ts_monitor"
NODE_TYPE_T2MI_ENCAPSULATOR = "t2mi_encapsulator"
NODE_TYPE_T2MI_DEMUX = "t2mi_demux"

# --- T2-MI config schemas (SPEC-600/601/602 §5) -------------------------------------


class PlpAssignmentEntryDTO(DomainModel):
    """One PLP assignment entry (SPEC-602 §5): business tag → PLP ID."""

    plp_id: int = Field(ge=0, le=0xFF)  # 8-bit PLP_ID value domain
    source_tag: str = Field(min_length=1)


class PlpAssignmentDTO(DomainModel):
    """The encapsulator-side assignment table (SPEC-602 §5)."""

    entries: list[PlpAssignmentEntryDTO] = Field(min_length=1)

    @model_validator(mode="after")
    def _entries_must_not_conflict(self) -> "PlpAssignmentDTO":
        tags = [entry.source_tag for entry in self.entries]
        if len(tags) != len(set(tags)):
            raise ValueError(
                "plp_assignment: duplicate source_tag entries — one "
                "business source may map to at most one PLP (SPEC-602 §8 "
                "assignment-table conflict)"
            )
        plp_ids = [entry.plp_id for entry in self.entries]
        if len(plp_ids) != len(set(plp_ids)):
            raise ValueError(
                "plp_assignment: duplicate plp_id entries (SPEC-602 §8)"
            )
        return self


class BBFrameBuildParamsDTO(DomainModel):
    """BBFrame build parameters (SPEC-601 §5 ``BBFrameBuildConfigDTO``).

    Value domains beyond the field widths stay with #123's implementation
    spec (ISSY mode vocabulary is pinned progressively with golden);
    this schema pins the wire keys and the field-width bounds only.
    """

    matype_value: int = Field(ge=0, le=0xFFFF)  # MATYPE: 16-bit field
    upl: int = Field(ge=1)  # UPL: user packet length (bits)
    n_ups: int = Field(ge=1)  # N_UPS: UPs per BBFrame (≥ 1)
    issy_mode: str = Field(min_length=1)
    npd_enabled: bool


class T2miEncapsulatorConfigDTO(DomainModel):
    """``t2mi_encapsulator`` node config (SPEC-600 §5)."""

    plp_assignment: PlpAssignmentDTO
    bbframe_params: BBFrameBuildParamsDTO


class PlpFilterConfigDTO(DomainModel):
    """The demux-side PLP filter (SPEC-602 §5)."""

    mode: Literal["expected", "all"]
    expected_plp: int | None = Field(default=None, ge=0, le=0xFF)

    @model_validator(mode="after")
    def _expected_mode_needs_a_plp(self) -> "PlpFilterConfigDTO":
        if self.mode == "expected" and self.expected_plp is None:
            raise ValueError(
                "plp_filter: mode 'expected' requires expected_plp "
                "(SPEC-602 §5)"
            )
        return self


class T2miDemuxConfigDTO(DomainModel):
    """``t2mi_demux`` node config (SPEC-600 §5)."""

    plp_filter: PlpFilterConfigDTO
    strict_crc: bool = True


# --- the registry -------------------------------------------------------------------


@dataclass(frozen=True)
class NodeTypePortSpec:
    """One default port of a node type (SPEC-401 §Phase2 table)."""

    port_id: str
    direction: PortDirection
    plane: SignalPlane
    max_connections: int


@dataclass(frozen=True)
class NodeTypeSpec:
    """One registry entry: wire string, slug prefix, ports, config schema."""

    node_type: str
    id_prefix: str
    label: str
    ports: tuple[NodeTypePortSpec, ...]
    config_model: type | None = None
    config_schema_name: str | None = None


#: The four MVP node types (MVP registry; config opaque except the
#: generator's ``GeneratorConfigDTO`` pointer, mirrored from the
#: frontend registry — the model itself lives in ``ts.generator``).
MVP_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    NodeTypeSpec(
        node_type=NODE_TYPE_TS_GENERATOR,
        id_prefix="gen",
        label="TS 生成器",
        ports=(NodeTypePortSpec("ts_out", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),),
        config_model=None,
        config_schema_name="GeneratorConfigDTO",
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_TS_MUX,
        id_prefix="mux",
        label="TS 复用器",
        ports=(
            NodeTypePortSpec("ts_in_1", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),
            NodeTypePortSpec("ts_in_2", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),
            NodeTypePortSpec("ts_out", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),
        ),
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_TS_DEMUX,
        id_prefix="demux",
        label="TS 解复用器",
        ports=(
            NodeTypePortSpec("ts_in", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),
            NodeTypePortSpec("ts_out_1", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),
            NodeTypePortSpec("ts_out_2", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),
        ),
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_TS_MONITOR,
        id_prefix="mon",
        label="TS 监测器",
        ports=(NodeTypePortSpec("ts_in", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),),
    ),
)

#: The Phase 2 node types (SPEC-003 §Phase2 / ADR-0010 §3; SPEC-401
#: §Phase2 table pins the port templates the frontend mirror reuses).
PHASE2_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    NodeTypeSpec(
        node_type=NODE_TYPE_T2MI_ENCAPSULATOR,
        id_prefix="enc",
        label="T2-MI 封装器",
        ports=(
            NodeTypePortSpec("inner_in", PortDirection.INPUT, SignalPlane.MPEG_TS, 1),
            NodeTypePortSpec("t2mi_out", PortDirection.OUTPUT, SignalPlane.T2MI, 1),
        ),
        config_model=T2miEncapsulatorConfigDTO,
        config_schema_name="T2miEncapsulatorConfigDTO",
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_T2MI_DEMUX,
        id_prefix="dmx",
        label="T2-MI 解封装器",
        ports=(
            NodeTypePortSpec("t2mi_in", PortDirection.INPUT, SignalPlane.T2MI, 1),
            NodeTypePortSpec("inner_out", PortDirection.OUTPUT, SignalPlane.MPEG_TS, 1),
        ),
        config_model=T2miDemuxConfigDTO,
        config_schema_name="T2miDemuxConfigDTO",
    ),
)

#: The full backend registry (additive union; MVP baseline untouched).
ALL_NODE_TYPES: tuple[NodeTypeSpec, ...] = MVP_NODE_TYPES + PHASE2_NODE_TYPES


def get_node_type(node_type: str) -> NodeTypeSpec | None:
    """Registry lookup by the authoritative wire string."""
    for spec in ALL_NODE_TYPES:
        if spec.node_type == node_type:
            return spec
    return None


NODE_TYPE_UNKNOWN = "NODE_TYPE_UNKNOWN"
NODE_CONFIG_INVALID = "NODE_CONFIG_INVALID"


def validate_node_config(node_type: str, config: dict) -> tuple[str, ...]:
    """Validate one node's ``config`` dict against its registry schema.

    Returns detail strings (empty tuple = valid): a single
    ``NODE_TYPE_UNKNOWN`` detail for an unregistered node_type, or one
    ``NODE_CONFIG_INVALID`` detail per schema error.  Pure: no I/O, no
    exceptions escape, no wall clock.
    """
    spec = get_node_type(node_type)
    if spec is None:
        return (
            f"{NODE_TYPE_UNKNOWN}: node_type {node_type!r} is not in the "
            "backend registry (SPEC-003 §6)",
        )
    if spec.config_model is None:
        # MVP opaque-config types (mux/demux/monitor) and the generator
        # (schema owned by ts.generator) accept any dict here; deeper
        # validation stays with their owning validators.
        return ()
    try:
        spec.config_model.model_validate(config)
    except ValidationError as error:
        return tuple(
            f"{NODE_CONFIG_INVALID}: "
            f"{'.'.join(str(loc) for loc in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    return ()
