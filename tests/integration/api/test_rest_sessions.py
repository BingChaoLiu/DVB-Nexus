"""REST session lifecycle routes (SPEC-500 §4.2 / REQ-API-500-003,
ticket #48) over the real #41 SimulationRuntime.

The §4.2 endpoints are the one-to-one mapping of the SPEC-200 §5
exhaustive transition table; the matrix below walks the legal edges and
samples the illegal ones — every illegal transition answers **409** with
``SIM_INVALID_LIFECYCLE_TRANSITION`` and the current/target/allowed detail.
"""

from __future__ import annotations

import pytest

from rest_stack import build_rest_stack

pytestmark = pytest.mark.integration


@pytest.fixture
def stack_client(api_client, tmp_path):
    client = api_client.build(build_rest_stack(tmp_path).app)
    with client.client:
        yield client


def _create(client, *, seed: int = 20260101, topology_id: str = "topo-1"):
    response = client.post(
        "/api/v1/sessions",
        json={"topology_id": topology_id, "seed": seed},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestSessionCreation:
    def test_create_answers_201_with_session_view(self, stack_client):
        body = _create(stack_client)
        assert body["revision"] == 0  # revision rows grow on mutation
        assert body["lifecycle"] == "created"
        assert body["topology_revision"] == 1
        assert body["virtual_time_ns"] == 0
        assert body["node_states"] == {}
        assert body["active_faults"] == []
        assert body["latest_artifact_refs"] == []

    def test_create_body_defaults_mirror_the_spec(self, stack_client):
        # SPEC-500 §4.2 row 1: topology_id+revision, seed, clock_config,
        # resource_limits, scenario_id 可选 — the minimal body works.
        response = stack_client.post(
            "/api/v1/sessions", json={"topology_id": "topo-1", "seed": 7}
        )
        assert response.status_code == 201

    def test_unknown_topology_is_404(self, stack_client):
        response = stack_client.post(
            "/api/v1/sessions",
            json={"topology_id": "no-such-topology", "seed": 1},
        )
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_TOPOLOGY_NOT_FOUND"

    def test_malformed_body_is_400_envelope(self, stack_client):
        response = stack_client.post("/api/v1/sessions", json={"seed": 1})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"
        assert body["error"]["details"]["errors"][0]["loc"][-1] == "topology_id"


class TestLegalLifecycleEdges:
    """SPEC-200 §5 exhaustive table, walked through REST (§4.2 mapping)."""

    def test_created_validate_ready_start_running(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        validated = stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        assert validated.status_code == 200
        assert validated.json() == {"ok": True, "violations": []}
        started = stack_client.post(f"/api/v1/sessions/{session_id}/start")
        assert started.status_code == 200
        assert started.json()["lifecycle"] == "running"

    def test_running_pause_resumed(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        stack_client.post(f"/api/v1/sessions/{session_id}/start")
        paused = stack_client.post(f"/api/v1/sessions/{session_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["lifecycle"] == "paused"
        resumed = stack_client.post(f"/api/v1/sessions/{session_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["lifecycle"] == "running"

    def test_stop_is_idempotent_and_ends_stopped(self, stack_client):
        # §4.2: stop * → STOPPING (幂等) — the runtime drains immediately,
        # so the observable answer is STOPPED; a repeated stop is a no-op.
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        stack_client.post(f"/api/v1/sessions/{session_id}/start")
        stopped = stack_client.post(f"/api/v1/sessions/{session_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["lifecycle"] == "stopped"
        stopped_again = stack_client.post(f"/api/v1/sessions/{session_id}/stop")
        assert stopped_again.status_code == 200
        assert stopped_again.json()["lifecycle"] == "stopped"

    def test_stop_from_created_is_409(self, stack_client):
        # SPEC-200 §5 table: CREATED has exactly one outgoing edge
        # (VALIDATING) — "* → STOPPING" reads over the non-CREATED states.
        session_id = _create(stack_client)["session_id"]
        response = stack_client.post(f"/api/v1/sessions/{session_id}/stop")
        assert response.status_code == 409
        assert response.json()["error"]["details"]["current"] == "created"

    def test_snapshot_echoes_lifecycle_and_optional_cursor(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        without_cursor = stack_client.get(
            f"/api/v1/sessions/{session_id}/snapshot"
        )
        assert without_cursor.status_code == 200
        assert without_cursor.json()["lifecycle"] == "created"
        assert without_cursor.json()["journal_seq_cursor"] is None
        with_cursor = stack_client.get(
            f"/api/v1/sessions/{session_id}/snapshot",
            params={"journal_seq_cursor": 41},
        )
        assert with_cursor.status_code == 200
        # Cursor passthrough only: the pull API echoes, never authors.
        assert with_cursor.json()["journal_seq_cursor"] == 41
        assert with_cursor.json()["connection_states"] == []

    def test_dispose_answers_204_and_recycles(self, stack_client):
        # SPEC-200 §5: only FAILED/STOPPED carry a DISPOSED edge, so the
        # legal dispose path runs through stop.
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        stack_client.post(f"/api/v1/sessions/{session_id}/start")
        stack_client.post(f"/api/v1/sessions/{session_id}/stop")
        response = stack_client.delete(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 204
        assert response.content == b""


class TestIllegalLifecycleTransitions:
    """Every sampled illegal edge answers 409 with the transition detail."""

    def test_start_from_created_is_409(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        response = stack_client.post(f"/api/v1/sessions/{session_id}/start")
        assert response.status_code == 409
        body = response.json()["error"]
        assert body["error_code"] == "SIM_INVALID_LIFECYCLE_TRANSITION"
        assert body["details"]["current"] == "created"
        assert body["details"]["target"] == "running"
        assert body["details"]["allowed"] == ["validating"]

    def test_validate_from_running_is_409(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        stack_client.post(f"/api/v1/sessions/{session_id}/start")
        response = stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        assert response.status_code == 409
        assert (
            response.json()["error"]["error_code"]
            == "SIM_INVALID_LIFECYCLE_TRANSITION"
        )

    def test_pause_from_ready_is_409(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        response = stack_client.post(f"/api/v1/sessions/{session_id}/pause")
        assert response.status_code == 409
        body = response.json()["error"]
        assert body["details"]["current"] == "ready"
        assert body["details"]["target"] == "paused"

    def test_resume_from_created_is_409(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        response = stack_client.post(f"/api/v1/sessions/{session_id}/resume")
        assert response.status_code == 409

    def test_dispose_of_unknown_session_is_404(self, stack_client):
        response = stack_client.delete("/api/v1/sessions/missing-session")
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_snapshot_of_unknown_session_is_404(self, stack_client):
        response = stack_client.get("/api/v1/sessions/missing-session/snapshot")
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_restarting_a_disposed_session_is_409(self, stack_client):
        session_id = _create(stack_client)["session_id"]
        stack_client.post(f"/api/v1/sessions/{session_id}/validate")
        stack_client.post(f"/api/v1/sessions/{session_id}/stop")  # → stopped
        disposed = stack_client.delete(f"/api/v1/sessions/{session_id}")
        assert disposed.status_code == 204
        response = stack_client.post(f"/api/v1/sessions/{session_id}/start")
        assert response.status_code == 409
        assert response.json()["error"]["details"]["current"] == "disposed"
