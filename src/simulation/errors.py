"""Simulation Engine error hierarchy (SPEC-201 section 8 and successors).

Code ownership follows the module-owned convention used across the repo
(TS-CORE-INTEGRATION-CONTRACT section 7 归属约定): each spec's error codes
live with the module that owns the spec — here, the simulation package.
Every :class:`SimulationError` carries its SPEC table code on ``code`` and
renders it as the ``"<CODE>: <message>"`` message prefix, matching the
``ts.errors`` / ``adapters.*`` message style.

SPEC-201 section 8 codes (this ticket, #39):

- ``SIM_CLOCK_TIME_BACKWARDS``  advance target <= current virtual time.
- ``SIM_CLOCK_CONFIG_INVALID``  config out of range (negative start,
  non-positive quantum/speed) — rejected at construction.
- ``SIM_CLOCK_PAUSED``          advance requested while frozen.
- ``SIM_SCHEDULER_OVERLOAD``    work budget persistently exceeded
  (report-only: the scheduler surfaces diagnostics, never interrupts the
  session — SPEC-201 section 8 row 4).
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
