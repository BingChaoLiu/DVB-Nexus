"""SPEC-201 section 7 — deterministic scheduler.

Sorting key (frozen, SPEC-201 section 7 item 1)::

    (deadline_ns, priority, insertion_sequence)

Earliest deadline first; equal deadlines run smaller ``priority`` values
first (smaller = more urgent); full ties resolve by insertion sequence.
The key contains ONLY these three fields — wall clock, random numbers,
paths and session IDs are structurally incapable of influencing event
order (SPEC-201 section 7 item 5, CONTEXT.md 确定性复现).

Work budget (item 2): a single scheduler iteration executes at most
``work_budget`` due callbacks. Zero-duration self-rescheduling callbacks
cannot starve time advancement: once the budget is exhausted the
iteration ends, the scheduler advances virtual time (by the clock's
``tick_quantum_ns``), and the leftover due callbacks run in the next
iteration (顺延到下一循环). Persistently exceeding the budget raises the
``SIM_SCHEDULER_OVERLOAD`` diagnostic through the ``on_overload`` hook —
report-only, the session is never interrupted (SPEC-201 section 8 row 4).
Event emission for that diagnostic belongs to the envelope consumers
(SIM-C/D); this module only surfaces the report and counters.

Callback discipline (item 3/4): callbacks must not block (long work goes
to a bounded worker per SPEC-203); a callback may be cancelled any time
before its execution starts, a started callback always runs to
completion (cooperative, never preempted).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable

from simulation.clock import SimulationClock
from simulation.errors import (
    SIM_SCHEDULER_OVERLOAD,
    SimulationTimeBackwardsError,
)

#: Default per-iteration callback budget (SPEC-201 section 7 item 2).
DEFAULT_WORK_BUDGET: int = 64

#: Default consecutive over-budget iterations before an overload report
#: is surfaced (SPEC-201 section 8 row 4 配置阈值).
DEFAULT_OVERLOAD_THRESHOLD: int = 8

__all__ = [
    "DEFAULT_OVERLOAD_THRESHOLD",
    "DEFAULT_WORK_BUDGET",
    "OverloadReport",
    "SchedulerOverloadReport",
    "ScheduledCallback",
    "DeterministicScheduler",
    "SIM_SCHEDULER_OVERLOAD",
]


@dataclass(frozen=True)
class OverloadReport:
    """``SIM_SCHEDULER_OVERLOAD`` diagnostic payload (report-only).

    Surfaced through the ``on_overload`` hook when the work budget has
    been exceeded for ``overload_threshold`` consecutive iterations. The
    session continues; envelope consumers decide whether/how to publish
    the diagnostic event (SPEC-301; not this module's obligation).
    """

    code: str = SIM_SCHEDULER_OVERLOAD
    consecutive_over_budget_iterations: int = 0
    pending_due_count: int = 0
    now_ns: int = 0


#: Alias kept explicit for readability in hook signatures.
SchedulerOverloadReport = OverloadReport


class ScheduledCallback:
    """Cancellable handle for one scheduled callback.

    ``cancel`` fully removes the callback if it has not started executing
    (SPEC-201 section 7 item 4); once execution started, cancellation is
    refused — a running callback is never preempted, it must exit
    cooperatively.
    """

    __slots__ = ("_state",)

    def __init__(self, state: "_Entry") -> None:
        self._state = state

    def cancel(self) -> bool:
        """Cancel before execution: True on first successful cancel."""
        state = self._state
        if state.executed or state.cancelled:
            return False
        state.cancelled = True
        return True

    def is_cancelled(self) -> bool:
        """Whether this callback was cancelled before it could run."""
        return self._state.cancelled


@dataclass
class _Entry:
    """Heap entry: the frozen sort key plus execution bookkeeping."""

    deadline_ns: int
    priority: int
    sequence: int
    callback: Callable[[], object]
    cancelled: bool = field(default=False)
    executed: bool = field(default=False)

    @property
    def key(self) -> tuple[int, int, int]:
        """The frozen sort key (deadline, priority, insertion sequence)."""
        return (self.deadline_ns, self.priority, self.sequence)

    def __lt__(self, other: "_Entry") -> bool:
        """Heap ordering IS the frozen sort key (never insertion order)."""
        return self.key < other.key


class DeterministicScheduler:
    """Event scheduler over a :class:`SimulationClock` (SPEC-201 section 7).

    Time commitment happens exclusively through the clock's
    ``advance_to`` (deterministic mode): virtual time only moves via
    scheduler commits or explicit clock advances — never via the wall
    clock (SPEC-201 section 5).
    """

    def __init__(
        self,
        clock: SimulationClock,
        *,
        work_budget: int = DEFAULT_WORK_BUDGET,
        overload_threshold: int = DEFAULT_OVERLOAD_THRESHOLD,
        on_overload: Callable[[OverloadReport], object] | None = None,
    ) -> None:
        if not isinstance(work_budget, int) or isinstance(work_budget, bool):
            raise TypeError(
                f"work_budget must be int, got {type(work_budget).__name__}"
            )
        if work_budget <= 0:
            raise ValueError(f"work_budget must be > 0, got {work_budget}")
        if not isinstance(overload_threshold, int) or isinstance(
            overload_threshold, bool
        ):
            raise TypeError(
                "overload_threshold must be int, got "
                f"{type(overload_threshold).__name__}"
            )
        if overload_threshold <= 0:
            raise ValueError(
                f"overload_threshold must be > 0, got {overload_threshold}"
            )
        self._clock = clock
        self._work_budget = work_budget
        self._overload_threshold = overload_threshold
        self._on_overload = on_overload
        self._heap: list[_Entry] = []
        self._next_sequence = 0
        self._executed_count = 0
        self._overload_report_count = 0

    # -- introspection (deterministic counters, no wall clock) ----------

    @property
    def pending_count(self) -> int:
        """Callbacks currently queued (cancelled entries not counted)."""
        return sum(
            1
            for entry in self._heap
            if not entry.cancelled and not entry.executed
        )

    @property
    def executed_count(self) -> int:
        """Total callbacks executed since construction."""
        return self._executed_count

    @property
    def cancelled_count(self) -> int:
        """Total callbacks cancelled before execution."""
        return sum(1 for entry in self._heap if entry.cancelled)

    @property
    def overload_report_count(self) -> int:
        """Total ``SIM_SCHEDULER_OVERLOAD`` reports surfaced so far."""
        return self._overload_report_count

    # -- scheduling ------------------------------------------------------

    def schedule(
        self,
        callback: Callable[[], object],
        *,
        deadline_ns: int,
        priority: int = 0,
    ) -> ScheduledCallback:
        """Enqueue ``callback`` at absolute virtual ``deadline_ns``.

        The insertion sequence is handed out in call order — the same
        schedule-call sequence therefore reproduces the same event order
        run after run (determinism, SPEC-201 section 7 item 5).
        """
        if not isinstance(deadline_ns, int) or isinstance(deadline_ns, bool):
            raise TypeError(
                f"deadline_ns must be int, got {type(deadline_ns).__name__}"
            )
        if deadline_ns < 0:
            raise ValueError(
                f"deadline_ns must be >= 0, got {deadline_ns}"
            )
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError(
                f"priority must be int, got {type(priority).__name__}"
            )
        entry = _Entry(
            deadline_ns=deadline_ns,
            priority=priority,
            sequence=self._next_sequence,
            callback=callback,
        )
        self._next_sequence += 1
        heapq.heappush(self._heap, entry)
        return ScheduledCallback(entry)

    # -- the deterministic run loop --------------------------------------

    async def run_until(self, target_ns: int) -> int:
        """Execute all callbacks due before ``target_ns``; return the
        virtual time reached.

        Iteration shape (per SPEC-201 section 7 item 2):

        1. Commit time forward to the next due deadline or the target,
           whichever comes first.
        2. Execute due callbacks in frozen key order, at most
           ``work_budget`` of them.
        3. If the budget was exhausted with callbacks still due, note an
           over-budget iteration, then force the clock forward by
           ``tick_quantum_ns`` — time advancement can never be starved.

        On reaching ``target_ns`` one final bounded batch of due
        callbacks executes; zero-length self-rescheduling callbacks that
        re-enqueue during that batch stay queued for the next ``run_until``
        (deterministic carry-over — the target time itself is always
        reached).
        """
        now = self._clock.now_ns()
        if target_ns < now:
            raise SimulationTimeBackwardsError(
                f"run_until target {target_ns} is behind current virtual "
                f"time {now}"
            )

        consecutive_over_budget = 0
        while self._clock.now_ns() < target_ns:
            now = self._clock.now_ns()
            executed = await self._execute_due(now)
            now = self._clock.now_ns()
            over_budget = executed == self._work_budget and self._has_due(now)
            if over_budget:
                consecutive_over_budget += 1
                if (
                    consecutive_over_budget >= self._overload_threshold
                    and self._on_overload is not None
                ):
                    self._overload_report_count += 1
                    self._on_overload(
                        OverloadReport(
                            consecutive_over_budget_iterations=(
                                consecutive_over_budget
                            ),
                            pending_due_count=self.pending_count,
                            now_ns=now,
                        )
                    )
                # Force time forward by the scheduler quantum: zero-length
                # self-rescheduling callbacks must not starve advancement.
                step_end = min(
                    now + self._clock.config.tick_quantum_ns, target_ns
                )
                if step_end > now:
                    await self._clock.advance_to(step_end)
            else:
                consecutive_over_budget = 0
                if self._clock.now_ns() < target_ns:
                    # Nothing due right now (budget was not exhausted):
                    # jump to the next milestone, never beyond the target.
                    next_deadline = self._next_live_deadline()
                    if (
                        next_deadline is None
                        or next_deadline > target_ns
                    ):
                        milestone = target_ns
                    else:
                        milestone = next_deadline
                    if milestone > self._clock.now_ns():
                        await self._clock.advance_to(milestone)

        # Arrival batch: everything due at the target runs now (bounded by
        # the budget); storm children re-enqueued during it carry over.
        await self._execute_due(target_ns)
        return self._clock.now_ns()

    # -- internals --------------------------------------------------------

    def _has_due(self, now: int) -> bool:
        for entry in self._heap:
            if entry.cancelled or entry.executed:
                continue
            if entry.deadline_ns <= now:
                return True
        return False

    def _next_live_deadline(self) -> int | None:
        """Earliest deadline among live entries (None if none pending)."""
        best: int | None = None
        for entry in self._heap:
            if entry.cancelled or entry.executed:
                continue
            if best is None or entry.deadline_ns < best:
                best = entry.deadline_ns
        return best

    def _pop_next_due(self, now: int) -> _Entry | None:
        """Pop the minimal-key live entry due at ``now`` (lazy cancel)."""
        while self._heap:
            entry = heapq.heappop(self._heap)
            if entry.cancelled:
                continue
            if entry.executed:
                continue
            if entry.deadline_ns <= now:
                return entry
            # Not due yet: push back and stop (heap is key-ordered).
            heapq.heappush(self._heap, entry)
            return None
        return None

    async def _execute_due(self, now: int) -> int:
        """Execute up to ``work_budget`` due callbacks in key order."""
        executed = 0
        while executed < self._work_budget:
            entry = self._pop_next_due(now)
            if entry is None:
                break
            entry.executed = True
            result = entry.callback()
            # Callback discipline (SPEC-201 section 7 item 3): async
            # callbacks are awaited to completion (never preempted);
            # synchronous returns are accepted for trivial work.
            if hasattr(result, "__await__"):
                await result  # type: ignore[arg-type]
            executed += 1
            self._executed_count += 1
        return executed
