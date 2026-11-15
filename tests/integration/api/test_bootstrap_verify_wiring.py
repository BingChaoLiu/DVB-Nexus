"""Production composition-root wiring for the fault-lab chain (ticket #58).

Three additive bindings the #58 e2e loop needs from
``build_production_app`` (each previously absent at the integration/m4
tip — recorded as ticket #58 Spec Deviations with the #56/#53 report
pointers):

1. ``verification_port`` — the SPEC-206 verify endpoint serves the real
   three-state verdict through the production stack instead of the 501
   freeze answer (#56 report "需要他模块配合" gave the composition;
   orchestrator 批复: bind here, declare in the report).
2. ``SimulationRuntime(event_sink=gateway)`` — the session/run/fault
   lifecycle event family reaches the observation plane (without the
   sink the emitter is opt-out and fault.*/run_* never land in the
   journal; the wiring pattern is the #41 gateway-wiring precedent).
3. ``analysis_service`` — the 裁定 A analysis bridge is exposed on the
   stack (the 裁定 B in-process Analyze anchor; the REST analyze route
   stays frozen 501).
"""

from __future__ import annotations

import asyncio

import pytest

from api.versioning import API_V1_PREFIX
from bootstrap import build_production_app

SESSION = "sess-verify-wiring"

pytestmark = pytest.mark.integration


def _make_stack(tmp_path):
    return build_production_app(db_path=tmp_path / "wiring.sqlite3")


def test_verify_endpoint_serves_the_real_verdict_not_the_freeze(tmp_path):
    """POST .../verify answers the SPEC-206 contract on the production
    stack (the port is bound; an unbound port keeps the 501 freeze)."""
    stack = _make_stack(tmp_path)
    try:
        stack.gateway.accept(_lifecycle_envelope("simulation.run_started", 1))
        stack.gateway.accept(
            _lifecycle_envelope("simulation.run_completed", 2)
        )
        stack.drain_gateway()

        from fastapi.testclient import TestClient

        with TestClient(stack.app) as client:
            response = client.post(
                f"{API_V1_PREFIX}/sessions/{SESSION}/runs/run-1/verify",
                json={
                    "baseline_run_id": "run-1",
                    "scenario": {
                        "scenario_id": "3f2b4a1c-0000-4000-8000-00000000ab01",
                        "version": "1.0.0",
                        "content_hash": "deadbeef",
                    },
                    "pass_criteria": [
                        {
                            "criterion_id": "c1",
                            "kind": "fault_inactive",
                            "mandatory": True,
                            "fault_id": "fd000000-0000-4000-8000-000000000001",
                        }
                    ],
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verdict"] == "INCONCLUSIVE"  # candidate IS the baseline
        assert body["criteria"][0]["reason_code"] == "SIM_VERIF_BASELINE_REUSED"
    finally:
        stack.close()


def _lifecycle_envelope(event_type: str, value_ns: int) -> dict:
    """A minimal schema-valid run-lifecycle envelope (the same posture
    the bootstrap stack tests use)."""
    from tests.unit.application.observation.test_gateway_accept import (
        _raw_envelope,
    )

    envelope = _raw_envelope(event_type=event_type, session_id=SESSION)
    envelope["time"]["source"]["value_ns"] = value_ns
    envelope["time"]["source"]["clock_domain"] = f"sim:{SESSION}"
    envelope["scope"]["run_id"] = "run-1"
    return envelope


def test_runtime_lifecycle_events_reach_the_journal(tmp_path):
    """The runtime event sink rides the gateway: a session created through
    the REAL runtime face lands its ``session_created`` envelope in the
    journal (without the sink wiring the family is opt-out silent)."""
    stack = _make_stack(tmp_path)
    try:
        from simulation.clock import SimulationClockConfig
        from simulation.runtime import SimulationSessionSpec
        from simulation.state import TopologyGraph

        spec = SimulationSessionSpec(
            session_id="sess-runtime-sink",
            topology=TopologyGraph(
                topology_id="topo-1", revision=1, nodes=(), connections=()
            ),
            seed=7,
            deterministic=True,
            clock_config=SimulationClockConfig(mode="deterministic"),
        )

        async def main() -> None:
            await stack.runtime.create_session(spec)

        asyncio.run(main())
        stack.drain_gateway()
        rows = stack.journal.query("sess-runtime-sink", after_seq=0, limit=10)
        assert [row.event_type for row in rows] == [
            "simulation.session_created"
        ]
    finally:
        stack.close()


def test_analysis_service_is_on_the_stack(tmp_path):
    """The 裁定 A bridge is composed into the production stack (the
    裁定 B in-process Analyze anchor; the REST route stays frozen)."""
    from application.analysis import AnalysisService

    stack = _make_stack(tmp_path)
    try:
        assert isinstance(stack.analysis_service, AnalysisService)
        # Its publisher face is the stack's gateway (the §12 producer
        # binding): a published analysis event lands in the journal.
        publisher = getattr(stack.analysis_service, "_publisher")
        assert publisher is stack.gateway
    finally:
        stack.close()
