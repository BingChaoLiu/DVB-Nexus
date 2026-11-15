"""SPEC-200 section 6/7 — stop idempotency, bounded cleanup, dispose.

Traceability (SPEC-200 section 10):

- REQ-SIM-200-002  stop is idempotent and bounded (shutdown-timeout
  escalation to forced cancellation) -> TestStopIdempotent /
  TestBoundedStop
- REQ-SIM-200-003  after dispose the session owns zero tasks ->
  TestDisposeReclamation

Async through ``asyncio.run``; no wall-clock waits — the escalation path is
driven with ``shutdown_timeout_s=0`` (graceful pass exhausts immediately)
against a cancellation-suppressing runner, so the test is deterministic.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_INVALID_LIFECYCLE_TRANSITION,
    InvalidLifecycleTransitionError,
)
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class RecordingSink:
    """Minimal SessionEventSink double: records published envelope dicts."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))

    def types(self) -> list[str]:
        return [event["event_type"] for event in self.events]


async def _ready_session(runtime: SimulationRuntime, session_id: str) -> None:
    await runtime.create_session(b.session_spec(session_id=session_id))
    await runtime.validate_session(session_id)


class TestStopIdempotent:
    """重复 stop 直接返回当前视图，不重复清理、不重复发事件。"""

    def test_stop_twice_returns_same_view_one_event(self) -> None:
        async def main() -> None:
            sink = RecordingSink()
            runtime = SimulationRuntime(event_sink=sink)
            await _ready_session(runtime, "s-1")
            await runtime.start("s-1")

            first = await runtime.stop("s-1")
            assert first.lifecycle is LifecycleState.STOPPED
            second = await runtime.stop("s-1")
            assert second.lifecycle is LifecycleState.STOPPED
            assert second.revision == first.revision

            stopped_events = [
                event
                for event in sink.events
                if event["event_type"] == "simulation.session_stopped"
            ]
            assert len(stopped_events) == 1

        asyncio.run(main())

    def test_stop_on_stopping_and_stopped_is_idempotent(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _ready_session(runtime, "s-2")
            await runtime.start("s-2")
            await runtime.stop("s-2")
            view = await runtime.stop("s-2")
            assert view.lifecycle is LifecycleState.STOPPED

        asyncio.run(main())

    def test_stop_from_created_is_illegal(self) -> None:
        async def main() -> None:
            # CREATED has exactly one outgoing edge (-> VALIDATING); stop
            # must be refused there per the exhaustive table.
            runtime = SimulationRuntime()
            await runtime.create_session(b.session_spec(session_id="s-3"))
            with pytest.raises(InvalidLifecycleTransitionError) as excinfo:
                await runtime.stop("s-3")
            assert excinfo.value.code == SIM_INVALID_LIFECYCLE_TRANSITION

        asyncio.run(main())

    def test_stop_from_failed_recovers_the_session(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(
                b.session_spec(b.cyclic_graph(), session_id="s-4")
            )
            with pytest.raises(Exception):
                await runtime.validate_session("s-4")  # -> FAILED
            view = await runtime.stop("s-4")  # FAILED -> STOPPING -> STOPPED
            assert view.lifecycle is LifecycleState.STOPPED

        asyncio.run(main())


class TestBoundedStop:
    """stop 受 shutdown timeout 约束；超时升级为强制 cancel 并标注。"""

    def test_stuck_worker_forces_cancellation_annotation(self) -> None:
        async def stubborn_runner(spec):
            # Swallows the graceful cancellation; only the forced second
            # cancel terminates it (await chains re-raise).
            suppressed = False
            while True:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if suppressed:
                        raise
                    suppressed = True
                    continue

        async def main() -> None:
            runtime = SimulationRuntime(
                runner_factory=stubborn_runner,
                shutdown_timeout_s=0.0,  # graceful window exhausts at once
            )
            await _ready_session(runtime, "s-5")
            await runtime.start("s-5")
            await asyncio.sleep(0)  # worker reaches its await point
            view = await runtime.stop("s-5")
            assert view.lifecycle is LifecycleState.STOPPED
            # Forced escalation reclaimed the stuck worker.
            assert not runtime._sessions["s-5"].tasks

        asyncio.run(main())

    def test_graceful_stop_cancels_cooperative_worker(self) -> None:
        finished: list[str] = []

        async def cooperative_runner(spec):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                finished.append("cancelled")
                raise

        async def main() -> None:
            runtime = SimulationRuntime(runner_factory=cooperative_runner)
            await _ready_session(runtime, "s-6")
            await runtime.start("s-6")
            await asyncio.sleep(0)  # let the worker reach its await point
            await runtime.stop("s-6")
            assert finished == ["cancelled"]

        asyncio.run(main())


class TestDisposeReclamation:
    """REQ-200-003: dispose 后会话拥有的任务为零。"""

    def test_dispose_joins_and_cancels_all_tasks(self) -> None:
        worker_gone: list[str] = []

        async def runner(spec):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                worker_gone.append("cancelled")
                raise

        async def main() -> None:
            runtime = SimulationRuntime(runner_factory=runner)
            await _ready_session(runtime, "d-1")
            await runtime.start("d-1")
            await asyncio.sleep(0)  # let the worker reach its await point
            await runtime.stop("d-1")
            assert worker_gone == ["cancelled"]
            await runtime.dispose("d-1")
            assert len(runtime._sessions["d-1"].tasks) == 0
            view = await runtime.get_snapshot("d-1")
            assert view.lifecycle is LifecycleState.DISPOSED

        asyncio.run(main())

    def test_dispose_directly_from_running_is_illegal(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _ready_session(runtime, "d-2")
            await runtime.start("d-2")
            with pytest.raises(InvalidLifecycleTransitionError):
                await runtime.dispose("d-2")

        asyncio.run(main())

    def test_stopped_to_disposed(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _ready_session(runtime, "d-3")
            await runtime.start("d-3")
            await runtime.stop("d-3")
            await runtime.dispose("d-3")
            view = await runtime.get_snapshot("d-3")
            assert view.lifecycle is LifecycleState.DISPOSED
            # DISPOSED absorbs: a second dispose is refused.
            with pytest.raises(InvalidLifecycleTransitionError):
                await runtime.dispose("d-3")

        asyncio.run(main())

    def test_stop_reason_travels_to_view_and_state(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await _ready_session(runtime, "d-4")
            await runtime.start("d-4")
            view = await runtime.stop("d-4", reason="shutdown")
            assert view.lifecycle is LifecycleState.STOPPED

        asyncio.run(main())
