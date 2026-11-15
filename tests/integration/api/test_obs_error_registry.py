"""Error-code registry contract (ticket #53, 裁定 1e + SPEC-305 §7).

Two obligations in one file:

1. **The four M3-leftover codes over their REAL raise points** (码串不动
   既有代码行为，只登记 — the registration is the SPEC-300 §13 scoped
   append; these tests pin the code strings on the live HTTP surface):
   - ``PLT_ARTIFACT_NOT_FOUND`` — unknown artifact metadata (404);
   - ``HTTP_RANGE_MALFORMED`` — malformed Range header (400);
   - ``HTTP_501`` — the StarletteHTTPException fallback convention, still
     answered by the deliberately-unbound pending routes;
   - ``HTTP_416`` — unsatisfiable single range (Content-Range headers).
2. **The SPEC-305 §7 HTTP inventory**: the three new declarative rows
   (401/403/429) plus the real 403 raiser (cross-session export scope) and
   the complete row set {400,401,403,404,409,413,422,429,500,503}.
"""

from __future__ import annotations

import time

import pytest

from api.errors import ERROR_HTTP_MAPPING, SPEC305_ERROR_HTTP_MAPPING

from rest_stack import build_rest_stack, wire_generator_config
from tests.integration.api.test_obs_query_endpoints import _project_timeline
from tests.unit.simulation._ts_runtime_builders import make_generator_config


class TestHttpInventoryCompleteness:
    """SPEC-305 §7: 400/401/403/404/409/413/422/429/500/503 — the union of
    the frozen SPEC-500 §6 table, the #53 extension table and the 500
    fallback covers exactly this set."""

    def test_inventory_rows_are_exactly_the_spec305_section7_set(self):
        mapped = {status for _, status in ERROR_HTTP_MAPPING}
        extension = {status for _, status in SPEC305_ERROR_HTTP_MAPPING}
        assert mapped == {400, 404, 409, 413, 422, 503}
        assert extension == {401, 403, 429}
        # 500 is the Exception-level fallback (no table row by design).
        assert mapped | extension | {500} == {
            400, 401, 403, 404, 409, 413, 422, 429, 500, 503,
        }


class TestFourRegistryCodesOverRealRoutes:
    """裁定 1e: the four M3 codes, exercised at their existing raise points."""

    @pytest.fixture
    def stacked(self, tmp_path):
        rest = build_rest_stack(tmp_path)
        from fastapi.testclient import TestClient

        client = TestClient(rest.app)
        return rest, client

    def _seed_artifact(self, rest):
        """One real stored+registered artifact (content-addressed)."""
        from adapters.storage.repositories import ArtifactMeta
        from domain.observation import ArtifactKind, TSArtifact
        from tests._support.deterministic import PACKET_SIZE, SYNC_BYTE

        content = bytearray(PACKET_SIZE * 2)
        content[0] = SYNC_BYTE  # packet 0 sync-framed; payload deterministic
        ref = rest.store.store_bytes(bytes(content), ext="ts")
        artifact = TSArtifact(
            artifact_id=ref.sha256[:32],
            run_id="run-seed",
            kind=ArtifactKind.GENERATED_TS,
            relative_path=ref.relative_path,
            packet_size=188,
            packet_count=2,
            byte_size=ref.byte_size,
            sha256=ref.sha256,
            generator_version="0.1.0",
            config_hash="seed",
            fault_profile_ids=[],
            created_at_utc_ms=int(time.time() * 1000),
        )
        rest.repository.register(ArtifactMeta(artifact=artifact, session_id="sess-seed"))
        return ref.sha256[:32], ref.byte_size

    def test_unknown_artifact_is_404_with_registered_code(self, stacked):
        _, client = stacked
        response = client.get("/api/v1/artifacts/missing-artifact")
        assert response.status_code == 404, response.text
        assert response.json()["error"]["error_code"] == "PLT_ARTIFACT_NOT_FOUND"

    def test_malformed_range_is_400_with_registered_code(self, stacked):
        rest, client = stacked
        artifact_id, _ = self._seed_artifact(rest)
        response = client.get(
            f"/api/v1/artifacts/{artifact_id}/content",
            headers={"range": "bytes=1-2, 5-9"},
        )
        assert response.status_code == 400, response.text
        assert response.json()["error"]["error_code"] == "HTTP_RANGE_MALFORMED"

    def test_unsatisfiable_range_is_416_with_content_range(self, stacked):
        rest, client = stacked
        artifact_id, size = self._seed_artifact(rest)
        response = client.get(
            f"/api/v1/artifacts/{artifact_id}/content",
            headers={"range": f"bytes={size + 1}-"},
        )
        assert response.status_code == 416, response.text
        assert response.json()["error"]["error_code"] == "HTTP_416"
        assert response.headers["content-range"] == f"bytes */{size}"

    def test_unbound_pending_route_still_answers_http_501_code(self, stacked):
        _, client = stacked
        response = client.get("/api/v1/topologies")
        assert response.status_code == 501, response.text
        assert response.json()["error"]["error_code"] == "HTTP_501"


class TestNewHttpRowsOverHttp:
    """The #53 extension rows (401/403/429) render the same envelope."""

    @pytest.fixture
    def probe_client(self, api_client):
        from fastapi import APIRouter

        from api.app import create_app
        from application.errors import (
            ForbiddenError,
            RateLimitedError,
            UnauthorizedError,
        )

        router = APIRouter()

        @router.get("/probe/unauthorized")
        def unauthorized() -> dict:
            raise UnauthorizedError("HTTP_401", "no credentials")

        @router.get("/probe/forbidden")
        def forbidden() -> dict:
            raise ForbiddenError("OBS_SCOPE_FORBIDDEN", "outside session scope")

        @router.get("/probe/rate-limited")
        def rate_limited() -> dict:
            raise RateLimitedError("HTTP_429", "export throttle engaged")

        app = create_app(router)
        return api_client.build(app)

    @pytest.mark.parametrize(
        "path,status,code,retryable",
        [
            ("/probe/unauthorized", 401, "HTTP_401", False),
            ("/probe/forbidden", 403, "OBS_SCOPE_FORBIDDEN", False),
            ("/probe/rate-limited", 429, "HTTP_429", True),
        ],
        ids=["row-401", "row-403", "row-429"],
    )
    def test_extension_row_maps_to_status_and_envelope(
        self, probe_client, path, status, code, retryable
    ):
        response = probe_client.get(f"/api/v1{path}")
        assert response.status_code == status, response.text
        body = response.json()
        assert body["error"]["error_code"] == code
        assert body["error"]["retryable"] is retryable
        assert body["request_id"]


class TestRealScopeForbidden403:
    """The real 403 raiser: another session's export id under a foreign
    session path (SPEC-305 §7 row 403, OBS_SCOPE_FORBIDDEN)."""

    def test_cross_session_export_read_is_403(self, api_client, journal):
        from adapters.storage.alerts import SqliteAlertStore
        from adapters.storage.db import connect
        from adapters.storage.journal import SqliteEventJournal
        from api.app import create_app
        from api.routes.observation import (
            ServiceObservationQueryPort,
            build_observation_router,
        )
        from application.observation.alerts.rules import default_rule_set
        from application.observation.alerts.service import AlertService
        from application.observation.metrics.engine import MetricsEngine
        from application.observation.metrics.service import MetricsService
        from application.observation.query import ObservationQueryService
        from application.observation.query.exports import ExportTaskRegistry
        from application.observation.timeline.recorder import TimelineRecorder
        from application.observation.timeline.service import TimelineService
        from domain.observation import (
            TimepointSemantics,
            TimelineTimepoint,
        )

        from tests.unit.application.observation.alerts._alerts_fixtures import (
            CannedReader,
        )

        connection = SqliteEventJournal(
            connect(journal.db_path, check_same_thread=False)
        )
        recorder = TimelineRecorder()
        exports = ExportTaskRegistry(
            records_provider=lambda session_id, **_: recorder.records(session_id),
            export_id_factory=lambda: "export-x",
            created_at_factory=lambda: TimelineTimepoint(
                value_ns=1,
                clock_domain="wall:utc",
                clock_epoch=0,
                semantics=TimepointSemantics.OBSERVED,
            ),
        )
        query = ObservationQueryService(
            journal=connection,
            metrics=MetricsService(MetricsEngine()),
            timeline=TimelineService(recorder),
            alerts=AlertService(
                SqliteAlertStore(connect(journal.db_path, check_same_thread=False)),
                default_rule_set(),
            ),
            reader=CannedReader(),
            exports=exports,
        )
        app = create_app(build_observation_router(ServiceObservationQueryPort(query)))
        client = api_client.build(app)

        _seed = {
            "event_type": "simulation.run_started",
            "session_id": "sess-a",
        }
        from tests.unit.application.observation.test_gateway_accept import (
            _raw_envelope,
        )

        envelope = _raw_envelope(**_seed)
        envelope["time"]["source"]["clock_domain"] = "sim:sess-a"
        connection.append(envelope)
        # sess-b must be a KNOWN session for the 404 scope gate to pass and
        # the registry-level 403 to be the answering row.
        envelope_b = _raw_envelope(event_type="simulation.run_started", session_id="sess-b")
        envelope_b["time"]["source"]["clock_domain"] = "sim:sess-b"
        connection.append(envelope_b)

        created = client.post("/api/v1/sessions/sess-a/exports", json={})
        assert created.status_code == 200, created.text
        export_id = created.json()["data"]["export_id"]

        foreign = client.get(f"/api/v1/sessions/sess-b/exports/{export_id}")
        assert foreign.status_code == 403, foreign.text
        body = foreign.json()
        assert body["error"]["error_code"] == "OBS_SCOPE_FORBIDDEN"
        assert body["error"]["details"]["export_session"] == "sess-a"
