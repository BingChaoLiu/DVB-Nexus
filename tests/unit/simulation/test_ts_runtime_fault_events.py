"""fault.* real emission at the SPEC-203 execution points (ticket #56, 裁定 2).

The TS runtime owns the fault execution window, so it owns the four
``fault.*`` emission points (SPEC-204 §8.1 mapped onto the run):

- ``fault.injected`` (SCHEDULED)  — the prepare-validated plan binds to a
  run: emitted once per plan fault right after the run opens;
- ``fault.activated`` (ACTIVE)    — the window start: emitted at the
  shared-frame activation-index crossing (session_start = index 0);
- ``fault.applied`` (APPLIED)     — L1 only: the confirmation that faulted
  bytes entered the flow, attributed per fault from the §8.2 mutation-log
  document the tee partner produced, with the confirmed slot indexes;
- ``fault.cleared`` (REMOVED)     — window end / run end (MVP windows end
  with the run); completed AND cancelled runs close their windows, a FAILED
  run leaves the fault in the FAILED state (no cleared event, SPEC-204
  §8.1/§11 — the fault_inactive baseline anchor correctly stays open).

Unit layer: real SPEC-108 generator bytes (no hand-assembled TS), in-memory
sink legs, a §8.2-shaped filter fake standing in for the production
``SemanticFaultFilter`` document contract. The runtime is the wired #41
runtime carrying the RecordingSink — the same wiring posture as
``test_runtime_gateway_wiring.py``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_TS_CANCELLED,
    TSGenerationFailedError,
)
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.runtime import SimulationRuntime
from simulation.ts_runtime import TSRuntime
from ts.packet import TS_PACKET_SIZE

from tests.unit.simulation._ts_runtime_builders import (
    FakeArtifactSink,
    make_generator_config,
    make_session_spec,
)
from tests.unit.simulation.runtime.test_events import RecordingSink


# --- §8.2-shaped filter fake -----------------------------------------------------


class DocumentedLogFilter:
    """Slot-preserving fake emitting the SPEC-204 §8.2 log document.

    Mirrors the production ``SemanticFaultFilter`` document contract at the
    fields the runtime reads for applied attribution (``faults[]`` entries
    with fault identity, target addressing and the ``lifecycle`` summary).
    Every slot at or after a fault's activation index is transformed, so
    the applied list is the exact suffix of the shared frame.
    """

    def __init__(self, plan: tuple[FaultDefinition, ...]) -> None:
        self._plan = plan
        self._applied: dict[str, list[int]] = {}

    @staticmethod
    def _activation_index(fault: FaultDefinition) -> int:
        return (
            0
            if fault.activation.kind == "session_start"
            else fault.activation.packet_index
        )

    def apply(self, index: int, packet):
        for fault in self._plan:
            if index >= self._activation_index(fault):
                self._applied.setdefault(fault.fault_id, []).append(index)
        return replace(
            packet, continuity_counter=(packet.continuity_counter + 1) % 16
        )

    def mutation_log(self) -> bytes:
        entries = []
        for fault in self._plan:
            entries.append(
                {
                    "fault_id": fault.fault_id,
                    "fault_type": fault.fault_type,
                    "target": {"node_id": "demux-0", "pid": 0x0100},
                    "activation": {
                        "kind": fault.activation.kind,
                        "packet_index": fault.activation.packet_index,
                    },
                    "lifecycle": {
                        "fault.applied": self._applied.get(fault.fault_id, []),
                    },
                }
            )
        document = {"faults": entries, "mutations": []}
        return json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


class SilentFilter:
    """Slot-preserving identity-shaped filter (log lacks the §8.2 shape)."""

    def apply(self, index: int, packet):
        return packet

    def mutation_log(self) -> bytes:
        return b"{}"


# --- helpers ---------------------------------------------------------------------


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


def _dual_plan() -> tuple[FaultDefinition, ...]:
    """SC-05-style dual-fault plan (distinct activation indexes)."""
    return (
        FaultDefinition(
            fault_id="fault-cc-1",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=10),
            expected_observations=("ts.continuity_error",),
        ),
        FaultDefinition(
            fault_id="fault-pat-2",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            parameters={},
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("ts.psi_section_observed",),
        ),
    )


async def _wired_stack(session_id: str):
    sink = RecordingSink()
    runtime = SimulationRuntime(event_sink=sink)
    spec = make_session_spec(session_id=session_id)
    await runtime.create_session(spec)
    await runtime.validate_session(session_id)
    await runtime.start(session_id)
    return sink, runtime, spec


def _fault_events(sink: RecordingSink) -> list[dict]:
    return [e for e in sink.events if e["event_type"].startswith("fault.")]


class TestFaultLifecycleSequence:
    """The four emission points land in lifecycle order on one run."""

    def test_packet_index_activation_full_sequence(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-1")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()  # drop the session lifecycle events
            result = await ts_runtime.run(prepared, FakeArtifactSink())

            assert result.status == "completed"
            assert [event["event_type"] for event in sink.events] == [
                "simulation.run_started",
                "fault.injected",
                "fault.activated",
                "fault.applied",
                "fault.cleared",
                "simulation.run_completed",
            ]

        asyncio.run(main())

    def test_injected_and_activated_payloads_carry_index_precision(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-2")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            events = _fault_events(sink)
            injected = next(
                e for e in events if e["event_type"] == "fault.injected"
            )
            activated = next(
                e for e in events if e["event_type"] == "fault.activated"
            )
            # Atomic-boundary precision: the declared window start rides the
            # payload AND the correlation block (SPEC-204 §9).
            for event in (injected, activated):
                assert event["payload"]["injection_index"] == 10
                assert event["payload"]["fault_id"] == "fault-cc-1"
                assert event["payload"]["fault_type"] == "CC_DISCONTINUITY"
                assert event["correlation"]["fault_id"] == "fault-cc-1"
                assert event["correlation"]["node_id"] == "demux-0"
                assert event["correlation"]["pid"] == 0x0100
                assert event["scope"]["run_id"] == result_run_id(events, sink)
            # injected additionally declares the prepare contract.
            assert injected["payload"]["expected_observations"] == [
                "ts.continuity_error"
            ]

        asyncio.run(main())

    def test_session_start_window_opens_at_index_zero(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-3")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            plan = (
                FaultDefinition(
                    fault_id="fault-cc-0",
                    fault_type="CC_DISCONTINUITY",
                    target_id="demux-0:pid:0x0100",
                    parameters={"delta": 3},
                    activation=FaultActivation(
                        kind="session_start", packet_index=None
                    ),
                    expected_observations=("ts.continuity_error",),
                ),
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), plan)
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            events = _fault_events(sink)
            types = [event["event_type"] for event in events]
            assert types == [
                "fault.injected",
                "fault.activated",
                "fault.applied",
                "fault.cleared",
            ]
            assert events[1]["payload"]["injection_index"] == 0

        asyncio.run(main())

    def test_activated_fires_only_at_the_crossing(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-4")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(30))
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            activated = [
                e for e in _fault_events(sink)
                if e["event_type"] == "fault.activated"
            ]
            # One window, one activation — not one per transformed slot.
            assert len(activated) == 1

        asyncio.run(main())

    def test_applied_attribution_reads_the_mutation_log_document(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-5")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            applied = next(
                e for e in _fault_events(sink)
                if e["event_type"] == "fault.applied"
            )
            indexes = applied["payload"]["applied_packet_indexes"]
            assert indexes, "the confirmation must carry the slot list"
            assert all(index >= 10 for index in indexes)
            assert indexes == sorted(indexes)
            # The before-after summary pointer: the log tee leg artifact.
            assert applied["payload"]["mutation_log_ref"].startswith("artifact-")

        asyncio.run(main())

    def test_dual_fault_plan_attributes_each_fault(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-6")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _dual_plan())
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            events = _fault_events(sink)
            injected_ids = [
                e["payload"]["fault_id"]
                for e in events
                if e["event_type"] == "fault.injected"
            ]
            assert injected_ids == ["fault-cc-1", "fault-pat-2"]
            applied_by_id = {
                e["payload"]["fault_id"]: e
                for e in events
                if e["event_type"] == "fault.applied"
            }
            assert set(applied_by_id) == {"fault-cc-1", "fault-pat-2"}
            # The session_start fault confirms slots from index 0; the
            # packet_index fault only from its crossing.
            assert applied_by_id["fault-cc-1"]["payload"][
                "applied_packet_indexes"
            ][0] >= 10
            assert applied_by_id["fault-pat-2"]["payload"][
                "applied_packet_indexes"
            ][0] == 0

        asyncio.run(main())


def result_run_id(events: list[dict], sink: RecordingSink) -> str:
    """The run id the run_started event carries (scope attribution anchor)."""
    started = [
        e for e in sink.events
        if e["event_type"] == "simulation.run_started"
    ]
    assert started, "the run face must have opened the run"
    return started[0]["scope"]["run_id"]


class TestFaultLifecycleEdges:
    """Empty plans, unwired runtimes, cancelled and failed runs."""

    def test_empty_plan_emits_no_fault_events(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-7")
            ts_runtime = TSRuntime(runtime=runtime)
            prepared = ts_runtime.prepare(spec, make_generator_config())
            sink.events.clear()
            result = await ts_runtime.run(prepared, FakeArtifactSink())

            assert result.status == "completed"
            assert _fault_events(sink) == []

        asyncio.run(main())

    def test_unwired_runtime_emits_nothing(self) -> None:
        async def main() -> None:
            ts_runtime = TSRuntime(
                filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            spec = make_session_spec(session_id="sess-fe-8")
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            result = await ts_runtime.run(prepared, FakeArtifactSink())
            assert result.status == "completed"  # no emission face, no crash

        asyncio.run(main())

    def test_filter_without_log_document_shape_still_closes_window(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-9")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: SilentFilter()
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()
            await ts_runtime.run(prepared, FakeArtifactSink())

            types = [e["event_type"] for e in _fault_events(sink)]
            # injected/activated are plan-driven; applied needs the §8.2
            # attribution (absent here); cleared still closes the window.
            assert "fault.applied" not in types
            assert types.count("fault.cleared") == 1

        asyncio.run(main())

    def test_cancelled_run_closes_the_window_without_confirmation(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-10")
            ts_runtime = TSRuntime(
                runtime=runtime,
                batch_size=10,
                filter_factory=lambda plan, config: DocumentedLogFilter(plan),
            )
            prepared = ts_runtime.prepare(
                spec, make_generator_config(output_packet_count=5000), _cc_plan(10)
            )
            sink.events.clear()
            task = asyncio.create_task(ts_runtime.run(prepared, FakeArtifactSink()))
            for _ in range(100_000):
                if ts_runtime.active_run_ids:
                    break
                await asyncio.sleep(0)
            assert ts_runtime.active_run_ids, "run never registered"
            ts_runtime.cancel(next(iter(ts_runtime.active_run_ids)))
            result = await task

            assert result.status == "cancelled"
            types = [e["event_type"] for e in sink.events]
            # Window close at run end (REMOVED) even on the cancelled path;
            # the run terminal event stays failed/cancelled (SPEC-203 §6).
            assert "fault.injected" in types
            assert "fault.cleared" in types
            assert "simulation.run_completed" not in types
            failed = next(
                e for e in sink.events
                if e["event_type"] == "simulation.run_failed"
            )
            assert failed["payload"]["reason"] == SIM_TS_CANCELLED

        asyncio.run(main())

    def test_fault_execution_failure_marks_the_run_exec_failed(self) -> None:
        """SPEC-204 §11: a run-stage transform failure puts the fault in
        FAILED (no cleared event) and fails the run per SPEC-203 semantics
        (partial artifacts marked, generation-failed face with the fault
        code as the root cause)."""

        class ExplodingTransform:
            def __init__(self, plan):
                pass

            def apply(self, index, packet):
                from faults.errors import FaultExecutionError

                raise FaultExecutionError(
                    "declared transform impossible for this stream shape"
                )

            def mutation_log(self) -> bytes:
                return b"{}"

        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-11")
            ts_runtime = TSRuntime(
                runtime=runtime,
                filter_factory=lambda plan, config: ExplodingTransform(plan),
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()
            with pytest.raises(TSGenerationFailedError) as excinfo:
                await ts_runtime.run(prepared, FakeArtifactSink())

            from faults.errors import SIM_FAULT_EXEC_FAILED

            assert excinfo.value.root_code == SIM_FAULT_EXEC_FAILED
            types = [e["event_type"] for e in sink.events]
            assert "fault.injected" in types
            # FAILED state: no applied confirmation, no window close.
            assert "fault.applied" not in types
            assert "fault.cleared" not in types
            failed = next(
                e for e in sink.events
                if e["event_type"] == "simulation.run_failed"
            )
            assert failed["payload"]["reason"] == SIM_FAULT_EXEC_FAILED

        asyncio.run(main())


class TestIndexPrecision:
    """The 188-byte invariant stays intact alongside the emission hooks."""

    def test_run_result_counts_unchanged_by_emission(self) -> None:
        async def main() -> None:
            sink, runtime, spec = await _wired_stack("sess-fe-12")
            ts_runtime = TSRuntime(
                runtime=runtime, filter_factory=lambda plan, config: DocumentedLogFilter(plan)
            )
            prepared = ts_runtime.prepare(spec, make_generator_config(), _cc_plan(10))
            sink.events.clear()
            result = await ts_runtime.run(prepared, FakeArtifactSink())

            assert result.packet_count == prepared.config.output_packet_count
            assert result.byte_count == result.packet_count * TS_PACKET_SIZE

        asyncio.run(main())
