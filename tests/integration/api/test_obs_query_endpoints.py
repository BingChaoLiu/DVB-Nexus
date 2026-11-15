"""SPEC-305 eight-endpoint REST contract (ticket #53, REQ-OBS-305-001~005).

The eight SPEC-500 §4.5 routes switch from the 501 freeze to the real
observation query plane; this file pins the HTTP contract on the switched
handlers over a REAL wired stack (SQLite journal fixture + the #50/#51/#52
services + the #53 query plane) — the same composition posture the
production bootstrap uses:

- REQ-OBS-305-005: the §6 response envelope (request_id/scope/data/meta)
  and the §7 error envelope on every surface;
- REQ-OBS-305-001: scope forcing (unknown session 404) + read-only
  discipline (export POST creates only an Observation export task);
- REQ-OBS-305-002: the flat-scalar baseline (clock-domain rules over HTTP);
- REQ-OBS-305-003/004: pagination + bounds over HTTP;
- the error-code→HTTP-row matrix (SPEC-305 §7 inventory).
"""

from __future__ import annotations

import uuid

import pytest

from adapters.storage.db import connect
from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.journal import SqliteEventJournal
from api.app import create_app
from api.dto.observation import ObservationResponseDTO
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
    parse_envelope,
)

from tests.unit.application.observation.alerts._alerts_fixtures import CannedReader
from tests.unit.application.observation.test_gateway_accept import _raw_envelope

SESSION = "sess-query"
DOMAIN = f"sim:{SESSION}"


def _append(stack, **overrides) -> int:
    journal = stack["journal"]
    session_id = overrides.pop("session_id", SESSION)
    envelope = _raw_envelope(
        event_type=overrides.pop("event_type", "simulation.run_started"),
        session_id=session_id,
        producer_id=overrides.pop("producer_id", "sim-engine"),
    )
    envelope["severity"] = overrides.pop("severity", "info")
    envelope["time"]["source"]["value_ns"] = overrides.pop("value_ns", 1)
    # Keep the source domain coherent with the scope session (the raw
    # builder's sim:sess-1 literal is a cross-test default, not a rule).
    envelope["time"]["source"]["clock_domain"] = f"sim:{session_id}"
    if "run_id" in overrides:
        envelope["scope"]["run_id"] = overrides.pop("run_id")
    assert not overrides
    seq, _ = journal.append(envelope)
    return seq


@pytest.fixture
def wired_stack(journal):
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    recorder = TimelineRecorder()
    engine = MetricsEngine()
    alerts_store = SqliteAlertStore(connection)
    alerts = AlertService(alerts_store, default_rule_set())
    exports = ExportTaskRegistry(
        records_provider=lambda session_id, **_: recorder.records(session_id),
        export_id_factory=lambda: f"export-{uuid.uuid4().hex[:8]}",
        created_at_factory=lambda: TimelineTimepoint(
            value_ns=1_000,
            clock_domain="wall:utc",
            clock_epoch=0,
            semantics=TimepointSemantics.OBSERVED,
        ),
    )
    query = ObservationQueryService(
        journal=journal_adapter,
        metrics=MetricsService(engine),
        timeline=TimelineService(recorder),
        alerts=alerts,
        reader=CannedReader(),
        exports=exports,
    )
    app = create_app(build_observation_router(ServiceObservationQueryPort(query)))
    return {
        "journal": journal_adapter,
        "recorder": recorder,
        "engine": engine,
        "query": query,
        "exports": exports,
        "app": app,
    }


@pytest.fixture
def client(api_client, wired_stack):
    return api_client.build(wired_stack["app"])


def _project_timeline(stack) -> None:
    """Project journal rows into the wired recorder (the production path
    feeds it via gateway fan-out; direct appends need the explicit pass)."""
    journal = stack["journal"]
    for row in journal.query(SESSION, after_seq=0, limit=2000):
        stack["recorder"].record_event_document(row.envelope)


class TestResponseEnvelope:
    """REQ-OBS-305-005: the §6 envelope on every endpoint."""

    def test_events_envelope_has_exactly_the_spec_shape(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(f"/api/v1/sessions/{SESSION}/events")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body.keys()) == {"request_id", "scope", "data", "meta"}
        assert body["scope"] == {"tenant_id": "local", "session_id": SESSION}
        assert set(body["meta"].keys()) == {
            "schema_version",
            "next_cursor",
            "truncated",
            "clock_domain",
        }
        assert body["meta"]["schema_version"] == "1.0"
        assert body["request_id"]
        # DTO round-trip discipline (SPEC-505 §7 via api_client).
        ObservationResponseDTO.model_validate(body)

    def test_summary_envelope_reports_watermark_and_count(self, client, wired_stack):
        for index in range(3):
            _append(wired_stack, value_ns=index)
        response = client.get(f"/api/v1/sessions/{SESSION}/observation/summary")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["session_id"] == SESSION
        assert data["journal_seq_watermark"] == 3
        assert data["event_count"] == 3
        assert data["tenant_id"] == "local"


class TestScopeForcing:
    """REQ-OBS-305-001: every endpoint is session-scoped and read-only."""

    @pytest.mark.parametrize(
        "method,path,params,json_body",
        [
            ("get", "/api/v1/sessions/ghost/observation/summary", None, None),
            ("get", "/api/v1/sessions/ghost/events", None, None),
            ("get", "/api/v1/sessions/ghost/timeline", None, None),
            (
                "post",
                "/api/v1/sessions/ghost/metrics/query",
                None,
                {
                    "metric_names": ["simulation.virtual_time_ns"],
                    "start_ns": 0,
                    "end_ns": 100,
                    "step_ns": 50,
                    "clock_domain": "sim:ghost",
                },
            ),
            ("get", "/api/v1/sessions/ghost/alerts", None, None),
            (
                "get",
                "/api/v1/sessions/ghost/health",
                {"clock_domain": "sim:ghost", "now_ns": 1},
                None,
            ),
            ("get", "/api/v1/sessions/ghost/exports/e-1", None, None),
            ("post", "/api/v1/sessions/ghost/exports", None, {}),
        ],
        ids=[
            "summary",
            "events",
            "timeline",
            "metrics",
            "alerts",
            "health",
            "export-get",
            "export-post",
        ],
    )
    def test_unknown_session_is_404_across_all_eight(
        self, client, method, path, params, json_body
    ):
        response = (
            client.get(path, params=params)
            if method == "get"
            else client.post(path, params=params, json=json_body)
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_export_post_never_mutates_the_simulation(self, client, wired_stack):
        """The export POST creates only an Observation export task — the
        journal is untouched and no session/run command fires."""
        _append(wired_stack)
        journal = wired_stack["journal"]
        before = journal.max_seq(SESSION)
        response = client.post(f"/api/v1/sessions/{SESSION}/exports", json={})
        assert response.status_code == 200, response.text
        assert journal.max_seq(SESSION) == before


class TestFlatBaselineOverHttp:
    """REQ-OBS-305-002: clock-domain rules at the HTTP surface."""

    def test_time_bounded_events_query_without_domain_is_422(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(
            f"/api/v1/sessions/{SESSION}/events",
            params={"start_ns": 0, "end_ns": 10},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["error_code"] == "OBS_INVALID_TIME_DOMAIN"

    def test_iso_bounds_accepted_on_wall_domain(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(
            f"/api/v1/sessions/{SESSION}/events",
            params={
                "clock_domain": "wall:utc",
                "start_ns": "2020-01-01T00:00:00Z",
                "end_ns": "2030-01-01T00:00:00Z",
            },
        )
        assert response.status_code == 200, response.text
        # The sim-stamped events are outside the pinned wall window — an
        # honest empty page.
        assert response.json()["data"]["items"] == []
        assert response.json()["meta"]["clock_domain"] == "wall:utc"

    def test_non_integer_limit_is_400(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(
            f"/api/v1/sessions/{SESSION}/events", params={"limit": "abc"}
        )
        assert response.status_code == 400, response.text

    def test_metrics_body_shape_matches_metric_query_example(self, client, wired_stack):
        """The flat body mirrors examples/metric-query-example.json (SPEC-305
        §10: 扁平查询形状与示例互证)."""
        _append(wired_stack)
        body = {
            "metric_names": ["simulation.virtual_time_ns"],
            "start_ns": 0,
            "end_ns": 1_000_000_000,
            "step_ns": 500_000_000,
            "clock_domain": DOMAIN,
        }
        response = client.post(f"/api/v1/sessions/{SESSION}/metrics/query", json=body)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["clock_domain"] == DOMAIN
        assert "series" in data
        assert "bucket_convention" in data


class TestPaginationAndBoundsOverHttp:
    """REQ-OBS-305-003/004 at the HTTP surface."""

    def test_events_cursor_pagination_walks_all_pages(self, client, wired_stack):
        for index in range(4):
            _append(wired_stack, value_ns=index)
        seen: list[int] = []
        url = f"/api/v1/sessions/{SESSION}/events"
        response = client.get(url, params={"limit": 2})
        while True:
            assert response.status_code == 200, response.text
            body = response.json()
            seen.extend(item["journal_seq"] for item in body["data"]["items"])
            if body["meta"]["next_cursor"] is None:
                assert body["meta"]["truncated"] is False
                break
            response = client.get(
                url,
                params={"limit": 2, "cursor": body["meta"]["next_cursor"]},
            )
        assert seen == [1, 2, 3, 4]

    def test_metrics_range_overrun_is_422_with_code(self, client, wired_stack):
        _append(wired_stack)
        response = client.post(
            f"/api/v1/sessions/{SESSION}/metrics/query",
            json={
                "metric_names": ["simulation.virtual_time_ns"],
                "start_ns": 10,
                "end_ns": 0,
                "step_ns": 1,
                "clock_domain": DOMAIN,
            },
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["error_code"] == "OBS_QUERY_RANGE_TOO_LARGE"
        )

    def test_unknown_metric_is_404_unless_allow_unknown(self, client, wired_stack):
        _append(wired_stack)
        payload = {
            "metric_names": ["no.such.metric"],
            "start_ns": 0,
            "end_ns": 100,
            "step_ns": 50,
            "clock_domain": DOMAIN,
        }
        denied = client.post(f"/api/v1/sessions/{SESSION}/metrics/query", json=payload)
        assert denied.status_code == 404, denied.text
        assert denied.json()["error"]["error_code"] == "OBS_METRIC_NOT_FOUND"
        payload["allow_unknown"] = True
        allowed = client.post(f"/api/v1/sessions/{SESSION}/metrics/query", json=payload)
        assert allowed.status_code == 200, allowed.text

    def test_timeline_requires_domain_or_lanes(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(f"/api/v1/sessions/{SESSION}/timeline")
        assert response.status_code == 422, response.text
        assert response.json()["error"]["error_code"] == "OBS_INVALID_TIME_DOMAIN"

    def test_timeline_lanes_mode_answers(self, client, wired_stack):
        _append(wired_stack)
        _project_timeline(wired_stack)
        response = client.get(
            f"/api/v1/sessions/{SESSION}/timeline", params={"lanes": True}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["lanes"], "the lane partition must be present"

    def test_timeline_pinned_domain_answers_records(self, client, wired_stack):
        _append(wired_stack)
        _project_timeline(wired_stack)
        response = client.get(
            f"/api/v1/sessions/{SESSION}/timeline",
            params={"clock_domain": DOMAIN, "clock_epoch": 0},
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["data"]["records"]) == 1

    def test_alerts_endpoint_answers_empty_page(self, client, wired_stack):
        _append(wired_stack)
        response = client.get(f"/api/v1/sessions/{SESSION}/alerts")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_health_requires_domain_and_now(self, client, wired_stack):
        _append(wired_stack)
        missing = client.get(f"/api/v1/sessions/{SESSION}/health")
        assert missing.status_code == 400, missing.text
        ok = client.get(
            f"/api/v1/sessions/{SESSION}/health",
            params={"clock_domain": DOMAIN, "now_ns": 1_000},
        )
        assert ok.status_code == 200, ok.text
        data = ok.json()["data"]
        assert data["overall"] in {"unknown", "healthy", "degraded", "critical"}

    def test_export_roundtrip_and_unknown_is_404(self, client, wired_stack):
        _append(wired_stack)
        _project_timeline(wired_stack)
        created = client.post(f"/api/v1/sessions/{SESSION}/exports", json={})
        assert created.status_code == 200, created.text
        export_id = created.json()["data"]["export_id"]
        manifest = created.json()["data"]["manifest"]
        assert manifest["total_records"] == 1
        fetched = client.get(f"/api/v1/sessions/{SESSION}/exports/{export_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["export_id"] == export_id
        missing = client.get(f"/api/v1/sessions/{SESSION}/exports/nope")
        assert missing.status_code == 404, missing.text
        assert missing.json()["error"]["error_code"] == "PLT_ARTIFACT_NOT_FOUND"
