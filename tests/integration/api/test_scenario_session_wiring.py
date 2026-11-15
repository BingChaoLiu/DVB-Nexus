"""``CreateSessionRequest.scenario_id`` consumption (SPEC-500 §4.2 row 1
× SPEC-205 §5, ticket #80 scope item 2) through the PRODUCTION
composition root.

Pinned semantics:

- the loader's full service face rides the REST seam:
  ``open_scenario_session`` — 加载即建 session (fresh uuid4, never in-place
  mutation), 版本/内容哈希钉扎, the VALIDATING double gate (#41 topology +
  the scenario fault-plan gate) → READY/FAILED;
- the document governs the session shape (initial_topology / seed / clock /
  deterministic — §7.5 预设 = 场景文档自带); the request's
  ``topology_id``/``seed`` are permissive-ignored (orchestrator OQ-6,
  documented loudly for ticket #67);
- the reconstructed spec lands in ``stack.session_specs`` — the runs seam
  accepts scenario sessions;
- the session-creation hook fires: the observation plane's metrics
  consumer attaches;
- unknown scenario id → 404 ``SIM_SCENARIO_NOT_FOUND``; a fault plan that
  fails the VALIDATING gate → 422 ``SIM_VALIDATION_FAILED`` carrying the
  path-addressed report (SPEC-204 codes 透传).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bootstrap import build_production_app

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[2] / "fixtures" / "scenarios" / "fault-lab-cc-discontinuity.json"
SCENARIO_ID = "5a1e0000-0000-4000-8000-00000000e203"


def _write_registry(tmp_path: Path, *, document_mutator=None) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if document_mutator is not None:
        document_mutator(raw)
    (root / "scenario.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )
    return root


@pytest.fixture
def harness(api_client, tmp_path):
    root = _write_registry(tmp_path)

    def build(**kwargs):
        stack = build_production_app(
            db_path=tmp_path / "scen-session.sqlite3", scenario_dir=root, **kwargs
        )
        built = api_client.build(stack.app)
        return built, stack

    return build


class TestScenarioSessionCreation:
    def test_scenario_id_creates_a_ready_session_from_the_document(
        self, harness
    ):
        client, stack = harness()
        # OQ-6: the request's topology_id/seed are permissive-ignored —
        # the document governs (its seed is 1234567, topology topo-1 rev 1).
        response = client.post(
            "/api/v1/sessions",
            json={
                "topology_id": "topo-1",
                "seed": 1,
                "scenario_id": SCENARIO_ID,
            },
        )
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["lifecycle"] == "ready"  # the loader validated to READY
        assert view["topology_revision"] == 1
        assert view["session_id"] != SCENARIO_ID  # fresh uuid4 (加载即建)
        # The runs seam: the reconstructed spec is in session_specs.
        assert view["session_id"] in stack.session_specs
        spec = stack.session_specs[view["session_id"]]
        assert spec.seed == 1234567  # the DOCUMENT's seed
        assert spec.deterministic is True
        # The observation plane attached (the creation hook fired).
        assert view["session_id"] in stack.consumers

    def test_unknown_scenario_id_is_404(self, harness):
        client, _ = harness()
        response = client.post(
            "/api/v1/sessions",
            json={"topology_id": "topo-1", "seed": 1, "scenario_id": "ghost"},
        )
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_SCENARIO_NOT_FOUND"
        )

    def test_fault_plan_gate_failure_is_422_with_the_report(self, api_client, tmp_path):
        """缺 expected_observations 在 VALIDATING 被拒绝 (#12 裁决边) —
        the #45 acceptance core through the REST seam."""
        root = _write_registry(
            tmp_path,
            document_mutator=lambda raw: raw["fault_plan"][0].pop(
                "expected_observations"
            ),
        )
        stack = build_production_app(
            db_path=tmp_path / "gate.sqlite3", scenario_dir=root
        )
        built = api_client.build(stack.app)
        try:
            with built.client:
                response = built.post(
                    "/api/v1/sessions",
                    json={
                        "topology_id": "topo-1",
                        "seed": 1,
                        "scenario_id": SCENARIO_ID,
                    },
                )
            assert response.status_code == 422, response.text
            body = response.json()
            assert body["error"]["error_code"] == "SIM_VALIDATION_FAILED"
            joined = json.dumps(body["error"]["details"])
            assert "SIM_SCENARIO_FAULT_PLAN_INVALID" in joined
            assert "expected_observations" in joined
        finally:
            stack.close()

    def test_plain_path_untouched_by_the_branch(self, harness):
        """The non-scenario path stays byte-identical (topo-1 + seed)."""
        client, stack = harness()
        response = client.post(
            "/api/v1/sessions", json={"topology_id": "topo-1", "seed": 7}
        )
        assert response.status_code == 201
        view = response.json()
        assert view["lifecycle"] == "created"  # no loader validation pass
        assert view["session_id"] in stack.session_specs
