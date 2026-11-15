"""Simulation Engine error hierarchy (SPEC-201 section 8 and successors).

Code ownership follows the module-owned convention used across the repo
(TS-CORE-INTEGRATION-CONTRACT section 7 归属约定): each spec's error codes
live with the module that owns the spec — here, the simulation package.
Every :class:`SimulationError` carries its SPEC table code on ``code`` and
renders it as the ``"<CODE>: <message>"`` message prefix, matching the
``ts.errors`` / ``adapters.*`` message style.

SPEC-201 section 8 codes (ticket #39):

- ``SIM_CLOCK_TIME_BACKWARDS``  advance target <= current virtual time.
- ``SIM_CLOCK_CONFIG_INVALID``  config out of range (negative start,
  non-positive quantum/speed) — rejected at construction.
- ``SIM_CLOCK_PAUSED``          advance requested while frozen.
- ``SIM_SCHEDULER_OVERLOAD``    work budget persistently exceeded
  (report-only: the scheduler surfaces diagnostics, never interrupts the
  session — SPEC-201 section 8 row 4).

SPEC-202 section 8 codes (ticket #40, appended — SPEC-202 §5/§8):

- ``SIM_TOPO_DUPLICATE_ID``       nodeId / portId / connectionId conflict.
- ``SIM_TOPO_ENDPOINT_MISSING``   connection references a nonexistent
  node/port.
- ``SIM_TOPO_DIRECTION_INVALID``  output->output, input->input (or any
  from-side without output capability / to-side without input capability).
- ``SIM_TOPO_MEDIA_INCOMPATIBLE`` plane mismatch on a link.
- ``SIM_TOPO_CARDINALITY``        maxConnections exceeded on a port.
- ``SIM_TOPO_SELF_LOOP``          from == to (same node, same port).
- ``SIM_TOPO_CYCLE``              topology contains a cycle (MVP rejects;
  a DAG is required for deterministic evaluation).
- ``SIM_EVAL_NODE_FAILED``        evaluator-internal exception — the node
  is isolated as error health and the report is surfaced; the whole-graph
  evaluation never crashes (report path in ``simulation.state.evaluate``).
"""

from __future__ import annotations

#: SPEC-201 section 8 — advance target <= current virtual time.
SIM_CLOCK_TIME_BACKWARDS = "SIM_CLOCK_TIME_BACKWARDS"

#: SPEC-201 section 8 — config out of range, rejected at construction.
SIM_CLOCK_CONFIG_INVALID = "SIM_CLOCK_CONFIG_INVALID"

#: SPEC-201 section 8 — advance requested while the clock is frozen.
SIM_CLOCK_PAUSED = "SIM_CLOCK_PAUSED"

#: SPEC-201 section 8 — work budget persistently exceeded (report-only).
SIM_SCHEDULER_OVERLOAD = "SIM_SCHEDULER_OVERLOAD"

# --- SPEC-202 section 8 (ticket #40) -----------------------------------------

#: SPEC-202 section 8 — nodeId / portId / connectionId conflict.
SIM_TOPO_DUPLICATE_ID = "SIM_TOPO_DUPLICATE_ID"

#: SPEC-202 section 8 — connection references a nonexistent node/port.
SIM_TOPO_ENDPOINT_MISSING = "SIM_TOPO_ENDPOINT_MISSING"

#: SPEC-202 section 8 — illegal direction pairing on a link.
SIM_TOPO_DIRECTION_INVALID = "SIM_TOPO_DIRECTION_INVALID"

#: SPEC-202 section 8 — plane mismatch on a link.
SIM_TOPO_MEDIA_INCOMPATIBLE = "SIM_TOPO_MEDIA_INCOMPATIBLE"

#: SPEC-202 section 8 — maxConnections exceeded on a port.
SIM_TOPO_CARDINALITY = "SIM_TOPO_CARDINALITY"

#: SPEC-202 section 8 — self loop (same node, same port).
SIM_TOPO_SELF_LOOP = "SIM_TOPO_SELF_LOOP"

#: SPEC-202 section 8 — topology contains a cycle (MVP rejects).
SIM_TOPO_CYCLE = "SIM_TOPO_CYCLE"

#: SPEC-202 section 8 — evaluator-internal exception; the node is isolated
#: as error health and the failure reported (never crashes the whole graph).
SIM_EVAL_NODE_FAILED = "SIM_EVAL_NODE_FAILED"


class SimulationError(Exception):
    """Base class for every error owned by the simulation package.

    Subclasses own exactly one SPEC table row via the ``code`` class
    attribute (SPEC-201 section 8 for this ticket).
    """

    code: str = "SIMULATION_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


class SimulationClockError(SimulationError):
    """Base class for simulation clock failures (SPEC-201 section 8)."""


class SimulationConfigError(SimulationClockError):
    """``SIM_CLOCK_CONFIG_INVALID``: config 越界（负 start、非正量子/倍速）."""

    code = SIM_CLOCK_CONFIG_INVALID


class SimulationTimeBackwardsError(SimulationClockError):
    """``SIM_CLOCK_TIME_BACKWARDS``: advance 目标 <= 当前虚拟时间."""

    code = SIM_CLOCK_TIME_BACKWARDS


class SimulationPausedError(SimulationClockError):
    """``SIM_CLOCK_PAUSED``: 冻结期间请求 advance（拒绝，编排方可见）."""

    code = SIM_CLOCK_PAUSED


class SimulationSchedulerError(SimulationError):
    """Base class for deterministic scheduler failures (SPEC-201 section 7)."""


class SimulationTopologyError(SimulationError):
    """Base class for state-engine topology failures (SPEC-202 section 8)."""


class TopologyCycleError(SimulationTopologyError):
    """``SIM_TOPO_CYCLE``: 拓扑含环，MVP 拒绝（确定性求值需要 DAG）."""

    code = SIM_TOPO_CYCLE
