"""SPEC-200 section 4/§10 — snapshot pull API (ticket #41).

Traceability (SPEC-200 section 10):

- REQ-SIM-200-005  snapshot revision strictly monotonic; snapshot is a
  pull API and accepts a ``journal_seq`` cursor -> TestRevisionMonotonic /
  TestCursorSemantics
- (section 9)      same revision => same view content (same session) ->
  TestRevisionMonotonic.test_same_revision_same_content
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from simulation.lifecycle import LifecycleState
from simulation.runtime import SimulationRuntime
from simulation.snapshot import SimulationSnapshot

from tests.unit.simulation.runtime import _sim_c_builders as b


async def _build_to_running(session_id: str) -> SimulationRuntime:
    runtime = SimulationRuntime()
    await runtime.create_session(b.session_spec(session_id=session_id))
    await runtime.validate_session(session_id)
    await runtime.start(session_id)
    return runtime


class TestRevisionMonotonic:
    def test_revision_strictly_increases_with_mutations(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-1")
            revisions: list[int] = []

            revisions.append((await runtime.get_snapshot("sn-1")).revision)
            await runtime.pause("sn-1")
            revisions.append((await runtime.get_snapshot("sn-1")).revision)
            await runtime.resume("sn-1")
            revisions.append((await runtime.get_snapshot("sn-1")).revision)
            await runtime.stop("sn-1")
            revisions.append((await runtime.get_snapshot("sn-1")).revision)
            await runtime.dispose("sn-1")
            revisions.append((await runtime.get_snapshot("sn-1")).revision)

            # create=0, validate=2, start=3, pause=4, resume=5, stop=7,
            # dispose=8 — strictly monotonic throughout.
            assert revisions == [3, 4, 5, 7, 8]
            assert all(
                later > earlier
                for earlier, later in zip(revisions, revisions[1:])
            )

        asyncio.run(main())

    def test_same_revision_same_content(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-2")
            first = await runtime.get_snapshot("sn-2")
            second = await runtime.get_snapshot("sn-2")
            assert first.revision == second.revision
            assert first == second  # frozen dataclass: full content equality

        asyncio.run(main())

    def test_snapshot_is_read_only_mirror(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-3")
            snapshot = await runtime.get_snapshot("sn-3")
            assert isinstance(snapshot, SimulationSnapshot)
            with pytest.raises(Exception):
                snapshot.revision = 99  # type: ignore[misc]

        asyncio.run(main())


class TestCursorSemantics:
    """Snapshot 是拉取 API：接受 journal_seq cursor 参数（ADR-0006 第 5 条）."""

    def test_cursor_is_accepted_and_echoed(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-4")
            snapshot = await runtime.get_snapshot("sn-4", journal_seq_cursor=42)
            assert snapshot.journal_seq_cursor == 42

        asyncio.run(main())

    def test_cursor_defaults_to_none(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-5")
            snapshot = await runtime.get_snapshot("sn-5")
            assert snapshot.journal_seq_cursor is None

        asyncio.run(main())

    def test_cursor_validation(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-6")
            with pytest.raises(ValueError):
                await runtime.get_snapshot("sn-6", journal_seq_cursor=-1)
            with pytest.raises(TypeError):
                await runtime.get_snapshot("sn-6", journal_seq_cursor="7")  # type: ignore[arg-type]

        asyncio.run(main())

    def test_snapshot_carries_full_replacement_view(self) -> None:
        async def main() -> None:
            runtime = await _build_to_running("sn-7")
            snapshot = await runtime.get_snapshot("sn-7")
            assert snapshot.lifecycle is LifecycleState.RUNNING
            assert set(snapshot.node_states) == {"gen-0"}
            assert snapshot.connection_states == ()
            assert snapshot.active_faults == ()
            assert snapshot.latest_artifact_refs == ()
            assert snapshot.topology_revision == 0

        asyncio.run(main())
