"""Simulation runtime layer (SPEC-001 section 3.4).

MVP scope: the unified ``SimulationRuntime`` interface plus the TS runtime
implementation (ADR-0005 decisions 2 and 4). Depends on ``ts``, ``faults``
and ``adapters``; long tasks must be cancellable and must never block the API
event loop.

SPEC-201 (ticket #39) contributes the sandbox's single controllable clock
and the deterministic scheduler:

- :class:`simulation.clock.SimulationClockConfig` — frozen config:
  deterministic/realtime modes, rational speed, tick quantum.
- :class:`simulation.clock.SimulationClock` — monotonic int64
  ``virtual_time_ns``; pause/resume freeze semantics; all mutations share
  one critical section (SPEC-200 section 5.1 coupling point).
- :class:`simulation.scheduler.DeterministicScheduler` — frozen sort key
  ``(deadline_ns, priority, insertion_sequence)``, work budget against
  zero-duration callback storms, cancellable handles.
- :mod:`simulation.clock_convert` — the explicit ``virtual_time_ns``
  ↔ PCR/PTS conversion boundary; all 27 MHz/90 kHz modular arithmetic and
  wrap semantics are delegated to SPEC-105 (``ts.clock`` / ``ts.pcr``),
  never re-implemented.
- :mod:`simulation.errors` — the SPEC-201 section 8 and SPEC-202 section 8
  error codes.

SPEC-202 (ticket #40) contributes the State Engine skeleton via
:mod:`simulation.state`:

- :mod:`simulation.state.graph` — the frozen graph contract: nodes with
  named ports, port-level four-tuple connections, deterministic
  ``topological_order`` (nodeId lexicographic tie-break).
- :mod:`simulation.state.validate` — non-mutating, repeatable topology
  validation; every SPEC-202 section 5 rule reports as a path-addressed
  ``TopologyViolation`` with a stable ``SIM_TOPO_*`` code.
- :mod:`simulation.state.evaluate` — the frozen evaluation interface plus
  the deterministic skeleton walk: per-node evaluator dispatch (pure,
  injected), ``SIM_EVAL_NODE_FAILED`` isolation, severity precedence
  ``error > warn > idle > ok``, downstream causal reference threading and
  the pure ``changed_nodes`` diff. The full L0 node-semantics evaluation
  is an explicit stub deferred out of MVP (ADR-0005 decision 2;
  unregistered node types evaluate idle) — see
  ``simulation.state.evaluate.L0_DEFERRED_RATIONALE``.

Event emission (``simulation.clock_advanced``, the overload diagnostic and
``topology.state_changed``) is the envelope consumers' obligation
(SIM-C/D, SPEC-301); the clock, scheduler and state engine expose
hooks/diffs only and emit nothing themselves. Wall clock, random numbers,
paths and session IDs never participate in virtual time, event ordering or
evaluation results (CONTEXT.md 确定性复现).
"""

from simulation.clock import SimulationClock, SimulationClockConfig
from simulation.clock_convert import (
    NS_PER_SECOND,
    pcr_to_virtual_ns,
    pts90_to_virtual_ns,
    ticks27_to_virtual_ns,
    virtual_ns_to_ticks27,
    virtual_to_pcr,
    virtual_to_pts90,
)
from simulation.errors import (
    SIM_CLOCK_CONFIG_INVALID,
    SIM_CLOCK_PAUSED,
    SIM_CLOCK_TIME_BACKWARDS,
    SIM_SCHEDULER_OVERLOAD,
    SIM_TOPO_CARDINALITY,
    SIM_TOPO_CYCLE,
    SIM_TOPO_DIRECTION_INVALID,
    SIM_TOPO_DUPLICATE_ID,
    SIM_EVAL_NODE_FAILED,
    SIM_TOPO_ENDPOINT_MISSING,
    SIM_TOPO_MEDIA_INCOMPATIBLE,
    SIM_TOPO_SELF_LOOP,
    SimulationClockError,
    SimulationConfigError,
    SimulationError,
    SimulationPausedError,
    SimulationSchedulerError,
    SimulationTimeBackwardsError,
    SimulationTopologyError,
    TopologyCycleError,
)
from simulation.scheduler import (
    DeterministicScheduler,
    OverloadReport,
    ScheduledCallback,
)
from simulation.state import (
    CauseRef,
    Connection,
    ConnectionId,
    EvalContext,
    Health,
    L0_DEFERRED_RATIONALE,
    NodeConfig,
    NodeEvalResult,
    NodeEvaluator,
    NodeFailure,
    NodeId,
    PortDirection,
    PortId,
    PortSpec,
    PortState,
    SignalPlane,
    TopologyEvalResult,
    TopologyGraph,
    TopologyViolation,
    changed_nodes,
    evaluate_topology,
    severity_rank,
    topological_order,
    validate_topology,
)

__all__ = [
    # clock
    "SimulationClock",
    "SimulationClockConfig",
    # scheduler
    "DeterministicScheduler",
    "ScheduledCallback",
    "OverloadReport",
    # conversion boundary
    "NS_PER_SECOND",
    "virtual_ns_to_ticks27",
    "ticks27_to_virtual_ns",
    "virtual_to_pcr",
    "pcr_to_virtual_ns",
    "virtual_to_pts90",
    "pts90_to_virtual_ns",
    # errors (SPEC-201 section 8)
    "SIM_CLOCK_CONFIG_INVALID",
    "SIM_CLOCK_PAUSED",
    "SIM_CLOCK_TIME_BACKWARDS",
    "SIM_SCHEDULER_OVERLOAD",
    "SimulationError",
    "SimulationClockError",
    "SimulationConfigError",
    "SimulationTimeBackwardsError",
    "SimulationPausedError",
    "SimulationSchedulerError",
    # state engine skeleton (SPEC-202, ticket #40)
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
    "SIM_TOPO_CARDINALITY",
    "SIM_TOPO_CYCLE",
    "SIM_TOPO_DIRECTION_INVALID",
    "SIM_TOPO_DUPLICATE_ID",
    "SIM_TOPO_ENDPOINT_MISSING",
    "SIM_TOPO_MEDIA_INCOMPATIBLE",
    "SIM_TOPO_SELF_LOOP",
    "TopologyViolation",
    "validate_topology",
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
    "SimulationTopologyError",
    "TopologyCycleError",
]
