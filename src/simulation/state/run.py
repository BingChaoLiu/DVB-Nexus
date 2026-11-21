"""SIM_STATE Run orchestration (ticket #165 — ADR-0012 decisions 2/5/6).

The state-domain run form as a first-class citizen beside
``simulation.ts_runtime.TSRuntime`` (the SIM_TS form).  The lifecycle
mirrors the SPEC-203 §4 shape:

- :func:`prepare_state_run` — ``prepare(session, fault_plan=())``:
  the gate chain (topology gate → bidirectional mixed-plan gate →
  state-layer prepare checks → per-fault registry validation), the A15
  intent-bridge assembly, the **L0 baseline evaluation trigger**
  (decision 6: 求值触发点 = Run prepare) and the deterministic state
  fingerprint (§5.1 shape derivation — see :func:`compute_state_run_hash`).
  The plan binds at prepare and nowhere else; ``run`` takes no plan.
- :func:`run_state_run` — ``run(prepared, host)``: the journal
  composition (the #164 observation bridge ``emit_state_snapshots`` /
  ``publish_topology_changes`` at both evaluation trigger points), the
  **pre-evaluation transform application point** (:data:`simulation.
  state.fault_transforms.STATE_TRANSFORM_BY_FAULT_TYPE` — the evaluators
  stay fault-blind, decision 3), the re-evaluation, the terminal state.

Honesty discipline (ADR-0012 decision 2 / SPEC-303 §Phase3): a SIM_STATE
run has **no TS artifact and no ``gen.*`` construction event** — the
Generate product is the ``rf.*``/``sec.*`` state_observed stream.  The
fault lifecycle is honestly two-faced: ``fault.injected`` (SCHEDULED, run
open) → ``fault.cleared`` (REMOVED, completed-run end; a failed run
leaves its faults FAILED — no cleared, the TS-face posture).
``fault.applied`` is L1-only (the registry's own comment: "APPLIED
confirms fault bytes in the flow") — the state-domain application
evidence IS the faulted evaluation products (the snapshot diff +
``topology.state_changed``), never a fabricated packet-slot list.
``fault.activated`` has no packet-index crossing in the state domain
(session_start activations apply once at assembly).

The host seam (:class:`StateRunHost`) is structural (the import-linter
C6 posture): the composition root binds it to the #41
``SimulationRuntime`` through the #43 ``RunIdAllocator`` shim (which
duck-types the whole run face), exactly as the TS face does.

Import-contract note: this module imports only ``faults.*`` (the
contract-8 legal direction), ``ts.canonical_json`` and ``simulation.*`` —
never ``application``/``api``/``domain.topology``.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections import deque
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol

from faults.registry import (
    LAYER_BY_FAULT_TYPE,
    validate_fault_definition,
)
from faults.targets import parse_target_id
from ts.canonical_json import canonical_json

from simulation.errors import (
    SIM_FAULT_PLAN_LAYER_MISMATCH,
    SIM_FAULT_STATE_TRANSFORM_UNREGISTERED,
    StatePlanInvalidError,
    SimulationValidationError,
)
from simulation.fault_plan import FaultDefinition
from simulation.state.evaluate import (
    EvalContext,
    Health,
    TopologyEvalResult,
    evaluate_topology,
)
from simulation.state.evaluators import DEFAULT_EVALUATORS
from simulation.state.evaluators._vocab import DISEQC_COMMANDS_CONFIG_KEY
from simulation.state.fault_transforms import (
    STATE_FAULT_LAYERS,
    STATE_TRANSFORM_BY_FAULT_TYPE,
    state_layer_prepare_checks,
)
from simulation.state.graph import TopologyGraph
from simulation.state.observation_bridge import (
    emit_state_snapshots,
    publish_topology_changes,
)
from simulation.state.validate import (
    DISEQC_SWITCH_NODE_TYPE,
    TUNER_NODE_TYPE,
    validate_topology,
)

if TYPE_CHECKING:  # annotation-only: no runtime import cycle with runtime.py
    from simulation.runtime import SimulationSessionSpec

__all__ = [
    "SIM_FAULT_EXEC_FAILED_REASON",
    "PreparedStateRun",
    "STATE_RUN_ENGINE_VERSION",
    "STATE_RUN_FIDELITY",
    "StateRunHost",
    "StateRunResult",
    "bridge_tuner_diseqc_commands",
    "canonical_state_plan_projection",
    "compute_state_run_hash",
    "prepare_state_run",
    "run_state_run",
]

#: The wire fidelity value declared by the REST submit face (the DTO
#: ``Literal`` and the runs-backend dispatch discriminator).
STATE_RUN_FIDELITY = "SIM_STATE"

#: The state-domain fingerprint registry version (§D.8 derivation: the
#: "求值器/注册表版本" input).  Bumped whenever the evaluator registry,
#: the transform registry or the evaluation semantics change in a way
#: that moves terminal states — the 确定性复现契约 stays explicit about
#: which engine produced a terminal state.
STATE_RUN_ENGINE_VERSION = "0.7.0"

#: The close reason for a run-stage transform failure (the TS face's
#: ``SIM_FAULT_EXEC_FAILED`` root-cause posture, SPEC-204 §11).
SIM_FAULT_EXEC_FAILED_REASON = "SIM_FAULT_EXEC_FAILED"

#: ``state_run_fingerprint_version`` — the projection document's own
#: schema version (the §D.8 document shape itself; bump on shape change).
_STATE_RUN_FINGERPRINT_VERSION = 1


# --- A15: the tuner→switch intent bridge (ruling A15) ------------------------------


def bridge_tuner_diseqc_commands(graph: TopologyGraph) -> TopologyGraph:
    """Bridge tuner-side DiSEqC command intent into the target switch's
    config (orchestrator ruling A15 — 编排职责, not a fault transform).

    SPEC-622 §5 places the command intent on the **tuner** config, but the
    frozen walk evaluates the switch upstream of the tuners — the intent
    is unreachable in the walk direction.  At evaluation-assembly time
    (prepare / the session initial evaluation) this bridge copies each
    intent-carrying tuner's ``diseqc_commands`` into the config of the
    switch feeding it, so :class:`simulation.state.evaluators.
    DiseqcSwitchEvaluator`'s primary channel (the switch's own config
    key) sees the intent.

    Deterministic assembly rules (REPORT-frozen):

    - the target switch of a tuner = the nearest ``diseqc_switch`` node in
      the tuner's transitive upstream set (min hop distance, BFS; ties
      broken lexicographically by node_id);
    - a switch that already declares its own ``diseqc_commands`` (the
      creation convention, kept as the compatibility channel) is never
      overwritten;
    - multiple tuners bridging into one switch apply in lexicographic
      tuner order — the last writer wins;
    - the input graph and its config dicts are never mutated: affected
      switch nodes are replaced with copied configs, every other node
      keeps its identity;
    - a tuner intent with no upstream switch stays untouched (no
      fabrication — the tuner evaluator does not consume it either).

    Cycle-safe (visited-set upstream walk): an invalid cyclic graph
    reaches the topology gate's cycle violation instead of hanging here.
    """
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    parents: dict[str, set[str]] = {}
    for connection in graph.connections:
        parents.setdefault(connection.to_node, set()).add(connection.from_node)

    def _nearest_upstream_switch(tuner_id: str) -> str | None:
        """BFS upstream for the nearest ``diseqc_switch`` (min hops,
        lexicographic tie-break); ``None`` = no switch feeds the tuner."""
        visited: set[str] = set()
        queue: deque[str] = deque(parents.get(tuner_id, ()))
        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = nodes_by_id.get(node_id)
            if node is not None and node.node_type == DISEQC_SWITCH_NODE_TYPE:
                return node_id
            queue.extend(parents.get(node_id, ()))
        return None

    # Lexicographic tuner application order; the last bridging writer of
    # one switch wins (deterministic — never list-order dependent).
    intents: dict[str, dict] = {}
    for node in sorted(graph.nodes, key=lambda item: item.node_id):
        if node.node_type != TUNER_NODE_TYPE:
            continue
        intent = node.config.get(DISEQC_COMMANDS_CONFIG_KEY)
        if not isinstance(intent, dict):
            continue
        target = _nearest_upstream_switch(node.node_id)
        if target is None:
            continue
        target_node = nodes_by_id[target]
        if isinstance(
            target_node.config.get(DISEQC_COMMANDS_CONFIG_KEY), dict
        ):
            continue  # the switch's own creation intent wins (A15)
        intents[target] = intent

    if not intents:
        return graph
    bridged_nodes = [
        node
        if node.node_id not in intents
        else dataclasses.replace(
            node,
            config={**node.config, DISEQC_COMMANDS_CONFIG_KEY: intents[node.node_id]},
        )
        for node in graph.nodes
    ]
    return TopologyGraph(
        topology_id=graph.topology_id,
        revision=graph.revision,
        nodes=bridged_nodes,
        connections=list(graph.connections),
    )


# --- the state fingerprint (§D.8 shape derivation) ---------------------------------


def canonical_state_plan_projection(
    plan: tuple[FaultDefinition, ...],
) -> list[dict[str, Any]]:
    """The plan fingerprint projection — the ``ts_runtime._canonical_plan``
    shape field-for-field (fault_type + target_id + key-sorted parameters
    + activation + expected_observations; ``fault_id`` uuid4 identity
    excluded, ``layer`` excluded — the #121 regression pin).  Drift-locked
    against the TS face by ``tests/unit/simulation/state/test_run.py``.
    """
    entries: list[dict[str, Any]] = []
    for fault in plan:
        entries.append(
            {
                "fault_type": fault.fault_type,
                "target_id": fault.target_id,
                "parameters": {
                    key: fault.parameters[key] for key in sorted(fault.parameters)
                },
                "activation": {
                    "kind": fault.activation.kind,
                    "packet_index": fault.activation.packet_index,
                },
                "expected_observations": list(fault.expected_observations),
            }
        )
    return entries


def compute_state_run_hash(
    *,
    graph: TopologyGraph,
    fault_plan: tuple[FaultDefinition, ...],
    seed: int,
) -> str:
    """The deterministic SIM_STATE run fingerprint (SPEC-203 §5.1 shape,
    state-domain derivation per brief §D.8).

    Inputs, explicitly: the engine/registry version
    (:data:`STATE_RUN_ENGINE_VERSION`), the evaluator + transform registry
    faces (node-type / fault-type key sets), the canonical topology
    assembly (topology identity + revision + every node's type and config
    dict + every connection's four-tuple and plane), the session seed and
    the canonical plan projection.  Wall clock, session_id, run_id and
    paths never enter (the TS-face rule).  Same config + plan + seed +
    version ⇒ same hash ⇒ same terminal state (decision 6's 确定性复现
    契约); different plan/seed/config ⇒ different hash.  The fingerprint
    covers the **declared** graph (pre-bridge) — the A15 bridge is
    deterministic assembly, its product adds no input.
    """
    document: dict[str, Any] = {
        "state_run_fingerprint_version": _STATE_RUN_FINGERPRINT_VERSION,
        "engine_version": STATE_RUN_ENGINE_VERSION,
        "evaluator_registry": {
            "evaluator_node_types": sorted(DEFAULT_EVALUATORS),
            "state_transform_fault_types": sorted(STATE_TRANSFORM_BY_FAULT_TYPE),
        },
        "topology": {
            "topology_id": graph.topology_id,
            "revision": graph.revision,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "config": node.config,
                }
                for node in sorted(graph.nodes, key=lambda item: item.node_id)
            ],
            "connections": [
                {
                    "connection_id": connection.connection_id,
                    "from_node": connection.from_node,
                    "from_port": connection.from_port,
                    "to_node": connection.to_node,
                    "to_port": connection.to_port,
                    "plane": connection.plane.value,
                }
                for connection in sorted(
                    graph.connections,
                    key=lambda item: item.connection_id,
                )
            ],
        },
        "seed": seed,
        "fault_plan": canonical_state_plan_projection(fault_plan),
    }
    canonical = canonical_json(document)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- the prepare face ---------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PreparedStateRun:
    """The frozen SIM_STATE prepare answer (the ``PreparedTSRun`` mirror).

    ``graph`` is the **bridged** evaluation assembly (A15); ``baseline``
    is the prepare-triggered L0 evaluation product over it (decision 6 —
    the first 求值触发点).  The fault plan is bound here and nowhere else;
    ``fault_id`` uuids are identity, not semantics, and do not enter the
    fingerprint.
    """

    session_id: str
    graph: TopologyGraph
    fault_plan: tuple[FaultDefinition, ...]
    config_hash: str
    topology_revision: int
    baseline: TopologyEvalResult


def prepare_state_run(
    session: "SimulationSessionSpec",
    fault_plan=(),
) -> PreparedStateRun:
    """Validate and bind: topology + plan → frozen :class:`PreparedStateRun`.

    Gate chain (AC-204-01 alignment — every knowable rejection happens
    here, before any scheduling):

    1. the topology gate (:func:`validate_topology` — the unique entry,
       the #160 ``SIM_TOPO_UB_*`` rules included); violations raise
       :class:`SimulationValidationError` with the path-addressed report
       (the session-validation translation path reused verbatim over the
       REST face);
    2. the bidirectional mixed-plan gate: a package-layer fault
       (``SIM_FAULT_PLAN_LAYER_MISMATCH``) is rejected on the state face
       (the mirror of the TS face's ``allowed_layers`` gate — a SIM_STATE
       run never routes a package fault into the ADR-0007 filter chain);
    3. per-fault registry validation (SPEC-204 §11 detail codes) and the
       state-layer prepare checks (:func:`state_layer_prepare_checks` —
       target existence / node kind / transform registration);
       combined details raise :class:`StatePlanInvalidError`.

    Non-``FaultDefinition`` elements are a caller programming error
    (``TypeError``), mirroring the TS face.
    """
    graph = session.topology
    violations = tuple(validate_topology(graph))
    if violations:
        from simulation.runtime import ValidationReport

        raise SimulationValidationError(
            f"session {session.session_id} topology rejected at state-run "
            f"prepare with {len(violations)} violation(s); nothing was "
            "scheduled (AC-204-01)",
            report=ValidationReport(violations=violations),
        )
    plan_tuple = tuple(fault_plan)
    details: list[str] = []
    for fault in plan_tuple:
        if not isinstance(fault, FaultDefinition):
            raise TypeError(
                f"fault plan elements must be FaultDefinition, got "
                f"{type(fault).__name__}"
            )
        effective_layer = LAYER_BY_FAULT_TYPE.get(fault.fault_type, fault.layer)
        if effective_layer not in STATE_FAULT_LAYERS:
            # Bidirectional gate, state-side: SIM_STATE runs execute the
            # pre-evaluation transform path only (decision 3's two
            # execution paths per layer routing).
            details.append(
                f"{SIM_FAULT_PLAN_LAYER_MISMATCH}: fault "
                f"{fault.fault_id!r}: fault_type {fault.fault_type!r} "
                f"routes to layer {effective_layer!r}, outside the "
                f"SIM_STATE state-layer set {sorted(STATE_FAULT_LAYERS)} "
                "(ADR-0012 decisions 2/3 — package layers execute on a "
                "SIM_TS run)"
            )
            continue
        details.extend(validate_fault_definition(fault))
    details.extend(state_layer_prepare_checks(plan_tuple, graph))
    if details:
        raise StatePlanInvalidError(
            f"SIM_STATE fault plan rejected at prepare with "
            f"{len(details)} validation error(s); nothing was scheduled "
            "(AC-204-01)",
            details=tuple(details),
        )
    bridged = bridge_tuner_diseqc_commands(graph)
    baseline = evaluate_topology(
        bridged,
        evaluators=DEFAULT_EVALUATORS,
        context=EvalContext(topology_revision=graph.revision),
    )
    return PreparedStateRun(
        session_id=session.session_id,
        graph=bridged,
        fault_plan=plan_tuple,
        config_hash=compute_state_run_hash(
            graph=graph, fault_plan=plan_tuple, seed=session.seed
        ),
        topology_revision=graph.revision,
        baseline=baseline,
    )


# --- the run face --------------------------------------------------------------------


class StateRunHost(Protocol):
    """The structural host seam for :func:`run_state_run`.

    Production binding: the #43 ``RunIdAllocator`` shim over the #41
    ``SimulationRuntime`` (the TS-face posture — ``start_run`` honors the
    REST-staged run id, everything else delegates).  The additive runtime
    faces the orchestration consumes: the ``emitter`` accessor (the #164
    bridge's emit seam) and ``now_ns`` (the committed virtual-time
    reading).
    """

    @property
    def emitter(self) -> Any:  # SimulationEventEmitter-shaped
        ...

    def now_ns(self, session_id: str) -> int: ...

    async def start_run(self, session_id: str) -> Any:  # RunView-shaped
        ...

    async def complete_run(self, session_id: str, run_id: str) -> Any: ...

    async def fail_run(
        self, session_id: str, run_id: str, *, reason: str
    ) -> Any: ...

    def emit_fault_event(
        self,
        session_id: str,
        run_id: str,
        event_type: str,
        *,
        fault_id: str,
        fault_type: str,
        target_node_id: str | None,
        target_pid: int | None,
        payload: Mapping[str, Any] | None = None,
        severity: str = "info",
    ) -> None: ...


@dataclasses.dataclass(frozen=True)
class StateRunResult:
    """One SIM_STATE run's digest (the ``TSRunResult`` mirror, honestly
    two-formed): **no artifacts, no packet/byte counts, no generator
    version** — the L0 evaluation products instead (decision 2's 诚实
    区分)."""

    run_id: str
    status: Literal["completed", "failed"]
    config_hash: str
    topology_id: str
    revision: int
    #: The final evaluation's whole-graph health aggregate (decision 5's
    #: health-display data source on the run status face).
    graph_health: Health
    #: The final evaluation's per-node health, JSON-safe ``Health.value``
    #: strings keyed by node_id (the canvas health-badge read face).
    node_health: Mapping[str, str]
    baseline_graph_health: Health
    #: The walk's ``NodeFailure`` reports ("node_id: detail" — the
    #: SIM_EVAL_NODE_FAILED isolation face), in walk order.
    failures: tuple[str, ...]
    #: How many state snapshots the run delivered (the Lab L0 summary's
    #: 快照事件计数 input; the journal is the authoritative stream — this
    #: count is a digest face, never a substitute).
    snapshot_event_count: int
    #: The failed-close reason (``None`` on completed runs).
    error: str | None = None


def _fault_addressing(fault: FaultDefinition) -> tuple[str | None, int | None, int]:
    """(node_id, pid, injection_index) for one plan fault — the TS-face
    addressing shape; state targets are node-level (pid always ``None``)."""
    try:
        target = parse_target_id(fault.target_id)
        node_id: str | None = target.node_id
    except ValueError:
        node_id = None
    pid: int | None = None
    injection_index = (
        0
        if fault.activation.kind == "session_start"
        else fault.activation.packet_index or 0
    )
    return node_id, pid, injection_index


def _emit_fault_safe(
    host: StateRunHost,
    prepared: PreparedStateRun,
    run_id: str,
    event_type: str,
    fault: FaultDefinition,
    payload: dict[str, Any],
) -> None:
    """Emission wrapper that never breaks the run outcome (the TS-face
    teardown-race posture; the gateway is the authoritative non-drop
    point)."""
    node_id, pid, _index = _fault_addressing(fault)
    try:
        host.emit_fault_event(
            prepared.session_id,
            run_id,
            event_type,
            fault_id=fault.fault_id,
            fault_type=fault.fault_type,
            target_node_id=node_id,
            target_pid=pid,
            payload=payload,
        )
    except Exception:  # noqa: BLE001 — teardown race only
        pass


def _emit_and_publish(
    host: StateRunHost,
    prepared: PreparedStateRun,
    run_id: str,
    previous: TopologyEvalResult,
    current: TopologyEvalResult,
) -> int:
    """One evaluation trigger point's bridge face (#164 binding): emit the
    per-node snapshot stream, then publish the ``topology.state_changed``
    diff against ``previous`` (no diff → no event — the bridge's own
    contract).  Delivery never breaks the run outcome."""
    virtual_time_ns = host.now_ns(prepared.session_id)
    emitted = 0
    try:
        documents = emit_state_snapshots(
            host.emitter,
            current,
            graph=prepared.graph,
            session_id=prepared.session_id,
            run_id=run_id,
            virtual_time_ns=virtual_time_ns,
        )
        emitted = len(documents)
    except Exception:  # noqa: BLE001 — teardown race only
        pass
    try:
        publish_topology_changes(
            host.emitter,
            previous,
            current,
            session_id=prepared.session_id,
            run_id=run_id,
            virtual_time_ns=virtual_time_ns,
        )
    except Exception:  # noqa: BLE001 — teardown race only
        pass
    return emitted


def _rebuild_graph(
    graph: TopologyGraph, configs_by_id: Mapping[str, dict]
) -> TopologyGraph:
    """The post-transform evaluation assembly: every node carries its
    (possibly rewritten) config.  Pure — the input graph is never
    mutated."""
    nodes = [
        dataclasses.replace(node, config=configs_by_id[node.node_id])
        for node in graph.nodes
    ]
    return TopologyGraph(
        topology_id=graph.topology_id,
        revision=graph.revision,
        nodes=nodes,
        connections=list(graph.connections),
    )


def _build_result(
    prepared: PreparedStateRun,
    run_id: str,
    status: str,
    final: TopologyEvalResult,
    snapshot_event_count: int,
    error: str | None,
) -> StateRunResult:
    return StateRunResult(
        run_id=run_id,
        status=status,  # type: ignore[arg-type]
        config_hash=prepared.config_hash,
        topology_id=prepared.graph.topology_id,
        revision=prepared.topology_revision,
        graph_health=final.graph_health,
        node_health={
            node_result.node_id: node_result.health.value
            for node_result in final.node_results
        },
        baseline_graph_health=prepared.baseline.graph_health,
        failures=tuple(
            f"{failure.node_id}: {failure.detail}" for failure in final.failures
        ),
        snapshot_event_count=snapshot_event_count,
        error=error,
    )


async def run_state_run(
    prepared: PreparedStateRun, host: StateRunHost
) -> StateRunResult:
    """Execute one deterministic SIM_STATE run (the ``TSRuntime.run``
    mirror; the plan is bound in ``prepared`` and nowhere else).

    Journal composition (SPEC-303 §Phase3): the run opens/closes through
    the run face (``run_started``/``run_completed``), each plan fault
    emits ``fault.injected`` (SCHEDULED) at open and ``fault.cleared``
    (REMOVED) at the completed-run end, and **both evaluation trigger
    points** call the #164 bridge once (emit + publish):

    1. the prepare-triggered baseline (decision 6 trigger 1) — the
       Generate product; the publish half runs too (各调一次, the #164
       binding) but the baseline-vs-baseline diff is empty by
       construction → no event (honest no-op);
    2. the post-transform re-evaluation (decision 6 trigger 2, plan
       non-empty only) — with the ``topology.state_changed`` diff against
       the baseline.

    Returns the terminal result; a run-stage transform failure
    (unreachable for prepare-validated plans) closes the run as failed
    with ``SIM_FAULT_EXEC_FAILED`` as the reason — the fault stays FAILED
    (no cleared) and the result carries the error digest (no exception
    crosses the host seam).
    """
    run_view = await host.start_run(prepared.session_id)
    run_id = run_view.run_id
    snapshot_event_count = 0

    for fault in prepared.fault_plan:
        _emit_fault_safe(
            host, prepared, run_id, "fault.injected", fault,
            {
                "fault_id": fault.fault_id,
                "fault_type": fault.fault_type,
                "layer": fault.layer,
                "injection_index": _fault_addressing(fault)[2],
                "expected_observations": list(fault.expected_observations),
            },
        )

    # Trigger point 1 — the L0 baseline (decision 6).
    snapshot_event_count += _emit_and_publish(
        host, prepared, run_id, prepared.baseline, prepared.baseline
    )

    status: str = "completed"
    error: str | None = None
    faulted = prepared.baseline
    if prepared.fault_plan:
        # The pre-evaluation transform application point (decision 3):
        # STATE_TRANSFORM_BY_FAULT_TYPE rewrites the node configs; the
        # evaluators stay fault-blind.
        configs_by_id: dict[str, dict] = {
            node.node_id: node.config for node in prepared.graph.nodes
        }
        applied: list[FaultDefinition] = []
        transform_error: str | None = None
        for fault in prepared.fault_plan:
            transform = STATE_TRANSFORM_BY_FAULT_TYPE.get(fault.fault_type)
            if transform is None:
                # prepare guarantees registration; a miss is a programming
                # error surfaced as the unregistered-transform code.
                transform_error = (
                    f"{SIM_FAULT_STATE_TRANSFORM_UNREGISTERED}: fault "
                    f"{fault.fault_id!r}: no state transform registered "
                    f"for {fault.fault_type!r}"
                )
                break
            try:
                configs_by_id = dict(transform(fault, configs_by_id))
            except ValueError as exc:
                transform_error = (
                    f"{SIM_FAULT_EXEC_FAILED_REASON}: fault "
                    f"{fault.fault_id!r}: {exc}"
                )
                break
            applied.append(fault)

        faulted_graph = _rebuild_graph(prepared.graph, configs_by_id)
        faulted = evaluate_topology(
            faulted_graph,
            evaluators=DEFAULT_EVALUATORS,
            context=EvalContext(topology_revision=prepared.topology_revision),
        )
        if transform_error is None:
            # Trigger point 2 — the faulted re-evaluation (decision 6).
            snapshot_event_count += _emit_and_publish(
                host, prepared, run_id, prepared.baseline, faulted
            )
            for fault in applied:
                _emit_fault_safe(
                    host, prepared, run_id, "fault.cleared", fault,
                    {
                        "fault_id": fault.fault_id,
                        "fault_type": fault.fault_type,
                        "layer": fault.layer,
                        "injection_index": _fault_addressing(fault)[2],
                        "cleared_reason": "run_end",
                    },
                )
        else:
            # SPEC-204 §11 run-stage transform failure: the run fails, the
            # fault stays FAILED (no cleared — the TS-face posture); the
            # partial assembly's evaluation is still the honest run face.
            status = "failed"
            error = transform_error
            try:
                await host.fail_run(
                    prepared.session_id, run_id, reason=SIM_FAULT_EXEC_FAILED_REASON
                )
            except ValueError:  # concurrent close already terminated it
                pass

    if status == "completed":
        try:
            await host.complete_run(prepared.session_id, run_id)
        except ValueError:  # concurrent close already terminated it
            pass
    return _build_result(
        prepared, run_id, status, faulted, snapshot_event_count, error
    )
