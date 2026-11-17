"""等位替换逐层不变式 — the per-layer slot-preserving test base (#128).

SPEC-204 §Phase2: every layer's filter keeps the slot count and the packet
order (same index, same packet/frame count), and CBR holds at the TS layer
AND at the Inner TS layer independently.  This module pins those invariants
for layered runs whose faults live at BBFRAME / T2MI / BISS layers:

- layer faces: baseline and faulted legs produce equal slot counts at every
  executed stage (TS packets → BBFrame frames → T2-MI packets);
- T2-MI packet_counter continuity holds on both transmitted faces;
- payload-only faults (the BISS scrambler family touches payload bytes and
  the TSC bits only) keep the continuity counter continuous at the inner TS
  face of BOTH legs — CBR at the Inner TS layer is independent of the TS
  layer's face.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.integration

from faults.definition import FaultDefinition
from faults.factory import build_semantic_filter_factory
from simulation.fault_plan import FaultActivation
from simulation.layered_pipeline import LayerPipelineConfig
from simulation.ts_runtime import TSRuntime
from ts.generator.generator import TSGenerator
from ts.t2mi.parser import parse as parse_t2mi
from ts.t2mi.plp import PlpFilterConfig

from tests.integration.simulation.test_layered_runtime_biss import (
    _mode1_pipeline_with_oracle,
)
from tests.integration.simulation.test_layered_runtime_t2mi import (
    LayeredFakeSink,
    _t2mi_fault,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

import faults.filters.biss_mode_e  # noqa: F401 — activation
import faults.filters.bbheader_sync  # noqa: F401
import faults.filters.scrambler  # noqa: F401
import faults.filters.t2mi_plp_mismatch  # noqa: F401


def _run_layered(plan, pipeline=None, *, output_packet_count: int = 60):
    config = make_generator_config(output_packet_count=output_packet_count)
    runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
    prepared = runtime.prepare(
        make_session_spec(), config, plan, pipeline=pipeline
    )
    sink = LayeredFakeSink()
    result = asyncio.run(runtime.run(prepared, sink))
    assert result.status == "completed"
    return sink, config


def _inner_bytes(sink: LayeredFakeSink, leg: str) -> bytes:
    from ts.t2mi.inner_ts import reconstruct

    return reconstruct(parse_t2mi(sink.leg(leg))).inner_ts


def _continuity_errors(ts_bytes: bytes, config) -> int:
    """CBR verdict over one TS face — the PRODUCTION analysis chain
    (application.analysis, the same facts the journal carries), never a
    hand-rolled CC walker."""
    from application.analysis.parser import analyze_transport_stream

    facts = analyze_transport_stream(ts_bytes, config)
    return sum(getattr(fact, "continuity_error_count", 0) for fact in facts)


class TestPerLayerSlotInvariants:
    """Same index, same packet/frame count at every executed stage."""

    def test_t2mi_fault_keeps_every_layer_slot_aligned(self) -> None:
        sink, _ = _run_layered((_t2mi_fault(),), LayerPipelineConfig())
        baseline = parse_t2mi(sink.leg("baseline"))
        faulted = parse_t2mi(sink.leg("faulted"))
        assert len(baseline) == len(faulted)
        for index, (clean, drifted) in enumerate(zip(baseline, faulted)):
            assert drifted.packet_counter == clean.packet_counter
            assert drifted.frame_index == clean.frame_index
            assert drifted.total_size == clean.total_size

    def test_bbframe_fault_keeps_every_layer_slot_aligned(self) -> None:
        fault = FaultDefinition(
            fault_id="fd-b2-inv-1",
            fault_type="BBHEADER_SYNC_FAULT",
            target_id="enc-0",
            parameters={"field": "SYNCD", "mode": "shift"},
            activation=FaultActivation(kind="packet_index", packet_index=2),
            expected_observations=("bbframe.recovery_failed",),
            layer="BBFRAME",
        )
        sink, _ = _run_layered((fault,), LayerPipelineConfig())
        baseline = parse_t2mi(sink.leg("baseline"))
        faulted = parse_t2mi(sink.leg("faulted"))
        assert len(baseline) == len(faulted)
        frame_blobs_clean = [p.bbframe for p in baseline if p.bbframe]
        frame_blobs_faulted = [p.bbframe for p in faulted if p.bbframe]
        assert len(frame_blobs_clean) == len(frame_blobs_faulted)
        for clean, drifted in zip(frame_blobs_clean, frame_blobs_faulted):
            assert len(clean) == len(drifted)

    def test_biss_fault_keeps_every_layer_slot_aligned(self, golden_loader, monkeypatch) -> None:
        monkeypatch.setattr(
            "faults.filters.scrambler._DEFAULT_BACKEND_LOADER",
            lambda: __import__(
                "tests._support.csa1_oracle", fromlist=["Csa1Oracle"]
            ).Csa1Oracle(),
        )
        pipeline = _mode1_pipeline_with_oracle(golden_loader)
        sink, _ = _run_layered(
            (
                FaultDefinition(
                    fault_id="fd-biss-inv-1",
                    fault_type="BISS_KEY_MISMATCH",
                    target_id="mux-0",
                    parameters={
                        "wrong_session_word": "0123456789ab",
                        "pid_scope": [256],
                    },
                    activation=FaultActivation(
                        kind="session_start", packet_index=None
                    ),
                    expected_observations=("biss.descramble_failed",),
                    layer="BISS",
                ),
            ),
            pipeline,
        )
        baseline = parse_t2mi(sink.leg("baseline"))
        faulted = parse_t2mi(sink.leg("faulted"))
        assert len(baseline) == len(faulted)


class TestCBRPerFace:
    """CBR holds at the TS layer and at the Inner TS layer independently."""

    def test_payload_only_faults_keep_cbr_on_both_inner_faces(
        self, golden_loader, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "faults.filters.scrambler._DEFAULT_BACKEND_LOADER",
            lambda: __import__(
                "tests._support.csa1_oracle", fromlist=["Csa1Oracle"]
            ).Csa1Oracle(),
        )
        pipeline = _mode1_pipeline_with_oracle(golden_loader)
        sink, config = _run_layered(
            (
                FaultDefinition(
                    fault_id="fd-biss-inv-2",
                    fault_type="BISS_KEY_MISMATCH",
                    target_id="mux-0",
                    parameters={
                        "wrong_session_word": "0123456789ab",
                        "pid_scope": [256],
                    },
                    activation=FaultActivation(
                        kind="session_start", packet_index=None
                    ),
                    expected_observations=("biss.descramble_failed",),
                    layer="BISS",
                ),
            ),
            pipeline,
        )
        # The reference face: a faultless generator stream is CBR-clean.
        reference = b"".join(
            packet.to_bytes()
            for packet in TSGenerator().iter_packets(config)
        )
        assert _continuity_errors(reference, config) == 0
        # CBR at the Inner TS layer: BOTH legs' reconstructions stay
        # continuous — the BISS scrambler family is payload-only.
        assert _continuity_errors(_inner_bytes(sink, "baseline"), config) == 0
        assert _continuity_errors(_inner_bytes(sink, "faulted"), config) == 0

    def test_t2mi_packet_counters_stay_continuous_on_both_faces(self) -> None:
        sink, _ = _run_layered((_t2mi_fault(),), LayerPipelineConfig())
        for leg in ("baseline", "faulted"):
            packets = parse_t2mi(sink.leg(leg))
            counters = [packet.packet_counter for packet in packets]
            for previous, current in zip(counters, counters[1:]):
                assert current == (previous + 1) % 256
