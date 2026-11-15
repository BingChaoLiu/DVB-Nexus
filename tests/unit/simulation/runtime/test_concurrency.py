"""SPEC-200 §7 items 1/2 — command serialization and session isolation.

Traceability (SPEC-200 section 10):

- REQ-SIM-200-002  repeated start under concurrency still spawns exactly
  one worker (the per-session lock serializes the two racers)
  -> TestCommandSerialization
- REQ-SIM-200-004  sessions are isolated: one session's failure and event
  stream never touch another session's state or events
  -> TestSessionIsolation
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import InvalidLifecycleTransitionError
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))


async def _ready(runtime: SimulationRuntime, session_id: str) -> None:
    await runtime.create_session(b.session_spec(session_id=session_id))
    await runtime.validate_session(session_id)


class TestCommandSerialization:
    """并发命令在 per-session 锁下串行：终态唯一、worker 唯一."""

    def test_concurrent_start_spawns_exactly_one_worker(self) -> None:
        started: list[str] = []

        async def runner(spec) -> None:
            started.append(spec.session_id)
            await asyncio.Event().wait()

        async def main() -> None:
            runtime = SimulationRuntime(runner_factory=runner)
            await _ready(runtime, "cx-1")
            results = await asyncio.gather(
                runtime.start("cx-1"),
                runtime.start("cx-1"),
                return_exceptions=True,
            )
            ok = [r for r in results if not isinstance(r, BaseException)]
            refused = [r for r in results if isinstance(r, BaseException)]
            assert len(ok) == 1  # exactly one racer won the lock
            assert len(refused) == 1
            assert isinstance(refused[0], InvalidLifecycleTransitionError)
            await asyncio.sleep(0)
            assert started == ["cx-1"]  # exactly one worker, no duplicate
            await runtime.stop("cx-1")

        asyncio.run(main())

    def test_concurrent_pause_resume_lands_consistent_terminal(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _ready(runtime, "cx-2")
            await runtime.start("cx-2")
            # pause and resume race: serialized, so the second command sees
            # the first's committed state — the pair can't corrupt anything.
            await asyncio.gather(
                runtime.pause("cx-2"), runtime.resume("cx-2")
            )
            snapshot = await runtime.get_snapshot("cx-2")
            session = runtime._sessions["cx-2"]
            # The racing pair ends either PAUSED (pause won twice-queued?
            # no — both run) or RUNNING; lifecycle and clock always agree.
            assert snapshot.lifecycle in (
                LifecycleState.PAUSED,
                LifecycleState.RUNNING,
            )
            assert session.clock.is_paused() == (
                snapshot.lifecycle is LifecycleState.PAUSED
            )

        asyncio.run(main())

    def test_cross_session_commands_do_not_block_each_other(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            for sid in ("cx-3a", "cx-3b"):
                await _ready(runtime, sid)
                await runtime.start(sid)
            # Different sessions hold different locks: all four commands
            # complete concurrently without interleaving damage.
            await asyncio.gather(
                runtime.pause("cx-3a"),
                runtime.pause("cx-3b"),
                runtime.resume("cx-3a"),
                runtime.resume("cx-3b"),
            )
            for sid in ("cx-3a", "cx-3b"):
                snapshot = await runtime.get_snapshot(sid)
                assert snapshot.lifecycle is LifecycleState.RUNNING

        asyncio.run(main())


class TestSessionIsolation:
    """REQ-200-004: 单会话故障不外溢."""

    def test_failed_session_does_not_affect_sibling(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(
                b.session_spec(b.cyclic_graph(), session_id="bad")
            )
            await _ready(runtime, "good")
            with pytest.raises(Exception):
                await runtime.validate_session("bad")
            assert (await runtime.get_snapshot("bad")).lifecycle is (
                LifecycleState.FAILED
            )
            # The sibling keeps operating on its own lifecycle path.
            good_view = await runtime.start("good")
            assert good_view.lifecycle is LifecycleState.RUNNING
            await runtime.pause("good")
            assert (await runtime.get_snapshot("good")).lifecycle is (
                LifecycleState.PAUSED
            )

        asyncio.run(main())

    def test_event_streams_do_not_cross_sessions(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await runtime.create_session(
                b.session_spec(b.cyclic_graph(), session_id="bad")
            )
            await _ready(runtime, "good")
            with pytest.raises(Exception):
                await runtime.validate_session("bad")  # no event types exist
            await runtime.start("good")

            good_events = [
                event
                for event in sink.events
                if event["scope"]["session_id"] == "good"
            ]
            assert good_events, "sibling must emit its own events"
            assert all(
                event["scope"]["session_id"] == "good"
                for event in good_events
            )
            # The failed session's events stay addressed to itself (its
            # create event exists; the failure produced no cross-talk).
            bad_events = [
                event
                for event in sink.events
                if event["scope"]["session_id"] == "bad"
            ]
            assert [event["event_type"] for event in bad_events] == [
                "simulation.session_created"
            ]

        asyncio.run(main())

    def test_one_sessions_stuck_stop_does_not_block_the_other(self) -> None:
        async def main() -> None:
            async def stubborn(spec):
                suppressed = False
                while True:
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        if suppressed:
                            raise
                        suppressed = True
                        continue

            runtime = SimulationRuntime(
                runner_factory=stubborn, shutdown_timeout_s=0.0
            )
            await _ready(runtime, "a")
            await _ready(runtime, "b")
            await runtime.start("a")
            await runtime.start("b")
            await asyncio.sleep(0)
            await asyncio.gather(runtime.stop("a"), runtime.stop("b"))
            assert (await runtime.get_snapshot("a")).lifecycle is (
                LifecycleState.STOPPED
            )
            assert (await runtime.get_snapshot("b")).lifecycle is (
                LifecycleState.STOPPED
            )

        asyncio.run(main())
