"""501 mount points: the frozen-table routes whose backing use-cases land
with M4 (SPEC-500 §4.1/§4.4/§4.5/§4.7, ticket #48).

Route presence is the REQ-API-500-001 freeze obligation; each stub answers
**501 Not Implemented** through the unified SPEC-305 §7 envelope
(framework-fallback code ``HTTP_501``), so a premature client gets a
well-formed error, never a naked 404.
"""

from __future__ import annotations

import pytest

from rest_stack import build_rest_stack

pytestmark = pytest.mark.integration


@pytest.fixture
def client(api_client, tmp_path):
    built = api_client.build(build_rest_stack(tmp_path).app)
    with built.client:
        yield built


def _assert_501(response, session_hint: str | None = None) -> None:
    assert response.status_code == 501, response.text
    body = response.json()
    # Unified envelope shape (SPEC-305 §7) with the fallback code.
    assert body["error"]["error_code"] == "HTTP_501"
    assert body["error"]["message"]
    assert body["error"]["retryable"] is False
    assert body["request_id"]


class TestObservationMountPoints:
    """SPEC-305 §4 logical endpoints, verbatim (SPEC-500 §4.5)."""

    def test_observation_summary(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/observation/summary"))

    def test_events(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/events"))

    def test_timeline(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/timeline"))

    def test_metrics_query(self, client):
        _assert_501(client.post("/api/v1/sessions/s-1/metrics/query"))

    def test_alerts(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/alerts"))

    def test_health(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/health"))

    def test_export_read(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/exports/exp-1"))

    def test_export_create_never_touches_the_session(self, client):
        # SPEC-305 §4: export POST creates only an Observation export task.
        _assert_501(client.post("/api/v1/sessions/s-1/exports"))


class TestTopologyMountPoints:
    def test_create_topology(self, client):
        _assert_501(client.post("/api/v1/topologies"))

    def test_list_topologies(self, client):
        _assert_501(client.get("/api/v1/topologies"))

    def test_read_topology(self, client):
        _assert_501(client.get("/api/v1/topologies/topo-1"))

    def test_modify_topology_is_a_new_revision_row(self, client):
        _assert_501(client.put("/api/v1/topologies/topo-1"))

    def test_validate_topology(self, client):
        _assert_501(client.post("/api/v1/topologies/topo-1/validate"))


class TestDiagnosisMountPoints:
    def test_diagnoses_list(self, client):
        _assert_501(client.get("/api/v1/sessions/s-1/diagnoses"))

    def test_diagnose_run(self, client):
        _assert_501(client.post("/api/v1/sessions/s-1/runs/r-1/diagnose"))

    def test_verify_run(self, client):
        _assert_501(client.post("/api/v1/sessions/s-1/runs/r-1/verify"))


class TestScenarioMountPoints:
    def test_list_scenarios(self, client):
        _assert_501(client.get("/api/v1/scenarios"))

    def test_scenario_detail(self, client):
        _assert_501(client.get("/api/v1/scenarios/sc-1"))
