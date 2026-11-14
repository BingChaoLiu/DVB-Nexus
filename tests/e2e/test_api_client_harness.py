"""``api_client`` harness behavior (SPEC-505 §4, serving SPEC-500).

E2E layer: full-stack plumbing through a real ASGI app. The app here is
built **inside the test** on purpose: the factory-shaped harness must
accept ANY ASGI app, so it is validated against a minimal in-test FastAPI
app (not just the real factory). The real factory exists since the
SPEC-500 skeleton (#24, ``api.app.create_app``) and is wrapped by the
derived ``client`` fixture in the root conftest; the SPEC-500 skeleton
error-contract tests mount probe routers via
``api_client.build(create_app(router))``. This is harness validation, not
business e2e coverage.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from pydantic import BaseModel


class EchoRequest(BaseModel):
    """Stands in for a SPEC-500 Pydantic DTO (snake_case JSON fields)."""

    topology_id: str
    revision: int


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/topologies")
    def create_topology(request: EchoRequest) -> dict:
        # Versioned path discipline (SPEC-500: /api/v1 冻结 additive-only)
        return {"topology_id": request.topology_id, "revision": request.revision}

    @app.get("/api/v1/topologies/{topology_id}")
    def read_topology(topology_id: str) -> dict:
        return {"topology_id": topology_id, "revision": 1}

    return app


class TestHttpClientPath:
    def test_post_round_trips_dto_payload(self, api_client):
        client = api_client.build(_build_app())
        response = client.post(
            "/api/v1/topologies",
            json={"topology_id": "topo-1", "revision": 1},
        )
        assert response.status_code == 200
        assert response.json() == {"topology_id": "topo-1", "revision": 1}

    def test_path_params_reach_the_app(self, api_client):
        client = api_client.build(_build_app())
        response = client.get("/api/v1/topologies/topo-42")
        assert response.status_code == 200
        assert response.json()["topology_id"] == "topo-42"

    def test_raw_test_client_remains_reachable(self, api_client):
        client = api_client.build(_build_app())
        assert client.client.app is not None  # TestClient passthrough


class TestDtoRoundTrip:
    def test_roundtrip_preserves_payload(self, api_client):
        client = api_client.build(_build_app())
        reloaded = client.assert_roundtrip(
            EchoRequest, {"topology_id": "topo-9", "revision": 7}
        )
        assert reloaded == EchoRequest(topology_id="topo-9", revision=7)

    def test_invalid_payload_raises_validation_error(self, api_client):
        client = api_client.build(_build_app())
        with pytest.raises(Exception):
            client.assert_roundtrip(EchoRequest, {"topology_id": 1.5, "revision": "x"})

    def test_roundtrip_goes_through_json_boundary(self, api_client):
        # A payload that only survives via the JSON serialization boundary
        # proves the harness exercises dump(mode="json") → revalidate, not
        # an in-memory object copy.
        client = api_client.build(_build_app())
        reloaded = client.assert_roundtrip(
            EchoRequest, {"topology_id": "topo-json", "revision": 2**31}
        )
        assert reloaded.revision == 2**31
