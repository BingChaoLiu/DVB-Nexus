"""The fault-lab e2e harness — the eight-step teaching-loop driver
(ticket #58, CONTEXT.md 八步闭环 / ADR-0002).

One driver over the PRODUCTION composition (``build_production_app`` —
the #53 guidance for #57/#58): REST rides the frozen SPEC-500 §4 routes
and WS rides the SPEC-501 route on the same ASGI app; the Analyze step
is the 裁定 B in-process anchor (``stack.analysis_service``, the REST
analyze route stays frozen 501); the deterministic pipeline is pumped
through the stack's driver faces (``drain_gateway`` — no threads, no
wall-clock waits: run completion is polled through the job surface with
event-driven yields, the ``test_rest_runs`` posture).

Eight-step mapping (per fault):

- Create    → ``POST /api/v1/sessions`` (scenario initial_topology/seed)
- Generate  → ``POST .../runs`` with an EMPTY plan (clean baseline run)
- Inject    → ``POST .../runs`` with the scenario's single-fault plan (202)
- Analyze   → ``stack.analysis_service.analyze_artifact`` (in-process)
- Diagnose  → ``POST .../runs/{run_id}/diagnose`` (SPEC-306)
- Inspect   → ``GET .../events`` + ``GET /artifacts/{id}/content``
- Recover   → ``POST .../runs`` again with an EMPTY plan (new Run)
- Verify    → ``POST .../runs/{run_id}/verify`` (SPEC-206 three-state)
"""

from __future__ import annotations

import contextlib
import itertools
import json
from typing import Any

from fastapi.testclient import TestClient
from simulation.scenario.schema import ScenarioDocument, parse_scenario_document

from bootstrap import build_production_app

from tests._support.fault_lab_materials import (
    FAULT_LAB_NODE_ID,
    golden_geometry_wire_config,
)
from tests._support.paths import REPO_ROOT

POLL_BOUND = 2000  # event-driven yield points; no wall-clock waits

SCENARIO_DIR = REPO_ROOT / "tests" / "fixtures" / "scenarios"

#: The runtime scenario directory (the Lab Pack 落库形态 — SC-01..SC-11;
#: the SIM_STATE 支路 reads the v3 pack from here, ticket #172 SHARED
#: harness extension — registered on the #172 ticket).
RUNTIME_SCENARIO_DIR = REPO_ROOT / "scenarios"

#: The four golden fault pairs (docs/test-vectors/golden — SPEC-506).
GOLDEN_VECTOR_IDS = (
    "pat-missing",
    "pmt-invalid-crc",
    "cc-discontinuity",
    "pmt-pid-mismatch",
)


def load_scenario(name: str) -> tuple[dict[str, Any], ScenarioDocument]:
    """The fixture document + the production-loader's parsed form."""
    path = SCENARIO_DIR / f"fault-lab-{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw, parse_scenario_document(raw)


def load_runtime_scenario(name: str) -> tuple[dict[str, Any], ScenarioDocument]:
    """A runtime scenario (``scenarios/`` — the Lab Pack 落库形态) as the
    raw wire mapping + the production-loader's parsed form (#172)."""
    path = RUNTIME_SCENARIO_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw, parse_scenario_document(raw)


def fault_plan_wire(document: ScenarioDocument) -> list[dict[str, Any]]:
    """The scenario's single-fault plan as the run-request wire body."""
    fault = document.fault_plan[0]
    return [
        {
            "fault_id": fault.fault_id,
            "fault_type": fault.fault_type,
            "target_id": fault.target_id,
            "parameters": dict(fault.parameters),
            "activation": {
                "kind": fault.activation.kind,
                "packet_index": fault.activation.packet_index,
            },
            "expected_observations": list(fault.expected_observations),
        }
    ]


def pass_criteria_wire(document: ScenarioDocument) -> list[dict[str, Any]]:
    """The scenario's pass criteria as the verify-request wire body."""
    return [
        {
            "criterion_id": criterion.criterion_id,
            "kind": criterion.kind,
            "mandatory": criterion.mandatory,
            "fault_id": criterion.fault_id,
        }
        for criterion in document.pass_criteria
    ]


def scenario_identity(document: ScenarioDocument) -> dict[str, str]:
    """The SPEC-205 §5 version-pinning identity for the verify body."""
    return {
        "scenario_id": document.scenario_id,
        "version": document.version,
        "content_hash": document.content_hash,
    }


class FaultLab:
    """One production stack + one TestClient portal + step faces."""

    def __init__(self, db_path: Any) -> None:
        wall = itertools.count(start=1_000_000_000, step=1_000_000)
        self.stack = build_production_app(
            db_path=db_path, now_wall_ns=lambda: next(wall)
        )
        self._client = TestClient(self.stack.app)
        self._client.__enter__()

    def close(self) -> None:
        self._client.__exit__(None, None, None)
        self.stack.close()

    def __enter__(self) -> "FaultLab":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- driver faces -----------------------------------------------------

    def drain(self) -> int:
        """Commit the queued events (the deterministic dispatcher slice)."""
        return self.stack.drain_gateway()

    # --- the eight steps ----------------------------------------------------

    def create_session(
        self, raw: dict[str, Any], *, scenario_id: str | None = None
    ) -> str:
        """Create — the scenario's simulation_config as the session body.

        ``scenario_id`` rides the body when given: the #80 加载即建 branch
        (the document governs — the Lab UI's 开局 body shape for registry-
        foreign topologies, e.g. the v2 pack's ``topo-sc-09``)."""
        clock = raw["simulation_config"]["clock"]
        body: dict[str, Any] = {
            "topology_id": raw["initial_topology"]["topology_id"],
            "topology_revision": raw["initial_topology"]["revision"],
            "seed": raw["simulation_config"]["seed"],
            "deterministic": raw["simulation_config"]["mode"]
            == "deterministic",
            "clock_config": {
                "mode": clock["mode"],
                "start_time_ns": clock["start_time_ns"],
                "speed_num": clock["speed_num"],
                "speed_den": clock["speed_den"],
                "tick_quantum_ns": clock["tick_quantum_ns"],
            },
        }
        if scenario_id is not None:
            body["scenario_id"] = scenario_id
        response = self._client.post("/api/v1/sessions", json=body)
        assert response.status_code == 201, response.text
        return response.json()["session_id"]

    def start_session(self, session_id: str) -> None:
        assert (
            self._client.post(f"/api/v1/sessions/{session_id}/validate").status_code
            == 200
        )
        assert (
            self._client.post(f"/api/v1/sessions/{session_id}/start").status_code
            == 200
        )

    def create_scenario_session(self, document: ScenarioDocument) -> str:
        """Create — the #80 加载即建 branch over a REGISTRY scenario
        (the Lab 开局 body shape for the Lab Pack 落库 scenarios, #172):
        the request echoes the scenario identity, the DOCUMENT governs
        (open_scenario_session full semantics run inside — CREATED →
        VALIDATING → READY), then the READY → RUNNING start transition
        (runs require a RUNNING session — the SPEC-200 run face)."""
        body: dict[str, Any] = {
            "topology_id": document.topology.topology_id,
            "topology_revision": document.topology.revision,
            "seed": document.seed,
            "scenario_id": document.scenario_id,
        }
        response = self._client.post("/api/v1/sessions", json=body)
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["lifecycle"] == "ready", view
        session_id = view["session_id"]
        started = self._client.post(f"/api/v1/sessions/{session_id}/start")
        assert started.status_code == 200, started.text
        return session_id

    def submit_state_run(
        self, session_id: str, fault_plan: list[dict[str, Any]]
    ) -> str:
        """Generate/Inject/Recover on the SIM_STATE face (#165/#172):
        202 + run_id — the state-domain submission carries NO generator
        config (a state run has no generator; the backend refuses one)."""
        response = self._client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_STATE", "fault_plan": fault_plan},
        )
        assert response.status_code == 202, response.text
        return response.json()["run_id"]

    def await_state_run(self, session_id: str, run_id: str) -> dict[str, Any]:
        """Poll the async job to its terminal state (event-driven); the
        SIM_STATE terminal body carries the L0 products (fidelity +
        graph_health/node_health, honestly no artifacts)."""
        for _ in range(POLL_BOUND):
            view = self._client.get(
                f"/api/v1/sessions/{session_id}/runs/{run_id}"
            )
            assert view.status_code == 200, view.text
            body = view.json()
            if body["status"] != "running":
                assert body["status"] == "completed", body
                assert body["fidelity"] == "SIM_STATE", body
                assert body["artifacts"] == [], body
                return body
        raise AssertionError(f"run {run_id} never completed ({POLL_BOUND} yields)")

    def evaluate_alerts(self, session_id: str) -> None:
        """The #52 alert lifecycle over the REAL metrics reader (the
        in-process driver face — same posture as drain_gateway): metrics
        consumer catch-up first (the state-snapshot gauges ride the
        committed journal), then TWO evaluation ticks at the newest
        observed virtual time (event-driven now_ns — no wall clock):
        the arming tick opens the breach as pending, the second tick's
        fresh breach reading fires the for_duration=0 rules (the #52
        pending→firing cadence, test_obs_ws_hint_pull posture)."""
        self.stack.process_observation(session_id)
        newest = 0
        for item in self.events(session_id):
            newest = max(
                newest,
                int((item.get("time") or {}).get("source", {}).get("value_ns", 0)),
            )
        for _ in range(2):
            self.stack.evaluate_alerts(
                session_id,
                now_ns=newest + 1,
                clock_domain=f"sim:{session_id}",
            )

    def submit_run(
        self, session_id: str, fault_plan: list[dict[str, Any]]
    ) -> str:
        """Generate/Inject/Recover — 202 + run_id (never synchronous)."""
        response = self._client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={
                "config": golden_geometry_wire_config(),
                "fault_plan": fault_plan,
            },
        )
        assert response.status_code == 202, response.text
        return response.json()["run_id"]

    def await_run(self, session_id: str, run_id: str) -> dict[str, Any]:
        """Poll the async job to its terminal state (event-driven)."""
        for _ in range(POLL_BOUND):
            view = self._client.get(
                f"/api/v1/sessions/{session_id}/runs/{run_id}"
            )
            assert view.status_code == 200, view.text
            body = view.json()
            if body["status"] != "running":
                assert body["status"] == "completed", body
                return body
        raise AssertionError(f"run {run_id} never completed ({POLL_BOUND} yields)")

    def analyze_artifact(
        self,
        session_id: str,
        run_id: str,
        artifact_id: str,
    ):
        """Analyze — the 裁定 B in-process bridge anchor. Publishes the
        ``ts.*`` facts into the gateway; the caller drains."""
        from tests._support.fault_lab_materials import golden_geometry_config

        report = self.stack.analysis_service.analyze_artifact(
            session_id=session_id,
            run_id=run_id,
            artifact_id=artifact_id,
            config=golden_geometry_config(),
            node_id=FAULT_LAB_NODE_ID,
        )
        self.drain()
        return report

    def artifacts_of_kind(self, run: dict[str, Any], kind: str) -> list[dict]:
        return [a for a in run["artifacts"] if a["kind"] == kind]

    def diagnose(self, session_id: str, run_id: str) -> dict[str, Any]:
        """Diagnose — the SPEC-306 §5 evaluation endpoint (idempotent)."""
        response = self._client.post(
            f"/api/v1/sessions/{session_id}/runs/{run_id}/diagnose"
        )
        assert response.status_code == 200, response.text
        return response.json()

    def verify(
        self,
        session_id: str,
        recovery_run_id: str,
        baseline_run_id: str,
        document: ScenarioDocument,
    ) -> dict[str, Any]:
        """Verify — the SPEC-206 three-state verdict endpoint."""
        response = self._client.post(
            f"/api/v1/sessions/{session_id}/runs/{recovery_run_id}/verify",
            json={
                "baseline_run_id": baseline_run_id,
                "scenario": scenario_identity(document),
                "pass_criteria": pass_criteria_wire(document),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    # --- Inspect faces ------------------------------------------------------

    def events(self, session_id: str, event_type: str | None = None):
        """The journal over the SPEC-305 §4.5 events endpoint."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            page = self._client.get(
                f"/api/v1/sessions/{session_id}/events", params=params
            )
            assert page.status_code == 200, page.text
            data = page.json()["data"]
            items.extend(data["items"])
            cursor = page.json()["meta"].get("next_cursor")
            if cursor is None:
                break
        if event_type is None:
            return items
        return [i for i in items if i["event_type"] == event_type]

    def artifact_content(self, artifact_id: str) -> bytes:
        response = self._client.get(f"/api/v1/artifacts/{artifact_id}/content")
        assert response.status_code == 200, response.text
        return response.content

    def diagnoses(self, session_id: str) -> list[dict[str, Any]]:
        response = self._client.get(f"/api/v1/sessions/{session_id}/diagnoses")
        assert response.status_code == 200, response.text
        return response.json()

    def alerts(self, session_id: str) -> dict[str, Any]:
        """The alert-list read face (record authority; the #52 REST pull)."""
        response = self._client.get(f"/api/v1/sessions/{session_id}/alerts")
        assert response.status_code == 200, response.text
        return response.json()["data"]

    # --- WS face ------------------------------------------------------------

    @contextlib.contextmanager
    def websocket(self, session_id: str):
        """The SPEC-501 subscription (hint→REST pull closure)."""
        with self._client.websocket_connect(
            f"/ws/v1/sessions/{session_id}"
        ) as ws:
            ws.send_json({"type": "subscribe", "session_id": session_id})
            ws.receive_json()  # ready frame (live from now)
            yield ws


def receive_hint(ws, topic: str, *, max_frames: int = 300) -> dict:
    """Collect frames until the wanted hint arrives (journal frames
    interleave — the hub's combined stream)."""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame["type"] == "hint" and frame["topic"] == topic:
            return frame
    raise AssertionError(f"hint {topic!r} never arrived within {max_frames} frames")
