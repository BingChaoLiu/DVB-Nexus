"""SIM_STATE Run REST face (ticket #165, ADR-0012 decisions 2/5/6).

Integration half over the production composition
(:func:`bootstrap.build_production_app` — the real journal → gateway →
query chain, so the journal-composition assertions ride the REST events
read face):

- ``POST /sessions/{id}/runs`` with ``fidelity="SIM_STATE"`` → 202 +
  prepare-bound state fingerprint; the status face carries the L0
  evaluation products (graph_health + node_health) and **no TS artifact,
  no packet counts** — the honest two-run-form distinction
  (ADR-0012 decision 2: SIM_STATE Run 无 gen.* 事件、无 TS artifact).
- the mixed-plan bidirectional rejections over the wire: SIM_STATE plan
  with a TS-layer fault → 422 ``SIM_STATE_PLAN_INVALID``; SIM_TS plan
  with an RF-layer fault → 422 ``SIM_TS_PLAN_INVALID`` (the clean
  rejection — no ``LayerFaultFilter`` construction crash).
- DTO round-trip: the additive ``RunStatusDTO`` keys parse back through
  the Pydantic model without disturbing the frozen TS keys.

Harness note: the TestClient is used as a context manager (one portal
event loop, the ``test_rest_runs`` precedent); polling is event-driven —
no wall-clock waits.
"""

from __future__ import annotations

import pytest

from api.dto.runs import RunStatusDTO

pytestmark = pytest.mark.integration

_POLL_BOUND = 2000

# The SC-10-shaped shared-coax topology in SPEC-500 §4.1 wire shape
# (snake_case; config dicts ride opaque).
_TOPOLOGY_SPEC = {
    "nodes": [
        {
            "node_id": "lnb-0",
            "node_type": "lnb",
            "config": {
                "lnb_kind": "universal",
                "lo_frequencies": {"low_khz": 9750000, "high_khz": 10600000},
                "voltage": "13V",
                "tone_commanded": "none",
                "scr": {
                    "protocol": "EN50494",
                    "ub_assignments": [
                        {
                            "tuner_node": "tuner-a",
                            "ub_slot": 0,
                            "ub_center_freq_mhz": 1210,
                            "position": "A",
                        },
                        {
                            "tuner_node": "tuner-b",
                            "ub_slot": 1,
                            "ub_center_freq_mhz": 1420,
                            "position": "B",
                        },
                    ],
                },
            },
            "ports": [
                {
                    "port_id": "coax_out",
                    "direction": "output",
                    "plane": "SEC_CONTROL",
                    "max_connections": 2,
                }
            ],
        },
        {
            "node_id": "tuner-a",
            "node_type": "tuner",
            "config": {
                "tuning_request": {
                    "frequency_khz": 11095000,
                    "polarization": "vertical",
                },
                "ub_slot": 0,
            },
            "ports": [
                {"port_id": "rf_in", "direction": "input", "plane": "SEC_CONTROL"}
            ],
        },
        {
            "node_id": "tuner-b",
            "node_type": "tuner",
            "config": {
                "tuning_request": {
                    "frequency_khz": 12070000,
                    "polarization": "horizontal",
                },
                "ub_slot": 1,
            },
            "ports": [
                {"port_id": "rf_in", "direction": "input", "plane": "SEC_CONTROL"}
            ],
        },
    ],
    "connections": [
        {
            "connection_id": "conn-a",
            "from_node": "lnb-0",
            "from_port": "coax_out",
            "to_node": "tuner-a",
            "to_port": "rf_in",
            "plane": "SEC_CONTROL",
        },
        {
            "connection_id": "conn-b",
            "from_node": "lnb-0",
            "from_port": "coax_out",
            "to_node": "tuner-b",
            "to_port": "rf_in",
            "plane": "SEC_CONTROL",
        },
    ],
}

_UB_CONFLICT_PLAN = [
    {
        "fault_type": "UB_SLOT_CONFLICT",
        "target_id": "tuner-b:ub_slot",
        "parameters": {"conflicting_ub_slot": 0},
        "activation": {"kind": "session_start"},
        "expected_observations": ["sec.state_observed", "rf.state_observed"],
    }
]

_TS_LAYER_PLAN = [
    {
        "fault_type": "CC_DISCONTINUITY",
        "target_id": "tuner-a:pid:0x0100",
        "parameters": {"delta": 3},
        "activation": {"kind": "packet_index", "packet_index": 10},
        "expected_observations": ["ts.continuity_error"],
    }
]


@pytest.fixture
def prod_client(api_client, tmp_path):
    from bootstrap import build_production_app

    stack = build_production_app(db_path=tmp_path / "state-runs.sqlite3")
    client = api_client.build(stack.app)
    with client.client:
        yield client, stack
    stack.close()


def _running_session(client, topology_id: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"topology_id": topology_id, "seed": 20260101},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]
    assert client.post(f"/api/v1/sessions/{session_id}/validate").status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/start").status_code == 200
    return session_id


def _wait_terminal(client, session_id: str, run_id: str) -> dict:
    for _ in range(_POLL_BOUND):
        response = client.get(f"/api/v1/sessions/{session_id}/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "running":
            return body
        client.get("/api/v1/version")  # yield point: the job task advances
    pytest.fail("run did not reach a terminal state within the poll bound")


class TestSimStateRunRestFace:
    def test_submit_evaluates_and_reports_l0_products(self, prod_client):
        client, _stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        assert topology.status_code == 201, topology.text
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)

        response = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_STATE", "fault_plan": _UB_CONFLICT_PLAN},
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert set(accepted) == {"run_id", "config_hash", "status"}

        status = _wait_terminal(client, session_id, accepted["run_id"])
        # the honest two-form status: L0 products present, TS face absent.
        assert status["fidelity"] == "SIM_STATE"
        assert status["status"] == "completed"
        assert status["config_hash"] == accepted["config_hash"]
        assert status["artifacts"] == []  # 无 TS artifact — 诚实空态
        assert status["packet_count"] is None
        assert status["generator_version"] is None
        assert status["graph_health"] == "error"  # the conflict chain
        assert status["node_health"]["tuner-b"] == "error"
        assert status["node_health"]["lnb-0"] == "ok"
        # DTO round-trip: the additive keys parse through the frozen model.
        parsed = RunStatusDTO.model_validate(status)
        assert parsed.fidelity == "SIM_STATE"
        assert parsed.node_health == status["node_health"]

    def test_state_run_journal_composition_over_rest(self, prod_client):
        client, stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)
        accepted = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_STATE", "fault_plan": _UB_CONFLICT_PLAN},
        ).json()
        _wait_terminal(client, session_id, accepted["run_id"])
        assert stack.drain_gateway() > 0

        events = client.get(f"/api/v1/sessions/{session_id}/events")
        assert events.status_code == 200, events.text
        items = events.json()["data"]["items"]
        types = [item["event_type"] for item in items]
        assert "rf.state_observed" in types
        assert "sec.state_observed" in types
        assert "fault.injected" in types
        assert "fault.cleared" in types
        assert "topology.state_changed" in types
        # 无 gen.* — the honesty discipline (SPEC-303 §Phase3).
        assert not any(event_type.startswith("gen.") for event_type in types)
        assert not any(event_type.startswith("ts.") for event_type in types)
        # every state-domain event sits in the frozen composition set.
        from simulation.state.observation_bridge import (
            is_sim_state_journal_event_type,
        )

        state_domain = [
            event_type
            for event_type in types
            if not event_type.startswith("simulation.")
        ]
        assert all(is_sim_state_journal_event_type(t) for t in state_domain)

    def test_same_plan_twice_same_fingerprint(self, prod_client):
        client, _stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)
        hashes = []
        for _ in range(2):
            accepted = client.post(
                f"/api/v1/sessions/{session_id}/runs",
                json={"fidelity": "SIM_STATE", "fault_plan": _UB_CONFLICT_PLAN},
            ).json()
            _wait_terminal(client, session_id, accepted["run_id"])
            hashes.append(accepted["config_hash"])
        # fault_id uuid4 identity never enters the state fingerprint.
        assert hashes[0] == hashes[1]

    def test_list_rows_declare_fidelity(self, prod_client):
        client, _stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)
        accepted = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_STATE", "fault_plan": _UB_CONFLICT_PLAN},
        ).json()
        _wait_terminal(client, session_id, accepted["run_id"])
        rows = client.get(f"/api/v1/sessions/{session_id}/runs").json()
        assert len(rows) == 1
        assert rows[0]["fidelity"] == "SIM_STATE"
        assert rows[0]["graph_health"] == "error"


class TestMixedPlanRejectionsOverWire:
    def test_state_run_rejects_package_layer_fault(self, prod_client):
        client, _stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)
        response = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_STATE", "fault_plan": _TS_LAYER_PLAN},
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error"]["error_code"] == "SIM_STATE_PLAN_INVALID"

    def test_ts_run_rejects_rf_layer_fault_cleanly(self, prod_client):
        client, _stack = prod_client
        session_id = _running_session(client, "topo-1")
        from tests.integration.api.test_rest_runs import wire_generator_config
        from tests.unit.simulation._ts_runtime_builders import (
            make_generator_config,
        )

        response = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={
                "config": wire_generator_config(make_generator_config()),
                "fault_plan": [
                    {
                        "fault_type": "TONE_RESIDUE",
                        "target_id": "lnb-0",
                        "parameters": {"tone_actual": "continuous"},
                        "activation": {"kind": "session_start"},
                        "expected_observations": [
                            "sec.state_observed",
                            "rf.state_observed",
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error"]["error_code"] == "SIM_TS_PLAN_INVALID"

    def test_state_run_refuses_generator_config(self, prod_client):
        client, _stack = prod_client
        topology = client.post("/api/v1/topologies", json=_TOPOLOGY_SPEC)
        topology_id = topology.json()["topology_id"]
        session_id = _running_session(client, topology_id)
        from tests.integration.api.test_rest_runs import wire_generator_config
        from tests.unit.simulation._ts_runtime_builders import (
            make_generator_config,
        )

        response = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={
                "fidelity": "SIM_STATE",
                "config": wire_generator_config(make_generator_config()),
            },
        )
        # a structural request-shape rule: 400 at the envelope gate (the
        # fidelity/config contract is a DTO model validator).
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"

    def test_ts_run_still_requires_config(self, prod_client):
        client, _stack = prod_client
        session_id = _running_session(client, "topo-1")
        response = client.post(
            f"/api/v1/sessions/{session_id}/runs",
            json={"fidelity": "SIM_TS"},
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"
