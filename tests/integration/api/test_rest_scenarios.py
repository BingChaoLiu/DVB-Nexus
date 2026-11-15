"""Scenario REST §4.7 + the solution-reveal gate (SPEC-500 §4.7, ticket
#80 / REQ-API-500-001/-009) through the PRODUCTION composition root.

Registry semantics (裁定 F): the composition scans ``scenario_dir`` for
``*.json`` (filename-ASC order); a missing directory is an empty registry.
Detail answers are the loader's export face — ``hidden_reference_solution``
stripped BY CONSTRUCTION (REQ-SIM-205-003: 政策外不得经任何 API 泄露), the
authored camelCase ``initial_topology`` keys preserved verbatim (#45
canonical-example authority — documented for ticket #67).

Reveal gate (裁定 F): 200 ``{scenario_id, hidden_reference_solution}`` iff
the SPEC-502 ``verification_verdicts`` table carries a verdict=PASS row
for the (session_id, scenario_id) pair; otherwise 403
``SIM_SCENARIO_SOLUTION_LEAK``; unknown scenario → 404
``SIM_SCENARIO_NOT_FOUND``; missing ``session_id`` query → 400. A PASS on
a scenario that declares no hidden field answers 200 with null
(orchestrator OQ-3 — no fabricated text).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.storage.repositories import (
    SqliteVerificationRepository,
    VerdictRecord,
)
from bootstrap import build_production_app

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[2] / "fixtures" / "scenarios" / "fault-lab-cc-discontinuity.json"

#: Distinct uuid4 scenario ids for the two registry documents.
WITH_HIDDEN_ID = "6b2f0000-0000-4000-8000-00000000e204"
NO_HIDDEN_ID = "5a1e0000-0000-4000-8000-00000000e203"  # the fixture's own
SOLUTION_TEXT = "recover: rerun with an empty fault plan after re-emitting PAT"


def _document(path: Path, *, scenario_id: str, hidden: str | None) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scenario_id"] = scenario_id
    if hidden is not None:
        raw["hidden_reference_solution"] = hidden
    else:
        raw.pop("hidden_reference_solution", None)
    return raw


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    # filename-ASC order: "a-…" loads before "b-…" — the list order pin.
    (root / "b-with-hidden.json").write_text(
        json.dumps(
            _document(FIXTURE, scenario_id=WITH_HIDDEN_ID, hidden=SOLUTION_TEXT),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "a-no-hidden.json").write_text(
        json.dumps(
            _document(FIXTURE, scenario_id=NO_HIDDEN_ID, hidden=None),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def harness(api_client, tmp_path, registry_dir):
    stack = build_production_app(
        db_path=tmp_path / "scen.sqlite3", scenario_dir=registry_dir
    )
    built = api_client.build(stack.app)
    with built.client:
        yield built, stack
    stack.close()


@pytest.fixture
def client(harness):
    built, _ = harness
    return built


def _seed_pass(stack, *, session_id: str, scenario_id: str, verdict: str = "PASS"):
    SqliteVerificationRepository(stack.connection).save(
        VerdictRecord(
            verdict_id=f"verdict-{session_id[:8]}-{scenario_id[:8]}",
            session_id=session_id,
            run_id="run-1",
            baseline_run_id="run-0",
            scenario_id=scenario_id,
            scenario_version="1.0.0",
            scenario_content_hash="c" * 64,
            verdict=verdict,
            criteria=[],
            evidence_refs=[],
            summary="",
            verified_at_utc_ms=1_700_000_000_000,
        )
    )


class TestScenarioList:
    def test_list_is_the_summary_projection_in_scan_order(self, client):
        rows = client.get("/api/v1/scenarios").json()
        assert [row["scenario_id"] for row in rows] == [NO_HIDDEN_ID, WITH_HIDDEN_ID]
        with_hidden = rows[1]
        assert with_hidden["version"] == "1.0.0"
        assert with_hidden["title"].startswith("Fault Lab:")
        assert with_hidden["difficulty"] == "intermediate"
        # summary projection only — no document payload, no solution.
        assert set(rows[0].keys()) == {"scenario_id", "version", "title", "difficulty"}

    def test_empty_registry_answers_200_empty_list(self, api_client, tmp_path):
        stack = build_production_app(
            db_path=tmp_path / "empty.sqlite3",
            scenario_dir=tmp_path / "does-not-exist",
        )
        built = api_client.build(stack.app)
        with built.client:
            response = built.get("/api/v1/scenarios")
        stack.close()
        assert response.status_code == 200
        assert response.json() == []


class TestScenarioDetail:
    def test_detail_is_the_exported_document_hidden_stripped(self, client):
        body = client.get(f"/api/v1/scenarios/{WITH_HIDDEN_ID}").json()
        assert body["scenario_id"] == WITH_HIDDEN_ID
        assert "hidden_reference_solution" not in body  # 政策外不泄露
        assert body["objectives"]
        assert body["pass_criteria"]
        # The authored camelCase initial_topology island (#45 authority).
        node = body["initial_topology"]["nodes"][0]
        assert set(node.keys()) == {"nodeId", "nodeType", "config", "ports"}
        port = node["ports"][0]
        assert set(port.keys()) == {"portId", "direction", "plane", "maxConnections"}

    def test_unknown_scenario_is_404_registered_code(self, client):
        response = client.get("/api/v1/scenarios/no-such-scenario")
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_SCENARIO_NOT_FOUND"
        )


class TestSolutionRevealGate:
    def test_missing_session_id_is_400(self, client):
        response = client.get(f"/api/v1/scenarios/{WITH_HIDDEN_ID}/solution")
        assert response.status_code == 400
        assert (
            response.json()["error"]["error_code"] == "REQUEST_BODY_INVALID"
        )

    def test_unknown_scenario_is_404(self, client):
        response = client.get(
            "/api/v1/scenarios/no-such-scenario/solution?session_id=s-1"
        )
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_SCENARIO_NOT_FOUND"
        )

    def test_no_verdict_is_403_solution_leak(self, client, harness):
        _, stack = harness
        response = client.get(
            f"/api/v1/scenarios/{WITH_HIDDEN_ID}/solution?session_id=learner-1"
        )
        assert response.status_code == 403, response.text
        assert (
            response.json()["error"]["error_code"]
            == "SIM_SCENARIO_SOLUTION_LEAK"
        )

    def test_fail_verdict_is_not_a_pass(self, client, harness):
        _, stack = harness
        _seed_pass(stack, session_id="learner-2", scenario_id=WITH_HIDDEN_ID, verdict="FAIL")
        response = client.get(
            f"/api/v1/scenarios/{WITH_HIDDEN_ID}/solution?session_id=learner-2"
        )
        assert response.status_code == 403
        assert (
            response.json()["error"]["error_code"]
            == "SIM_SCENARIO_SOLUTION_LEAK"
        )

    def test_pass_on_a_different_scenario_is_403(self, client, harness):
        """The gate is per (session, scenario) — a PASS on another scenario
        of the same session must not unlock this one."""
        _, stack = harness
        _seed_pass(stack, session_id="learner-3", scenario_id=NO_HIDDEN_ID)
        response = client.get(
            f"/api/v1/scenarios/{WITH_HIDDEN_ID}/solution?session_id=learner-3"
        )
        assert response.status_code == 403

    def test_pass_reveals_the_hidden_solution(self, client, harness):
        client_built, stack = harness
        _seed_pass(stack, session_id="learner-4", scenario_id=WITH_HIDDEN_ID)
        response = client_built.get(
            f"/api/v1/scenarios/{WITH_HIDDEN_ID}/solution?session_id=learner-4"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scenario_id"] == WITH_HIDDEN_ID
        assert body["hidden_reference_solution"] == SOLUTION_TEXT

    def test_pass_but_no_declared_hidden_field_is_200_null(self, client, harness):
        """OQ-3: PASS granted, scenario declares no hidden field — 200
        with explicit null, never fabricated text."""
        _, stack = harness
        _seed_pass(stack, session_id="learner-5", scenario_id=NO_HIDDEN_ID)
        response = client.get(
            f"/api/v1/scenarios/{NO_HIDDEN_ID}/solution?session_id=learner-5"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scenario_id"] == NO_HIDDEN_ID
        assert body["hidden_reference_solution"] is None
