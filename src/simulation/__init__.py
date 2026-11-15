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
- :mod:`simulation.errors` — the SPEC-201 section 8 error codes.

Event emission (``simulation.clock_advanced`` and the overload diagnostic
event) is the envelope consumers' obligation (SIM-C/D, SPEC-301); the
clock and scheduler expose hooks/counters only and emit nothing
themselves. Wall clock, random numbers, paths and session IDs never
participate in virtual time or event ordering (CONTEXT.md 确定性复现).
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
    SimulationClockError,
    SimulationConfigError,
    SimulationError,
    SimulationPausedError,
    SimulationSchedulerError,
    SimulationTimeBackwardsError,
)
from simulation.scheduler import (
    DeterministicScheduler,
    OverloadReport,
    ScheduledCallback,
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
]
