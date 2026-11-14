"""SPEC-201 — Simulation Clock: controlled virtual time, deterministic
and rational-speed realtime modes.

Time-domain separation (SPEC-201 section 3):

- ``virtual_time_ns`` is the simulation's single monotonic time: an int64
  nanosecond count from the session epoch that only ever moves forward.
- The wall clock is operational metadata only. It drives the *realtime*
  mode through an injected integer-nanosecond source (default
  ``time.monotonic_ns``) but never participates in event ordering and never
  enters deterministic TS bytes (CONTEXT.md 确定性复现).
- PCR/PTS/DTS are SPEC-105 media clock domains; conversions go exclusively
  through :mod:`simulation.clock_convert` (SPEC-201 section 6).

Modes (SPEC-201 section 5):

- ``deterministic``: virtual time moves only via explicit
  ``advance_to`` / ``advance_by`` (the deterministic scheduler commits
  time through the same calls). No wall clock involvement.
- ``realtime``: virtual time = frozen accumulator +
  (wall now - resume-point wall) * speed_num / speed_den, all in exact
  integer arithmetic (floats never touch time advancement).

Pause/resume (SPEC-201 section 5, SPEC-200 section 5.1): ``pause`` freezes
the accumulator in the same critical section that serializes ``advance``;
an advance requested while frozen raises ``SIM_CLOCK_PAUSED`` (reject —
the deliberate编排方-visible choice; queuing would be silent-deferral and
SPEC-201 section 8 forbids silent drops).

Error codes: see :mod:`simulation.errors` (SPEC-201 section 8).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Literal

from simulation.errors import (
    SimulationConfigError,
    SimulationPausedError,
    SimulationTimeBackwardsError,
)

#: Modes accepted by :class:`SimulationClockConfig` (SPEC-201 section 4).
ClockMode = Literal["deterministic", "realtime"]

_VALID_MODES: tuple[str, ...] = ("deterministic", "realtime")


def _require_int(value: object, field: str) -> int:
    """Type gate: numeric fields must be true ints (bools are not ints here).

    Non-integers are programming errors (``TypeError``); range violations
    are config errors (``SIM_CLOCK_CONFIG_INVALID``) — the split used by
    ``ts.pcr`` / ``ts.clock``.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class SimulationClockConfig:
    """Immutable clock configuration (SPEC-201 section 4).

    - ``mode``: ``deterministic`` or ``realtime``.
    - ``start_time_ns``: virtual time at session epoch, ``>= 0``.
    - ``speed_num`` / ``speed_den``: rational realtime speed, both ``> 0``;
      speed = ``speed_num / speed_den`` (rational integers only — no float
      ever participates in time advancement, SPEC-201 section 4).
    - ``tick_quantum_ns``: scheduler minimum advancement quantum, ``> 0``.
    """

    mode: ClockMode
    start_time_ns: int = 0
    speed_num: int = 1
    speed_den: int = 1
    tick_quantum_ns: int = 1_000_000

    def __post_init__(self) -> None:
        _require_int(self.start_time_ns, "start_time_ns")
        _require_int(self.speed_num, "speed_num")
        _require_int(self.speed_den, "speed_den")
        _require_int(self.tick_quantum_ns, "tick_quantum_ns")
        if self.mode not in _VALID_MODES:
            raise SimulationConfigError(
                f"mode must be one of {list(_VALID_MODES)}, got {self.mode!r}"
            )
        if self.start_time_ns < 0:
            raise SimulationConfigError(
                f"start_time_ns must be >= 0, got {self.start_time_ns}"
            )
        if self.speed_num <= 0:
            raise SimulationConfigError(
                f"speed_num must be > 0, got {self.speed_num}"
            )
        if self.speed_den <= 0:
            raise SimulationConfigError(
                f"speed_den must be > 0, got {self.speed_den}"
            )
        if self.tick_quantum_ns <= 0:
            raise SimulationConfigError(
                f"tick_quantum_ns must be > 0, got {self.tick_quantum_ns}"
            )


class SimulationClock:
    """The sandbox's single controllable clock (SPEC-201 section 5).

    One instance per session. All mutating operations (``advance_to`` /
    ``advance_by`` / ``pause`` / ``resume``) serialize on one
    :class:`asyncio.Lock` — the same critical section, so a pause can never
    interleave halfway through a time commitment (SPEC-200 section 5.1
    同临界区联动 at the clock boundary; the runtime-level state-machine
    coupling is SPEC-200's).

    ``wall_ns_source`` injects the wall clock in integer nanoseconds
    (default ``time.monotonic_ns``). It exists so realtime math is testable
    with exact integers (tests/README section 5 断言时钟纪律) — production
    code passes nothing.
    """

    def __init__(
        self,
        config: SimulationClockConfig,
        *,
        wall_ns_source: Callable[[], int] | None = None,
    ) -> None:
        self._config = config
        self._wall_ns_source: Callable[[], int] = (
            wall_ns_source if wall_ns_source is not None else time.monotonic_ns
        )
        self._lock = asyncio.Lock()
        self._paused = False
        # Frozen accumulator: the authoritative committed virtual time.
        # Deterministic mode: this IS the current virtual time.
        # Realtime mode: current virtual time = this value + (wall now -
        # resume-point wall) * speed_num // speed_den while running; the
        # accumulator is re-frozen on every pause and every explicit
        # advance (SPEC-201 section 5).
        self._virtual_ns = config.start_time_ns
        # Wall reading at the last resume (or construction, realtime only).
        # ``None`` while paused — the wall stretch during a pause is never
        # counted (REQ-SIM-201-003 freeze semantics).
        self._resume_wall_ns: int | None = (
            self._wall_ns_source() if config.mode == "realtime" else None
        )

    @property
    def config(self) -> SimulationClockConfig:
        """The immutable configuration this clock was built from."""
        return self._config

    def now_ns(self) -> int:
        """Current virtual time: monotonic int64 nanoseconds from epoch."""
        return self._now()

    def _now(self) -> int:
        """Compute current virtual time (lock-free read of committed state).

        Realtime running mode adds the wall-driven delta with pure integer
        arithmetic; a negative wall delta (a misbehaving injected source —
        ``time.monotonic_ns`` itself never goes backwards) clamps to zero so
        the monotonic invariant holds regardless of the source.
        """
        if self._resume_wall_ns is not None:
            elapsed = self._wall_ns_source() - self._resume_wall_ns
            if elapsed > 0:
                return (
                    self._virtual_ns
                    + elapsed * self._config.speed_num
                    // self._config.speed_den
                )
        return self._virtual_ns

    async def advance_to(self, target_ns: int) -> int:
        """Advance virtual time to ``target_ns``; return the reached ns.

        Deterministic mode commits the value directly; realtime mode jumps
        the frozen accumulator forward and re-anchors the resume wall point
        (an explicit orchestrator-driven jump, never a wall wait).
        ``target_ns <=`` current time raises ``SIM_CLOCK_TIME_BACKWARDS``;
        a request while frozen raises ``SIM_CLOCK_PAUSED``.
        """
        async with self._lock:
            return self._commit_locked(target_ns)

    async def advance_by(self, delta_ns: int) -> int:
        """Advance virtual time by ``delta_ns`` (> 0); return reached ns."""
        if not isinstance(delta_ns, int) or isinstance(delta_ns, bool):
            raise TypeError(
                f"delta_ns must be int, got {type(delta_ns).__name__}"
            )
        async with self._lock:
            return self._commit_locked(self._now() + delta_ns)

    async def pause(self) -> None:
        """Freeze virtual time in the same critical section as advance.

        Realtime mode: the wall-driven delta so far is folded into the
        frozen accumulator; wall time elapsed after this point never counts.
        Deterministic mode: only the frozen flag changes (no wall clock
        involved). Idempotent: pausing an already-frozen clock is a no-op.
        """
        async with self._lock:
            if self._paused:
                return
            self._virtual_ns = self._now()
            self._resume_wall_ns = None
            self._paused = True

    async def resume(self) -> None:
        """Re-anchor the wall resume point; continuation from frozen value.

        Idempotent: resuming a running clock is a no-op.
        """
        async with self._lock:
            if not self._paused:
                return
            # Only realtime mode owns a wall anchor; deterministic mode
            # stays wall-free forever (no wall clock involvement).
            self._resume_wall_ns = (
                self._wall_ns_source()
                if self._config.mode == "realtime"
                else None
            )
            self._paused = False

    def is_paused(self) -> bool:
        """Whether virtual time is currently frozen (SPEC-201 section 5)."""
        return self._paused

    def _commit_locked(self, target_ns: int) -> int:
        """Shared commit path; caller holds ``_lock``."""
        if not isinstance(target_ns, int) or isinstance(target_ns, bool):
            raise TypeError(
                f"target_ns must be int, got {type(target_ns).__name__}"
            )
        if self._paused:
            raise SimulationPausedError(
                f"advance requested at virtual time {self._virtual_ns} "
                "while the clock is frozen; resume first (SPEC-200 section "
                "5.1 routes pause/resume through the runtime)"
            )
        current = self._now()
        if target_ns <= current:
            raise SimulationTimeBackwardsError(
                f"advance target {target_ns} <= current virtual time "
                f"{current}; virtual time only moves forward"
            )
        self._virtual_ns = target_ns
        # Re-anchor: the committed jump becomes the new frozen base so the
        # wall-driven delta resumes scaling from the reached value.
        self._resume_wall_ns = (
            self._wall_ns_source() if self._config.mode == "realtime" else None
        )
        return target_ns
