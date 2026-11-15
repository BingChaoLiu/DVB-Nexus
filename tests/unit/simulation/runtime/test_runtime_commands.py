"""SPEC-200 section 6 — SimulationRuntime command face (ticket #41).

Traceability (SPEC-200 section 10):

- REQ-SIM-200-001  command face drives the section 5 table; illegal
  command/state pairs are rejected -> TestCommandLifecyclePath
- REQ-SIM-200-002  repeated start spawns no duplicate worker; (stop
  idempotency lives in ``test_stop_dispose``) -> TestStartWorker
- REQ-SIM-200-004  session isolation basics (unknown ids, per-session
  failure containment; the cross-session matrix lives in
  ``test_concurrency``) -> TestSessionNotFound

Async tests run through ``asyncio.run`` (no pytest-asyncio dependency; the
dev dependency set is frozen — same discipline as test_clock.py).
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_ENGINE_ERROR,
    SIM_INVALID_LIFECYCLE_TRANSITION,
    SIM_SESSION_NOT_FOUND,
    SIM_VALIDATION_FAILED,
    InvalidLifecycleTransitionError,
    SessionNotFoundError,
    SimulationEngineError,
    SimulationValidationError,
)
from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime
from simulation.state import Health

from tests.unit.simulation.runtime import _sim_c_builders as b


def run(coro):
    return asyncio.run(coro)


class TestCommandLifecyclePath:
    """create -> validate -> start drives the section 5 table edges."""

    def test_create_returns_created_view(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            view = await runtime.create_session(b.session_spec())
            assert view.session_id == "session-1"
            assert view.lifecycle is LifecycleState.CREATED
            assert view.revision == 0
            assert view.virtual_time_ns == 0
            assert view.topology_revision == 0
            assert set(view.node_states) == {"gen-0"}
            # Initial L0-skeleton evaluation: deferred stub reports idle.
            assert view.node_states["gen-0"].health is Health.IDLE
            assert view.active_faults == ()
            assert view.latest_artifact_refs == ()

        run(main())

    def test_validate_ok_transitions_created_to_ready(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(b.session_spec())
            report = await runtime.validate_session("session-1")
            assert report.ok is True
            assert report.violations == ()
            view = await runtime.get_snapshot("session-1")
            assert view.lifecycle is LifecycleState.READY
            # CREATED->VALIDATING and VALIDATING->READY: revision 2.
            assert view.revision == 2

        run(main())

    def test_validate_failure_goes_straight_to_failed_with_report(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(
                b.session_spec(b.cyclic_graph(), session_id="bad")
            )
            with pytest.raises(SimulationValidationError) as excinfo:
                await runtime.validate_session("bad")
            assert excinfo.value.code == SIM_VALIDATION_FAILED
            report = excinfo.value.report
            assert report is not None
            assert report.ok is False
            codes = [violation.code for violation in report.violations]
            assert "SIM_TOPO_CYCLE" in codes
            # 验证失败直达 FAILED（#12 裁决边 VALIDATING->FAILED）。
            view = await runtime.get_snapshot("bad")
            assert view.lifecycle is LifecycleState.FAILED
            assert view.revision == 2

        run(main())

    def test_second_validate_is_an_illegal_transition(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(b.session_spec())
            await runtime.validate_session("session-1")
            # Only CREATED -> VALIDATING exists; validating from READY is
            # refused by the exhaustive table.
            with pytest.raises(InvalidLifecycleTransitionError) as excinfo:
                await runtime.validate_session("session-1")
            assert excinfo.value.code == SIM_INVALID_LIFECYCLE_TRANSITION

        run(main())

    def test_failed_session_disposes_directly(self) -> None:
        async def main() -> None:
            # FAILED -> DISPOSED 直达（#12 裁决边）：失败会话无需 stop 即回收。
            runtime = SimulationRuntime()
            await runtime.create_session(
                b.session_spec(b.cyclic_graph(), session_id="bad")
            )
            with pytest.raises(SimulationValidationError):
                await runtime.validate_session("bad")
            await runtime.dispose("bad")
            view = await runtime.get_snapshot("bad")
            assert view.lifecycle is LifecycleState.DISPOSED

        run(main())


class TestStartWorker:
    """REQ-200-002: one start, one worker; repeated start refused."""

    def test_start_spawns_exactly_one_worker(self) -> None:
        started: list[str] = []

        async def runner(spec) -> None:
            started.append(spec.session_id)
            await asyncio.Event().wait()  # cancelled by stop/dispose

        async def main() -> None:
            runtime = SimulationRuntime(runner_factory=runner)
            await runtime.create_session(b.session_spec())
            await runtime.validate_session("session-1")
            view = await runtime.start("session-1")
            assert view.lifecycle is LifecycleState.RUNNING
            assert view.revision == 3
            await asyncio.sleep(0)  # scheduling yield: let the worker run
            assert started == ["session-1"]

            with pytest.raises(InvalidLifecycleTransitionError):
                await runtime.start("session-1")
            assert started == ["session-1"]  # no duplicate worker
            await runtime.stop("session-1")  # RUNNING -> STOPPING -> STOPPED
            await runtime.dispose("session-1")

        run(main())

    def test_start_requires_ready(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            await runtime.create_session(b.session_spec())
            with pytest.raises(InvalidLifecycleTransitionError):
                await runtime.start("session-1")

        run(main())

    def test_start_failure_lands_failed_with_engine_error(self) -> None:
        def broken_factory(spec):
            # Engine construction fails synchronously (SIM-D seam).
            raise RuntimeError("engine boom")

        async def main() -> None:
            runtime = SimulationRuntime(runner_factory=broken_factory)
            await runtime.create_session(b.session_spec())
            await runtime.validate_session("session-1")
            with pytest.raises(SimulationEngineError) as excinfo:
                await runtime.start("session-1")
            assert excinfo.value.code == SIM_ENGINE_ERROR
            # start 失败可直达 FAILED（READY -> FAILED edge）.
            view = await runtime.get_snapshot("session-1")
            assert view.lifecycle is LifecycleState.FAILED

        run(main())


class TestSessionNotFound:
    """Unknown session_id: stable 404 semantics on every command."""

    COMMANDS = ("validate", "start", "pause", "resume", "dispose")

    def _expect_not_found(self, excinfo) -> None:
        assert isinstance(excinfo.value, SessionNotFoundError)
        assert excinfo.value.code == SIM_SESSION_NOT_FOUND

    def test_get_snapshot_unknown_session(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            with pytest.raises(SessionNotFoundError) as excinfo:
                await runtime.get_snapshot("ghost")
            self._expect_not_found(excinfo)

    def test_commands_unknown_session(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            for name in self.COMMANDS:
                with pytest.raises(SessionNotFoundError) as excinfo:
                    await getattr(runtime, name)("ghost")
                self._expect_not_found(excinfo)

    def test_stop_unknown_session(self) -> None:
        async def main() -> None:
            runtime = SimulationRuntime()
            with pytest.raises(SessionNotFoundError) as excinfo:
                await runtime.stop("ghost")
            self._expect_not_found(excinfo)
