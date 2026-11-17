"""Layered runtime end-to-end — BBFRAME layer injection (ticket #128, AC).

The B2 story through the instantiated pipeline: ``BBHEADER_SYNC_FAULT``
(corrupt, SYNCD) routes to the BBFRAME layer's filter instance and faults
exactly the frames at/after its activation index — the faulted frames
re-parse with ``crc8_invalid`` (the ``bbframe.recovery_failed`` evidence
face, #123), the frame count stays identical (等位替换逐层 at the frame
index space), and the receiver face lands the reconstruction evidence.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.integration

from faults.definition import FaultDefinition
from faults.factory import build_semantic_filter_factory
from simulation.fault_plan import FaultActivation
from simulation.layered_pipeline import LayerPipelineConfig
from simulation.ts_runtime import TSRuntime
from ts.t2mi.bbframe import parse as parse_bbframe
from ts.t2mi.bbframe_summary import RECOVERY_FAILED_PAYLOAD_KEYS
from ts.t2mi.parser import parse as parse_t2mi

from tests.integration.simulation.test_layered_runtime_t2mi import (
    LayeredFakeSink,
    _payloads_of,
    _stub_phase2_registry,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

import faults.filters.bbheader_sync  # noqa: F401 — self-registration activation
import faults.filters.biss_mode_e  # noqa: F401
import faults.filters.scrambler  # noqa: F401
import faults.filters.t2mi_plp_mismatch  # noqa: F401


def _bbframe_fault(*, index: int = 1, fault_id: str = "fd-b2-128-1"):
    return FaultDefinition(
        fault_id=fault_id,
        fault_type="BBHEADER_SYNC_FAULT",
        target_id="enc-0",
        parameters={"field": "SYNCD", "mode": "corrupt"},
        activation=FaultActivation(kind="packet_index", packet_index=index),
        expected_observations=("bbframe.recovery_failed",),
        layer="BBFRAME",
    )


class TestLayeredBBFramePipeline:
    """BBFRAME-layer injection end-to-end (the B2 symptom chain)."""

    @pytest.fixture()
    def run_faces(self):
        config = make_generator_config(output_packet_count=40)
        runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
        prepared = runtime.prepare(
            make_session_spec(),
            config,
            (_bbframe_fault(index=1),),
            pipeline=LayerPipelineConfig(),
        )
        sink = LayeredFakeSink()
        result = asyncio.run(runtime.run(prepared, sink))
        return runtime, prepared, sink, result

    def test_run_completes_and_faces_stay_slot_aligned(self, run_faces) -> None:
        _, _, sink, result = run_faces
        assert result.status == "completed"
        baseline_frames = _frames_of(sink.leg("baseline"))
        faulted_frames = _frames_of(sink.leg("faulted"))
        # 等位替换逐层 at the BBFRAME index space: same frame count, the
        # faulted frames keep their slots and lengths.
        assert len(baseline_frames) == len(faulted_frames) > 1
        for clean, faulted in zip(baseline_frames, faulted_frames):
            assert _frame_size(clean) == _frame_size(faulted)

    def test_faulted_frames_carry_crc8_invalid_from_the_activation(
        self, run_faces
    ) -> None:
        _, _, sink, _ = run_faces
        baseline_frames = _frames_of(sink.leg("baseline"))
        faulted_frames = _frames_of(sink.leg("faulted"))
        assert all(frame.crc8_valid for frame in baseline_frames)
        # Activation semantics (ADR-0007 item 3): the fault runs from its
        # packet_index activation through run end — every frame at/after
        # index 1 carries the corrupt SYNCD (crc8_invalid); the frame
        # before it passes through untouched.
        assert faulted_frames[0].crc8_valid
        for frame in faulted_frames[1:]:
            assert not frame.crc8_valid
            assert frame.state == "crc8_invalid"

    def test_mutation_log_documents_the_frame_layer(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        document = json.loads(sink.leg("log").decode("utf-8"))
        assert document["layers"] == ["BBFRAME"]
        entry = document["layer_logs"]["BBFRAME"]["faults"][0]
        assert entry["layer"] == "BBFRAME"
        applied = entry["lifecycle"]["fault.applied"]
        assert applied[0] == 1 and applied == list(range(1, len(applied) + 1))
        record = document["layer_logs"]["BBFRAME"]["mutations"][0]
        assert record["packet_index"] == 1
        assert record["before"]["frame_len"] == record["after"]["frame_len"]

    def test_result_counts_describe_the_outer_face(self, run_faces) -> None:
        _, _, sink, result = run_faces
        assert result.packet_count == len(parse_t2mi(sink.leg("baseline")))
        assert result.byte_count == len(sink.leg("baseline"))


class TestBBFrameEventDelivery:
    """``bbframe.recovery_failed`` + ``fault.activated`` at the frame index."""

    def test_recovery_failed_carries_the_frozen_payload_keys(
        self, monkeypatch
    ) -> None:
        _stub_phase2_registry(monkeypatch)
        events = _run_with_delivery()
        recovery = _payloads_of(events, "bbframe.recovery_failed")
        assert len(recovery) == 1
        assert set(recovery[0]) == RECOVERY_FAILED_PAYLOAD_KEYS
        assert recovery[0]["failure_count"] >= 1
        assert recovery[0]["first_failed_frame_index"] == 1
        # The activation crossing fired in the frame index space.
        activated = _payloads_of(events, "fault.activated")
        assert activated and activated[0]["layer"] == "BBFRAME"

    def test_clean_run_emits_no_recovery_failed(self, monkeypatch) -> None:
        _stub_phase2_registry(monkeypatch)
        events = _run_with_delivery(faulted=False)
        assert _payloads_of(events, "bbframe.recovery_failed") == []


def _frames_of(outer: bytes):
    packets = parse_t2mi(outer)
    blobs = [packet.bbframe for packet in packets if packet.bbframe is not None]
    return parse_bbframe(blobs)


def _frame_size(frame) -> int:
    return 10 + len(frame.data_field)


def _run_with_delivery(*, faulted: bool = True) -> list[dict]:
    from simulation.runtime import SimulationRuntime

    sink = LayeredFakeSink()
    events: list[dict] = []

    class RecordingGateway:
        def publish(self, event) -> None:
            events.append(dict(event))

    async def main() -> None:
        sim_runtime = SimulationRuntime(event_sink=RecordingGateway())
        config = make_generator_config(output_packet_count=40)
        session = make_session_spec(session_id="layered-b2")
        await sim_runtime.create_session(session)
        await sim_runtime.validate_session(session.session_id)
        await sim_runtime.start(session.session_id)
        ts_runtime = TSRuntime(
            runtime=sim_runtime, filter_factory=build_semantic_filter_factory()
        )
        plan = (_bbframe_fault(index=1),) if faulted else ()
        prepared = ts_runtime.prepare(
            session, config, plan, pipeline=LayerPipelineConfig()
        )
        result = await ts_runtime.run(prepared, sink)
        assert result.status == "completed"
        ts_runtime.shutdown()

    asyncio.run(main())
    return events
