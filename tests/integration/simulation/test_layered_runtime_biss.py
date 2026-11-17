"""Layered runtime end-to-end — BISS layer injection (ticket #128, AC).

ADR-0011 §2 posture: the scrambler is the ADR-0007 packet-level filter
family at ``layer=BISS``; the construction feature (scenario-declared key)
and the fault injection (``BISS_KEY_MISMATCH`` mismatched key) drive the
same transform family — only the key source differs.  On the faulted leg
the fault's scrambler replaces the construction scrambler; the receiver
face descrambles with the DECLARED key, so the faulted face produces the
``biss.descramble_failed`` candidate (解扰失败 ≠ 码流损坏, ADR-0011 §4)
while the baseline face descrambles cleanly.

Key discipline (SPEC-610 §9, 简报 §5-6): the construction keys come from
the registered golden manifests (public standard constants with
provenance); the synthetic wrong keys are test constants whose absence
from every journal payload and the mutation log is asserted.  The CSA1
backend is the pure-Python CI oracle (tests/_support, 禁进运行时).
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.integration

from faults.definition import FaultDefinition
from faults.factory import build_semantic_filter_factory
from simulation.fault_plan import FaultActivation
from simulation.layered_pipeline import (
    BissFaceConfig,
    LayerPipelineConfig,
)
from simulation.ts_runtime import TSRuntime
from ts.packet import TSPacket
from ts.t2mi.inner_ts import reconstruct
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

import faults.filters.biss_mode_e  # noqa: F401 — self-registration activation
import faults.filters.bbheader_sync  # noqa: F401
import faults.filters.scrambler  # noqa: F401
import faults.filters.t2mi_plp_mismatch  # noqa: F401

from tests._support.csa1_oracle import Csa1Oracle

#: The synthetic WRONG key (the fault's shape — must never reach any
#: journal payload or the mutation log; asserted below).
WRONG_SESSION_WORD = "0123456789ab"

SCRAMBLE_APPLIED_KEYS = {
    "pid_scope",
    "packet_count",
    "key_fingerprint",
    "mutation_log_ref",
    "mode",
}
DESCRAMBLE_FAILED_KEYS = {
    "pid_scope",
    "failed_indices_sample",
    "self_check_kind",
    "key_fingerprint_ref",
    "mode",
}


def _golden_biss(golden_loader, vector_id: str) -> dict:
    """The registered manifest's ``biss`` block (public standard constants
    with provenance — no in-test key literals for the construction face)."""
    manifest_path = golden_loader.root / vector_id / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))["biss"]


def _mode1_pipeline_with_oracle(golden_loader) -> LayerPipelineConfig:
    biss = _golden_biss(golden_loader, "biss-j96-mode1")
    face = BissFaceConfig(
        mode=str(biss["mode"]),
        session_word=str(biss["session_word"]),
        pid_scope=tuple(biss["pid_scope"]),
    )
    return LayerPipelineConfig(
        biss=face,
        csa_backend_factory=lambda: Csa1Oracle(),
    )


def _mode_e_pipeline_with_derived(golden_loader) -> LayerPipelineConfig:
    biss = _golden_biss(golden_loader, "biss-mode-e-derive")
    face = BissFaceConfig(
        mode=str(biss["mode"]),
        encrypted_sw=str(biss["encrypted_sw"]),
        injected_id=str(biss["injected_id"]),
        pid_scope=tuple(biss["pid_scope"]),
    )
    return LayerPipelineConfig(biss=face)  # CISSA: pure Python, no DLL


def _biss_fault(*, fault_id: str = "fd-biss-128-1") -> FaultDefinition:
    return FaultDefinition(
        fault_id=fault_id,
        fault_type="BISS_KEY_MISMATCH",
        target_id="mux-0",
        parameters={
            "wrong_session_word": WRONG_SESSION_WORD,
            "pid_scope": [256],
        },
        activation=FaultActivation(kind="session_start", packet_index=None),
        expected_observations=("biss.descramble_failed",),
        layer="BISS",
    )


def _descramble_checks(inner_ts: bytes, session_word: str):
    from ts.biss.biss1 import descramble

    packets = [
        TSPacket.from_bytes(inner_ts[offset : offset + 188])
        for offset in range(0, len(inner_ts), 188)
    ]
    _, checks = descramble(
        packets, session_word, (256,), backend=Csa1Oracle()
    )
    return checks


class TestLayeredBISSMode1Pipeline:
    """BISS-layer injection end-to-end (Mode 1, CSA1 oracle backend)."""

    @pytest.fixture(autouse=True)
    def _oracle_backend_loader(self, monkeypatch):
        """The scrambler's sanctioned default-backend seam (module docstring:
        tests swap it) — the pure-Python CSA1 oracle is the CI face, so the
        fault-path filter needs no DLL anywhere (ADR-0011 §5)."""
        from faults.filters import scrambler as scrambler_module

        monkeypatch.setattr(
            scrambler_module, "_DEFAULT_BACKEND_LOADER", lambda: Csa1Oracle()
        )

    @pytest.fixture()
    def run_faces(self, golden_loader):
        config = make_generator_config(output_packet_count=60)
        runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
        prepared = runtime.prepare(
            make_session_spec(),
            config,
            (_biss_fault(),),
            pipeline=_mode1_pipeline_with_oracle(golden_loader),
        )
        sink = LayeredFakeSink()
        result = asyncio.run(runtime.run(prepared, sink))
        return runtime, prepared, sink, result, golden_loader

    def test_run_completes_with_slot_aligned_faces(self, run_faces) -> None:
        _, _, sink, result, _ = run_faces
        assert result.status == "completed"
        baseline = parse_t2mi(sink.leg("baseline"))
        faulted = parse_t2mi(sink.leg("faulted"))
        assert len(baseline) == len(faulted) > 0

    def test_baseline_descrambles_cleanly_with_the_declared_key(
        self, run_faces
    ) -> None:
        _, _, sink, _, golden_loader = run_faces
        declared = str(_golden_biss(golden_loader, "biss-j96-mode1")["session_word"])
        inner = reconstruct(parse_t2mi(sink.leg("baseline")))
        assert inner.reconstruction_status == "ok"
        failures = [
            check for check in _descramble_checks(inner.inner_ts, declared) if not check.ok
        ]
        assert failures == []

    def test_faulted_face_fails_the_declared_key_descramble(
        self, run_faces
    ) -> None:
        _, _, sink, _, golden_loader = run_faces
        declared = str(_golden_biss(golden_loader, "biss-j96-mode1")["session_word"])
        inner = reconstruct(parse_t2mi(sink.leg("faulted")))
        assert inner.reconstruction_status == "ok"
        failures = [
            check for check in _descramble_checks(inner.inner_ts, declared) if not check.ok
        ]
        # 解扰失败 ≠ 码流损坏: explicit self-check failures — the stream
        # is structurally intact, the key is wrong.
        assert failures
        assert {check.self_check_kind for check in failures}

    def test_biss_events_delivered_with_frozen_key_sets(
        self, run_faces, monkeypatch
    ) -> None:
        # Re-run with delivery + registry stub to assert the payloads.
        _, prepared, _, _, golden_loader = run_faces
        del prepared
        _stub_phase2_registry(monkeypatch)
        events = _run_mode1_with_delivery(golden_loader)
        applied = _payloads_of(events, "biss.scramble_applied")
        assert len(applied) == 2  # construction + fault path
        for payload in applied:
            assert set(payload) == SCRAMBLE_APPLIED_KEYS
            assert payload["mode"] == "1"
            assert payload["mutation_log_ref"]
        failed = _payloads_of(events, "biss.descramble_failed")
        assert len(failed) == 1
        assert set(failed[0]) == DESCRAMBLE_FAILED_KEYS
        assert failed[0]["mode"] == "1"
        assert failed[0]["failed_indices_sample"]
        # The construction and fault scrambles use DIFFERENT keys
        # (fingerprints differ) — the mismatch is observable without any
        # key body.
        fingerprints = {payload["key_fingerprint"] for payload in applied}
        assert len(fingerprints) == 2

    def test_key_material_never_reaches_journal_or_log(
        self, run_faces, monkeypatch
    ) -> None:
        _, _, sink, _, golden_loader = run_faces
        declared = str(_golden_biss(golden_loader, "biss-j96-mode1")["session_word"])
        _stub_phase2_registry(monkeypatch)
        events = _run_mode1_with_delivery(golden_loader)
        journal_text = json.dumps(events).lower()
        assert WRONG_SESSION_WORD.lower() not in journal_text
        assert declared.lower() not in journal_text
        log_text = sink.leg("log").decode("utf-8").lower()
        assert WRONG_SESSION_WORD.lower() not in log_text
        assert declared.lower() not in log_text
        # Only fingerprint traces carry the key faces.
        assert journal_text.count("sha256:") >= 2


class TestLayeredBISSModeEPipeline:
    """Mode E construction face (CISSA, pure Python — CI 全测面)."""

    def test_mode_e_construction_descrambles_cleanly(
        self, golden_loader
    ) -> None:
        config = make_generator_config(output_packet_count=60)
        runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
        prepared = runtime.prepare(
            make_session_spec(),
            config,
            (),
            pipeline=_mode_e_pipeline_with_derived(golden_loader),
        )
        sink = LayeredFakeSink()
        result = asyncio.run(runtime.run(prepared, sink))
        assert result.status == "completed"
        inner = reconstruct(parse_t2mi(sink.leg("baseline")))
        assert inner.reconstruction_status == "ok"

    def test_mode_e_wrong_key_fault_produces_the_evidence(
        self, golden_loader, monkeypatch
    ) -> None:
        biss = _golden_biss(golden_loader, "biss-mode-e-derive")
        wrong_esw_fault = FaultDefinition(
            fault_id="fd-bisse-128-1",
            fault_type="BISS_KEY_MISMATCH",
            target_id="mux-0",
            parameters={
                "wrong_esw": "0123456789abcdef",
                "pid_scope": [256],
            },
            activation=FaultActivation(kind="session_start", packet_index=None),
            expected_observations=("biss.descramble_failed",),
            layer="BISS",
        )
        _stub_phase2_registry(monkeypatch)
        events = _run_with_delivery(
            pipeline=_mode_e_pipeline_with_derived(golden_loader),
            plan=(wrong_esw_fault,),
        )
        applied = _payloads_of(events, "biss.scramble_applied")
        assert len(applied) == 2  # construction face + fault path
        assert applied[0]["mode"] == "E"
        # 错面证据可区分 (SPEC-611 §8): the fault-path summary names the
        # wrong face and carries the whole wrong-chain fingerprints.
        assert applied[1]["mismatch_variants"] == ["wrong_esw"]
        assert set(applied[1]["derivation_ref"]) == {
            "esw_fingerprint",
            "injected_id_fingerprint",
            "session_word_fingerprint",
            "ciss_key_fingerprint",
        }
        failed = _payloads_of(events, "biss.descramble_failed")
        assert len(failed) == 1
        assert failed[0]["mode"] == "E"
        journal_text = json.dumps(events).lower()
        assert "0123456789abcdef" not in journal_text
        assert str(biss["encrypted_sw"]).lower() not in journal_text


def _run_mode1_with_delivery(golden_loader) -> list[dict]:
    return _run_with_delivery(
        pipeline=_mode1_pipeline_with_oracle(golden_loader),
        plan=(_biss_fault(),),
    )


def _run_with_delivery(*, pipeline: LayerPipelineConfig, plan) -> list[dict]:
    from simulation.runtime import SimulationRuntime

    sink = LayeredFakeSink()
    events: list[dict] = []

    class RecordingGateway:
        def publish(self, event) -> None:
            events.append(dict(event))

    async def main() -> None:
        sim_runtime = SimulationRuntime(event_sink=RecordingGateway())
        config = make_generator_config(output_packet_count=60)
        session = make_session_spec(session_id="layered-biss")
        await sim_runtime.create_session(session)
        await sim_runtime.validate_session(session.session_id)
        await sim_runtime.start(session.session_id)
        ts_runtime = TSRuntime(
            runtime=sim_runtime, filter_factory=build_semantic_filter_factory()
        )
        prepared = ts_runtime.prepare(session, config, plan, pipeline=pipeline)
        result = await ts_runtime.run(prepared, sink)
        assert result.status == "completed"
        ts_runtime.shutdown()

    asyncio.run(main())
    return events
