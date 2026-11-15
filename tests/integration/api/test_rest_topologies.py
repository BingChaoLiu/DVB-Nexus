"""Topology REST ×5 (SPEC-500 §4.1, ticket #80 / REQ-API-500-001).

The five frozen-table routes switch from 501 mount points to the SPEC-502
topologies-table persistence behind the ``TopologyPort`` — through the
PRODUCTION composition root (``build_production_app``; the wiring gate is
the authoritative seam). The unbound rest_stack keeps the 501 freeze
answers (the mount-point pins in ``test_rest_pending_endpoints.py`` stay
green unchanged).

Accepted semantics pinned here:

- POST creates a NEW topology (server uuid4 id, revision=1, 201);
- PUT appends the next immutable revision row (never in-place; the old
  revision stays fetchable — 不可变追加, SPEC-502 §4);
- GET list = the latest-revision projection per topology_id;
- GET detail = the requested revision (default latest), 404 unknown;
- validate = the SPEC-202 §5 path-addressed report over the STORED graph
  (ok=false reports with 200 — session VALIDATING is where rejection
  happens, SPEC-200 §6 posture);
- a session can reference a saved (topology_id, revision) — the provider
  resolves the EXACT revision (pinning survives newer revisions);
- vocabulary violations are 400 REQUEST_BODY_INVALID (Literal gate).
"""

from __future__ import annotations

import pytest

from bootstrap import build_production_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(api_client, tmp_path):
    stack = build_production_app(db_path=tmp_path / "topo.sqlite3")
    built = api_client.build(stack.app)
    with built.client:
        yield built
    stack.close()


def _body(**overrides):
    body = {
        "nodes": [
            {
                "node_id": "mux-0",
                "node_type": "muxer",
                "config": {},
                "ports": [
                    {
                        "port_id": "out",
                        "direction": "output",
                        "plane": "MPEG_TS",
                        "max_connections": 1,
                    }
                ],
            }
        ],
        "connections": [],
    }
    body.update(overrides)
    return body


def _create(client, **overrides):
    response = client.post("/api/v1/topologies", json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


class TestCreate:
    def test_post_answers_201_with_new_identity_revision_1(self, client):
        created = _create(client)
        assert created["revision"] == 1
        assert created["topology_id"]
        assert created["nodes"][0]["node_id"] == "mux-0"
        assert created["connections"] == []

    def test_each_post_is_a_new_topology_id(self, client):
        first = _create(client)
        second = _create(client)
        assert first["topology_id"] != second["topology_id"]

    def test_identity_is_server_assigned(self, client):
        """SPEC-500 §4.1 row 1: 创建 = 新 topology_id, revision=1 — the
        request body carries graph content only (strict DTO: extra keys
        are a 400, so identity cannot ride the body)."""
        response = client.post(
            "/api/v1/topologies", json=_body(topology_id="client-picked")
        )
        assert response.status_code == 400
        assert (
            response.json()["error"]["error_code"] == "REQUEST_BODY_INVALID"
        )

    def test_bad_plane_vocabulary_is_400(self, client):
        response = client.post(
            "/api/v1/topologies",
            json=_body(
                nodes=[
                    {
                        "node_id": "mux-0",
                        "node_type": "muxer",
                        "config": {},
                        "ports": [
                            {
                                "port_id": "out",
                                "direction": "output",
                                "plane": "NOT_A_PLANE",
                                "max_connections": 1,
                            }
                        ],
                    }
                ]
            ),
        )
        assert response.status_code == 400
        assert (
            response.json()["error"]["error_code"] == "REQUEST_BODY_INVALID"
        )


class TestImmutableRevisionAppends:
    def test_put_creates_next_revision_and_old_row_stays_fetchable(self, client):
        created = _create(client)
        topology_id = created["topology_id"]
        updated = client.put(
            f"/api/v1/topologies/{topology_id}",
            json=_body(
                nodes=[
                    {
                        "node_id": "demux-0",
                        "node_type": "demuxer",
                        "config": {},
                        "ports": [
                            {
                                "port_id": "in",
                                "direction": "input",
                                "plane": "MPEG_TS",
                                "max_connections": 1,
                            }
                        ],
                    }
                ]
            ),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        # 不可变追加: revision 1 is still exactly the created payload.
        old = client.get(f"/api/v1/topologies/{topology_id}?revision=1")
        assert old.status_code == 200, old.text
        assert old.json()["revision"] == 1
        assert old.json()["nodes"][0]["node_id"] == "mux-0"

    def test_get_detail_defaults_to_latest(self, client):
        created = _create(client)
        topology_id = created["topology_id"]
        client.put(f"/api/v1/topologies/{topology_id}", json=_body())
        detail = client.get(f"/api/v1/topologies/{topology_id}")
        assert detail.status_code == 200
        assert detail.json()["revision"] == 2

    def test_unknown_revision_is_404(self, client):
        created = _create(client)
        response = client.get(
            f"/api/v1/topologies/{created['topology_id']}?revision=9"
        )
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_TOPOLOGY_NOT_FOUND"
        )

    def test_unknown_topology_detail_is_404(self, client):
        response = client.get("/api/v1/topologies/no-such-topology")
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_TOPOLOGY_NOT_FOUND"
        )


class TestList:
    def test_list_is_the_latest_revision_projection(self, client):
        first = _create(client)
        second = _create(client)
        client.put(f"/api/v1/topologies/{first['topology_id']}", json=_body())
        rows = client.get("/api/v1/topologies").json()
        by_id = {row["topology_id"]: row["revision"] for row in rows}
        assert by_id[first["topology_id"]] == 2
        assert by_id[second["topology_id"]] == 1


class TestValidate:
    def test_legal_graph_reports_ok_true_empty_violations(self, client):
        created = _create(client)
        response = client.post(
            f"/api/v1/topologies/{created['topology_id']}/validate"
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True
        assert response.json()["violations"] == []

    def test_dangling_connection_reports_path_addressed_violation(self, client):
        """SPEC-202 §5: violations are path-addressed {code, path,
        message} — a connection referencing an unknown endpoint reports
        SIM_TOPO_ENDPOINT_MISSING at connections[<id>]."""
        created = _create(
            client,
            connections=[
                {
                    "connection_id": "conn-1",
                    "from_node": "mux-0",
                    "from_port": "out",
                    "to_node": "demux-ghost",
                    "to_port": "in",
                    "plane": "MPEG_TS",
                }
            ],
        )
        response = client.post(
            f"/api/v1/topologies/{created['topology_id']}/validate"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is False
        codes = {(v["code"], v["path"]) for v in body["violations"]}
        assert any(
            code == "SIM_TOPO_ENDPOINT_MISSING" and "conn-1" in path
            for code, path in codes
        )

    def test_cycle_reports_violation_without_raising(self, client):
        created = _create(
            client,
            nodes=[
                {
                    "node_id": "a",
                    "node_type": "muxer",
                    "config": {},
                    "ports": [
                        {
                            "port_id": "out",
                            "direction": "output",
                            "plane": "MPEG_TS",
                            "max_connections": 1,
                        }
                    ],
                },
                {
                    "node_id": "b",
                    "node_type": "demuxer",
                    "config": {},
                    "ports": [
                        {
                            "port_id": "in-out",
                            "direction": "bidirectional",
                            "plane": "MPEG_TS",
                            "max_connections": 1,
                        }
                    ],
                },
            ],
            connections=[
                {
                    "connection_id": "c1",
                    "from_node": "a",
                    "from_port": "out",
                    "to_node": "b",
                    "to_port": "in-out",
                    "plane": "MPEG_TS",
                },
                {
                    "connection_id": "c2",
                    "from_node": "b",
                    "from_port": "in-out",
                    "to_node": "a",
                    "to_port": "out",
                    "plane": "MPEG_TS",
                },
            ],
        )
        response = client.post(
            f"/api/v1/topologies/{created['topology_id']}/validate"
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is False
        assert any(
            v["code"] == "SIM_TOPO_CYCLE"
            for v in response.json()["violations"]
        )

    def test_validate_explicit_revision(self, client):
        created = _create(client)
        topology_id = created["topology_id"]
        client.put(f"/api/v1/topologies/{topology_id}", json=_body())
        response = client.post(
            f"/api/v1/topologies/{topology_id}/validate?revision=1"
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_validate_unknown_topology_is_404(self, client):
        response = client.post("/api/v1/topologies/ghost/validate")
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_TOPOLOGY_NOT_FOUND"
        )


class TestSessionReferencesSavedTopology:
    def test_session_binds_saved_revision_and_survives_newer_revisions(
        self, client
    ):
        """The provider upgrade: a session references a SAVED
        (topology_id, revision); a later PUT (revision 2) must not
        re-bind the live session — revision pinning (SPEC-502 §4
        topologyRevision 防旧配置覆盖)."""
        created = _create(client)
        topology_id = created["topology_id"]
        session = client.post(
            "/api/v1/sessions",
            json={"topology_id": topology_id, "topology_revision": 1, "seed": 7},
        )
        assert session.status_code == 201, session.text
        assert session.json()["topology_revision"] == 1
        client.put(f"/api/v1/topologies/{topology_id}", json=_body())
        snapshot = client.get(f"/api/v1/sessions/{session.json()['session_id']}/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["topology_revision"] == 1

    def test_unknown_saved_reference_is_404_same_code(self, client):
        response = client.post(
            "/api/v1/sessions",
            json={"topology_id": "no-such-topology", "seed": 1},
        )
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_TOPOLOGY_NOT_FOUND"
        )
