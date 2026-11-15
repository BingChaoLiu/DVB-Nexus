"""SPEC-200 section 5.1 — pause/resume 与 SimulationClock 同临界区联动.

Traceability (SPEC-200 section 10):

- REQ-SIM-200-006  pause/resume couple with SimulationClock correctly;
  virtual time freezes while PAUSED -> TestFreezeSemantics
- (section 5.1)    state transition and clock mutation share one critical
  section: no observer can see a PAUSED session with a running clock or a
  RUNNING session with a frozen clock -> TestSameCriticalSection

Clock discipline (tests/README section 5): the realtime clock is driven by
an injected fake wall source (exact integers, no wall-clock waits); async
exercises go through ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_CLOCK_PAUSED,
    SimulationPausedError,
)
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime

from tests.unit.simulation.runtime import _sim_c_builders as b


class FakeWall:
    """Controllable integer-nanosecond wall source (SPEC-201 injection)."""

    def __init__(self) -> None:
        self.now = 1_000_000_000

    def __call__(self) -> int:
        return self.now


class TestFreezeSemantics:
    """PAUSED 期间虚拟时间冻结（realtime 以注入墙钟推进验证）。"""

    def test_paused_realtime_clock_freezes_and_resumes(self) -> None:
        async def main() -> None:
            wall = FakeWall()
            from simulation.clock import SimulationClockConfig

            spec = b.session_spec(
                clock_config=SimulationClockConfig(mode="realtime"),
                session_id="rt-1",
                deterministic=False,
            )
            runtime = SimulationRuntime(wall_ns_source=wall)
            await runtime.create_session(spec)
            await runtime.validate_session("rt-1")
            await runtime.start("rt-1")

            wall.now += 5_000_000_000  # wall moves while RUNNING
            view_running = await runtime.get_snapshot("rt-1")
            frozen_base = view_running.virtual_time_ns
            assert frozen_base >= 5_000_000_000

            await runtime.pause("rt-1")
            paused_view = await runtime.get_snapshot("rt-1")
            assert paused_view.lifecycle is LifecycleState.PAUSED

            wall.now += 7_000_000_000  # wall keeps moving while PAUSED
            after_wall = await runtime.get_snapshot("rt-1")
            # 暂停期间流逝的墙钟不计入虚拟时间.
            assert (
                after_wall.virtual_time_ns == paused_view.virtual_time_ns
            )

            await runtime.resume("rt-1")
            wall.now += 1_000_000  # wall counts again after resume
            resumed_view = await runtime.get_snapshot("rt-1")
            assert resumed_view.lifecycle is LifecycleState.RUNNING
            assert resumed_view.virtual_time_ns > after_wall.virtual_time_ns

        asyncio.run(main())

    def test_deterministic_advance_rejected_while_paused(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            spec = b.session_spec(session_id="det-1")
            await runtime.create_session(spec)
            await runtime.validate_session("det-1")
            await runtime.start("det-1")
            view = await runtime.get_snapshot("det-1")
            base = view.virtual_time_ns

            await runtime.pause("det-1")
            clock = runtime._sessions["det-1"].clock
            with pytest.raises(SimulationPausedError) as excinfo:
                await clock.advance_by(1_000_000)
            assert excinfo.value.code == SIM_CLOCK_PAUSED
            # frozen: nothing advanced
            after = await runtime.get_snapshot("det-1")
            assert after.virtual_time_ns == base

        asyncio.run(main())

    def test_clock_pause_not_exposed_as_public_runtime_api(self) -> None:
        # §5.1: clock 的 pause/resume 是 Runtime 内部编排接口，不直接暴露
        # UI/API 层 — the runtime's public face has no clock passthrough.
        public = [name for name in dir(SimulationRuntime) if not name.startswith("_")]
        assert not any("clock" in name.lower() for name in public)


class TestSameCriticalSection:
    """状态迁移与时钟冻结同一临界区：观察者永远看到一致的组合。"""

    def test_concurrent_pause_resume_snapshot_always_consistent(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            spec = b.session_spec(session_id="cs-1")
            await runtime.create_session(spec)
            await runtime.validate_session("cs-1")
            await runtime.start("cs-1")

            inconsistencies: list[str] = []

            async def observer() -> None:
                for _ in range(30):
                    snapshot = await runtime.get_snapshot("cs-1")
                    session = runtime._sessions["cs-1"]
                    paused_expected = snapshot.lifecycle is LifecycleState.PAUSED
                    if session.clock.is_paused() != paused_expected:
                        inconsistencies.append(
                            f"{snapshot.lifecycle.value}/"
                            f"clock_paused={session.clock.is_paused()}"
                        )
                    await asyncio.sleep(0)

            pause_task = asyncio.create_task(runtime.pause("cs-1"))
            resume_task = asyncio.create_task(runtime.resume("cs-1"))
            observe_task = asyncio.create_task(observer())
            await asyncio.gather(pause_task, resume_task, observe_task)

            assert inconsistencies == []
            final = await runtime.get_snapshot("cs-1")
            assert final.lifecycle is LifecycleState.RUNNING

        asyncio.run(main())

    def test_pause_from_running_only_and_resume_from_paused_only(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            spec = b.session_spec(session_id="cs-2")
            await runtime.create_session(spec)
            await runtime.validate_session("cs-2")
            with pytest.raises(Exception):
                await runtime.pause("cs-2")  # READY -> PAUSED is illegal
            await runtime.start("cs-2")
            await runtime.pause("cs-2")
            with pytest.raises(Exception):
                await runtime.pause("cs-2")  # PAUSED -> PAUSED is illegal
            await runtime.resume("cs-2")
            with pytest.raises(Exception):
                await runtime.resume("cs-2")  # RUNNING -> RUNNING is illegal

        asyncio.run(main())
