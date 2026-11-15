"""REST run routes: 202 async-job semantics + prepare-bound fault_plan
(SPEC-500 §4.3 / REQ-API-500-004, ticket #48).

End-to-end through the real stack (``rest_stack`` composition): REST
create → validate → start → submit run (202) → poll to terminal, with the
real #43 TSRuntime prepare binding the plan into the deterministic
fingerprint (ADR-0007 item 2) and the real #42 store landing the tee
artifacts.

The fingerprint binding proof: the ``config_hash`` returned over REST must
equal ``simulation.ts_runtime.compute_config_hash`` evaluated on the SAME
domain config + session clock config + fault plan — same plan ⇒ same
fingerprint, different plan ⇒ different fingerprint.

Harness note: the TestClient is used as a context manager (one portal
event loop across requests) so the scheduled run task can finish between
requests — a per-request portal would cancel it. Polling is event-driven
(each HTTP request yields to the loop); no wall-clock waits.
"""

from __future__ import annotations

import uuid

import pytest

from simulation.clock import SimulationClockConfig
from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.ts_runtime import compute_config_hash
from ts.generator.config import GeneratorConfig

from rest_stack import (
    build_rest_stack,
    make_generator_config,
    wire_generator_config,
)

pytestmark = pytest.mark.integration

_POLL_BOUND = 2000  # event-driven yield points; no wall-clock waits


@pytest.fixture
def stack_client(api_client, tmp_path):
    """One composed REST stack behind a single-portal TestClient."""
    client = api_client.build(build_rest_stack(tmp_path).app)
    with client.client:
        yield client


def _cc_plan_wire(*, packet_index: int = 10, delta: int = 3) -> list[dict]:
    """The SPEC-204 §6.3 CC_DISCONTINUITY fault in wire shape."""
    return [
        {
            "fault_type": "CC_DISCONTINUITY",
            "target_id": "demux-0:pid:0x0100",
            "parameters": {"delta": delta},
            "activation": {"kind": "packet_index", "packet_index": packet_index},
            "expected_observations": ["ts.continuity_error"],
        }
    ]


def _expected_fingerprint(
    config: GeneratorConfig, plan_wire: list[dict]
) -> str:
    """The authoritative fingerprint for the submitted wire payload."""
    plan = tuple(
        FaultDefinition(
            fault_id=f"fault-{i}",
            fault_type=fault["fault_type"],
            target_id=fault["target_id"],
            parameters=dict(fault["parameters"]),
            activation=FaultActivation(
                kind=fault["activation"]["kind"],
                packet_index=fault["activation"]["packet_index"],
            ),
            expected_observations=tuple(fault["expected_observations"]),
        )
        for i, fault in enumerate(plan_wire)
    )
    return compute_config_hash(
        config,
        clock_config=SimulationClockConfig(
            mode="deterministic"
        ),  # the REST default clock body
        fault_plan=plan,
    )


def _running_session(client) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"topology_id": "topo-1", "seed": 20260101},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]
    assert client.post(f"/api/v1/sessions/{session_id}/validate").status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/start").status_code == 200
    return session_id


def _submit(client, session_id: str, payload: dict):
    return client.post(f"/api/v1/sessions/{session_id}/runs", json=payload)


def _wait_terminal(client, session_id: str, run_id: str) -> dict:
    """Poll until the async job reaches a terminal state (event-driven)."""
    for _ in range(_POLL_BOUND):
        response = client.get(f"/api/v1/sessions/{session_id}/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "running":
            return body
        client.get("/api/v1/version")  # yield point: the job task advances
    pytest.fail("run did not reach a terminal state within the poll bound")


class TestAsyncJobSemantics:
    def test_submit_answers_202_with_run_id_and_bound_fingerprint(
        self, stack_client
    ):
        client = stack_client
        session_id = _running_session(client)
        response = _submit(
            client,
            session_id,
            {"config": wire_generator_config(make_generator_config())},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        # 202 + run_id (SPEC-500 §4.3): the acceptance answer carries the
        # job identity and the prepare-bound fingerprint — never a result.
        assert set(body) == {"run_id", "config_hash", "status"}
        assert body["status"] == "running"
        uuid.UUID(body["run_id"])  # uuid4-opaque identity (ADR-0006 item 3)
        assert body["config_hash"] == _expected_fingerprint(
            make_generator_config(), []
        )

    def test_202_is_not_a_synchronous_completion_in_disguise(self, stack_client):
        # REQ-API-500-004 discipline: the POST must not run the generation
        # synchronously — the answer is the acceptance shape, and the run
        # closes asynchronously through the run face.
        client = stack_client
        session_id = _running_session(client)
        response = _submit(
            client,
            session_id,
            {"config": wire_generator_config(make_generator_config())},
        )
        assert response.status_code == 202
        assert "artifacts" not in response.json()
        assert "packet_count" not in response.json()

    def test_submit_to_unknown_session_is_404(self, stack_client):
        response = _submit(
            stack_client,
            "no-such-session",
            {"config": wire_generator_config(make_generator_config())},
        )
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_run_requires_a_running_session_409(self, stack_client):
        # SPEC-200 run face: runs open only in a RUNNING session; the
        # CREATED session must answer the 409 lifecycle row synchronously.
        client = stack_client
        created = client.post(
            "/api/v1/sessions",
            json={"topology_id": "topo-1", "seed": 1},
        ).json()
        response = _submit(
            client,
            created["session_id"],
            {"config": wire_generator_config(make_generator_config())},
        )
        assert response.status_code == 409
        assert (
            response.json()["error"]["error_code"]
            == "SIM_INVALID_LIFECYCLE_TRANSITION"
        )

    def test_unknown_run_is_404_envelope(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        response = client.get(f"/api/v1/sessions/{session_id}/runs/missing")
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_RUN_NOT_FOUND"

    def test_malformed_request_body_is_400_envelope(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        response = _submit(client, session_id, {"fault_plan": []})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"


class TestPrepareRejectionMapping:
    """SPEC-500 §4.3: prepare rejects synchronously → 422 + detail path."""

    def test_unknown_parameter_key_rejected_422(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        plan = _cc_plan_wire()
        plan[0]["parameters"] = {"delta": 3, "bogus_key": 1}
        response = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": plan,
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error"]["error_code"] == "SIM_TS_PLAN_INVALID"
        assert body["error"]["details"]["errors"], "schema path detail required"
        assert "bogus_key" in body["error"]["details"]["errors"][0]

    def test_out_of_range_delta_rejected_422(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        response = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": _cc_plan_wire(delta=16),
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["error_code"] == "SIM_TS_PLAN_INVALID"

    def test_unknown_fault_type_rejected_422(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        plan = [
            {
                "fault_type": "NOT_A_MVP_FAULT",
                "target_id": "demux-0",
                "expected_observations": ["ts.continuity_error"],
            }
        ]
        response = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": plan,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["error_code"] == "SIM_TS_PLAN_INVALID"

    def test_prepare_rejection_leaves_no_job_behind(self, stack_client):
        # AC-204-01: the rejection happens before scheduling — nothing to
        # poll afterwards (the session itself is untouched too).
        client = stack_client
        session_id = _running_session(client)
        response = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": _cc_plan_wire(delta=16),
            },
        )
        assert response.status_code == 422
        snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
        assert snapshot["lifecycle"] == "running"


class TestFaultPlanPrepareBinding:
    """ADR-0007 item 2 end-to-end: plan binds at prepare into the hash."""

    def test_bound_fingerprint_matches_compute_config_hash(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        plan = _cc_plan_wire(packet_index=7, delta=5)
        config = make_generator_config()
        response = _submit(
            client,
            session_id,
            {"config": wire_generator_config(config), "fault_plan": plan},
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        # THE binding proof: the REST-returned fingerprint equals the
        # authoritative prepare computation over the same plan.
        assert accepted["config_hash"] == _expected_fingerprint(config, plan)

    def test_different_plans_bind_different_fingerprints(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        empty = _submit(
            client,
            session_id,
            {"config": wire_generator_config(make_generator_config())},
        ).json()
        planned = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": _cc_plan_wire(packet_index=3, delta=1),
            },
        )
        assert planned.status_code == 202
        assert (
            planned.json()["config_hash"] != empty["config_hash"]
        ), "a different plan must not collide on one fingerprint (SPEC-203 §5.1)"

    def test_full_job_completes_with_tee_artifacts(self, stack_client):
        client = stack_client
        session_id = _running_session(client)
        plan = _cc_plan_wire(packet_index=10, delta=3)
        accepted = _submit(
            client,
            session_id,
            {
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": plan,
            },
        ).json()
        result = _wait_terminal(client, session_id, accepted["run_id"])
        # SPEC-203 §5.2 through REST: terminal status + tee artifacts.
        assert result["status"] == "completed"
        assert result["run_id"] == accepted["run_id"]
        assert result["config_hash"] == accepted["config_hash"]
        kinds = sorted(artifact["kind"] for artifact in result["artifacts"])
        assert kinds == ["faulted_ts", "generated_ts", "log"]
        assert result["packet_count"] == 500
        assert result["byte_count"] == result["packet_count"] * 188
        for artifact in result["artifacts"]:
            assert artifact["partial"] is False
            if artifact["kind"] != "log":
                assert artifact["packet_count"] == result["packet_count"]
                assert artifact["byte_size"] == artifact["packet_count"] * 188

    def test_completed_run_fingerprint_stable_across_runs(self, stack_client):
        # Repeated runs of one prepared shape keep the fingerprint stable.
        client = stack_client
        session_id = _running_session(client)
        payload = {
            "config": wire_generator_config(make_generator_config()),
            "fault_plan": _cc_plan_wire(packet_index=2, delta=2),
        }
        first = _wait_terminal(
            client,
            session_id,
            _submit(client, session_id, payload).json()["run_id"],
        )
        second = _wait_terminal(
            client,
            session_id,
            _submit(client, session_id, payload).json()["run_id"],
        )
        assert first["status"] == "completed"
        assert second["status"] == "completed"
        assert first["config_hash"] == second["config_hash"]
