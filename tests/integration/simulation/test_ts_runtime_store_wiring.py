"""SPEC-203 TS Runtime — store wiring + lifecycle run-face integration
(ticket #43, REQ-SIM-203-003/004 + SPEC-200 §7.4 run-face coupling).

Integration layer (SPEC-505 §3): real filesystem + real SQLite index via
the #42 store adapter; the tee legs land through the SAME tmp → atomic
rename → 先文件后索引 protocol the storage tests pin.

Programmatic bytes only (tests/README.md §5): every TS byte comes from the
real SPEC-108 generator; the fake fault filter is a slot-preserving
in-place CC rewrite.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from ts.packet import TSPacket

from adapters.storage import db
from adapters.storage.artifact_errors import ArtifactNotFoundError
from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.repositories import SqliteArtifactRepository
from simulation.runtime import SimulationRuntime
from simulation.clock import SimulationClockConfig
from simulation.ts_runtime import StoreArtifactSink, TSRuntime
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

pytestmark = pytest.mark.integration


def _cc_plan(index: int = 10) -> tuple:
    from simulation.fault_plan import FaultActivation, FaultDefinition

    return (
        FaultDefinition(
            fault_id="fault-cc-1",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=index),
            expected_observations=("ts.continuity_error",),
        ),
    )


class CCShiftFilter:
    """Slot-preserving fake fault filter (same shape as the unit fake)."""

    def __init__(self, plan) -> None:
        self._entries: list[dict] = []

    def apply(self, index: int, packet: TSPacket) -> TSPacket:
        shifted = (packet.continuity_counter + 3) % 16
        self._entries.append({"index": index, "pid": packet.pid})
        return replace(packet, continuity_counter=shifted)

    def mutation_log(self) -> bytes:
        return json.dumps({"mutations": self._entries}, sort_keys=True).encode("utf-8")


def _store_with_index(tmp_path: Path, dirname: str):
    connection = db.connect(tmp_path / f"{dirname}.sqlite3")
    apply_sql_migrations(connection, default_migrations_dir())
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(tmp_path / dirname, index=repository)
    return store, repository


class RecordingEventSink:
    """Captures published SPEC-301 envelope documents (structural sink)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))

    def of_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e["event_type"] == event_type]


class TestStoreLandingProtocol:
    """REQ-SIM-203-003: the tee lands through the SPEC-503 protocol."""

    def _make_wiring(self, tmp_path: Path, dirname: str):
        store, repository = _store_with_index(tmp_path, dirname)
        sink = StoreArtifactSink(store, index=repository)
        runtime = TSRuntime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = runtime.prepare(make_session_spec(), make_generator_config(), _cc_plan())
        return runtime, prepared, sink, store, repository

    def test_three_kinds_landed_and_registered(self, tmp_path: Path) -> None:
        runtime, prepared, sink, store, _ = self._make_wiring(tmp_path, "tee-landing")
        result = asyncio.run(runtime.run(prepared, sink))

        kinds = sorted(a.kind for a in result.artifacts)
        assert kinds == ["faulted_ts", "generated_ts", "log"]
        for artifact in result.artifacts:
            # 先文件后索引: every registered record has its physical file.
            physical = store.root / artifact.sha256[:2]
            content = store.root / "artifacts" / artifact.sha256[:2] / (
                f"{artifact.sha256}.{'log' if artifact.kind == 'log' else 'ts'}"
            )
            assert content.exists(), f"missing content file for {artifact.sha256}"

    def test_index_alignment_across_landed_streams(self, tmp_path: Path) -> None:
        runtime, prepared, sink, store, repository = self._make_wiring(
            tmp_path, "tee-align"
        )
        result = asyncio.run(runtime.run(prepared, sink))
        baseline = next(a for a in result.artifacts if a.kind == "generated_ts")
        faulted = next(a for a in result.artifacts if a.kind == "faulted_ts")
        baseline_bytes = store.read_bytes(
            _relative_of(repository, baseline.sha256), verify=True
        )
        faulted_bytes = store.read_bytes(
            _relative_of(repository, faulted.sha256), verify=True
        )
        # Shared packet frame: same slot count, same PIDs per slot.
        assert len(baseline_bytes) == len(faulted_bytes)
        slot = 100
        b_packet = TSPacket.from_bytes(
            baseline_bytes[slot * 188 : (slot + 1) * 188]
        )
        f_packet = TSPacket.from_bytes(
            faulted_bytes[slot * 188 : (slot + 1) * 188]
        )
        assert b_packet.pid == f_packet.pid
        assert b_packet.continuity_counter != f_packet.continuity_counter


def _relative_of(repository, sha256: str) -> str:
    rows = repository.find_by_sha256(sha256)
    assert rows, f"no index row for {sha256}"
    return rows[0].relative_path


class TestBaselineDedup:
    """REQ-SIM-203-004: same fingerprint second run reuses the baseline
    record (one index row) and the physical file is not duplicated."""

    def test_record_and_file_reuse(self, tmp_path: Path) -> None:
        store, repository = _store_with_index(tmp_path, "dedup-run")
        sink = StoreArtifactSink(store, index=repository)
        runtime = TSRuntime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = runtime.prepare(make_session_spec(), make_generator_config(), _cc_plan())

        first = asyncio.run(runtime.run(prepared, sink))
        second = asyncio.run(runtime.run(prepared, sink))

        first_baseline = next(a for a in first.artifacts if a.kind == "generated_ts")
        second_baseline = next(
            a for a in second.artifacts if a.kind == "generated_ts"
        )
        assert second_baseline.artifact_id == first_baseline.artifact_id
        rows = repository.find_by_sha256(first_baseline.sha256)
        assert len(rows) == 1  # record reused, not re-registered
        content = store.root / "artifacts" / first_baseline.sha256[:2]
        files = [
            p for p in content.iterdir() if p.name.startswith(first_baseline.sha256)
        ]
        assert len(files) == 1  # 同 SHA 不复制: one physical file
        # faulted/log do NOT dedup at the record level: every run
        # registers its own row (the content file converges by content
        # addressing, but the rows are per-run, 引用不复制).
        faulted_rows = repository.find_by_sha256(
            next(a.sha256 for a in second.artifacts if a.kind == "faulted_ts")
        )
        assert len(faulted_rows) == 2

    def test_public_face_resolution_without_explicit_index_kwarg(
        self, tmp_path: Path
    ) -> None:
        """M3 review-fix: the sink resolves the index through the store's
        public accessor — no private-attribute poke, and dedup is never
        silently disabled by a ``None`` fallback."""
        store, repository = _store_with_index(tmp_path, "dedup-public-face")
        sink = StoreArtifactSink(store)
        runtime = TSRuntime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = runtime.prepare(make_session_spec(), make_generator_config(), _cc_plan())

        first = asyncio.run(runtime.run(prepared, sink))
        second = asyncio.run(runtime.run(prepared, sink))

        first_baseline = next(a for a in first.artifacts if a.kind == "generated_ts")
        second_baseline = next(
            a for a in second.artifacts if a.kind == "generated_ts"
        )
        assert second_baseline.artifact_id == first_baseline.artifact_id
        rows = repository.find_by_sha256(first_baseline.sha256)
        assert len(rows) == 1  # record reused, not re-registered

    def test_store_without_index_is_an_explicit_error(self, tmp_path: Path) -> None:
        """A store without an index can never satisfy the record-level
        dedup contract — construction fails loudly instead of silently
        disabling baseline dedup."""
        store = ArtifactStore(tmp_path / "dedup-no-index")
        with pytest.raises(ArtifactNotFoundError, match="index"):
            StoreArtifactSink(store)


class TestLifecycleRunFace:
    """SIM_TS 编排走 #41 生命周期状态机：runs require RUNNING; run_* events
    emit through the runtime's §7.4 emitter; snapshot carries artifact refs."""

    def _make_session(self, tmp_path: Path):
        sink_recorder = RecordingEventSink()
        runtime = SimulationRuntime(event_sink=sink_recorder)
        ts_runtime = TSRuntime(
            runtime=runtime,
            filter_factory=lambda plan, config: CCShiftFilter(plan),
        )
        session_spec = make_session_spec(
            clock_config=SimulationClockConfig(mode="deterministic")
        )
        return runtime, ts_runtime, session_spec, sink_recorder

    def _start_running_session(self, runtime: SimulationRuntime, session_spec):
        async def flow():
            await runtime.create_session(session_spec)
            await runtime.validate_session(session_spec.session_id)
            await runtime.start(session_spec.session_id)

        asyncio.run(flow())

    def test_run_requires_running_session(self, tmp_path: Path) -> None:
        runtime, ts_runtime, session_spec, _ = self._make_session(tmp_path)
        prepared = ts_runtime.prepare(make_session_spec(), make_generator_config())
        from tests.unit.simulation._ts_runtime_builders import FakeArtifactSink

        async def flow():
            await runtime.create_session(session_spec)
            # Session is CREATED, never validated/started.
            await ts_runtime.run(prepared, FakeArtifactSink())

        with pytest.raises(ValueError, match="RUNNING"):
            asyncio.run(flow())

    def test_completed_run_emits_run_events_and_artifact_refs(
        self, tmp_path: Path
    ) -> None:
        runtime, ts_runtime, session_spec, recorder = self._make_session(tmp_path)
        store, repository = _store_with_index(tmp_path, "lifecycle-ok")
        sink = StoreArtifactSink(store, index=repository)
        prepared = ts_runtime.prepare(
            make_session_spec(session_id=session_spec.session_id),
            make_generator_config(),
            _cc_plan(),
        )
        self._start_running_session(runtime, session_spec)

        result = asyncio.run(ts_runtime.run(prepared, sink))

        assert result.status == "completed"
        started = recorder.of_type("simulation.run_started")
        completed = recorder.of_type("simulation.run_completed")
        assert len(started) == 1 and len(completed) == 1
        assert completed[0]["scope"]["run_id"] == result.run_id
        assert started[0]["scope"]["session_id"] == session_spec.session_id
        snapshot = asyncio.run(
            runtime.get_snapshot(session_spec.session_id)
        )
        ref_kinds = {ref.kind: ref.status for ref in snapshot.latest_artifact_refs}
        assert ref_kinds == {
            "generated_ts": "complete",
            "faulted_ts": "complete",
            "log": "complete",
        }

    def test_cancelled_run_closes_as_failed_with_cancel_reason(
        self, tmp_path: Path
    ) -> None:
        runtime, ts_runtime, session_spec, recorder = self._make_session(tmp_path)
        store, repository = _store_with_index(tmp_path, "lifecycle-cancel")
        sink = StoreArtifactSink(store, index=repository)
        prepared = ts_runtime.prepare(
            make_session_spec(session_id=session_spec.session_id),
            make_generator_config(output_packet_count=5000),
            _cc_plan(),
        )
        self._start_running_session(runtime, session_spec)

        async def flow():
            task = asyncio.create_task(ts_runtime.run(prepared, sink))
            for _ in range(100_000):
                if ts_runtime.active_run_ids:
                    break
                await asyncio.sleep(0)
            run_id = next(iter(ts_runtime.active_run_ids))
            ts_runtime.cancel(run_id)
            return await task

        result = asyncio.run(flow())

        assert result.status == "cancelled"
        for artifact in result.artifacts:
            assert artifact.partial is True
        failed = recorder.of_type("simulation.run_failed")
        assert len(failed) == 1
        assert failed[0]["payload"]["reason"] == "SIM_TS_CANCELLED"
        snapshot = asyncio.run(runtime.get_snapshot(session_spec.session_id))
        for ref in snapshot.latest_artifact_refs:
            assert ref.status == "partial"
