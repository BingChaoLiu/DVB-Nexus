"""Error contract integration tests (SPEC-500 §6 + SPEC-305 §7, ticket #24).

Integration layer: every row of the declarative SPEC-500 §6 mapping table is
exercised through the app's public HTTP surface (seams 2 and 3), using a
test-only probe router mounted via the same ``create_app`` seam M3 routes
will use. The skeleton ships no business routes, so raising application
exceptions from probe routes is the honest production-equivalent path.

Envelope shape authority: SPEC-305 §7 (via SPEC-500 §3), rendered by
``api.errors`` handlers, DTO authority in ``api.dto.ErrorResponse``.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.testclient import TestClient

from api.app import create_app
from api.dto import ErrorResponse
from application.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    SemanticValidationError,
    ServiceUnavailableError,
)


class EchoRequest(BaseModel):
    """Probe request DTO: schema-invalid bodies drive the 400 row."""

    topology_id: str
    revision: int


def _probe_router() -> APIRouter:
    """Routes that raise each application error category (test-only)."""
    router = APIRouter()

    @router.get("/probe/bad-request")
    def bad_request() -> dict:
        raise BadRequestError("TEST_BAD_REQUEST", "body is malformed", details={"field": "topology_id"})

    @router.get("/probe/not-found")
    def not_found() -> dict:
        raise NotFoundError("TEST_NOT_FOUND", "no session 0f0e")

    @router.get("/probe/conflict")
    def conflict() -> dict:
        raise ConflictError(
            "TEST_CONFLICT", "start is invalid in state PAUSED", details={"current_state": "PAUSED"}
        )

    @router.get("/probe/payload-too-large")
    def payload_too_large() -> dict:
        raise PayloadTooLargeError("TEST_PAYLOAD_TOO_LARGE", "body exceeds limit", retryable=False)

    @router.get("/probe/semantic-invalid")
    def semantic_invalid() -> dict:
        raise SemanticValidationError(
            "TEST_SEMANTIC_INVALID",
            "fault prepare rejected",
            details={"schema_path": "$.fault_plan[0].kind"},
        )

    @router.get("/probe/service-unavailable")
    def service_unavailable() -> dict:
        raise ServiceUnavailableError(
            "TEST_STORAGE_UNAVAILABLE", "journal store unreachable", retryable=True
        )

    @router.get("/probe/unhandled")
    def unhandled() -> dict:
        raise RuntimeError("boom: internal detail must not leak")

    @router.post("/probe/echo")
    def echo(request: EchoRequest) -> dict:
        return {"topology_id": request.topology_id, "revision": request.revision}

    return router


def _build_client(api_client):
    return api_client.build(create_app(_probe_router()))


# (probe path, expected HTTP status, expected error_code, retryable, details)
_ROWS = [
    ("/probe/bad-request", 400, "TEST_BAD_REQUEST", False, {"field": "topology_id"}),
    ("/probe/not-found", 404, "TEST_NOT_FOUND", False, {}),
    ("/probe/conflict", 409, "TEST_CONFLICT", False, {"current_state": "PAUSED"}),
    ("/probe/payload-too-large", 413, "TEST_PAYLOAD_TOO_LARGE", False, {}),
    (
        "/probe/semantic-invalid",
        422,
        "TEST_SEMANTIC_INVALID",
        False,
        {"schema_path": "$.fault_plan[0].kind"},
    ),
    ("/probe/service-unavailable", 503, "TEST_STORAGE_UNAVAILABLE", True, {}),
]

_ROW_IDS = [f"{status}-{code}" for _, status, code, _, _ in _ROWS]


class TestMappingTableRowsOverHttp:
    """Seam 2: every SPEC-500 §6 row renders its exact status + envelope."""

    @pytest.mark.parametrize("path,status,code,retryable,details", _ROWS, ids=_ROW_IDS)
    def test_row_maps_to_exact_status_and_envelope(
        self, api_client, path, status, code, retryable, details
    ):
        client = _build_client(api_client)
        response = client.get(f"/api/v1{path}")
        assert response.status_code == status
        body = response.json()
        # Envelope keys are exactly the SPEC-305 §7 shape.
        assert set(body.keys()) == {"error", "request_id"}
        assert set(body["error"].keys()) == {"error_code", "message", "retryable", "details"}
        assert body["error"]["error_code"] == code
        assert isinstance(body["error"]["message"], str) and body["error"]["message"]
        assert body["error"]["retryable"] is retryable
        assert body["error"]["details"] == details
        assert body["request_id"]

    @pytest.mark.parametrize("path,status,code,retryable,details", _ROWS, ids=_ROW_IDS)
    def test_row_response_validates_against_error_dto(
        self, api_client, path, status, code, retryable, details
    ):
        client = _build_client(api_client)
        response = client.get(f"/api/v1{path}")
        reloaded = client.assert_roundtrip(ErrorResponse, response.json())
        assert reloaded.error.error_code == code
        assert reloaded.error.details == details


class TestRequestBodyInvalidMapsTo400:
    """SPEC-500 §6 row 400 covers request body/envelope illegality.

    FastAPI's default RequestValidationError status is 422, which the spec
    reserves for semantic invalidity — the skeleton overrides it to 400.
    """

    def test_schema_invalid_body_renders_400_envelope(self, api_client):
        client = _build_client(api_client)
        response = client.post("/api/v1/probe/echo", json={"revision": "not-an-int"})
        assert response.status_code == 400
        body = response.json()
        assert set(body.keys()) == {"error", "request_id"}
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"
        # Path-addressed details: the invalid field is locatable. `details`
        # stays a spec-shaped object (SPEC-305 §7 shows an object); the
        # validation entries ride under the "errors" key.
        entries = body["error"]["details"]["errors"]
        locations = [tuple(entry["loc"]) for entry in entries]
        assert ("body", "revision") in locations

    def test_valid_body_still_round_trips(self, api_client):
        client = _build_client(api_client)
        response = client.post(
            "/api/v1/probe/echo", json={"topology_id": "topo-1", "revision": 1}
        )
        assert response.status_code == 200
        assert response.json() == {"topology_id": "topo-1", "revision": 1}


class TestUnhandledExceptionMapsTo500:
    """Seam 3: unknown/unhandled exceptions render the spec 500 shape.

    Starlette's ServerErrorMiddleware always re-raises after rendering the
    registered Exception-level handler, so this test needs a TestClient
    built with ``raise_server_exceptions=False`` (the scaffold ``api_client``
    harness cannot express that flag — extension requested in the report).
    """

    def test_unhandled_exception_renders_500_envelope(self):
        client = TestClient(create_app(_probe_router()), raise_server_exceptions=False)
        response = client.get("/api/v1/probe/unhandled")
        assert response.status_code == 500
        body = response.json()
        assert set(body.keys()) == {"error", "request_id"}
        assert body["error"]["error_code"] == "INTERNAL_UNCLASSIFIED"
        assert body["error"]["retryable"] is False
        assert body["error"]["details"] == {}
        # No internals leak into the envelope.
        assert "boom" not in body["error"]["message"]

    def test_bare_application_error_is_unclassified_too(self):
        from application.errors import ApplicationError

        router = APIRouter()

        @router.get("/probe/bare")
        def bare() -> dict:
            raise ApplicationError("SOME_CODE", "no category row claims me")

        client = TestClient(create_app(router), raise_server_exceptions=False)
        response = client.get("/api/v1/probe/bare")
        assert response.status_code == 500
        assert response.json()["error"]["error_code"] == "INTERNAL_UNCLASSIFIED"


class TestFrameworkHttpErrorRendersEnvelope:
    def test_unknown_route_renders_404_envelope(self, api_client):
        client = _build_client(api_client)
        response = client.get("/api/v1/definitely-not-a-route")
        assert response.status_code == 404
        body = response.json()
        assert set(body.keys()) == {"error", "request_id"}
        assert body["error"]["error_code"] == "HTTP_404"

    def test_method_not_allowed_renders_405_envelope(self, api_client):
        client = _build_client(api_client)
        response = client.post("/api/v1/probe/bad-request")
        assert response.status_code == 405
        body = response.json()
        assert set(body.keys()) == {"error", "request_id"}
        assert body["error"]["error_code"] == "HTTP_405"


class TestRequestId:
    def test_request_id_varies_per_request(self, api_client):
        client = _build_client(api_client)
        first = client.get("/api/v1/definitely-not-a-route").json()["request_id"]
        second = client.get("/api/v1/definitely-not-a-route").json()["request_id"]
        assert first and second
        assert first != second

    def test_request_id_is_hex_uuid_shaped(self, api_client):
        client = _build_client(api_client)
        request_id = client.get("/api/v1/definitely-not-a-route").json()["request_id"]
        assert len(request_id) == 32
        int(request_id, 16)  # raises if not hex
