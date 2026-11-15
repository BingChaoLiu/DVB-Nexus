"""SPEC-201 Simulation Clock — unit tests (ticket #39).

Traceability (SPEC-201 section 10 acceptance criteria):

- REQ-SIM-201-001  virtual time monotonic, backwards rejected -> TestClockMonotonic
- REQ-SIM-201-003  pause freezes, resume resumes symmetrically -> TestPauseFreeze
- REQ-SIM-201-004  rational speed, integer arithmetic only    -> TestRealtimeRationalSpeed
- (concurrency)    pause/clock share one critical section     -> TestPauseAdvanceConcurrency

Determinism discipline (tests/README section 5): no wall-clock waits and no
uncontrolled wall clock reads — the realtime clock is driven by an injected
fake wall source, so every assertion is over exact integers. Async behavior
is exercised through ``asyncio.run`` (no pytest-asyncio dependency; the dev
dependency set is frozen by the orchestrator).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# SimulationClockConfig — construction validation (SPEC-201 section 4)
# ---------------------------------------------------------------------------


class TestClockConfig:
    """SPEC-201 section 4: 数值字段范围校验，越界构造时拒绝."""

    def test_default_config_is_valid_deterministic(self) -> None:
        from simulation.clock import SimulationClockConfig

        config = SimulationClockConfig(mode="deterministic")
        assert config.mode == "deterministic"
        assert config.start_time_ns == 0
        assert config.speed_num == 1
        assert config.speed_den == 1
        assert config.tick_quantum_ns == 1_000_000

    def test_config_is_frozen(self) -> None:
        from simulation.clock import SimulationClockConfig

        config = SimulationClockConfig(mode="realtime")
        with pytest.raises(Exception):
            config.start_time_ns = 10  # type: ignore[misc]

    def test_negative_start_time_rejected(self) -> None:
        from simulation.clock import SimulationClockConfig
        from simulation.errors import (
            SIM_CLOCK_CONFIG_INVALID,
            SimulationConfigError,
        )

        with pytest.raises(SimulationConfigError) as excinfo:
            SimulationClockConfig(mode="deterministic", start_time_ns=-1)
        assert excinfo.value.code == SIM_CLOCK_CONFIG_INVALID

    def test_non_positive_tick_quantum_rejected(self) -> None:
        from simulation.clock import SimulationClockConfig
        from simulation.errors import (
            SIM_CLOCK_CONFIG_INVALID,
            SimulationConfigError,
        )

        with pytest.raises(SimulationConfigError) as excinfo:
            SimulationClockConfig(mode="deterministic", tick_quantum_ns=0)
        assert excinfo.value.code == SIM_CLOCK_CONFIG_INVALID

    def test_non_positive_speed_rejected(self) -> None:
        from simulation.clock import SimulationClockConfig
        from simulation.errors import (
            SIM_CLOCK_CONFIG_INVALID,
            SimulationConfigError,
        )

        for num, den in ((0, 1), (-1, 3), (7, 0), (7, -3)):
            with pytest.raises(SimulationConfigError) as excinfo:
                SimulationClockConfig(mode="realtime", speed_num=num, speed_den=den)
            assert excinfo.value.code == SIM_CLOCK_CONFIG_INVALID

    def test_unknown_mode_rejected(self) -> None:
        from simulation.clock import SimulationClockConfig
        from simulation.errors import (
            SIM_CLOCK_CONFIG_INVALID,
            SimulationConfigError,
        )

        with pytest.raises(SimulationConfigError) as excinfo:
            SimulationClockConfig(mode="wallclock")  # type: ignore[arg-type]
        assert excinfo.value.code == SIM_CLOCK_CONFIG_INVALID

    def test_non_integer_fields_rejected(self) -> None:
        from simulation.clock import SimulationClockConfig

        with pytest.raises(TypeError):
            SimulationClockConfig(mode="deterministic", start_time_ns=1.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            SimulationClockConfig(mode="deterministic", tick_quantum_ns="100")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# REQ-SIM-201-001 — virtual time monotonic, backwards rejected
# ---------------------------------------------------------------------------


class TestClockMonotonic:
    """REQ-SIM-201-001: 虚拟时间单调，倒退请求拒绝（deterministic 模式）."""

    @staticmethod
    def _make_clock(**overrides: object) -> object:
        from simulation.clock import SimulationClock, SimulationClockConfig

        config = SimulationClockConfig(mode="deterministic", **overrides)  # type: ignore[arg-type]
        return SimulationClock(config)

    def test_starts_at_configured_start_time(self) -> None:
        clock = self._make_clock(start_time_ns=12345)
        assert clock.now_ns() == 12345

    def test_advance_by_moves_forward_and_returns_reached_ns(self) -> None:
        import asyncio

        clock = self._make_clock()
        assert asyncio.run(clock.advance_by(500)) == 500
        assert clock.now_ns() == 500
        assert asyncio.run(clock.advance_by(1)) == 501
        assert clock.now_ns() == 501

    def test_advance_to_moves_forward_and_returns_reached_ns(self) -> None:
        import asyncio

        clock = self._make_clock()
        assert asyncio.run(clock.advance_to(1_000)) == 1_000
        assert clock.now_ns() == 1_000

    def test_advance_to_backwards_rejected(self) -> None:
        import asyncio

        from simulation.errors import (
            SIM_CLOCK_TIME_BACKWARDS,
            SimulationTimeBackwardsError,
        )

        clock = self._make_clock()
        asyncio.run(clock.advance_to(1_000))
        # target < current: rejected.
        with pytest.raises(SimulationTimeBackwardsError) as excinfo:
            asyncio.run(clock.advance_to(999))
        assert excinfo.value.code == SIM_CLOCK_TIME_BACKWARDS
        # target == current: also rejected (SPEC-201 section 5 "target <= 当前值").
        with pytest.raises(SimulationTimeBackwardsError):
            asyncio.run(clock.advance_to(1_000))
        # Monotonic: the clock did not move.
        assert clock.now_ns() == 1_000

    def test_advance_by_zero_or_negative_rejected(self) -> None:
        import asyncio

        from simulation.errors import (
            SIM_CLOCK_TIME_BACKWARDS,
            SimulationTimeBackwardsError,
        )

        clock = self._make_clock()
        asyncio.run(clock.advance_by(100))
        for delta in (0, -1, -10**9):
            with pytest.raises(SimulationTimeBackwardsError) as excinfo:
                asyncio.run(clock.advance_by(delta))
            assert excinfo.value.code == SIM_CLOCK_TIME_BACKWARDS
        assert clock.now_ns() == 100

    def test_mixed_operation_sequence_stays_monotonic(self) -> None:
        import asyncio

        clock = self._make_clock()
        async def scenario() -> list[int]:
            seen = [clock.now_ns()]
            seen.append(await clock.advance_by(750))
            seen.append(await clock.advance_to(2_000))
            seen.append(await clock.advance_by(1))
            seen.append(await clock.advance_to(2_001 + 999))
            seen.append(clock.now_ns())
            return seen

        seen = asyncio.run(scenario())
        assert seen == [0, 750, 2_000, 2_001, 3_000, 3_000]
        assert all(later >= earlier for earlier, later in zip(seen, seen[1:]))


# ---------------------------------------------------------------------------
# REQ-SIM-201-003 — pause freezes virtual time, resume resumes symmetrically
# ---------------------------------------------------------------------------


class TestPauseFreeze:
    """REQ-SIM-201-003: pause 冻结虚拟时间，resume 对称恢复."""

    def test_deterministic_pause_rejects_advance(self) -> None:
        import asyncio

        from simulation.errors import (
            SIM_CLOCK_PAUSED,
            SimulationPausedError,
        )

        from simulation.clock import SimulationClock, SimulationClockConfig

        clock = SimulationClock(SimulationClockConfig(mode="deterministic"))
        asyncio.run(clock.advance_by(1_000))

        assert clock.is_paused() is False
        asyncio.run(clock.pause())
        assert clock.is_paused() is True

        # Advance while frozen: rejected, not silently dropped or queued.
        with pytest.raises(SimulationPausedError) as excinfo:
            asyncio.run(clock.advance_by(1))
        assert excinfo.value.code == SIM_CLOCK_PAUSED
        with pytest.raises(SimulationPausedError):
            asyncio.run(clock.advance_to(2_000))

        # Frozen value unchanged.
        assert clock.now_ns() == 1_000

        # Resume: symmetric continuation from the frozen value.
        asyncio.run(clock.resume())
        assert clock.is_paused() is False
        assert asyncio.run(clock.advance_by(500)) == 1_500
        assert clock.now_ns() == 1_500

    def test_realtime_pause_ignores_wall_clock_elapsed(self) -> None:
        """PAUSED 期间墙钟流逝不改变 now_ns；resume 后从冻结值继续."""
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig

        wall = {"now_ns": 10_000}

        def fake_wall() -> int:
            return wall["now_ns"]

        clock = SimulationClock(
            SimulationClockConfig(mode="realtime"),
            wall_ns_source=fake_wall,
        )
        # Virtual time counts from the session epoch (start_time_ns=0);
        # the wall reading at construction is the resume anchor, not the
        # virtual value.
        assert clock.now_ns() == 0

        # Wall elapses while running: virtual time follows, 1:1 speed.
        wall["now_ns"] = 15_000
        assert clock.now_ns() == 5_000

        asyncio.run(clock.pause())
        frozen = clock.now_ns()
        assert frozen == 5_000

        # Wall keeps elapsing while frozen: virtual time must not move.
        wall["now_ns"] = 100_000
        assert clock.now_ns() == frozen

        # Resume re-anchors the wall point; continuation is from the
        # frozen value, and the paused wall stretch never counts.
        asyncio.run(clock.resume())
        assert clock.now_ns() == frozen
        wall["now_ns"] = 105_000
        assert clock.now_ns() == frozen + 5_000

    def test_pause_and_resume_are_idempotent(self) -> None:
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig

        clock = SimulationClock(SimulationClockConfig(mode="deterministic"))
        asyncio.run(clock.pause())
        asyncio.run(clock.pause())  # second pause: no-op, still frozen
        assert clock.is_paused() is True
        asyncio.run(clock.resume())
        asyncio.run(clock.resume())  # second resume: no-op, still running
        assert clock.is_paused() is False
        assert asyncio.run(clock.advance_by(1)) == 1


# ---------------------------------------------------------------------------
# REQ-SIM-201-004 — rational speed, exact integer arithmetic, no float drift
# ---------------------------------------------------------------------------


class TestRealtimeRationalSpeed:
    """REQ-SIM-201-004: 有理数倍速全程整数运算，无 float 漂移.

    Speed vectors from SPEC-201 section 9: 7/3, 1/1, 1/1000. Every
    assertion is an exact integer comparison against hand-derived values
    (independent source of truth: the rational arithmetic itself, computed
    in the test, never via the implementation's code path).
    """

    @staticmethod
    def _make_realtime(speed_num: int, speed_den: int) -> tuple[object, dict[str, int]]:
        from simulation.clock import SimulationClock, SimulationClockConfig

        wall = {"now_ns": 0}

        def fake_wall() -> int:
            return wall["now_ns"]

        clock = SimulationClock(
            SimulationClockConfig(
                mode="realtime", speed_num=speed_num, speed_den=speed_den
            ),
            wall_ns_source=fake_wall,
        )
        return clock, wall

    def test_speed_seven_thirds(self) -> None:
        import asyncio

        clock, wall = self._make_realtime(7, 3)
        wall["now_ns"] = 9_000
        # 9000 * 7/3 = 21000 exactly.
        assert clock.now_ns() == 21_000
        # Non-exact quotient floors: 1 * 7 // 3 = 2.
        wall["now_ns"] = 9_001
        assert clock.now_ns() == 21_002

    def test_speed_one(self) -> None:
        import asyncio

        clock, wall = self._make_realtime(1, 1)
        wall["now_ns"] = 123_456
        assert clock.now_ns() == 123_456

    def test_speed_one_thousandth(self) -> None:
        import asyncio

        clock, wall = self._make_realtime(1, 1000)
        wall["now_ns"] = 1_000_000
        assert clock.now_ns() == 1_000
        wall["now_ns"] = 1_999_999
        # 1999999 // 1000 = 1999 (floor, exact integer division).
        assert clock.now_ns() == 1_999

    def test_thousand_freeze_resume_cycles_accumulate_exactly(self) -> None:
        """1000 次 pause/resume 循环累计无漂移（float 会在这里失真）."""
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig

        wall = {"now_ns": 0}

        def fake_wall() -> int:
            return wall["now_ns"]

        clock = SimulationClock(
            SimulationClockConfig(
                mode="realtime", speed_num=7, speed_den=3
            ),
            wall_ns_source=fake_wall,
        )
        # 1000 cycles, each adding wall delta 3 → virtual delta 7 each.
        for _ in range(1_000):
            wall["now_ns"] += 3
            assert clock.now_ns() == 7 * (_ + 1)  # exact, cycle by cycle
            asyncio.run(clock.pause())
            asyncio.run(clock.resume())

        assert clock.now_ns() == 7_000

    def test_realtime_explicit_advance_jumps_and_rejects_backwards(self) -> None:
        import asyncio

        from simulation.errors import (
            SIM_CLOCK_TIME_BACKWARDS,
            SimulationTimeBackwardsError,
        )

        clock, wall = self._make_realtime(7, 3)
        wall["now_ns"] = 9_000  # virtual 21000
        # Explicit jump: orchestrator-driven, no wall wait; the jump
        # becomes the new frozen base.
        assert asyncio.run(clock.advance_to(30_000)) == 30_000
        assert clock.now_ns() == 30_000
        wall["now_ns"] = 9_003  # +3 wall → +7 virtual from the new base
        assert clock.now_ns() == 30_007

        with pytest.raises(SimulationTimeBackwardsError) as excinfo:
            asyncio.run(clock.advance_to(30_000))
        assert excinfo.value.code == SIM_CLOCK_TIME_BACKWARDS


# ---------------------------------------------------------------------------
# Concurrency — pause/clock share ONE critical section (SPEC-200 §5.1 at
# the clock boundary: advance/pause/resume serialize on the same lock)
# ---------------------------------------------------------------------------


class TestPauseAdvanceConcurrency:
    """并发纪律：advance/pause/resume 同临界区串行，结果一致可复现."""

    def test_concurrent_advances_serialize_to_their_sum(self) -> None:
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig

        clock = SimulationClock(SimulationClockConfig(mode="deterministic"))

        async def scenario() -> list[int]:
            results = await asyncio.gather(
                *(clock.advance_by(1) for _ in range(50))
            )
            return list(results)

        results = asyncio.run(scenario())
        # Every commit got its own strictly increasing value: the lock
        # serialized them, none was lost or doubled.
        assert results == list(range(1, 51))
        assert clock.now_ns() == 50

    def test_pause_atomically_blocks_later_advances(self) -> None:
        import asyncio

        from simulation.errors import SimulationPausedError

        from simulation.clock import SimulationClock, SimulationClockConfig

        clock = SimulationClock(SimulationClockConfig(mode="deterministic"))

        async def scenario() -> tuple[int, object, int]:
            first = await clock.advance_by(100)
            # pause wins the critical section before the next advance:
            # once pause() completes, the later advance must observe the
            # frozen state — never a half-committed advance.
            await clock.pause()
            try:
                await clock.advance_by(1)
                blocked: object = "advanced"
            except SimulationPausedError:
                blocked = "paused"
            frozen_now = clock.now_ns()
            return first, blocked, frozen_now

        first, blocked, frozen_now = asyncio.run(scenario())
        assert first == 100
        assert blocked == "paused"
        assert frozen_now == 100
        assert clock.is_paused() is True

    def test_concurrent_advance_pause_resume_race_invariants(self) -> None:
        """Mixed gather: every advance either commits (increasing values)
        or fails with SIM_CLOCK_PAUSED; virtual time never decreases and
        the final state is consistent with the outcomes."""
        import asyncio

        from simulation.clock import SimulationClock, SimulationClockConfig
        from simulation.errors import SimulationPausedError

        clock = SimulationClock(SimulationClockConfig(mode="deterministic"))

        async def toggle_pause() -> str:
            await clock.pause()
            await asyncio.sleep(0)
            await clock.resume()
            return "toggled"

        async def try_advance(delta: int) -> str:
            try:
                await clock.advance_by(delta)
            except SimulationPausedError:
                return "paused"
            return "advanced"

        async def scenario() -> list[str]:
            tasks = []
            for i in range(40):
                tasks.append(try_advance(1))
                if i % 7 == 3:
                    tasks.append(toggle_pause())
            return await asyncio.gather(*tasks)

        outcomes = asyncio.run(scenario())
        # No silent drops: every operation is accounted for.
        assert len(outcomes) == 40 + len([i for i in range(40) if i % 7 == 3])
        assert outcomes.count("paused") + outcomes.count("advanced") == 40
        # Monotonicity: the clock ended at exactly the sum of committed
        # advances — a frozen-period advance cannot have committed.
        assert clock.now_ns() == outcomes.count("advanced")
        assert clock.is_paused() is False  # toggles always resume
