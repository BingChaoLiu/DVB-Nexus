"""State Engine skeleton (SPEC-202, ticket #40) — public freeze surface.

SIM-E (#44, SPEC-204) depends on exactly this surface; any change to the
exported names or their annotations is an interface-freeze break and needs
a ticket-level ruling. The L0 node-semantics evaluation point is an
explicit stub deferred out of MVP (ADR-0005 decision 2) — see
:data:`simulation.state.evaluate.L0_DEFERRED_RATIONALE`.

Event obligation note (SPEC-202 section 6.3): state changes surface as the
pure diff :func:`changed_nodes`; publishing ``topology.state_changed``
through the SPEC-301 envelope is the envelope consumers' obligation
(SIM-C/D) — this package emits nothing.
"""

from simulation.state.evaluate import (
    SIM_EVAL_NODE_FAILED,
    CauseRef,
    EvalContext,
    Health,
    L0_DEFERRED_RATIONALE,
    NodeEvalResult,
    NodeEvaluator,
    NodeFailure,
    PortState,
    TopologyEvalResult,
    changed_nodes,
    evaluate_topology,
    severity_rank,
)
from simulation.state.graph import (
    Connection,
    ConnectionId,
    NodeConfig,
    NodeId,
    PortDirection,
    PortId,
    PortSpec,
    SignalPlane,
    TopologyGraph,
    topological_order,
)
from simulation.state.validate import (
    SIM_TOPO_CARDINALITY,
    SIM_TOPO_CYCLE,
    SIM_TOPO_DIRECTION_INVALID,
    SIM_TOPO_DUPLICATE_ID,
    SIM_TOPO_ENDPOINT_MISSING,
    SIM_TOPO_MEDIA_INCOMPATIBLE,
    SIM_TOPO_SELF_LOOP,
    SIM_TOPO_UB_PROTOCOL_MIXED,
    SIM_TOPO_UB_SLOT_CONFLICT,
    SIM_TOPO_UB_SLOT_OUT_OF_RANGE,
    SIM_TOPO_UB_SLOT_UNMATCHED,
    TopologyViolation,
    validate_topology,
)

__all__ = [
    # graph contract (SPEC-202 section 4)
    "Connection",
    "ConnectionId",
    "NodeConfig",
    "NodeId",
    "PortDirection",
    "PortId",
    "PortSpec",
    "SignalPlane",
    "TopologyGraph",
    "topological_order",
    # validation rules (SPEC-202 section 5 / section 8 codes)
    "SIM_TOPO_CARDINALITY",
    "SIM_TOPO_CYCLE",
    "SIM_TOPO_DIRECTION_INVALID",
    "SIM_TOPO_DUPLICATE_ID",
    "SIM_TOPO_ENDPOINT_MISSING",
    "SIM_TOPO_MEDIA_INCOMPATIBLE",
    "SIM_TOPO_SELF_LOOP",
    # Unicable UB validator codes (SPEC-003 §Phase3, ticket #160)
    "SIM_TOPO_UB_PROTOCOL_MIXED",
    "SIM_TOPO_UB_SLOT_CONFLICT",
    "SIM_TOPO_UB_SLOT_OUT_OF_RANGE",
    "SIM_TOPO_UB_SLOT_UNMATCHED",
    "TopologyViolation",
    "validate_topology",
    # evaluation interface + skeleton walk (SPEC-202 section 6 / section 8)
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
