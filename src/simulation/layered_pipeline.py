"""ADR-0010 §3 — the layered pipeline instantiation face (ticket #128).

SIM_TS's Phase 2 chain: ``Inner TS → BBFrame → T2MI → 外层 mux`` — each
stage runs "生成 → 本层 fault 过滤器 → 本层封装/传递" (ADR-0010 §3, #108):

1. **TS stage** — the SPEC-108 generator produces the business (inner) TS;
   the MVP-path fault filter (the injected factory over the plan's TS
   group) applies slot-preserving per shared-frame index.
2. **BISS stage** — the scrambler face over the inner TS packets
   (ADR-0011 §2: contribution-order scrambling, before encapsulation).
   Construction features (the scenario-declared key, ADR-0011 §3) and
   fault injection (``BISS_KEY_MISMATCH`` mismatched keys) drive the same
   transform family; only the key source differs — on the faulted leg a
   BISS fault filter *replaces* the construction scrambler (the fault is
   "the stream scrambled under the wrong key").
3. **BBFRAME stage** — ``ts.t2mi.bbframe.build`` wraps the inner UP
   stream; the layer's fault filters transform BBFRAME byte frames at the
   frame index space.
4. **T2MI stage** — ``ts.t2mi.builder.build`` (+ the PLP assignment face)
   wraps the frames into T2-MI packets; the layer's fault filters
   transform packets at the T2-MI packet index space; ``encode_packet``
   concatenation is the transmitted face (外层 mux — the byte stream the
   demux chain consumes: ``ts.t2mi.parser.parse``).

Slot-preserving invariants hold **per layer** (等位替换逐层, SPEC-204
§Phase2): same index, same packet/frame count at every stage of both
legs.  The tee double-write lands at the outermost face (the transmitted
T2-MI stream); middle-layer evidence travels in the per-layer mutation
logs (key material only as fingerprints).

gen.* events (SPEC-303 §Phase2): ``stage_started`` / ``stage_completed``
per executed stage (layer field) + ``packet_sampled`` per the
:class:`StageSampler` window policy — injection-point slots are always
sampled; the magnitude obligation O(层数) + O(抽样) holds by construction.
The chain only *collects* the payloads (deterministic order); delivery
runs on the event-loop side through the guarded
:class:`simulation.events.SimulationEventEmitter` (ruling §10-7 — the
unregistered-type guard skips the Phase 2 namespaces until #129 lands
their registry entries).

Import-contract note: ``simulation`` may import ``ts`` / ``faults`` /
``adapters`` (M3 裁定缝); the ts-side emitter seams stay callable-shaped
(``ts`` never imports ``simulation``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform
from faults.mutation_log import (
    PARAMETERS_SCHEMA_VERSION,
    build_mutation_log_document,
    lifecycle_summary,
    serialize_mutation_log,
)
from ts.biss.biss1 import (
    BatchCipherBackend,
    descramble as biss1_descramble,
    key_fingerprint as biss1_key_fingerprint,
    parse_session_word,
    scramble as biss1_scramble,
)
from ts.biss.cissa import (
    BISS_MODE_1,
    BISS_MODE_E,
    descramble as cissa_descramble,
    scramble as cissa_scramble,
)
from ts.biss.mode_e import (
    derive_ciss_key,
    key_fingerprint as mode_e_key_fingerprint,
    parse_esw,
    parse_injected_id,
)
from ts.generator.config import GeneratorConfig
from ts.generator.generator import TSGenerator
from ts.packet import TSPacket
from ts.t2mi.bbframe import BBFrameBuildConfig, build as build_bbframe, parse as parse_bbframe
from ts.t2mi.bbframe_summary import (
    collect_recovery_failed,
    collect_stage_summary as collect_bbframe_stage_summary,
    emit_recovery_failed,
    emit_stage_summary as emit_bbframe_stage_summary,
)
from ts.t2mi.builder import T2miBuildConfig, build as build_t2mi
from ts.t2mi.inner_ts import InnerTsResult, reconstruct
from ts.t2mi.packet import T2miPacket, encode_packet
from ts.t2mi.parser import parse as parse_t2mi
from ts.t2mi.plp import (
    PlpAssignment,
    PlpFilterConfig,
    assign as assign_plp,
)
from ts.t2mi.summary import (
    collect_stage_summary as collect_t2mi_stage_summary,
    emit_stage_summary as emit_t2mi_stage_summary,
)

__all__ = [
    "BISS_STAGE_LAYER",
    "BBFRAME_STAGE_LAYER",
    "GEN_PACKET_SAMPLED_EVENT_TYPE",
    "GEN_STAGE_COMPLETED_EVENT_TYPE",
    "GEN_STAGE_STARTED_EVENT_TYPE",
    "SAMPLE_WINDOW_DEFAULT",
    "BissFaceConfig",
    "ChainResult",
    "LayerFaultFilter",
    "LayerPipelineConfig",
    "StageSampler",
    "TS_STAGE_LAYER",
    "T2MI_STAGE_LAYER",
    "default_demux_filter_for",
    "is_layered_plan",
    "layered_plan_groups",
    "pipeline_fingerprint_document",
    "run_layered_chain",
]

# --- gen.* event vocabulary (SPEC-303 §Phase2, registry entries = #129) ----------

GEN_STAGE_STARTED_EVENT_TYPE = "gen.stage_started"
GEN_STAGE_COMPLETED_EVENT_TYPE = "gen.stage_completed"
GEN_PACKET_SAMPLED_EVENT_TYPE = "gen.packet_sampled"

# --- stage layers (the SPEC-204 §Phase2 layer set, in chain order) ----------------

#: Contribution TS face (the generator stream; MVP fault path).
TS_STAGE_LAYER = "TS"
#: Scrambler face (ADR-0011 §2) — inner TS packets, before encapsulation.
BISS_STAGE_LAYER = "BISS"
#: BBFRAME byte-frame face (between ``bbframe.build`` and the T2-MI build).
BBFRAME_STAGE_LAYER = "BBFRAME"
#: T2-MI packet face (between the T2-MI build and the transmitted stream).
T2MI_STAGE_LAYER = "T2MI"

#: Execution order: BISS scrambles the contribution TS before the
#: encapsulation stages carry it (contribution order, ADR-0011 §2).
STAGE_ORDER: tuple[str, ...] = (TS_STAGE_LAYER, BISS_STAGE_LAYER, BBFRAME_STAGE_LAYER, T2MI_STAGE_LAYER)

#: Default sampling window: the first N slots of every stage are sampled
#: (plus activation slots and the stage's final slot — see StageSampler).
SAMPLE_WINDOW_DEFAULT = 8

#: Layer registry order shortcut (chain order is canonical for groups).
_LAYER_CHAIN_ORDER = {layer: order for order, layer in enumerate(STAGE_ORDER)}


# --- pipeline configuration -------------------------------------------------------


@dataclass(frozen=True)
class BissFaceConfig:
    """The construction-path BISS face (ADR-0011 §2/§3).

    Declared key material lives here only as run input — it is redacted to
    fingerprints in the fingerprint projection, the mutation log and every
    event payload (SPEC-610 §9: 密钥本体永不落).
    """

    mode: str  # "1" (CSA1 session word) | "E" (CISSA derived key)
    pid_scope: tuple[int, ...]
    session_word: str | None = None  # mode "1": 12 hex
    encrypted_sw: str | None = None  # mode "E": 16 hex
    injected_id: str | None = None  # mode "E": 32 hex

    def __post_init__(self) -> None:
        if self.mode not in (BISS_MODE_1, BISS_MODE_E):
            raise ValueError(
                f"BissFaceConfig mode must be {BISS_MODE_1!r} or "
                f"{BISS_MODE_E!r}, got {self.mode!r} (SPEC-610/611 §5)"
            )
        if not self.pid_scope:
            raise ValueError(
                "BissFaceConfig pid_scope must be a non-empty PID list "
                "(SPEC-610 §5)"
            )
        if self.mode == BISS_MODE_1:
            if self.session_word is None:
                raise ValueError(
                    "BissFaceConfig mode '1' requires session_word (12 hex)"
                )
            if self.encrypted_sw is not None or self.injected_id is not None:
                raise ValueError(
                    "BissFaceConfig mode '1' refuses the Mode E key faces "
                    "(encrypted_sw / injected_id, SPEC-610 §5)"
                )
            parse_session_word(self.session_word)  # format gate (value-free)
        else:
            if self.session_word is not None:
                raise ValueError(
                    "BissFaceConfig mode 'E' refuses session_word "
                    "(SPEC-611 §5)"
                )
            if self.encrypted_sw is None or self.injected_id is None:
                raise ValueError(
                    "BissFaceConfig mode 'E' requires encrypted_sw (16 hex) "
                    "and injected_id (32 hex)"
                )
            parse_esw(self.encrypted_sw)
            parse_injected_id(self.injected_id)

    @property
    def key_fingerprint(self) -> str:
        """The declared key's fingerprint trace (never the key body)."""
        if self.mode == BISS_MODE_1:
            return biss1_key_fingerprint(self.session_word)
        return mode_e_key_fingerprint(
            derive_ciss_key(self.encrypted_sw, self.injected_id)
        )


@dataclass(frozen=True)
class LayerPipelineConfig:
    """The layered chain's construction configuration (prepare-bound).

    ``csa_backend_factory`` is the runtime cipher seam (production: the
    dvbcsa dlopen adapter, lazily; tests: the pure-Python CSA1 oracle) —
    deliberately **excluded** from the fingerprint projection: both
    backends implement the same CSA1 transform, so the choice is not a
    bytes-semantics input.
    """

    bbframe: BBFrameBuildConfig = field(default_factory=BBFrameBuildConfig)
    t2mi: T2miBuildConfig = field(default_factory=T2miBuildConfig)
    plp_assignment: PlpAssignment | None = None
    demux_plp_filter: PlpFilterConfig | None = None
    biss: BissFaceConfig | None = None
    csa_backend_factory: Callable[[], BatchCipherBackend] | None = None

    def _backend(self) -> BatchCipherBackend:
        if self.csa_backend_factory is not None:
            return self.csa_backend_factory()
        from adapters.dvbcsa import load_dvbcsa_backend

        return load_dvbcsa_backend()


def pipeline_fingerprint_document(
    pipeline: "LayerPipelineConfig | None",
) -> dict[str, Any] | None:
    """The additive ``compute_config_hash`` projection for the pipeline.

    ``None`` → ``None`` (the MVP hash document stays byte-identical — the
    existing pins hold).  Key material never enters: the BISS face is
    projected as mode + pid scope + key fingerprint only (ADR-0011 §3).
    """
    if pipeline is None:
        return None
    assignment = None
    if pipeline.plp_assignment is not None:
        assignment = [
            {"plp_id": entry.plp_id, "source_tag": entry.source_tag}
            for entry in pipeline.plp_assignment.entries
        ]
    demux = None
    if pipeline.demux_plp_filter is not None:
        demux = {
            "mode": pipeline.demux_plp_filter.mode,
            "expected_plp": pipeline.demux_plp_filter.expected_plp,
        }
    biss = None
    if pipeline.biss is not None:
        biss = {
            "mode": pipeline.biss.mode,
            "pid_scope": sorted(pipeline.biss.pid_scope),
            "key_fingerprint": pipeline.biss.key_fingerprint,
        }
    return {
        "bbframe": dict(
            matype_value=pipeline.bbframe.matype_value,
            upl=pipeline.bbframe.upl,
            n_ups=pipeline.bbframe.n_ups,
            issy_mode=pipeline.bbframe.issy_mode,
            npd_enabled=pipeline.bbframe.npd_enabled,
        ),
        "t2mi": dict(
            plp_id=pipeline.t2mi.plp_id,
            first_packet_counter=pipeline.t2mi.first_packet_counter,
            first_frame_index=pipeline.t2mi.first_frame_index,
            superframe_index=pipeline.t2mi.superframe_index,
            interleaving_frame_start=pipeline.t2mi.interleaving_frame_start,
            upl_bytes=pipeline.t2mi.upl_bytes,
            inter_frame_padding=pipeline.t2mi.inter_frame_padding,
        ),
        "plp_assignment": assignment,
        "demux_plp_filter": demux,
        "biss": biss,
    }


# --- fault-plan layer routing (SPEC-204 §Phase2) -----------------------------------


def layered_plan_groups(
    plan: Sequence[FaultDefinition],
) -> dict[str, tuple[FaultDefinition, ...]]:
    """Group the plan by declared layer, in pipeline chain order.

    The MVP four (and PMT_PID_DRIFT) all route to ``TS``, so a TS-only
    plan is the single ``{"TS": plan}`` group — the exact MVP path.
    """
    from faults.registry import LAYER_BY_FAULT_TYPE

    grouped: dict[str, list[FaultDefinition]] = {}
    for fault in plan:
        layer = LAYER_BY_FAULT_TYPE.get(fault.fault_type, fault.layer)
        grouped.setdefault(layer, []).append(fault)
    return {
        layer: tuple(grouped[layer])
        for layer in sorted(grouped, key=lambda item: _LAYER_CHAIN_ORDER.get(item, 99))
    }


def is_layered_plan(plan: Sequence[FaultDefinition]) -> bool:
    """True iff any fault routes beyond the TS layer (the MVP path)."""
    return any(layer != TS_STAGE_LAYER for layer in layered_plan_groups(plan))


def default_demux_filter_for(
    plan: Sequence[FaultDefinition],
) -> PlpFilterConfig | None:
    """The demux expectation face a layered run verifies against.

    A ``T2MI_PLP_MISMATCH`` fault declares the receiver's ``expected_plp``
    — the B1 symptom (缺失 ≠ 零) needs the demux to filter on it, so the
    default demux filter derives from the fault when no explicit
    pipeline-level filter is wired.
    """
    for fault in plan:
        if fault.fault_type == "T2MI_PLP_MISMATCH":
            expected = fault.parameters.get("expected_plp")
            if isinstance(expected, int):
                return PlpFilterConfig(mode="expected", expected_plp=expected)
    return None


# --- sampling policy (SPEC-303 §Phase2, 票面裁量) -----------------------------------


class StageSampler:
    """Deterministic sampling-window policy for ``gen.packet_sampled``.

    Sampled slots = the first ``window`` slots of the stage ∪ every
    injection-point (activation) slot ∪ the stage's final slot.  The
    injection points are **always** sampled (票面 hard rule); the bound is
    O(window + activations + 1) per stage → the run's emission magnitude
    stays O(层数) + O(抽样) (#112 closed the per-packet stream).
    """

    def __init__(self, window: int = SAMPLE_WINDOW_DEFAULT) -> None:
        if window < 1:
            raise ValueError(f"sample window must be >= 1, got {window}")
        self._window = window

    def indexes(
        self,
        *,
        item_count: int,
        activation_indexes: Sequence[int] = (),
    ) -> list[int]:
        if item_count <= 0:
            return []
        sampled = set(range(min(self._window, item_count)))
        for index in activation_indexes:
            if 0 <= index < item_count:
                sampled.add(index)
        sampled.add(item_count - 1)
        return sorted(sampled)


# --- per-layer fault filter composition --------------------------------------------


class LayerFaultFilter:
    """One pipeline layer's fault filter instance (SPEC-204 §Phase2).

    Composes the layer's registered transforms (the #121 pluggable
    ``transform_builder_for`` resolution — the filters modules self-
    register at import, activated by the composition root) and produces
    the layer's §8.2 mutation-log document with the additive ``layer``
    key per fault entry.  Slot-preserving per the layer's index space.
    """

    def __init__(
        self,
        layer: str,
        definitions: Sequence[FaultDefinition],
        *,
        run_id: str | None = None,
        backend_factory: "Callable[[], Any] | None" = None,
    ) -> None:
        from faults.factory import transform_builder_for

        self.layer = layer
        self._definitions = tuple(definitions)
        self._run_id = run_id
        self._transforms: list[FaultTransform] = [
            self._build(transform_builder_for(definition.fault_type), definition, backend_factory)
            for definition in self._definitions
        ]

    @staticmethod
    def _build(builder, definition, backend_factory):
        """Build one transform, injecting the CSA backend when the builder
        declares the seam (the scrambler family, ADR-0011 §1 — a wired
        factory surfaces DLL absence at construction, never mid-run)."""
        import inspect

        if backend_factory is None:
            return builder(definition)
        try:
            parameters = inspect.signature(builder).parameters
            accepts_backend = "backend" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):  # C builtins without signatures
            accepts_backend = False
        if accepts_backend:
            return builder(definition, backend=backend_factory())
        return builder(definition)

    @property
    def definitions(self) -> tuple[FaultDefinition, ...]:
        return self._definitions

    def activation_indexes(self) -> list[int]:
        return [transform.activation_index for transform in self._transforms]

    def apply(self, index: int, item: Any) -> Any:
        for transform in self._transforms:
            item = transform.apply(index, item)
        return item

    def mutation_log(self) -> bytes:
        faults = []
        mutations = []
        for definition, transform in zip(self._definitions, self._transforms):
            faults.append(
                {
                    "fault_id": definition.fault_id,
                    "fault_type": definition.fault_type,
                    "layer": definition.layer,
                    "target": {
                        "node_id": transform.target.node_id,
                        "pid": transform.target.pid,
                    },
                    "activation": {
                        "kind": definition.activation.kind,
                        "packet_index": definition.activation.packet_index,
                    },
                    "parameters": self._effective_parameters(definition),
                    "parameters_schema_version": PARAMETERS_SCHEMA_VERSION,
                    "expected_observations": list(definition.expected_observations),
                    "lifecycle": lifecycle_summary(
                        injected=True,
                        activated_packet_index=transform.activation_index,
                        applied_packet_indexes=transform.applied_packet_indexes,
                        cleared=True,
                    ),
                }
            )
            for record in transform.records:
                mutations.append(
                    {
                        "fault_id": record.fault_id,
                        "fault_type": record.fault_type,
                        "layer": definition.layer,
                        "target": {
                            "node_id": record.target_node_id,
                            "pid": record.target_pid,
                        },
                        "packet_index": record.packet_index,
                        "before": dict(record.before),
                        "after": dict(record.after),
                        "change": record.change,
                        "parameters": dict(record.parameters),
                        "parameters_schema_version": record.parameters_schema_version,
                    }
                )
        mutations.sort(key=lambda entry: entry["packet_index"])
        document = build_mutation_log_document(
            tuple(faults), tuple(mutations), run_id=self._run_id
        )
        return serialize_mutation_log(document)

    @staticmethod
    def _effective_parameters(definition: FaultDefinition) -> dict[str, Any]:
        """The evidence-facing parameter snapshot (key bodies redacted).

        The scrambler family redacts its own snapshot internally
        (``faults.filters.scrambler.redact_key_parameters`` and the Mode E
        variant, SPEC-610 §9) — the layer's fault summary must carry the
        SAME redacted view, so it composes the same public helpers (lazy
        import: the filters modules stay bootstrap-activated, never
        forced by this module's import)."""
        parameters = dict(definition.parameters)
        if definition.fault_type != "BISS_KEY_MISMATCH":
            return parameters
        from faults.filters.biss_mode_e import redact_mode_e_key_parameters
        from faults.filters.scrambler import redact_key_parameters

        if ("wrong_esw" in parameters) or ("wrong_injected_id" in parameters):
            return redact_mode_e_key_parameters(parameters)
        return redact_key_parameters(parameters)

    def transform_summaries(self) -> list[dict[str, Any]]:
        """Per-transform observability summaries (fault terminal events).

        ``ScramblerTransform.scramble_summary()`` (BISS — the
        ``biss.scramble_applied`` face) and
        ``T2miPlpMismatchTransform.restamp_summary()`` (T2MI restamp
        statistics) are the upstream-reserved seams (ruling §10-7); the
        runtime composes event payloads from them.
        """
        summaries = []
        for transform in self._transforms:
            if hasattr(transform, "scramble_summary"):
                summaries.append(transform.scramble_summary())
            elif hasattr(transform, "restamp_summary"):
                summaries.append(transform.restamp_summary())
        return summaries


# --- the chain ---------------------------------------------------------------------


@dataclass
class ChainResult:
    """The layered chain's outcome (worker-side, pre-artifact)."""

    tee: bool
    baseline_outer: bytes
    faulted_outer: bytes  # == baseline_outer when no leg pair exists
    stage_counts: dict[str, int]  # executed stage → received-face item count
    events: list[tuple[str, dict[str, Any]]]  # ordered collected emissions
    layer_logs: dict[str, bytes]  # layer → §8.2 document bytes
    biss_scramble_summaries: list[dict[str, Any]]  # fault-path (terminal seam)
    inner_results: dict[str, InnerTsResult]  # leg label → reconstruction
    cancelled: bool = False  # a cancel boundary fired mid-chain (partial faces)


def run_layered_chain(
    *,
    config: GeneratorConfig,
    pipeline: LayerPipelineConfig,
    groups: Mapping[str, tuple[FaultDefinition, ...]],
    ts_filter: Any | None,
    layer_filters: Mapping[str, LayerFaultFilter],
    on_activation: Callable[[FaultDefinition], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    sample_window: int = SAMPLE_WINDOW_DEFAULT,
) -> ChainResult:
    """Execute the layered chain for one run (both legs, all stages).

    Deterministic: same (config, pipeline, plan, filters) → byte-identical
    faces, equal stage counts, equal collected events.  Raises whatever
    the generator/encapsulation/filters raise (the caller maps the failure
    families onto SPEC-203 semantics).  Cancellation is checked at the
    stage boundaries (bounded stages — the §6 item 3 posture at chain
    granularity); a cancelled chain returns its partial faces with
    ``cancelled=True`` and the caller lands them as ``partial`` artifacts.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    def emit(event_type: str, payload: Mapping[str, Any]) -> None:
        events.append((event_type, dict(payload)))

    def cancelled() -> bool:
        return cancel_check is not None and cancel_check()

    tee = bool(groups)
    sampler = StageSampler(sample_window)
    biss_fault_filter = layer_filters.get(BISS_STAGE_LAYER)
    biss_face = pipeline.biss

    # --- stage TS: generate + MVP-path filter (the contribution face) -----
    _stage_started(emit, TS_STAGE_LAYER)
    ts_group = groups.get(TS_STAGE_LAYER, ())
    ts_marks = _stage_marks(ts_group)
    baseline_packets: list[TSPacket] = []
    faulted_packets: list[TSPacket] = []
    mark_cursor = 0
    for index, packet in enumerate(TSGenerator().iter_packets(config)):
        while mark_cursor < len(ts_marks) and ts_marks[mark_cursor][0] <= index:
            if on_activation is not None:
                on_activation(ts_marks[mark_cursor][1])
            mark_cursor += 1
        baseline_packets.append(packet)
        if tee and ts_filter is not None:
            faulted_packets.append(ts_filter.apply(index, packet))
        else:
            faulted_packets.append(packet)
    for index in sampler.indexes(
        item_count=len(faulted_packets),
        activation_indexes=[mark[0] for mark in ts_marks],
    ):
        _emit_packet_sampled(
            emit, TS_STAGE_LAYER, index, faulted_packets[index].to_bytes()
        )
    _stage_completed(emit, TS_STAGE_LAYER, len(faulted_packets))
    stage_counts = {TS_STAGE_LAYER: len(faulted_packets)}
    carry_baseline = b"".join(packet.to_bytes() for packet in baseline_packets)
    carry_faulted = b"".join(packet.to_bytes() for packet in faulted_packets)
    if cancelled():
        return ChainResult(
            tee=tee,
            baseline_outer=carry_baseline,
            faulted_outer=carry_faulted,
            stage_counts=stage_counts,
            events=events,
            layer_logs={},
            biss_scramble_summaries=[],
            inner_results={},
            cancelled=True,
        )

    # --- stage BISS: scrambler face (contribution order) -------------------
    if biss_face is not None or biss_fault_filter is not None:
        _stage_started(emit, BISS_STAGE_LAYER)
        if biss_face is not None:
            # Construction scrambling = the scenario's normal operation on
            # every face; the primitive's reserved hook carries the
            # ``biss.scramble_applied`` payload (mutation_log_ref resolved
            # at delivery).
            baseline_packets = list(
                _scramble_construction(pipeline, baseline_packets, emit)
            )
        if tee and biss_fault_filter is not None:
            # Fault path: the mismatched-key scrambler IS the faulted
            # stream's BISS face (key source = the fault, ADR-0011 §2) —
            # it replaces the construction scrambler on this leg.
            biss_marks = _stage_marks(biss_fault_filter.definitions)
            mark_cursor = 0
            for index, packet in enumerate(faulted_packets):
                while (
                    mark_cursor < len(biss_marks)
                    and biss_marks[mark_cursor][0] <= index
                ):
                    if on_activation is not None:
                        on_activation(biss_marks[mark_cursor][1])
                    mark_cursor += 1
                faulted_packets[index] = biss_fault_filter.apply(index, packet)
        elif tee and biss_face is not None:
            faulted_packets = list(
                _scramble_construction(pipeline, faulted_packets, emit)
            )
        for index in sampler.indexes(
            item_count=len(faulted_packets),
            activation_indexes=(
                [mark[0] for mark in _stage_marks(biss_fault_filter.definitions)]
                if biss_fault_filter is not None
                else ()
            ),
        ):
            _emit_packet_sampled(
                emit, BISS_STAGE_LAYER, index, faulted_packets[index].to_bytes()
            )
        _stage_completed(emit, BISS_STAGE_LAYER, len(faulted_packets))
        stage_counts[BISS_STAGE_LAYER] = len(faulted_packets)
        carry_baseline = b"".join(
            packet.to_bytes() for packet in baseline_packets
        )
        carry_faulted = b"".join(
            packet.to_bytes() for packet in faulted_packets
        )
        if cancelled():
            return ChainResult(
                tee=tee,
                baseline_outer=carry_baseline,
                faulted_outer=carry_faulted,
                stage_counts=stage_counts,
                events=events,
                layer_logs={},
                biss_scramble_summaries=[],
                inner_results={},
                cancelled=True,
            )

    # --- stage BBFRAME: encapsulate + frame-layer filters ------------------
    _stage_started(emit, BBFRAME_STAGE_LAYER)
    bbframe_filter = layer_filters.get(BBFRAME_STAGE_LAYER)
    baseline_frames = _build_bbframes(carry_baseline, pipeline)
    faulted_frames = _build_bbframes(carry_faulted, pipeline)
    if len(baseline_frames) != len(faulted_frames):  # pragma: no cover
        raise AssertionError(
            "等位替换 invariant violated at the BBFRAME stage: baseline and "
            f"faulted legs produced {len(baseline_frames)} vs "
            f"{len(faulted_frames)} frame(s)"
        )
    if bbframe_filter is not None:
        bbframe_marks = _stage_marks(bbframe_filter.definitions)
        mark_cursor = 0
        for index, frame in enumerate(faulted_frames):
            while (
                mark_cursor < len(bbframe_marks)
                and bbframe_marks[mark_cursor][0] <= index
            ):
                if on_activation is not None:
                    on_activation(bbframe_marks[mark_cursor][1])
                mark_cursor += 1
            faulted_frames[index] = bbframe_filter.apply(index, frame)
    for index in sampler.indexes(
        item_count=len(faulted_frames),
        activation_indexes=(
            [mark[0] for mark in _stage_marks(bbframe_filter.definitions)]
            if bbframe_filter is not None
            else ()
        ),
    ):
        _emit_packet_sampled(
            emit, BBFRAME_STAGE_LAYER, index, faulted_frames[index]
        )
    _stage_completed(emit, BBFRAME_STAGE_LAYER, len(faulted_frames))
    stage_counts[BBFRAME_STAGE_LAYER] = len(faulted_frames)
    # The stage summary describes the encapsulator's production face —
    # collected through the ts-side emitter seam (key drift raises).
    emit_bbframe_stage_summary(
        emit,
        collect_bbframe_stage_summary(parse_bbframe(tuple(faulted_frames))),
    )
    carry_baseline = b"".join(baseline_frames)
    carry_faulted = b"".join(faulted_frames)
    if cancelled():
        return ChainResult(
            tee=tee,
            baseline_outer=carry_baseline,
            faulted_outer=carry_faulted,
            stage_counts=stage_counts,
            events=events,
            layer_logs={},
            biss_scramble_summaries=[],
            inner_results={},
            cancelled=True,
        )

    # --- stage T2MI: encapsulate + packet-layer filters → transmitted face -
    _stage_started(emit, T2MI_STAGE_LAYER)
    t2mi_filter = layer_filters.get(T2MI_STAGE_LAYER)
    baseline_t2mi = list(_build_t2mi_packets(tuple(baseline_frames), pipeline))
    faulted_t2mi = list(_build_t2mi_packets(tuple(faulted_frames), pipeline))
    if len(baseline_t2mi) != len(faulted_t2mi):  # pragma: no cover
        raise AssertionError(
            "等位替换 invariant violated at the T2MI stage: baseline and "
            f"faulted legs produced {len(baseline_t2mi)} vs "
            f"{len(faulted_t2mi)} packet(s)"
        )
    if t2mi_filter is not None:
        t2mi_marks = _stage_marks(t2mi_filter.definitions)
        mark_cursor = 0
        for index, packet in enumerate(faulted_t2mi):
            while (
                mark_cursor < len(t2mi_marks)
                and t2mi_marks[mark_cursor][0] <= index
            ):
                if on_activation is not None:
                    on_activation(t2mi_marks[mark_cursor][1])
                mark_cursor += 1
            faulted_t2mi[index] = t2mi_filter.apply(index, packet)
    for index in sampler.indexes(
        item_count=len(faulted_t2mi),
        activation_indexes=(
            [mark[0] for mark in _stage_marks(t2mi_filter.definitions)]
            if t2mi_filter is not None
            else ()
        ),
    ):
        _emit_packet_sampled(
            emit, T2MI_STAGE_LAYER, index, encode_packet(faulted_t2mi[index])
        )
    _stage_completed(emit, T2MI_STAGE_LAYER, len(faulted_t2mi))
    stage_counts[T2MI_STAGE_LAYER] = len(faulted_t2mi)
    emit_t2mi_stage_summary(emit, collect_t2mi_stage_summary(faulted_t2mi))
    baseline_outer = b"".join(encode_packet(packet) for packet in baseline_t2mi)
    faulted_outer = b"".join(encode_packet(packet) for packet in faulted_t2mi)
    if cancelled():
        return ChainResult(
            tee=tee,
            baseline_outer=baseline_outer,
            faulted_outer=faulted_outer,
            stage_counts=stage_counts,
            events=events,
            layer_logs={},
            biss_scramble_summaries=[],
            inner_results={},
            cancelled=True,
        )

    # --- receiver face: the demux chain over the received leg(s) -----------
    demux_filter = pipeline.demux_plp_filter or default_demux_filter_for(
        [fault for group in groups.values() for fault in group]
    )
    received_label = "faulted" if tee else "baseline"
    received_outer = faulted_outer if tee else baseline_outer
    inner_results: dict[str, InnerTsResult] = {}
    if tee:
        inner_results["baseline"] = reconstruct(parse_t2mi(baseline_outer))
    inner_results[received_label] = _receiver_face(
        received_outer,
        demux_filter=demux_filter,
        emit=emit,
        biss_face=biss_face,
        pipeline=pipeline,
    )

    layer_logs = {
        layer: layer_filter.mutation_log()
        for layer, layer_filter in layer_filters.items()
    }
    return ChainResult(
        tee=tee,
        baseline_outer=baseline_outer,
        faulted_outer=faulted_outer,
        stage_counts=stage_counts,
        events=events,
        layer_logs=layer_logs,
        biss_scramble_summaries=(
            biss_fault_filter.transform_summaries()
            if biss_fault_filter is not None
            else []
        ),
        inner_results=inner_results,
    )


# --- chain internals ---------------------------------------------------------------


def _stage_started(emit, layer: str) -> None:
    emit(GEN_STAGE_STARTED_EVENT_TYPE, {"layer": layer})


def _stage_completed(emit, layer: str, item_count: int) -> None:
    emit(
        GEN_STAGE_COMPLETED_EVENT_TYPE,
        {"layer": layer, "item_count": item_count},
    )


def _emit_packet_sampled(
    emit, layer: str, index: int, slot_bytes: bytes
) -> None:
    emit(
        GEN_PACKET_SAMPLED_EVENT_TYPE,
        {
            "layer": layer,
            "packet_index": index,
            "byte_size": len(slot_bytes),
            "sha256": hashlib.sha256(slot_bytes).hexdigest(),
        },
    )


def _stage_marks(
    definitions: Sequence[FaultDefinition],
) -> list[tuple[int, FaultDefinition]]:
    """(activation index, fault) in shared-stage order (ADR-0007 item 3)."""
    marks = [
        (
            (
                0
                if fault.activation.kind == "session_start"
                else fault.activation.packet_index or 0
            ),
            fault,
        )
        for fault in definitions
    ]
    return sorted(marks, key=lambda mark: mark[0])


def _build_bbframes(up_stream: bytes, pipeline: LayerPipelineConfig) -> list[bytes]:
    if not up_stream:
        return []
    return list(build_bbframe(up_stream, pipeline.bbframe))


def _build_t2mi_packets(
    frames: Sequence[bytes], pipeline: LayerPipelineConfig
) -> tuple[T2miPacket, ...]:
    if pipeline.plp_assignment is not None:
        first = pipeline.plp_assignment.entries[0]
        return assign_plp({first.source_tag: tuple(frames)}, pipeline.plp_assignment, pipeline.t2mi)
    if not frames:
        return ()
    return build_t2mi(tuple(frames), pipeline.t2mi)


def _scramble_construction(
    pipeline: LayerPipelineConfig,
    packets: Sequence[TSPacket],
    emit,
) -> tuple[TSPacket, ...]:
    """The construction-path scramble (scenario-declared key, ADR-0011 §3)."""
    if pipeline.biss is None or not packets:
        return tuple(packets)
    face = pipeline.biss
    # The biss primitive hooks take the payload dict alone (the event
    # type is fixed by the seam); the chain's collector takes
    # (event_type, payload) — adapt here.  The ``mode`` field enters at
    # this composition point (#128 owns the final payload shape; the
    # biss1 primitive payload predates the #127 field and stays frozen).
    applied = lambda payload: emit(  # noqa: E731
        "biss.scramble_applied", {**dict(payload), "mode": face.mode}
    )
    if face.mode == BISS_MODE_1:
        resolved = pipeline._backend()
        return biss1_scramble(
            packets,
            face.session_word,
            face.pid_scope,
            backend=resolved,
            on_scramble_applied=applied,
        )
    ciss_key = derive_ciss_key(face.encrypted_sw, face.injected_id)
    return cissa_scramble(
        packets,
        ciss_key,
        face.pid_scope,
        mode=BISS_MODE_E,
        on_scramble_applied=applied,
    )


def _receiver_face(
    outer: bytes,
    *,
    demux_filter: PlpFilterConfig | None,
    emit,
    biss_face: BissFaceConfig | None,
    pipeline: LayerPipelineConfig,
) -> InnerTsResult:
    """The demux chain over one received face (parse → recovery → reconstruct
    → descramble self-check), emitting the receiver-side candidate payloads."""
    parsed = parse_t2mi(outer)
    frame_blobs = [
        packet.bbframe for packet in parsed if packet.bbframe is not None
    ]
    if frame_blobs:
        recovery = collect_recovery_failed(parse_bbframe(frame_blobs))
        if recovery["failure_count"] > 0:
            emit_recovery_failed(emit, recovery)
    result = reconstruct(parsed, demux_filter, emitter=emit)
    if biss_face is not None and result.inner_ts:
        _descramble_face(
            result.inner_ts,
            biss_face=biss_face,
            pipeline=pipeline,
            emit=emit,
        )
    return result


def _descramble_face(
    inner_ts: bytes,
    *,
    biss_face: BissFaceConfig,
    pipeline: LayerPipelineConfig,
    emit,
) -> None:
    """Descramble the reconstructed inner TS with the DECLARED key.

    解扰失败 ≠ 码流损坏 (ADR-0011 §4): structural self-check failures are
    the candidate evidence, collected through the reserved hook and
    delivered by the runtime.
    """
    packets = [
        TSPacket.from_bytes(inner_ts[offset : offset + 188])
        for offset in range(0, len(inner_ts) - len(inner_ts) % 188, 188)
    ]
    # The biss primitive hooks take the payload dict alone; biss1's
    # payload predates the #127 ``mode`` field, so Mode 1 composes it here
    # (#128 owns the final payload shape).
    failed = lambda payload: emit("biss.descramble_failed", dict(payload))  # noqa: E731
    if biss_face.mode == BISS_MODE_1:
        resolved = pipeline._backend()

        def on_failed_mode1(payload: Mapping[str, Any]) -> None:
            failed({**dict(payload), "mode": BISS_MODE_1})

        biss1_descramble(
            packets,
            biss_face.session_word,
            biss_face.pid_scope,
            backend=resolved,
            on_descramble_failed=on_failed_mode1,
        )
        return
    ciss_key = derive_ciss_key(biss_face.encrypted_sw, biss_face.injected_id)
    cissa_descramble(
        packets,
        ciss_key,
        biss_face.pid_scope,
        mode=BISS_MODE_E,
        on_descramble_failed=failed,
    )
