"""SPEC-201 Deterministic Scheduler — unit tests (ticket #39).

Traceability (SPEC-201 section 10 acceptance criteria):

- REQ-SIM-201-002  frozen sort key, stable reproducible ties
                   -> TestSchedulerOrdering, TestSchedulerDeterminism
- REQ-SIM-201-005  work budget + cancellation prevent starvation
                   -> TestWorkBudget, TestCallbackCancellation
- (time advance)   run_until drives virtual time to the target
                   -> TestRunUntil

No wall clock, no I/O: the scheduler runs against a deterministic-mode
SimulationClock; async behavior is exercised through ``asyncio.run``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class Recorder:
    """Order recorder: appends a tag on each callback execution."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def callback(self, tag: str):
        async def run() -> None:
            self.calls.append(tag)

        return run


def make_scheduler(**clock_overrides: object):
    from simulation.clock import SimulationClock, SimulationClockConfig
    from simulation.scheduler import DeterministicScheduler

    config = SimulationClockConfig(mode="deterministic", **clock_overrides)  # type: ignore[arg-type]
    clock = SimulationClock(config)
    scheduler = DeterministicScheduler(clock)
    return clock, scheduler


# ---------------------------------------------------------------------------
# REQ-SIM-201-002 — sort key frozen: (deadline_ns, priority, insertion seq)
# ---------------------------------------------------------------------------


class TestSchedulerOrdering:
    """REQ-SIM-201-002: 排序键冻结，deadline 越早越先；同 deadline 按
    priority 数值越小越高；再同按 insertion_sequence（入队先后）定序."""

    def test_deadline_is_the_primary_key(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        # Insert out of deadline order on purpose.
        scheduler.schedule(recorder.callback("late"), deadline_ns=300)
        scheduler.schedule(recorder.callback("mid"), deadline_ns=200)
        scheduler.schedule(recorder.callback("early"), deadline_ns=100)
        asyncio.run(scheduler.run_until(300))
        assert recorder.calls == ["early", "mid", "late"]
        assert clock.now_ns() == 300

    def test_same_deadline_smaller_priority_runs_first(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        scheduler.schedule(
            recorder.callback("p5"), deadline_ns=100, priority=5
        )
        scheduler.schedule(
            recorder.callback("p1"), deadline_ns=100, priority=1
        )
        scheduler.schedule(
            recorder.callback("p3"), deadline_ns=100, priority=3
        )
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["p1", "p3", "p5"]

    def test_full_tie_falls_back_to_insertion_sequence(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        for tag in ("first", "second", "third"):
            scheduler.schedule(recorder.callback(tag), deadline_ns=100)
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["first", "second", "third"]

    def test_priority_beats_insertion_order_at_same_deadline(self) -> None:
        """Insertion order does NOT override priority: the key is frozen."""
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        scheduler.schedule(
            recorder.callback("late-inserted-high"), deadline_ns=100, priority=0
        )
        scheduler.schedule(
            recorder.callback("early-inserted-low"), deadline_ns=100, priority=9
        )
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["late-inserted-high", "early-inserted-low"]

    def test_callbacks_beyond_target_remain_pending(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        scheduler.schedule(recorder.callback("due"), deadline_ns=50)
        scheduler.schedule(recorder.callback("beyond"), deadline_ns=500)
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["due"]
        assert scheduler.pending_count == 1
        assert clock.now_ns() == 100
        # A later run_until picks up the pending callback.
        asyncio.run(scheduler.run_until(500))
        assert recorder.calls == ["due", "beyond"]


class TestSchedulerDeterminism:
    """SPEC-201 section 7 item 5: 相同输入下调度序逐次一致."""

    def test_identical_inputs_produce_identical_event_order(self) -> None:
        import asyncio

        plan = [
            (300, 2, "a"),
            (100, 1, "b"),
            (100, 0, "c"),
            (200, 5, "d"),
            (100, 0, "e"),
            (200, 5, "f"),
        ]

        def replay() -> list[str]:
            recorder = Recorder()
            clock, scheduler = make_scheduler()
            for deadline, priority, tag in plan:
                scheduler.schedule(
                    recorder.callback(tag),
                    deadline_ns=deadline,
                    priority=priority,
                )
            asyncio.run(scheduler.run_until(300))
            return recorder.calls

        first = replay()
        second = replay()
        third = replay()
        assert first == second == third
        assert first == ["c", "e", "b", "d", "f", "a"]

    def test_mid_run_scheduling_enters_the_same_key_order(self) -> None:
        """Callbacks scheduled during execution join the same frozen key
        order (no wall/random/path/session input in the key)."""
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()

        def spawner(tag: str, deadline: int):
            async def run() -> None:
                recorder.calls.append(tag)
                scheduler.schedule(recorder.callback(f"{tag}-child"), deadline_ns=deadline)

            return run

        scheduler.schedule(spawner("parent", 0), deadline_ns=100)
        scheduler.schedule(recorder.callback("standalone"), deadline_ns=150)
        scheduler.schedule(spawner("late-parent", 50), deadline_ns=100, priority=1)
        asyncio.run(scheduler.run_until(200))
        # Mid-run scheduled callbacks join the same frozen key: parent's
        # child (deadline 0) sorts ahead of late-parent (deadline 100) the
        # moment it is enqueued — purely key-driven, deterministic.
        assert recorder.calls == [
            "parent",
            "parent-child",
            "late-parent",
            "late-parent-child",
            "standalone",
        ]


# ---------------------------------------------------------------------------
# run_until — time commitment semantics
# ---------------------------------------------------------------------------


class TestRunUntil:
    def test_run_until_reaches_target_and_returns_it(self) -> None:
        import asyncio

        clock, scheduler = make_scheduler()
        assert asyncio.run(scheduler.run_until(1_000)) == 1_000
        assert clock.now_ns() == 1_000

    def test_run_until_backwards_target_rejected(self) -> None:
        import asyncio

        from simulation.errors import (
            SIM_CLOCK_TIME_BACKWARDS,
            SimulationTimeBackwardsError,
        )

        clock, scheduler = make_scheduler()
        asyncio.run(scheduler.run_until(1_000))
        with pytest.raises(SimulationTimeBackwardsError) as excinfo:
            asyncio.run(scheduler.run_until(999))
        assert excinfo.value.code == SIM_CLOCK_TIME_BACKWARDS

    def test_run_until_with_no_pending_work_jumps_straight_to_target(self) -> None:
        import asyncio

        clock, scheduler = make_scheduler()
        asyncio.run(scheduler.run_until(10**9))
        assert clock.now_ns() == 10**9


# ---------------------------------------------------------------------------
# REQ-SIM-201-005 (part) — cancellation discipline
# ---------------------------------------------------------------------------


class TestCallbackCancellation:
    """取消后不执行；已开始执行的回调不被强杀."""

    def test_cancel_before_execution_prevents_run(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        cancelled = scheduler.schedule(recorder.callback("gone"), deadline_ns=100)
        kept = scheduler.schedule(recorder.callback("kept"), deadline_ns=100)
        assert cancelled.cancel() is True
        assert recorder.calls == []
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["kept"]
        assert scheduler.pending_count == 0

    def test_cancel_is_idempotent_and_reports_state(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        handle = scheduler.schedule(recorder.callback("x"), deadline_ns=100)
        assert handle.cancel() is True
        assert handle.cancel() is False  # already cancelled
        assert handle.is_cancelled() is True
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == []

    def test_cancel_after_execution_reports_not_cancelled(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        handle = scheduler.schedule(recorder.callback("ran"), deadline_ns=100)
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["ran"]
        assert handle.cancel() is False
        assert handle.is_cancelled() is False

    def test_running_callback_completes_before_cancel_could_matter(self) -> None:
        """已开始执行的回调不被强杀：run_until 等待其完成再继续.

        The running callback records both its start and its completion; the
        next callback observes the completion (cooperative, non-preemptive
        execution — SPEC-201 section 7 item 4)."""
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()

        async def long_running() -> None:
            recorder.calls.append("long:start")
            await asyncio.sleep(0)  # yield to the loop, still not killed
            recorder.calls.append("long:done")

        scheduler.schedule(long_running, deadline_ns=100)
        scheduler.schedule(recorder.callback("after"), deadline_ns=100)
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["long:start", "long:done", "after"]


# ---------------------------------------------------------------------------
# REQ-SIM-201-005 — work budget prevents starvation; overload is report-only
# ---------------------------------------------------------------------------


class TestWorkBudget:
    """REQ-SIM-201-005: work budget 与取消机制防饿死.

    Zero-duration self-rescheduling callbacks (the classic starvation
    storm) cannot hold time hostage: the budget bounds each iteration and
    the quantum forces time forward between them.
    """

    @staticmethod
    def make_storm_scheduler(
        work_budget: int, tick_quantum_ns: int
    ) -> tuple[object, object, object]:
        from simulation.clock import SimulationClock, SimulationClockConfig
        from simulation.scheduler import DeterministicScheduler

        clock = SimulationClock(
            SimulationClockConfig(
                mode="deterministic", tick_quantum_ns=tick_quantum_ns
            )
        )
        scheduler = DeterministicScheduler(clock, work_budget=work_budget)
        return clock, scheduler, None

    def test_self_rescheduling_storm_cannot_block_time(self) -> None:
        import asyncio

        clock, scheduler, _ = self.make_storm_scheduler(
            work_budget=5, tick_quantum_ns=1_000_000
        )

        def storm(tag: str):
            async def run() -> None:
                # Zero-length self-continuation: re-enqueue at the CURRENT
                # virtual time (SPEC-201 section 7 item 2 starvation hazard).
                scheduler.schedule(
                    lambda: storm(tag), deadline_ns=clock.now_ns()
                )

            return run()

        for i in range(10):
            scheduler.schedule(
                lambda i=i: storm(f"s{i}"), deadline_ns=0
            )

        reached = asyncio.run(scheduler.run_until(10_000_000))
        # Time advanced all the way to the target despite the storm.
        assert reached == 10_000_000
        assert clock.now_ns() == 10_000_000
        # Budget bounded every batch: 10 quantum steps + the arrival batch,
        # 5 executions each; storm children re-enqueued at the target
        # carry over deterministically.
        assert scheduler.executed_count == 5 * (10 + 1)
        assert scheduler.pending_count == 10

    def test_budget_exhaustion_defers_leftovers_to_next_loop(self) -> None:
        """超预算的回调顺延到下一循环（不丢失、不乱序）."""
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig
        from simulation.scheduler import DeterministicScheduler

        recorder = Recorder()
        clock = SimulationClock(
            SimulationClockConfig(mode="deterministic")
        )
        scheduler = DeterministicScheduler(clock, work_budget=3)
        for i in range(10):
            scheduler.schedule(
                recorder.callback(f"c{i:02d}"), deadline_ns=100
            )
        asyncio.run(scheduler.run_until(100))
        # Only the first budgeted batch executed; the rest stay queued in
        # insertion order for the next loop.
        assert recorder.calls == ["c00", "c01", "c02"]
        assert scheduler.pending_count == 7
        assert clock.now_ns() == 100

        # The next run_until continues exactly where this one stopped.
        asyncio.run(scheduler.run_until(100))
        assert recorder.calls == ["c00", "c01", "c02", "c03", "c04", "c05"]
        assert scheduler.pending_count == 4

    def test_overload_report_surfaced_not_raised(self) -> None:
        """SIM_SCHEDULER_OVERLOAD：报告诊断，不中断会话."""
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig
        from simulation.errors import SIM_SCHEDULER_OVERLOAD
        from simulation.scheduler import DeterministicScheduler

        clock = SimulationClock(
            SimulationClockConfig(
                mode="deterministic", tick_quantum_ns=1_000_000
            )
        )
        reports: list[object] = []
        scheduler = DeterministicScheduler(
            clock,
            work_budget=4,
            overload_threshold=3,
            on_overload=reports.append,
        )

        def storm() -> None:
            scheduler.schedule(storm, deadline_ns=clock.now_ns())

        scheduler.schedule(storm, deadline_ns=0)

        # 10 quantum steps of over-budget iterations: threshold 3 breached
        # several times over, yet run_until completes normally.
        reached = asyncio.run(scheduler.run_until(10_000_000))
        assert reached == 10_000_000
        assert len(reports) >= 1
        report = reports[0]
        assert report.code == SIM_SCHEDULER_OVERLOAD
        assert report.now_ns >= 0
        assert report.consecutive_over_budget_iterations >= 3
        assert scheduler.overload_report_count == len(reports)


# ---------------------------------------------------------------------------
# Scheduler construction guards
# ---------------------------------------------------------------------------


class TestSchedulerConstruction:
    def test_non_positive_budget_rejected(self) -> None:
        from simulation.scheduler import DeterministicScheduler

        clock, scheduler, _ = TestWorkBudget.make_storm_scheduler(1, 1)
        with pytest.raises(ValueError):
            DeterministicScheduler(clock, work_budget=0)
        with pytest.raises(ValueError):
            DeterministicScheduler(clock, overload_threshold=0)

    def test_non_integer_budget_rejected(self) -> None:
        from simulation.scheduler import DeterministicScheduler

        clock, scheduler, _ = TestWorkBudget.make_storm_scheduler(1, 1)
        with pytest.raises(TypeError):
            DeterministicScheduler(clock, work_budget=3.5)  # type: ignore[arg-type]

    def test_negative_deadline_rejected(self) -> None:
        import asyncio

        recorder = Recorder()
        clock, scheduler = make_scheduler()
        with pytest.raises(ValueError):
            scheduler.schedule(recorder.callback("x"), deadline_ns=-1)
