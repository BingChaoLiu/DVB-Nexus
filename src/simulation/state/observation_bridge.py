"""Observation bridge — state snapshots + ``topology.state_changed`` (ticket #164).

SPEC-303 §Phase3落地 (ADR-0012 decisions 1/2): the L0 evaluation products
enter the observation plane through this bridge — the ONLY new seam; the
SPEC-202 walk, the evaluators and the emitter stay untouched consumers.

- :func:`emit_state_snapshots` — per-node ``rf.state_observed`` /
  ``sec.state_observed`` envelopes, **archived by the node's PRIMARY
  plane**: ``node_type=tuner`` → ``rf.*``; ``lnb``/``diseqc_switch`` →
  ``sec.*``.  The payload is the NodeEvalResult-shape JSON-safe
  projection (#161 metric key sets + ``health`` + the CauseRef chain +
  ``node_id`` + the constant observation-axes pairing
  ``state_evaluator``/``simulated`` — the SPEC-303 §Phase3 恒定配对, the
  honesty axis: state_evaluator products are never parsed/measured).
  ``severity`` is ``info``.  Nodes without evaluation facts (idle
  fallback / ``SIM_EVAL_NODE_FAILED`` isolation, ``metrics == {}``) and
  non-RF/SEC node types produce NO snapshot — no fabricated observations;
  failures surface through the walk's ``NodeFailure`` reports (#165's
  Run face), not through invented payloads.
- :func:`publish_topology_changes` — the envelope-publishing half of the
  ``topology.state_changed`` obligation (SPEC-202 §6.3; the pure-diff
  half is :func:`simulation.state.evaluate.changed_nodes`).  The payload
  carries the lexicographically sorted ``changed_nodes`` diff plus the
  ``degraded_node_count`` gauge input the SPEC-302 catalog derives from
  this event type (error/warn nodes of the current result).  No diff →
  no event (an unchanged evaluation publishes nothing).
- :data:`SIM_STATE_JOURNAL_EVENT_TYPES` / :func:`is_sim_state_journal_event_type`
  — the SIM_STATE Run journal composition contract (SPEC-303 §Phase3):
  ``rf.*/sec.*`` state_observed + ``topology.state_changed`` + ``fault.*``
  and **never ``gen.*``** (构造流水线事件是 TS 构造域；状态域 Generate
  产物即 state_observed 流，不冒充构造事件).  The Run orchestration
  wiring is ticket #165's composition-root face; the composition itself
  is pinned here so every producer asserts against one contract.

Honesty postures (ticket #164纪律): a UB conflict is never a separate
event — it is the tuner snapshot's ``lock_state="unlocked"`` + CauseRef
combination fact; no per-metric change stream is added (the #112
closed-full-stream precedent); ``tuning_message`` stays out of the
payload face (ruling A16 — SPEC-303 is the authority).

The emitter face is :meth:`simulation.events.SimulationEventEmitter.
state_event` (node-addressed correlation) and ``run_event`` (the
topology diff); both go through the shared ``_emit`` discipline — the
``is_registered`` guard (a no-op once #164 registered the types) and the
``parse_envelope`` construction guarantee.  This module is deliberately
NOT re-exported from the ``simulation.state`` package root — the frozen
export surface stays untouched (the evaluators subpackage precedent);
consumers import ``simulation.state.observation_bridge`` directly.
"""

from __future__ import annotations

from typing import Any, Mapping

from domain.observation.model import ConfidenceKind, ObservationSource
from domain.observation.registry import FAULT_EVENT_TYPES, TOPOLOGY_EVENT_TYPES
from simulation.events import SimulationEventEmitter
from simulation.state.evaluate import (
    Health,
    NodeEvalResult,
    TopologyEvalResult,
    changed_nodes,
)
from simulation.state.graph import TopologyGraph
from simulation.state.validate import (
    DISEQC_SWITCH_NODE_TYPE,
    LNB_NODE_TYPE,
    TUNER_NODE_TYPE,
)

__all__ = [
    "RF_STATE_OBSERVED",
    "SEC_STATE_OBSERVED",
    "SIM_STATE_JOURNAL_EVENT_TYPES",
    "STATE_EVENT_TYPE_BY_NODE_TYPE",
    "TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY",
    "TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY",
    "emit_state_snapshots",
    "is_sim_state_journal_event_type",
    "publish_topology_changes",
    "state_event_type_for",
    "state_snapshot_payload",
    "topology_state_changed_payload",
]

#: The ``rf.*`` state snapshot event type (tuner, SPEC-303 §Phase3).
RF_STATE_OBSERVED = "rf.state_observed"

#: The ``sec.*`` state snapshot event type (lnb / diseqc_switch).
SEC_STATE_OBSERVED = "sec.state_observed"

#: Node type → snapshot namespace: the primary-plane archiving table
#: (wire strings owned by the #160 validator; imported, never redefined).
STATE_EVENT_TYPE_BY_NODE_TYPE: Mapping[str, str] = {
    TUNER_NODE_TYPE: RF_STATE_OBSERVED,
    LNB_NODE_TYPE: SEC_STATE_OBSERVED,
    DISEQC_SWITCH_NODE_TYPE: SEC_STATE_OBSERVED,
}

#: ``topology.state_changed`` payload: the pure-diff node list.
TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY = "changed_nodes"

#: ``topology.state_changed`` payload: the SPEC-302 catalog's gauge input
#: (``topology.degraded_node_count`` — the metrics engine derives the
#: sample from this key, the derivation contract in the catalog module).
TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY = "degraded_node_count"

#: SIM_STATE Run journal composition (SPEC-303 §Phase3): the state
#: snapshot namespaces + the topology diff + the fault lifecycle — no
#: ``gen.*`` construction events, no ``ts.*`` stream faces.
SIM_STATE_JOURNAL_EVENT_TYPES = frozenset(
    {RF_STATE_OBSERVED, SEC_STATE_OBSERVED}
    | TOPOLOGY_EVENT_TYPES
    | FAULT_EVENT_TYPES
)

#: Health values counted as degraded (error > warn > idle > ok — idle is
#: the legal non-anomalous state, SPEC-202 §6.2).
_DEGRADED_HEALTHS = frozenset({Health.WARN, Health.ERROR})


def is_sim_state_journal_event_type(event_type: str) -> bool:
    """True when ``event_type`` belongs to the SIM_STATE Run composition."""
    return event_type in SIM_STATE_JOURNAL_EVENT_TYPES


def state_event_type_for(node_type: str) -> str | None:
    """The snapshot event type for ``node_type`` (None = no state face)."""
    return STATE_EVENT_TYPE_BY_NODE_TYPE.get(node_type)


def state_snapshot_payload(
    node_type: str, node_result: NodeEvalResult
) -> dict[str, Any]:
    """Project one ``NodeEvalResult`` into the registered payload shape.

    The metrics key sets ride verbatim (#161 evaluators own them — the
    registry's strict per-shape key sets are the drift lock: a new metric
    key without a payload registration fails at emission, never silently).
    ``health`` projects through ``.value`` (the str-Enum object itself
    must never enter the JSON payload — the R11 discipline); ``causes``
    project to ``{node_id, port_id}`` JSON-safe objects.

    Raises ``ValueError`` when ``node_type`` has no snapshot face (the
    emit path filters unmapped types first — calling this with one is a
    programmer error, not a skip).
    """
    if state_event_type_for(node_type) is None:
        raise ValueError(
            f"node type {node_type!r} has no state_observed snapshot face "
            "(SPEC-303 §Phase3 primary-plane archiving)"
        )
    health = node_result.health
    health_value = health.value if isinstance(health, Health) else health
    return {
        **node_result.metrics,
        "node_id": node_result.node_id,
        "health": health_value,
        "causes": [
            {"node_id": cause.node_id, "port_id": cause.port_id}
            for cause in node_result.causes
        ],
        "source": ObservationSource.STATE_EVALUATOR.value,
        "confidence": ConfidenceKind.SIMULATED.value,
    }


def emit_state_snapshots(
    emitter: SimulationEventEmitter,
    eval_result: TopologyEvalResult,
    *,
    graph: TopologyGraph,
    session_id: str,
    run_id: str,
    virtual_time_ns: int,
    severity: str = "info",
) -> tuple[dict[str, Any], ...]:
    """Emit one snapshot envelope per evaluated RF/SEC node, in walk order.

    ``graph`` supplies the node types (a ``NodeEvalResult`` carries no
    node type — the walk's product is typeless); the evaluation order is
    the deterministic topological order, so the journal order is
    deterministic too.  ``correlation.node_id`` addresses the observed
    node (the ADR-0006 decision 3 node-level form).  Returns the
    delivered documents (an empty tuple when nothing was observed).
    """
    documents: list[dict[str, Any]] = []
    for node_result in eval_result.node_results:
        if not node_result.metrics:
            # Idle fallback / SIM_EVAL_NODE_FAILED isolation: no facts to
            # observe — skipping is honest absence (缺失 ≠ 零), and the
            # failure report travels with the eval result, not here.
            continue
        node = graph.node(node_result.node_id)
        if node is None:  # defensive; cannot happen post-walk
            continue
        event_type = state_event_type_for(node.node_type)
        if event_type is None:
            continue  # non-RF/SEC node type — no snapshot face
        document = emitter.state_event(
            event_type,
            session_id,
            run_id,
            virtual_time_ns=virtual_time_ns,
            node_id=node_result.node_id,
            payload=state_snapshot_payload(node.node_type, node_result),
            severity=severity,
        )
        if document is not None:
            documents.append(document)
    return tuple(documents)


def topology_state_changed_payload(
    previous: TopologyEvalResult, current: TopologyEvalResult
) -> dict[str, Any] | None:
    """The frozen ``topology.state_changed`` payload (None = no diff).

    ``changed_nodes`` is the pure-diff half verbatim
    (:func:`simulation.state.evaluate.changed_nodes`, lexicographic); the
    ``degraded_node_count`` is the current result's error/warn node count
    — the derivation key the SPEC-302 catalog registered for this event
    type.
    """
    diff = changed_nodes(previous, current)
    if not diff:
        return None
    return {
        TOPOLOGY_STATE_CHANGED_CHANGED_NODES_KEY: list(diff),
        TOPOLOGY_STATE_CHANGED_DEGRADED_NODE_COUNT_KEY: _degraded_node_count(
            current
        ),
    }


def publish_topology_changes(
    emitter: SimulationEventEmitter,
    previous: TopologyEvalResult,
    current: TopologyEvalResult,
    *,
    session_id: str,
    run_id: str,
    virtual_time_ns: int,
    severity: str = "info",
) -> dict[str, Any] | None:
    """Publish the ``topology.state_changed`` envelope for a re-evaluation.

    The state-change propagation face of SPEC-303 §Phase3 (复用既有
    ``topology.state_changed`` 义务): the pure diff plus the degraded
    gauge input, delivered run-scoped with the default ``["simulation"]``
    tags (a graph-level event — no node correlation).  Identical results
    publish nothing and return ``None``.
    """
    payload = topology_state_changed_payload(previous, current)
    if payload is None:
        return None
    return emitter.run_event(
        "topology.state_changed",
        session_id,
        run_id,
        virtual_time_ns=virtual_time_ns,
        payload=payload,
        severity=severity,
    )


def _degraded_node_count(result: TopologyEvalResult) -> int:
    """Error/warn node count of ``result`` (the catalog gauge input)."""
    return sum(
        1 for node_result in result.node_results
        if node_result.health in _DEGRADED_HEALTHS
    )
