"""SPEC-203 TS Runtime — run orchestration: tee dual-write, artifacts list,
cancel, determinism, event-loop isolation (ticket #43).

Traceability:

- REQ-SIM-203-003  artifacts list-form + tee dual-write (baseline /
  faulted / log), 188 invariant and the shared packet frame.
- REQ-SIM-203-004  baseline dedup: same fingerprint re-run reuses the
  artifact record (same SHA, no duplicate landing).
- REQ-SIM-203-005  bounded-batch cancel, partial marking, no complete
  mislabeling.
- REQ-SIM-203-006  deterministic SHA-256 across runs of one prepared run.
- REQ-SIM-203-007  event loop stays responsive (bounded worker; the
  heartbeat runs while the worker thread generates).

Unit layer: the artifact sink is the in-memory structural fake (no
filesystem IO); every TS byte comes from the real SPEC-108 generator
driven by a fixed-seed config. Async behavior goes through ``asyncio.run``
(no pytest-asyncio; dev set frozen).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

import pytest
from ts.packet import TS_PACKET_SIZE, TSPacket

from simulation.errors import (
    SIM_TS_GENERATION_FAILED,
    SIM_TS_SINK_IO_ERROR,
    TSGenerationFailedError,
    TSSinkIOError,
)
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.ts_runtime import ArtifactRef, TSRuntime, TSRunResult
from tests.unit.simulation._ts_runtime_builders import (
    CCShiftFilter,
    FakeArtifactSink,
    make_generator_config,
    make_session_spec,
)

pytestmark = pytest.mark.unit


def _cc_plan(index: int = 10) -> tuple[FaultDefinition, ...]:
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


def _make_runtime(**kwargs) -> TSRuntime:
    return TSRuntime(**kwargs)


def _prepare(runtime: TSRuntime, *, plan=(), **config_overrides):
    return runtime.prepare(
        make_session_spec(),
        make_generator_config(**config_overrides),
        plan,
    )


def _run_now(runtime: TSRuntime, prepared, sink) -> TSRunResult:
    return asyncio.run(runtime.run(prepared, sink))


class TestBaselineOnlyRun:
    """plan 为空 = 仅出 baseline（八步闭环 Generate 步形态不变）。"""

    def test_completed_result_shape(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        sink = FakeArtifactSink()
        result = _run_now(runtime, prepared, sink)

        assert isinstance(result, TSRunResult)
        assert result.status == "completed"
        uuid.UUID(result.run_id)  # uuid4 opaque, parses
        assert result.packet_count == prepared.config.output_packet_count
        assert result.byte_count == result.packet_count * TS_PACKET_SIZE
        assert result.config_hash == prepared.config_hash
        assert result.generator_version == prepared.generator_version
        assert result.warnings == ()
        assert result.virtual_duration_ns >= 0

    def test_single_generated_ts_artifact(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        sink = FakeArtifactSink()
        result = _run_now(runtime, prepared, sink)

        assert len(result.artifacts) == 1
        artifact = result.artifacts[0]
        assert isinstance(artifact, ArtifactRef)
        assert artifact.kind == "generated_ts"
        assert artifact.partial is False
        assert artifact.packet_count == result.packet_count
        assert artifact.byte_size == result.byte_count
        assert artifact.sha256 == hashlib.sha256(
            sink.legs["baseline"].data
        ).hexdigest()

    def test_run_opens_baseline_leg_only(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        sink = FakeArtifactSink()
        _run_now(runtime, prepared, sink)
        assert sink.tee is False
        assert set(sink.legs) == {"baseline"}


class TestTeeDualWrite:
    """plan 非空：pre-filter → baseline leg, post-filter → faulted leg +
    mutation log leg（ADR-0007 item 2），共用同一包序 frame（item 4）。"""

    def test_three_artifacts_with_three_kinds(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        result = _run_now(runtime, prepared, sink)

        kinds = sorted(artifact.kind for artifact in result.artifacts)
        assert kinds == ["faulted_ts", "generated_ts", "log"]
        for artifact in result.artifacts:
            assert artifact.partial is False
        log_artifact = next(a for a in result.artifacts if a.kind == "log")
        assert log_artifact.packet_count is None  # log is not a TS stream
        assert sink.legs["log"].data  # mutation log carries content

    def test_faulted_stream_differs_from_baseline(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        result = _run_now(runtime, prepared, sink)

        baseline_sha = next(
            a.sha256 for a in result.artifacts if a.kind == "generated_ts"
        )
        faulted_sha = next(
            a.sha256 for a in result.artifacts if a.kind == "faulted_ts"
        )
        assert baseline_sha != faulted_sha
        assert sink.legs["baseline"].data != sink.legs["faulted"].data

    def test_shared_packet_frame_index_alignment(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        _run_now(runtime, prepared, sink)

        baseline_chunks = sink.legs["baseline"].chunks
        faulted_chunks = sink.legs["faulted"].chunks
        # One 188-byte write per packet, same slot count on both legs.
        assert len(baseline_chunks) == len(faulted_chunks)
        assert prepared.config.output_packet_count == len(baseline_chunks)
        for chunk in baseline_chunks + faulted_chunks:
            assert len(chunk) == TS_PACKET_SIZE
        # Sampled index alignment: same slot, same PID (ADR-0007 item 4).
        for index in (0, 10, 100, 499):
            baseline_packet = TSPacket.from_bytes(baseline_chunks[index])
            faulted_packet = TSPacket.from_bytes(faulted_chunks[index])
            assert baseline_packet.pid == faulted_packet.pid

    def test_188_invariant_on_both_streams(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        result = _run_now(runtime, prepared, sink)

        for kind in ("generated_ts", "faulted_ts"):
            artifact = next(a for a in result.artifacts if a.kind == kind)
            assert artifact.byte_size == artifact.packet_count * TS_PACKET_SIZE
        assert sink.legs["faulted"].data == b"".join(
            sink.legs["faulted"].chunks
        )

    def test_tee_run_without_wired_filter_is_rejected(self) -> None:
        runtime = _make_runtime()  # no filter_factory wired
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        with pytest.raises(ValueError, match="fault filter"):
            _run_now(runtime, prepared, sink)


class TestFailureSemantics:
    """SPEC-203 §8: SIM_TS_SINK_IO_ERROR / SIM_TS_GENERATION_FAILED."""

    def test_sink_write_failure_raises_sink_io_error(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        sink = FakeArtifactSink()
        sink.open_legs = _failing_legs_factory
        with pytest.raises(TSSinkIOError) as excinfo:
            _run_now(runtime, prepared, sink)
        assert excinfo.value.code == SIM_TS_SINK_IO_ERROR

    def test_filter_failure_wraps_generation_failed(self) -> None:
        class ExplodingFilter:
            def apply(self, index, packet):
                raise RuntimeError("filter blew up")

            def mutation_log(self):
                return b""

        runtime = _make_runtime(
            filter_factory=lambda plan, config: ExplodingFilter()
        )
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        with pytest.raises(TSGenerationFailedError) as excinfo:
            _run_now(runtime, prepared, sink)
        assert excinfo.value.code == SIM_TS_GENERATION_FAILED


def _failing_legs_factory(*, tee: bool, run_id: str, session_id: str):
    """A legs holder whose baseline leg fails on the first write."""

    class _BrokenLeg:
        def write(self, chunk: bytes) -> None:
            raise OSError("disk gone")

        def commit(self):
            raise AssertionError("commit must not be reached")

        def abort(self) -> None:
            pass

    class _Legs:
        baseline = _BrokenLeg()
        faulted = None
        log = None

    return _Legs()


class TestBaselineDedup:
    """REQ-SIM-203-004 (SPEC-203 §5.2 基线去重): 相同指纹二次 run，baseline
    artifact 记录复用（同 SHA 不重复注册）；faulted/log 不做跨 Run 去重。"""

    def test_same_fingerprint_second_run_reuses_baseline_record(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        first = _run_now(runtime, prepared, sink)
        second = _run_now(runtime, prepared, sink)

        first_baseline = next(a for a in first.artifacts if a.kind == "generated_ts")
        second_baseline = next(
            a for a in second.artifacts if a.kind == "generated_ts"
        )
        assert second_baseline.artifact_id == first_baseline.artifact_id
        assert second_baseline.sha256 == first_baseline.sha256
        # One registration per run for the re-generated legs, but the
        # baseline record itself is reused — the generated_ts kind is
        # registered exactly once across both runs.
        generated_registrations = [
            r for r in sink.registrations if r["kind"] == "generated_ts"
        ]
        assert len(generated_registrations) == 1

    def test_faulted_and_log_are_never_deduplicated(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, plan=_cc_plan())
        sink = FakeArtifactSink()
        first = _run_now(runtime, prepared, sink)
        second = _run_now(runtime, prepared, sink)

        for kind in ("faulted_ts", "log"):
            first_ref = next(a for a in first.artifacts if a.kind == kind)
            second_ref = next(a for a in second.artifacts if a.kind == kind)
            assert second_ref.artifact_id != first_ref.artifact_id

    def test_dedup_guard_checks_fingerprint_shape(self) -> None:
        # The reuse lookup carries the fingerprint triple: a record only
        # reuses when sha256 AND config_hash AND packet_count all match.
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        sink = FakeArtifactSink()
        first = _run_now(runtime, prepared, sink)
        sha = first.artifacts[0].sha256
        packet_count = first.packet_count

        assert (
            sink.find_reusable_baseline(sha, prepared.config_hash, packet_count)
            == first.artifacts[0].artifact_id
        )
        assert (
            sink.find_reusable_baseline(sha, "other-config-hash", packet_count)
            is None
        )
        assert (
            sink.find_reusable_baseline(sha, prepared.config_hash, packet_count - 1)
            is None
        )


class TestBoundedCancel:
    """REQ-SIM-203-005: cancel takes effect at a bounded batch boundary;
    cancelled artifacts are partial, never complete."""

    def _make_cancel_runtime(self) -> TSRuntime:
        return TSRuntime(batch_size=10)

    async def _run_until_cancelled(self, runtime: TSRuntime, prepared, sink):
        task = asyncio.create_task(runtime.run(prepared, sink))
        # Event-driven wait (no wall-clock sleep): the run registers its
        # cancel flag before the worker starts consuming batches.
        for _ in range(100_000):
            if runtime.active_run_ids:
                break
            await asyncio.sleep(0)
        assert runtime.active_run_ids, "run never registered for cancel"
        run_id = next(iter(runtime.active_run_ids))
        runtime.cancel(run_id)
        runtime.cancel(run_id)  # idempotent
        return await task

    def test_cancelled_run_yields_partial_artifacts(self) -> None:
        runtime = self._make_cancel_runtime()
        prepared = _prepare(runtime, output_packet_count=5000)
        sink = FakeArtifactSink()
        result = asyncio.run(self._run_until_cancelled(runtime, prepared, sink))

        assert result.status == "cancelled"
        assert result.artifacts, "cancelled run must land its produced bytes"
        assert result.packet_count < prepared.config.output_packet_count
        assert result.packet_count > 0
        assert result.byte_count == result.packet_count * TS_PACKET_SIZE
        for artifact in result.artifacts:
            assert artifact.partial is True
            assert artifact.packet_count == result.packet_count

    def test_bytes_stop_growing_at_batch_boundary(self) -> None:
        runtime = self._make_cancel_runtime()
        prepared = _prepare(runtime, output_packet_count=5000)
        sink = FakeArtifactSink()
        result = asyncio.run(self._run_until_cancelled(runtime, prepared, sink))
        landed_packets = len(sink.legs["baseline"].chunks)
        assert landed_packets == result.packet_count

    def test_cancel_unknown_run_rejected(self) -> None:
        runtime = TSRuntime()
        with pytest.raises(ValueError, match="not active"):
            runtime.cancel("no-such-run")


class TestDeterminism:
    """REQ-SIM-203-006: same config_hash (含 plan) → SHA-256 字节一致."""

    def test_same_prepared_baseline_sha_identical(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime, seed=7)
        first = _run_now(runtime, prepared, FakeArtifactSink())
        second = _run_now(runtime, prepared, FakeArtifactSink())
        assert first.artifacts[0].sha256 == second.artifacts[0].sha256

    def test_same_prepared_tee_run_both_streams_identical(self) -> None:
        runtime = _make_runtime(filter_factory=lambda plan, config: CCShiftFilter(plan))
        prepared = _prepare(runtime, seed=7, plan=_cc_plan())
        first = _run_now(runtime, prepared, FakeArtifactSink())
        second = _run_now(runtime, prepared, FakeArtifactSink())
        for kind in ("generated_ts", "faulted_ts"):
            sha_first = next(a.sha256 for a in first.artifacts if a.kind == kind)
            sha_second = next(a.sha256 for a in second.artifacts if a.kind == kind)
            assert sha_first == sha_second

    def test_wall_clock_and_session_identity_do_not_affect_bytes(self) -> None:
        runtime = _make_runtime()
        prepared = _prepare(runtime)
        other_session = make_session_spec(session_id="session-other")
        other_prepared = runtime.prepare(
            other_session, make_generator_config(seed=_prepare(runtime).config.seed)
        )
        first = _run_now(runtime, prepared, FakeArtifactSink())
        second = _run_now(runtime, other_prepared, FakeArtifactSink())
        assert first.artifacts[0].sha256 == second.artifacts[0].sha256


class TestEventLoopIsolation:
    """REQ-SIM-203-007: 生成走有界 worker，event loop 全程响应."""

    def test_heartbeat_runs_while_worker_generates(self) -> None:
        runtime = TSRuntime(batch_size=64)
        prepared = _prepare(runtime, output_packet_count=4000)
        sink = FakeArtifactSink()

        async def scenario():
            heartbeats = 0
            run_task = asyncio.create_task(runtime.run(prepared, sink))

            async def heartbeat():
                nonlocal heartbeats
                while not run_task.done():
                    heartbeats += 1
                    await asyncio.sleep(0)

            beat_task = asyncio.create_task(heartbeat())
            await run_task
            await beat_task
            return heartbeats

        heartbeats = asyncio.run(scenario())
        assert heartbeats > 10, (
            f"event loop starved during generation: {heartbeats} heartbeats"
        )


class TestImportContract:
    """REQ-SIM-203-001 (static): 只用 TS Core 公共契约 — the TS imports of
    the TS-runtime module stay inside the SPEC-108/100 public whitelist and
    the generation chain carries no fault branch."""

    def test_ts_import_whitelist(self) -> None:
        import ast
        import inspect

        import simulation.ts_runtime as ts_runtime_module

        source = inspect.getsource(ts_runtime_module)
        tree = ast.parse(source)
        ts_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ts" or alias.name.startswith("ts."):
                        ts_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ts" or module.startswith("ts."):
                    ts_imports.add(module)
        allowed = {
            "ts.errors",
            "ts.generator.config",
            "ts.generator.generator",
            "ts.packet",
        }
        assert ts_imports <= allowed, (
            f"TS imports outside the SPEC-108/100 public whitelist: "
            f"{sorted(ts_imports - allowed)}"
        )
