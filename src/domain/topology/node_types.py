"""SPEC-003 §Phase2/§Phase3 — the backend NodeType registry and config schemas.

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

Phase 3 (ticket #160, ADR-0012) adds the RF/SEC trio — ``lnb`` /
``tuner`` / ``diseqc_switch`` (SPEC-003 §Phase3; SPEC-621 §5 /
SPEC-622 §5 / SPEC-623 §5):

- ``LnbConfigDTO`` = ``lnb_kind`` + ``lo_frequencies``
  (:class:`LoFrequenciesDTO`, ``{low_khz, high_khz}``) + optional ``scr``
  (:class:`ScrConfigDTO` = ``protocol`` + ``ub_assignments`` list of
  :class:`UbAssignmentDTO` — the structure is owned by SPEC-623;
  ``legacy_cascade`` must not carry an ``scr`` sub-segment, SPEC-621 §8);
- ``TunerConfigDTO`` = ``tuning_request`` (:class:`TuningRequestDTO`) +
  ``ub_slot`` (optional; the protocol-dependent width upper bound is
  validator rule territory — SIM_TOPO_UB_SLOT_OUT_OF_RANGE) +
  ``diseqc_commands`` (optional structured command intent,
  :class:`DiseqcCommandsDTO`, SPEC-622 §5);
- ``SwitchConfigDTO`` = ``power_pass`` (config passthrough; the power
  domain evaluation belongs to SPEC-621).

Ticket #171 (orchestrator ruling A20) adds the lnb evaluation-time drive
keys (``voltage`` / ``tone_commanded`` / ``tone_actual`` /
``tone_composite`` / ``short_circuit_state``) as first-class optional
:class:`LnbConfigDTO` fields — the scenario-calibration and fault-transform
face becomes part of the declared schema instead of an undeclared
post-validation bypass.

Node ``config`` stays an opaque dict on the wire (``TopologyNodeDTO``);
these Pydantic models are the schema authority the topology validator and
the scenario loader (#128) validate against via
:func:`validate_node_config`.  No Pydantic DTO in ``src/api/dto/`` changes
shape → no OpenAPI/dto:check impact.  The simulation-side consumers
(#161 evaluators) read ``config`` dicts directly and must NOT import this
module (importlinter contract 8) — their mirrored vocabulary is drift-
locked from the tests layer (ruling A1, see
``tests/unit/simulation/state/test_validate.py``).
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
    "DiseqcCommandsDTO",
    "DiseqcNibbleWriteDTO",
    "DiseqcTargetRegisterDTO",
    "LnbConfigDTO",
    "LoFrequenciesDTO",
    "MVP_NODE_TYPES",
    "NODE_CONFIG_INVALID",
    "NODE_TYPE_DISEQC_SWITCH",
    "NODE_TYPE_LNB",
    "NODE_TYPE_T2MI_DEMUX",
    "NODE_TYPE_T2MI_ENCAPSULATOR",
    "NODE_TYPE_TS_DEMUX",
    "NODE_TYPE_TS_GENERATOR",
    "NODE_TYPE_TS_MONITOR",
    "NODE_TYPE_TS_MUX",
    "NODE_TYPE_TUNER",
    "NODE_TYPE_UNKNOWN",
    "NodeTypePortSpec",
    "NodeTypeSpec",
    "PHASE2_NODE_TYPES",
    "PHASE3_NODE_TYPES",
    "PlpAssignmentDTO",
    "PlpAssignmentEntryDTO",
    "PlpFilterConfigDTO",
    "ScrConfigDTO",
    "SwitchConfigDTO",
    "T2miDemuxConfigDTO",
    "T2miEncapsulatorConfigDTO",
    "TunerConfigDTO",
    "TuningRequestDTO",
    "UbAssignmentDTO",
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
NODE_TYPE_LNB = "lnb"
NODE_TYPE_TUNER = "tuner"
NODE_TYPE_DISEQC_SWITCH = "diseqc_switch"

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


# --- Phase 3 config schemas (SPEC-621/622/623 §5, ticket #160) ----------------------


class UbAssignmentDTO(DomainModel):
    """One SCR user-band assignment (SPEC-623 §5 ``UbAssignmentDTO``).

    ``ub_slot``'s protocol-dependent width upper bound (EN 50494 0–7 /
    EN 50607 0–31) is validator rule territory
    (``SIM_TOPO_UB_SLOT_OUT_OF_RANGE``), so the DTO pins ``>= 0`` only.
    """

    tuner_node: str = Field(min_length=1)
    ub_slot: int = Field(ge=0)
    ub_center_freq_mhz: int = Field(ge=1)
    #: EN 50494: ``"A"``/``"B"``; EN 50607: int 0–63.  Cross-checked
    #: against the owning SCR's protocol by :class:`ScrConfigDTO`.
    position: str | int
    #: Optional multihome PIN variant (EN 50494 0x5C / EN 50607 0x71).
    pin: int | None = Field(default=None, ge=0, le=255)
    ub_bandwidth_mhz: int = Field(default=46, ge=1)

    @model_validator(mode="after")
    def _position_vocabulary(self) -> "UbAssignmentDTO":
        if isinstance(self.position, bool) or not isinstance(
            self.position, (str, int)
        ):
            raise ValueError(
                "position must be 'A'/'B' (EN 50494) or int 0..63 "
                "(EN 50607)"
            )
        if isinstance(self.position, str):
            if self.position not in ("A", "B"):
                raise ValueError(
                    f"position {self.position!r} outside the EN 50494 "
                    "vocabulary ('A'/'B')"
                )
        elif not 0 <= self.position <= 63:
            raise ValueError(
                f"position {self.position} outside the EN 50607 domain "
                "(int 0..63)"
            )
        return self


class ScrConfigDTO(DomainModel):
    """The lnb-side SCR sub-segment (SPEC-623 §5 ``ScrConfigDTO``).

    The spec's default user-band frequency group (1210/1420/1680/2040
    MHz) is explicitly non-normative reference data and stays
    spec-document-only — the wire shape is exactly the SC-10 draft's.
    """

    protocol: Literal["EN50494", "EN50607"]
    ub_assignments: list[UbAssignmentDTO]

    @model_validator(mode="after")
    def _assignments_consistency(self) -> "ScrConfigDTO":
        tuner_nodes = [entry.tuner_node for entry in self.ub_assignments]
        if len(tuner_nodes) != len(set(tuner_nodes)):
            raise ValueError(
                "scr.ub_assignments: duplicate tuner_node entries — one "
                "tuner holds at most one user band per SCR (SPEC-623 §5 "
                "tuner→assignment map semantics)"
            )
        if self.protocol == "EN50494":
            for entry in self.ub_assignments:
                if isinstance(entry.position, bool) or not isinstance(
                    entry.position, str
                ):
                    raise ValueError(
                        "scr.ub_assignments: EN 50494 position must be "
                        "'A'/'B'"
                    )
        else:
            for entry in self.ub_assignments:
                if isinstance(entry.position, bool) or not isinstance(
                    entry.position, int
                ):
                    raise ValueError(
                        "scr.ub_assignments: EN 50607 position must be "
                        "int 0..63"
                    )
        return self


class LoFrequenciesDTO(DomainModel):
    """The LNB local-oscillator plan (SPEC-621 §5 ``lo_frequencies``).

    Required on the wire (SPEC-621 §8 lists missing ``lo_frequencies``
    as a prepare rejection); the spec's "universal default
    {9750, 10600}" stays a documented reference default for producer
    tooling, not a DTO default.
    """

    low_khz: int = Field(ge=1)
    high_khz: int = Field(ge=1)


class LnbConfigDTO(DomainModel):
    """``lnb`` node config (SPEC-621 §5; ``scr`` structure = SPEC-623).

    The five evaluation-time drive keys (ticket #171, orchestrator ruling
    A20's SHARED minimal additive) are first-class **optional** config
    fields: ``voltage`` / ``tone_commanded`` / ``tone_actual`` /
    ``tone_composite`` / ``short_circuit_state``.  The L0 evaluators
    (#161) read these keys from ``node.config`` and the fault transform
    TONE_RESIDUE (#163) rewrites ``tone_actual`` — before A20 the keys
    entered "after config validation" as an undeclared bypass; declaring
    them makes the drive face part of the schema authority (键是声明面的
    一部分，非旁路).  Defaults mirror the evaluator's fallback semantics
    (voltage ``off`` / tones ``none`` / absent ``tone_actual`` follows the
    commanded value / short-circuit ``normal`` — an unconfigured LNB
    delivers no carrier); a present key is vocabulary-checked (a foreign
    value is a ``NODE_CONFIG_INVALID`` rejection, not a silent degrade).
    The mirrored key names/vocabularies are drift-locked from the tests
    layer (ruling A20: ``test_evaluator_vocab_drift_lock`` +
    ``TestPhase3VocabularyDriftLock``).
    """

    lnb_kind: Literal["universal", "legacy_cascade"]
    lo_frequencies: LoFrequenciesDTO
    scr: ScrConfigDTO | None = None
    # -- evaluation-time drive keys (ruling A20; SPEC-621 §5 vocabularies) --
    voltage: Literal["off", "13V", "18V"] = "off"
    tone_commanded: Literal["none", "continuous", "tone_burst", "data_burst"] = (
        "none"
    )
    #: ``None`` = absent — the LNB follows its commanded tone (the #161
    #: fallback face); TONE_RESIDUE (#163) rewrites this key.
    tone_actual: (
        Literal["none", "continuous", "tone_burst", "data_burst"] | None
    ) = None
    tone_composite: Literal["none", "continuous_plus_data_burst"] = "none"
    short_circuit_state: Literal[
        "normal", "clamping", "hiccup", "thermal_fault", "fault_latched"
    ] = "normal"

    @model_validator(mode="after")
    def _legacy_cascade_carries_no_scr(self) -> "LnbConfigDTO":
        if self.lnb_kind == "legacy_cascade" and self.scr is not None:
            raise ValueError(
                "lnb: legacy_cascade must not carry an scr sub-segment "
                "(SPEC-621 §8 prepare rejection)"
            )
        return self


class TuningRequestDTO(DomainModel):
    """The tuner tuning intent (SPEC-620 §5 ``tuning_request``)."""

    frequency_khz: int = Field(ge=1)
    polarization: Literal["vertical", "horizontal"]


class DiseqcTargetRegisterDTO(DomainModel):
    """Which command registers the tuner's intent targets (SPEC-622 §5)."""

    committed: bool = False
    uncommitted: bool = False


class DiseqcNibbleWriteDTO(DomainModel):
    """One nibble write of the DiSEqC command intent (SPEC-622 §5).

    ``nibble`` follows the §5/§7 "high nibble clears first, low nibble
    sets" semantics; ``value`` is one 4-bit nibble payload.  The wire key
    is ``register`` (SPEC-622 §5 verbatim); the Python attribute is
    ``register_id`` because the wire name shadows ``ABCMeta.register``
    on the pydantic model base (field alias, wire shape unchanged).
    """

    register_id: Literal["committed", "uncommitted"] = Field(alias="register")
    nibble: Literal["high", "low"]
    value: int = Field(ge=0, le=15)


class DiseqcCommandsDTO(DomainModel):
    """The tuner-side structured DiSEqC command intent (SPEC-622 §5)."""

    target_register: DiseqcTargetRegisterDTO
    nibble_writes: list[DiseqcNibbleWriteDTO] = Field(min_length=1)

    @model_validator(mode="after")
    def _writes_reference_declared_registers(self) -> "DiseqcCommandsDTO":
        for index, write in enumerate(self.nibble_writes):
            declared = (
                write.register_id == "committed"
                and self.target_register.committed
            ) or (
                write.register_id == "uncommitted"
                and self.target_register.uncommitted
            )
            if not declared:
                raise ValueError(
                    f"diseqc_commands: nibble_writes[{index}] references "
                    f"register {write.register_id!r} which target_register "
                    "does not declare (SPEC-622 §8)"
                )
        return self


class TunerConfigDTO(DomainModel):
    """``tuner`` node config (SPEC-620 §5 / SPEC-622 §5 / SPEC-623 §5)."""

    tuning_request: TuningRequestDTO
    ub_slot: int | None = Field(default=None, ge=0)
    diseqc_commands: DiseqcCommandsDTO | None = None


class SwitchConfigDTO(DomainModel):
    """``diseqc_switch`` node config (SPEC-622 §5 ``SwitchConfigDTO``).

    ``power_pass`` is config passthrough — the power-domain evaluation
    belongs to SPEC-621.
    """

    power_pass: Literal["on", "off"]


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

#: The Phase 3 node types (SPEC-003 §Phase3 / ADR-0012, ticket #160; the
#: port templates follow the SC-10 lab-pack draft and SPEC-401 §Phase3 —
#: the frontend mirror is #169's territory):
#:
#: - ``lnb``: a single ``coax_out`` (SEC_CONTROL) with
#:   ``max_connections=2`` — the existing per-port cardinality carries
#:   the A1 dual-tuner shared-coax fan-out (1:N, mechanism
#:   zero-extension);
#: - ``tuner``: a single ``rf_in`` (SEC_CONTROL) with
#:   ``max_connections=1``;
#: - ``diseqc_switch``: the upstream lnb-side ``coax_in`` pins
#:   ``max_connections=1`` ("at most one DC path", SPEC-622 §7); the
#:   downstream ``coax_out`` fans out to tuners (template budget 4,
#:   aligned with the 4-bit committed register space, SPEC-622 §5).
PHASE3_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    NodeTypeSpec(
        node_type=NODE_TYPE_LNB,
        id_prefix="lnb",
        label="LNB",
        ports=(
            NodeTypePortSpec(
                "coax_out", PortDirection.OUTPUT, SignalPlane.SEC_CONTROL, 2
            ),
        ),
        config_model=LnbConfigDTO,
        config_schema_name="LnbConfigDTO",
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_TUNER,
        id_prefix="tuner",
        label="卫星调谐器",
        ports=(
            NodeTypePortSpec(
                "rf_in", PortDirection.INPUT, SignalPlane.SEC_CONTROL, 1
            ),
        ),
        config_model=TunerConfigDTO,
        config_schema_name="TunerConfigDTO",
    ),
    NodeTypeSpec(
        node_type=NODE_TYPE_DISEQC_SWITCH,
        id_prefix="sw",
        label="DiSEqC 开关",
        ports=(
            NodeTypePortSpec(
                "coax_in", PortDirection.INPUT, SignalPlane.SEC_CONTROL, 1
            ),
            NodeTypePortSpec(
                "coax_out", PortDirection.OUTPUT, SignalPlane.SEC_CONTROL, 4
            ),
        ),
        config_model=SwitchConfigDTO,
        config_schema_name="SwitchConfigDTO",
    ),
)

#: The full backend registry (additive union; MVP baseline untouched).
ALL_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    MVP_NODE_TYPES + PHASE2_NODE_TYPES + PHASE3_NODE_TYPES
)


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
