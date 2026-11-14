"""App factory integration contract (SPEC-500 §3/§10, ticket #24).

Integration layer: real ASGI app through FastAPI's TestClient (in-process,
no socket binding — Windows-first, ADR-0004). Covers:

- ``create_app()`` produces a FastAPI app whose canary route serves the
  version policy and the single-machine posture under the frozen prefix
  (seam 1: /api/v1 prefix behavior, HTTP-observable);
- extra routers mount under the same prefix (the seam M3 will use);
- OpenAPI paths live under ``/api/v1`` (SPEC-500 §10: OpenAPI schema 由
  FastAPI 生成并纳入契约测试快照);
- no auth middleware (SPEC-500 §3 Q4 posture).
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from api.app import create_app
from api.versioning import API_V1_PREFIX


class TestAppFactoryBasics:
    def test_create_app_returns_fastapi_app(self):
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_canary_serves_version_policy_and_posture(self, api_client):
        client = api_client.build(create_app())
        response = client.get("/api/v1/version")
        assert response.status_code == 200
        assert response.json() == {
            "api_version": "v1",
            "version_policy": "additive-only",
            "tenant_id": "local",
        }

    def test_canary_only_reachable_under_frozen_prefix(self, api_client):
        # The prefix is part of the frozen contract: the route must not leak
        # onto an unversioned path.
        client = api_client.build(create_app())
        response = client.get("/version")
        assert response.status_code == 404

    def test_app_has_no_auth_middleware(self):
        # SPEC-500 §3 Q4: 无认证 (MVP single machine). The only middleware
        # the skeleton registers is the request_id stamping middleware.
        app = create_app()
        middleware_names = {entry.cls.__name__ for entry in app.user_middleware}
        assert middleware_names == {"RequestIdMiddleware"}


class TestRouterMounting:
    def test_extra_routers_mount_under_frozen_prefix(self, api_client):
        router = APIRouter()

        @router.get("/mount-probe")
        def mount_probe() -> dict:
            return {"mounted": True}

        client = api_client.build(create_app(router))
        response = client.get("/api/v1/mount-probe")
        assert response.status_code == 200
        assert response.json() == {"mounted": True}

    def test_extra_router_paths_cannot_escape_the_prefix(self, api_client):
        # A router carrying its own prefix must still end up under /api/v1;
        # mounting is centralized so additive-only versioning cannot be bypassed.
        router = APIRouter(prefix="/nested")

        @router.get("/leaf")
        def leaf() -> dict:
            return {"leaf": True}

        client = api_client.build(create_app(router))
        assert client.get("/api/v1/nested/leaf").status_code == 200
        assert client.get("/nested/leaf").status_code == 404


class TestOpenapiInvariant:
    def test_every_openapi_path_lives_under_frozen_prefix(self, api_client):
        client = api_client.build(create_app())
        openapi = client.get("/openapi.json").json()
        assert openapi["paths"], "OpenAPI schema must be generated (SPEC-500 §10)"
        for path in openapi["paths"]:
            assert path.startswith(API_V1_PREFIX), (
                f"route {path!r} escapes the frozen /api/v1 prefix"
            )

    def test_skeleton_openapi_path_snapshot(self, api_client):
        # Contract-test snapshot discipline (SPEC-500 §10) for the skeleton
        # stage: exactly the canary route. Route tickets (M3/M4) extend this
        # snapshot with their SPEC-500 §4 paths.
        client = api_client.build(create_app())
        openapi = client.get("/openapi.json").json()
        assert set(openapi["paths"]) == {"/api/v1/version"}
