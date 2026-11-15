"""SPEC-202 section 6 — evaluation interface and skeleton walk (ticket #40).

**Interface freeze (SIM-E / #44 depends on this surface).** The frozen
types: :class:`Health`, :class:`PortState`, :class:`CauseRef`,
:class:`NodeEvalResult`, :class:`EvalContext`, :class:`NodeFailure`,
:class:`TopologyEvalResult` and the :class:`NodeEvaluator` protocol.

**L0 deferred (ADR-0005 decision 2, issue #40).** The *full* L0 node
semantics evaluation (per-node-type evaluators, real state propagation,
fault-plan expression) is deferred out of MVP — the evaluation point is an
explicit stub: with no evaluator registered for a node type the node
evaluates as **idle** (which also implements the SPEC-202 section 5
"isolated nodes report idle" semantics). The deferral basis is recorded on
:data:`L0_DEFERRED_RATIONALE` for audit. Canvas health displays degrade to
Run state + diagnostic-event mapping per ADR-0005 decision 2.

What the skeleton *does* implement, deterministically and purely:

- the deterministic walk over :func:`simulation.state.graph.topological_order`
  (nodeId lexicographic tie-break, REQ-SIM-202-002/003);
- per-node dispatch to registered evaluators (dependency injection — the
  purity seam of SPEC-202 section 9);
- ``SIM_EVAL_NODE_FAILED`` isolation: an evaluator-internal exception
  isolates that node as error health and surfaces a :class:`NodeFailure`,
  never crashing the whole-graph evaluation (SPEC-202 section 8);
- severity precedence ``error > warn > idle > ok`` for graph-level health
  (SPEC-202 section 6.2);
- downstream causal reference threading (REQ-SIM-202-004): when an
  upstream node is in an abnormal state (error/warn), every downstream
  node result carries a :class:`CauseRef` to the feeding node/port plus
  the upstream result's own causes — the chain survives healthy
  intermediate nodes and reaches the root cause;
- the pure diff half of the ``topology.state_changed`` emission obligation
  (:func:`changed_nodes`); envelope publication is the envelope consumers'
  obligation (SIM-C/D, SPEC-301) — this module emits nothing.

Purity (SPEC-202 section 3/6.1): no IO, no wall clock, no randomness.
Time enters only as the *committed* ``virtual_time_ns`` integer carried by
:class:`EvalContext` — the orchestrator (SPEC-200) commits it; a live
clock or wall-clock source is structurally incapable of entering (the
context fields are ints only).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable

from simulation.errors import SIM_EVAL_NODE_FAILED
from simulation.state.graph import (
    Connection,
    NodeConfig,
    NodeId,
    PortId,
    TopologyGraph,
    topological_order,
)

__all__ = [
    "SIM_EVAL_NODE_FAILED",
    "CauseRef",
    "EvalContext",
    "Health",
    "L0_DEFERRED_RATIONALE",
    "NodeEvalResult",
    "NodeEvaluator",
    "NodeFailure",
    "PortState",
    "TopologyEvalResult",
    "changed_nodes",
    "evaluate_topology",
    "severity_rank",
]

#: Deferred-basis record for the L0 evaluation point (issue #40 acceptance:
#"L0 求值点显式 stub 并记录 deferred 依据"). Full L0 node-semantics
#: evaluation is deferred out of MVP by ADR-0005 decision 2 (#7); the
#: interface stays frozen for SIM-E (#44) and the post-MVP roadmap.
L0_DEFERRED_RATIONALE = (
    "Full L0 (SIM_STATE) node-semantics evaluation is deferred out of MVP "
    "by ADR-0005 decision 2 (#7): the eight-step closed loop has no "
    "SIM_STATE dependency, and the canvas health display degrades to Run "
    "state + diagnostic-event mapping. SPEC-202 keeps only the skeleton: "
    "frozen evaluation interface + deterministic walk; unregistered node "
    "types evaluate idle (SPEC-202 section 5 isolated-node semantics). "
    "Recorded by ticket #40."
)


class Health(str, Enum):
    """Node/port health vocabulary (SPEC-202 section 6.1)."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    IDLE = "idle"


#: Severity precedence ``error > warn > idle > ok`` (SPEC-202 section 6.2)
#: as a total rank: higher rank = more severe.
_SEVERITY_RANK: dict["Health", int] = {
    Health.ERROR: 3,
    Health.WARN: 2,
    Health.IDLE: 1,
    Health.OK: 0,
}


def severity_rank(health: Health) -> int:
    """The severity rank of ``health`` (error > warn > idle > ok)."""
    return _SEVERITY_RANK[health]


#: Upstream health values that count as *anomalous* and therefore trigger
#: downstream causal references (SPEC-202 section 6.2). Idle is a legal,
#: non-anomalous state (isolated nodes report idle).
_ANOMALOUS = frozenset({Health.ERROR, Health.WARN})


@dataclass(frozen=True)
class CauseRef:
    """One reference in a downstream causal chain (SPEC-202 section 6.2).

    Points at the root-cause node (and optionally the feeding port) of an
    abnormal upstream state; consumed by the canvas "Run state +
    diagnostic mapping" and SPEC-306 diagnostics.
    """

    node_id: NodeId
    port_id: PortId | None = None


@dataclass(frozen=True)
class PortState:
    """The evaluated state of one port."""

    port_id: PortId
    health: Health


@dataclass(frozen=True)
class NodeEvalResult:
    """Per-node evaluation result (SPEC-202 section 6.1).

    ``metrics`` values are JSON-safe numbers; ``causes`` carries the
    causal reference chain (root cause first as produced by the walk).
    """

    node_id: NodeId
    health: Health
    port_states: tuple = ()
    metrics: Mapping = field(default_factory=dict)
    causes: tuple = ()


@dataclass(frozen=True)
class NodeFailure:
    """A ``SIM_EVAL_NODE_FAILED`` report (SPEC-202 section 8, row 8)."""

    node_id: NodeId
    code: str = SIM_EVAL_NODE_FAILED
    detail: str = ""


@dataclass(frozen=True)
class EvalContext:
    """Pure evaluation context (SPEC-202 section 6.1).

    Carries the topology revision, the node config version and the
    *committed* virtual time reading — integer fields only, so no wall
    clock, live clock object or random source can enter a pure evaluation
    (SPEC-202 section 3/6.1, tests/README section 5 断言时钟纪律).
    """

    topology_revision: int
    node_config_version: int = 0
    virtual_time_ns: int = 0


@runtime_checkable
class NodeEvaluator(Protocol):
    """Pure node evaluator protocol (SPEC-202 section 6.1 signature).

    Same input (node, input port states, context) must always produce the
    same output; IO, wall-clock reads, randomness and mutation of other
    nodes are forbidden.
    """

    def evaluate(
        self,
        node: NodeConfig,
        inputs: Mapping[PortId, PortState],
        context: EvalContext,
    ) -> NodeEvalResult: ...


@dataclass(frozen=True)
class TopologyEvalResult:
    """Whole-graph evaluation result (SPEC-202 sections 6.2/6.3).

    ``order`` is the deterministic topological order the walk followed;
    ``node_results`` is in that same order; ``graph_health`` aggregates
    node health by severity precedence.
    """

    topology_id: str
    revision: int
    order: tuple
    node_results: tuple
    failures: tuple = ()
    graph_health: Health = Health.OK

    def result_for(self, node_id: NodeId) -> NodeEvalResult | None:
        """The result of ``node_id`` (None when absent)."""
        for node_result in self.node_results:
            if node_result.node_id == node_id:
                return node_result
        return None


def _idle_result(node: NodeConfig) -> NodeEvalResult:
    """The explicit L0 deferred stub result (see L0_DEFERRED_RATIONALE)."""
    return NodeEvalResult(
        node_id=node.node_id,
        health=Health.IDLE,
        port_states=tuple(
            PortState(port.port_id, Health.IDLE) for port in node.ports
        ),
        metrics={},
        causes=(),
    )


def _feeding_connections(graph: TopologyGraph, node_id: NodeId) -> list:
    """Incoming connections in deterministic order.

    Sort key ``(from_node, from_port, connection_id)``: if several
    connections feed one input port (a cardinality violation the validator
    reports), the walk still picks a deterministic feeding state.
    """
    return sorted(
        graph.connections_to(node_id),
        key=lambda connection: (
            connection.from_node,
            connection.from_port,
            connection.connection_id,
        ),
    )


def _input_states(
    graph: TopologyGraph,
    node_id: NodeId,
    results_by_node: Mapping[NodeId, NodeEvalResult],
) -> dict:
    """Per-input-port state map for ``node_id`` (key = local input port).

    The value's health is the feeding upstream output port's health (the
    upstream node's health when the port has no explicit state). Upstream
    identity for causal chains is threaded by the walk itself, not via
    inputs.
    """
    inputs: dict[PortId, PortState] = {}
    for connection in _feeding_connections(graph, node_id):
        upstream = results_by_node.get(connection.from_node)
        feeding: Health | None = None
        if upstream is not None:
            for port_state in upstream.port_states:
                if port_state.port_id == connection.from_port:
                    feeding = port_state.health
                    break
            if feeding is None:
                feeding = upstream.health
        else:
            feeding = Health.IDLE
        if connection.to_port not in inputs:
            inputs[connection.to_port] = PortState(
                port_id=connection.to_port, health=feeding
            )
    return inputs


def _thread_causes(
    own: NodeEvalResult,
    graph: TopologyGraph,
    node_id: NodeId,
    results_by_node: Mapping[NodeId, NodeEvalResult],
) -> NodeEvalResult:
    """Merge upstream causal references into ``own`` (REQ-SIM-202-004).

    For every feeding connection whose upstream node is anomalous
    (error/warn) the result gains a direct :class:`CauseRef` to the
    feeding node/port plus that upstream result's own causes — the chain
    therefore reaches the root cause even through healthy intermediate
    nodes. Dedup keeps the first occurrence in deterministic connection
    order.
    """
    merged: list[CauseRef] = list(own.causes)
    seen: set[tuple] = {(cause.node_id, cause.port_id) for cause in own.causes}
    for connection in _feeding_connections(graph, node_id):
        upstream = results_by_node.get(connection.from_node)
        if upstream is None or upstream.health not in _ANOMALOUS:
            continue
        candidates = [
            CauseRef(node_id=connection.from_node, port_id=connection.from_port),
            *upstream.causes,
        ]
        for candidate in candidates:
            key = (candidate.node_id, candidate.port_id)
            if key not in seen:
                seen.add(key)
                merged.append(candidate)
    if len(merged) == len(own.causes):
        return own
    return replace(own, causes=tuple(merged))


def evaluate_topology(
    graph: TopologyGraph,
    *,
    evaluators: Mapping[str, NodeEvaluator] | None = None,
    context: EvalContext | None = None,
) -> TopologyEvalResult:
    """Evaluate ``graph`` in deterministic topological order.

    Nodes whose ``node_type`` has no registered evaluator evaluate **idle**
    — the explicit L0 deferred stub (:data:`L0_DEFERRED_RATIONALE`).
    Evaluator-internal exceptions are isolated as
    ``SIM_EVAL_NODE_FAILED`` (error health + :class:`NodeFailure` report)
    without crashing the whole-graph evaluation (SPEC-202 section 8).

    Raises :class:`simulation.errors.TopologyCycleError` on cyclic input —
    reject cycles via :func:`simulation.state.validate.validate_topology`
    first (SPEC-202 section 5).
    """
    if context is None:
        context = EvalContext(topology_revision=graph.revision)
    registry: Mapping[str, NodeEvaluator] = evaluators or {}
    order = topological_order(graph)  # cycle refusal point

    results_by_node: dict[NodeId, NodeEvalResult] = {}
    failures: list[NodeFailure] = []
    for node_id in order:
        node = graph.node(node_id)
        if node is None:  # defensive; cannot happen post-construction
            continue
        evaluator = registry.get(node.node_type)
        if evaluator is None:
            result = _idle_result(node)
        else:
            try:
                result = evaluator.evaluate(
                    node,
                    _input_states(graph, node_id, results_by_node),
                    context,
                )
            except Exception as exc:  # isolation boundary, SPEC-202 §8
                failures.append(
                    NodeFailure(node_id=node_id, detail=f"{type(exc).__name__}: {exc}")
                )
                result = NodeEvalResult(
                    node_id=node_id,
                    health=Health.ERROR,
                    port_states=tuple(
                        PortState(port.port_id, Health.ERROR)
                        for port in node.ports
                    ),
                    metrics={},
                    causes=(),
                )
        # Thread causes in walk order: topological order guarantees every
        # upstream is already threaded, so the reference chain survives
        # healthy intermediate nodes and reaches the root cause.
        results_by_node[node_id] = _thread_causes(
            result, graph, node_id, results_by_node
        )

    final_results = tuple(results_by_node[node_id] for node_id in order)
    graph_health = Health.OK
    for node_result in final_results:
        if severity_rank(node_result.health) > severity_rank(graph_health):
            graph_health = node_result.health
    return TopologyEvalResult(
        topology_id=graph.topology_id,
        revision=context.topology_revision,
        order=order,
        node_results=final_results,
        failures=tuple(failures),
        graph_health=graph_health,
    )


def changed_nodes(
    previous: TopologyEvalResult, current: TopologyEvalResult
) -> tuple:
    """Node IDs whose evaluated state changed between two results.

    The pure diff half of the ``topology.state_changed`` obligation
    (SPEC-202 section 6.3): sorted lexicographically for a deterministic
    payload; envelope emission itself belongs to the consumers (SIM-C/D).
    """
    node_ids = {
        node_result.node_id for node_result in previous.node_results
    } | {node_result.node_id for node_result in current.node_results}
    changed: list[str] = []
    for node_id in sorted(node_ids):
        if previous.result_for(node_id) != current.result_for(node_id):
            changed.append(node_id)
    return tuple(changed)
