"""FastAPI app factory (SPEC-500 skeleton, ticket #24).

``create_app()`` is the single assembly point of the API layer:

- every route mounts under the frozen prefix ``/api/v1`` (additive-only
  version strategy, SPEC-500 §3 — see ``api.versioning``);
- the unified error envelope + SPEC-500 §6 mapping table is registered
  (``api.errors``);
- a per-request id is stamped for the error envelope's ``request_id``;
- a version/posture canary route (``GET /api/v1/version``) makes the
  version policy and single-machine posture HTTP-observable.

Deployment posture (SPEC-500 §3, ticket #13 Q4): single machine, single
user, no authentication — this factory installs **no auth middleware**, and
the fixed tenant identity is ``application.context.LOCAL_TENANT_ID``.
Binding to ``127.0.0.1`` is a uvicorn run posture (deployment detail), not
an app-factory concern:

    uvicorn --factory api.app:create_app --host 127.0.0.1 --port 8000

Business routes are out of scope for the skeleton (SPEC-500 §4 arrives with
M3/M4); production routers are passed to ``create_app`` and mounted under
the frozen prefix — the same seam the test suite exercises.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from api.errors import register_error_handlers
from api.versioning import API_V1_PREFIX, API_VERSION_TOKEN, VERSION_POLICY
from application.context import LOCAL_TENANT_ID


class RequestIdMiddleware:
    """Stamp a per-request id into ``scope["state"]`` (envelope ``request_id``).

    Pure ASGI (no BaseHTTPMiddleware): the stamped state stays visible to
    route handlers and to the exception handlers that render the error
    envelope, because the same scope dict flows through the stack.
    HTTP-level transport identifiers are not TS bytes — the deterministic
    reproduction discipline (CONTEXT.md) does not apply here.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            state = scope.setdefault("state", {})
            state.setdefault("request_id", uuid4().hex)
        await self._app(scope, receive, send)


def _version_canary_router() -> APIRouter:
    """Skeleton canary: version policy + single-machine posture, observably.

    Not part of the SPEC-500 §4 route inventory; it exists so the frozen
    prefix behavior and the Q4 posture are assertable at the HTTP surface
    before any business route lands. Kept/removed at M3 per delegator.
    """
    router = APIRouter(prefix=API_V1_PREFIX)

    @router.get("/version")
    def version() -> dict:
        return {
            "api_version": API_VERSION_TOKEN,
            "version_policy": VERSION_POLICY,
            "tenant_id": LOCAL_TENANT_ID,
        }

    return router


def create_app(*routers: APIRouter) -> FastAPI:
    """Build the FastAPI app with the SPEC-500 cross-cutting contracts.

    Args:
        routers: extra routers to mount under :data:`api.versioning.API_V1_PREFIX`
            (business routes arrive with M3/M4 via this seam; the skeleton
            itself ships none).
    """
    app = FastAPI(
        title="DVB-Nexus API",
        version="0.1.0",  # package version; OpenAPI info.version (SPEC-500 §10)
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    for router in routers:
        app.include_router(router, prefix=API_V1_PREFIX)
    app.include_router(_version_canary_router())
    return app
