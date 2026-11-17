"""Layered runtime end-to-end — T2MI layer injection (ticket #128, AC).

The B1 story through the instantiated pipeline: the plan's
``T2MI_PLP_MISMATCH`` fault routes to the T2-MI layer's filter instance;
the encapsulated faulted face re-parses clean (外层绿灯 — CRC valid,
counters continuous, zero truncation) while the demux, filtering on the
declared ``expected_plp``, receives the explicit empty result and the
honest 缺失 ≠ 零 candidate.  The baseline face reconstructs the business
byte-identically (chain round-trip).

Discipline: real SPEC-108 generator bytes only; the tee artifacts are the
outermost (transmitted T2-MI) face; middle-layer evidence lives in the
per-layer mutation logs; per-layer slot-preserving invariants are asserted
at every stage (等位替换逐层).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest

pytestmark = pytest.mark.integration

from faults.definition import FaultDefinition
from faults.factory import build_semantic_filter_factory
from simulation.fault_plan import FaultActivation
from simulation.layered_pipeline import (
    GEN_PACKET_SAMPLED_EVENT_TYPE,
    GEN_STAGE_COMPLETED_EVENT_TYPE,
    GEN_STAGE_STARTED_EVENT_TYPE,
    LayerPipelineConfig,
    SAMPLE_WINDOW_DEFAULT,
    is_layered_plan,
)
from simulation.ts_runtime import TSRuntime
from ts.generator.generator import TSGenerator
from ts.t2mi.inner_ts import reconstruct
from ts.t2mi.parser import parse as parse_t2mi
from ts.t2mi.plp import (
    PLP_MISMATCH_PAYLOAD_KEYS,
    PlpFilterConfig,
    collect_plp_mismatch,
    filter as plp_filter,
    plps_seen,
)
from ts.t2mi.summary import STAGE_SUMMARY_PAYLOAD_KEYS

from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

# Filter activation duty (composition-root import face): the T2MI layer's
# real transform self-registers at import (ruling §10-4).
import faults.filters.t2mi_plp_mismatch  # noqa: F401,E402
import faults.filters.scrambler  # noqa: F401,E402
import faults.filters.bbheader_sync  # noqa: F401,E402
import faults.filters.biss_mode_e  # noqa: F401,E402


class LayeredFakeSink:
    """ArtifactSink fake with the #128 inner-ts landing face."""

    def __init__(self) -> None:
        self.legs = {}
        self.records: list[dict] = []
        self.inner_store: dict[str, bytes] = {}
        self._reusable: dict[tuple, str] = {}

    def open_legs(self, *, tee: bool, run_id: str, session_id: str) -> Any:
        from tests.unit.simulation._ts_runtime_builders import RecordingSinkLeg

        legs = {"baseline": RecordingSinkLeg("baseline")}
        if tee:
            legs["faulted"] = RecordingSinkLeg("faulted")
            legs["log"] = RecordingSinkLeg("log")
        self.legs = legs

        class _Legs:
            pass

        holder = _Legs()
        holder.baseline = legs["baseline"]
        holder.faulted = legs.get("faulted")
        holder.log = legs.get("log")
        return holder

    def register(
        self,
        *,
        run_id,
        session_id,
        kind,
        commit,
        packet_count,
        config_hash,
        generator_version,
        partial,
        packet_size="__legacy__",
    ) -> str:
        artifact_id = f"artifact-{len(self.records) + 1}"
        self.records.append(
            {
                "artifact_id": artifact_id,
                "kind": kind,
                "sha256": commit["sha256"],
                "byte_size": commit["byte_size"],
                "packet_count": packet_count,
                "packet_size": packet_size,
                "partial": partial,
            }
        )
        if kind == "generated_ts" and not partial:
            self._reusable.setdefault(
                (commit["sha256"], config_hash, packet_count), artifact_id
            )
        return artifact_id

    def find_reusable_baseline(self, sha256, config_hash, packet_count):
        return self._reusable.get((sha256, config_hash, packet_count))

    def store_inner_ts(
        self,
        *,
        run_id,
        session_id,
        data: bytes,
        config_hash,
        generator_version,
        partial=False,
    ) -> str:
        artifact_id = f"inner-{len(self.inner_store) + 1}"
        self.inner_store[artifact_id] = data
        self.records.append(
            {
                "artifact_id": artifact_id,
                "kind": "inner_ts",
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_size": len(data),
                "packet_count": len(data) // 188,
                "packet_size": 188,
                "partial": partial,
            }
        )
        return artifact_id

    def leg(self, name: str) -> bytes:
        return self.legs[name].data

    def kinds(self) -> list[str]:
        return [record["kind"] for record in self.records]


def _t2mi_fault(*, expected=0, actual=1, fault_id="fd-t2mi-128-1"):
    return FaultDefinition(
        fault_id=fault_id,
        fault_type="T2MI_PLP_MISMATCH",
        target_id="enc-0",
        parameters={"expected_plp": expected, "actual_plp": actual},
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("t2mi.plp_mismatch",),
        layer="T2MI",
    )


def _run(config, plan, pipeline=None):
    runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
    prepared = runtime.prepare(
        make_session_spec(), config, plan, pipeline=pipeline
    )
    sink = LayeredFakeSink()
    result = asyncio.run(runtime.run(prepared, sink))
    return runtime, prepared, sink, result


class TestLayerRoutingActivation:
    """The plan routes beyond TS; the MVP path would refuse it loudly."""

    def test_plan_is_detected_as_layered(self) -> None:
        assert is_layered_plan((_t2mi_fault(),))


class TestLayeredT2miPipeline:
    """T2MI-layer injection end-to-end (the B1 symptom chain)."""

    @pytest.fixture()
    def run_faces(self):
        config = make_generator_config(output_packet_count=60)
        return _run(config, (_t2mi_fault(),))

    def test_run_completes_with_three_tee_artifacts(self, run_faces) -> None:
        _, _, sink, result = run_faces
        assert result.status == "completed"
        # The receiver-face inner_ts rows land during the worker; the tee
        # legs register at commit time (run-dimension artifact refs).
        assert sink.kinds() == [
            "inner_ts",
            "inner_ts",
            "generated_ts",
            "faulted_ts",
            "log",
        ]

    def test_tee_faces_are_t2mi_streams(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        for leg in ("baseline", "faulted"):
            stream = sink.leg(leg)
            parsed = parse_t2mi(stream)
            assert len(parsed) >= 1
            assert not parsed.truncated
            # The outer face is NOT the 188-byte MVP frame: honest layered
            # registration carries no packet_size claim.
            assert sink.leg(leg) != b""

    def test_faulted_face_restamps_plp_and_stays_parseable(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        baseline = parse_t2mi(sink.leg("baseline"))
        faulted = parse_t2mi(sink.leg("faulted"))
        # 等位替换逐层: same T2-MI packet count at the same indexes.
        assert len(baseline) == len(faulted)
        assert all(packet.crc32_valid for packet in faulted)
        assert not faulted.truncated
        baseline_plps = plps_seen(baseline)["plps_seen"]
        faulted_plps = plps_seen(faulted)["plps_seen"]
        assert baseline_plps == [0]
        assert faulted_plps == [1]
        for index, packet in enumerate(faulted):
            if packet.payload_kind == "bbframe":
                assert packet.frame_index == baseline[index].frame_index
                assert packet.packet_counter == baseline[index].packet_counter

    def test_demux_expected_filter_yields_the_b1_candidate(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        faulted = parse_t2mi(sink.leg("faulted"))
        selected = plp_filter(
            faulted, PlpFilterConfig(mode="expected", expected_plp=0)
        )
        assert selected == ()
        candidate = collect_plp_mismatch(
            faulted, PlpFilterConfig(mode="expected", expected_plp=0)
        )
        assert candidate is not None
        assert set(candidate) == PLP_MISMATCH_PAYLOAD_KEYS

    def test_baseline_reconstructs_the_business_byte_identically(
        self, run_faces
    ) -> None:
        config = make_generator_config(output_packet_count=60)
        _, _, sink, result = run_faces
        parsed = parse_t2mi(sink.leg("baseline"))
        reconstructed = reconstruct(parsed)
        assert reconstructed.reconstruction_status == "ok"
        # Chain round-trip: the reconstructed inner TS IS the generator's
        # business stream (same deterministic config ⇒ same bytes).
        direct = hashlib.sha256(
            b"".join(
                packet.to_bytes()
                for packet in TSGenerator().iter_packets(config)
            )
        ).hexdigest()
        assert hashlib.sha256(reconstructed.inner_ts).hexdigest() == direct

    def test_inner_ts_artifacts_are_content_addressed(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        inner_records = [
            record for record in sink.records if record["kind"] == "inner_ts"
        ]
        assert len(inner_records) == 2  # baseline + faulted legs
        for record in inner_records:
            stored = sink.inner_store[record["artifact_id"]]
            assert record["sha256"] == hashlib.sha256(stored).hexdigest()

    def test_log_document_is_the_layered_wrapper(self, run_faces) -> None:
        _, _, sink, _ = run_faces
        document = json.loads(sink.leg("log").decode("utf-8"))
        assert document["log_kind"] == "layered_pipeline_mutation_log"
        assert document["layers"] == ["T2MI"]
        layer_doc = document["layer_logs"]["T2MI"]
        faults = layer_doc["faults"]
        assert faults[0]["fault_type"] == "T2MI_PLP_MISMATCH"
        assert faults[0]["layer"] == "T2MI"
        assert faults[0]["lifecycle"]["fault.applied"]
        # The pipeline section carries the faces and the inner-ts bindings.
        pipeline_section = document["pipeline"]
        assert pipeline_section["outer_packet_count"] == len(
            parse_t2mi(sink.leg("baseline"))
        )
        assert set(pipeline_section["inner_ts"]) == {"baseline", "faulted"}

    def test_result_counts_describe_the_outer_face(self, run_faces) -> None:
        _, _, sink, result = run_faces
        baseline = parse_t2mi(sink.leg("baseline"))
        assert result.packet_count == len(baseline)
        assert result.byte_count == len(sink.leg("baseline"))


def _reconstruct_all(parsed):
    return reconstruct(parsed)


# --- event delivery posture (wired runtime + registry stub) ----------------------


class TestLayeredEventDelivery:
    """gen.* + t2mi.* delivery through the wired runtime face.

    Ruling §10-7: the payloads are #128's deliverable; the registry stub
    path proves the envelopes would pass once #129 lands the entries.
    """

    def test_stage_event_order_and_magnitude(self, monkeypatch) -> None:
        _stub_phase2_registry(monkeypatch)
        events = _run_with_delivery()
        types = [event["event_type"] for event in events]
        # Stage frames: started/completed pairs in chain order.
        started = [t for t in types if t == GEN_STAGE_STARTED_EVENT_TYPE]
        completed = [t for t in types if t == GEN_STAGE_COMPLETED_EVENT_TYPE]
        layers_started = [
            payload["layer"]
            for payload in _payloads_of(events, GEN_STAGE_STARTED_EVENT_TYPE)
        ]
        assert layers_started == ["TS", "BBFRAME", "T2MI"]
        assert len(started) == len(completed) == 3
        # Magnitude obligation: O(层数) + O(抽样) — sampled events bounded
        # by window + tail per stage (no per-packet stream, #112).
        sampled = _payloads_of(events, GEN_PACKET_SAMPLED_EVENT_TYPE)
        assert 0 < len(sampled) <= 3 * (SAMPLE_WINDOW_DEFAULT + 1)
        # Per-layer sampled index spaces are independent (逐层 index spaces).
        layers_sampled = {payload["layer"] for payload in sampled}
        assert layers_sampled == {"TS", "BBFRAME", "T2MI"}
        # The t2mi stage summary + the B1 candidate both reached the sink.
        summary = _payloads_of(events, "t2mi.stage_summary")
        assert summary and set(summary[0]) == STAGE_SUMMARY_PAYLOAD_KEYS
        mismatch = _payloads_of(events, "t2mi.plp_mismatch")
        assert mismatch and set(mismatch[0]) == PLP_MISMATCH_PAYLOAD_KEYS
        # Injection-point rule: the fault.applied confirmation carries the
        # layer attribution and the confirmed restamp slots.
        applied = _payloads_of(events, "fault.applied")
        assert applied and applied[0]["layer"] == "T2MI"
        assert applied[0]["applied_packet_indexes"]

    def test_guard_world_skips_only_the_phase2_types(self) -> None:
        # Today's registry (no stub): the Phase 2 events are skipped by the
        # guard and the run still completes — no EnvelopeError may ever
        # break the run outcome (ruling §10-7). The registered families
        # (session_*/run_*/fault.*) still publish.
        events = _run_with_delivery()
        types = {event["event_type"] for event in events}
        assert "fault.applied" in types
        for event_type in types:
            assert not event_type.startswith(("gen.", "t2mi.", "bbframe.", "biss."))


def _stub_phase2_registry(monkeypatch) -> None:
    from domain.observation.registry import REGISTERED_EVENT_TYPES

    registered = frozenset(REGISTERED_EVENT_TYPES)
    lookup = lambda event_type: (  # noqa: E731
        event_type.startswith(("gen.", "t2mi.", "bbframe.", "biss."))
        or event_type in registered
    )
    monkeypatch.setattr("simulation.events.is_registered", lookup)
    monkeypatch.setattr("domain.observation.registry.is_registered", lookup)


def _payloads_of(events, event_type):
    return [
        event["payload"] for event in events if event["event_type"] == event_type
    ]


def _run_with_delivery() -> list[dict]:
    """A layered run through the full wired posture (run + sink faces)."""
    from simulation.runtime import SimulationRuntime

    sink = LayeredFakeSink()
    events: list[dict] = []

    class RecordingGateway:
        def publish(self, event) -> None:
            events.append(dict(event))

    async def main() -> None:
        sim_runtime = SimulationRuntime(event_sink=RecordingGateway())
        config = make_generator_config(output_packet_count=60)
        session = make_session_spec(session_id="layered-t2mi")
        await sim_runtime.create_session(session)
        await sim_runtime.validate_session(session.session_id)
        await sim_runtime.start(session.session_id)
        ts_runtime = TSRuntime(
            runtime=sim_runtime, filter_factory=build_semantic_filter_factory()
        )
        prepared = ts_runtime.prepare(
            session, config, (_t2mi_fault(),), pipeline=LayerPipelineConfig()
        )
        result = await ts_runtime.run(prepared, sink)
        assert result.status == "completed"
        ts_runtime.shutdown()

    asyncio.run(main())
    return events
