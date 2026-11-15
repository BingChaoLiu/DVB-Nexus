"""SPEC-305 cursor pagination over the REST surface (ticket #53,
REQ-OBS-305-003).

Page-walk consistency (no duplicates, no gaps), the opaque-cursor binding
discipline (filter hash + scope) and the expired-cursor HTTP row (409,
``OBS_CURSOR_EXPIRED``) for the three paginated collections — events,
timeline and alerts. The events face is exercised in depth in
``test_obs_query_endpoints.py``; this file pins the cross-collection
contract.
"""

from __future__ import annotations

import pytest

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
from application.observation.timeline.recorder import TimelineRecorder
from application.observation.timeline.service import TimelineService
from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    MetricSampleTimepoint,
    SampleSemantics,
)

from tests.unit.application.observation.alerts._alerts_fixtures import CannedReader
from tests.unit.application.observation.test_gateway_accept import _raw_envelope

SESSION = "sess-page"
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
    envelope["time"]["source"]["clock_domain"] = f"sim:{session_id}"
    seq, _ = journal.append(envelope)
    return seq


def _alert_record(alert_id: str, session_id: str) -> AlertRecord:
    return AlertRecord(
        alert_id=alert_id,
        fingerprint=f"fp-{alert_id}",
        rule_id="RULE",
        rule_version="1.0.0",
        state=AlertState.FIRING,
        severity=AlertSeverity.WARNING,
        scope=AlertScope(tenant_id="local", session_id=session_id),
        time=MetricSampleTimepoint(
            value_ns=1,
            clock_domain=DOMAIN,
            clock_epoch=0,
            semantics=SampleSemantics.SOURCE,
        ),
    )


@pytest.fixture
def stack(journal):
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    recorder = TimelineRecorder()
    alerts_store = SqliteAlertStore(connection)
    query = ObservationQueryService(
        journal=journal_adapter,
        metrics=MetricsService(MetricsEngine()),
        timeline=TimelineService(recorder),
        alerts=AlertService(alerts_store, default_rule_set()),
        reader=CannedReader(),
    )
    app = create_app(build_observation_router(ServiceObservationQueryPort(query)))
    return {
        "journal": journal_adapter,
        "recorder": recorder,
        "alerts_store": alerts_store,
        "app": app,
    }


@pytest.fixture
def client(api_client, stack):
    return api_client.build(stack["app"])


def _walk(client, url, params, *, items_key="items"):
    seen = []
    next_cursor = None
    while True:
        page_params = dict(params)
        if next_cursor is not None:
            page_params["cursor"] = next_cursor
        response = client.get(url, params=page_params)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(body["data"][items_key])
        next_cursor = body["meta"]["next_cursor"]
        if next_cursor is None:
            return seen


class TestEventsPaginationOverHttp:
    def test_walk_is_gap_free_and_duplicate_free(self, client, stack):
        for index in range(9):
            _append(stack, value_ns=index)
        seen = _walk(client, f"/api/v1/sessions/{SESSION}/events", {"limit": 4})
        assert [item["journal_seq"] for item in seen] == list(range(1, 10))

    def test_filtered_walk_applies_filters_before_pagination(self, client, stack):
        for index in range(6):
            _append(
                stack,
                value_ns=index,
                severity="error" if index % 2 else "info",
            )
        seen = _walk(
            client,
            f"/api/v1/sessions/{SESSION}/events",
            {"limit": 2, "severity": "error"},
        )
        assert [item["journal_seq"] for item in seen] == [2, 4, 6]

    def test_expired_cursor_is_409_with_code(self, client, stack):
        for index in range(5):
            _append(stack, value_ns=index)
        first = client.get(
            f"/api/v1/sessions/{SESSION}/events", params={"limit": 2}
        ).json()
        cursor = first["meta"]["next_cursor"]
        assert cursor
        replayed = client.get(
            f"/api/v1/sessions/{SESSION}/events",
            params={"limit": 2, "cursor": cursor, "severity": "error"},
        )
        assert replayed.status_code == 409, replayed.text
        assert replayed.json()["error"]["error_code"] == "OBS_CURSOR_EXPIRED"


class TestTimelinePaginationOverHttp:
    def test_pinned_domain_walk_is_gap_free(self, client, stack):
        for index in range(7):
            _append(stack, value_ns=100 * (index + 1))
            stack["recorder"].record_event_document(
                stack["journal"].query(SESSION, after_seq=index, limit=1)[0].envelope
            )
        seen = _walk(
            client,
            f"/api/v1/sessions/{SESSION}/timeline",
            {"limit": 3, "clock_domain": DOMAIN, "clock_epoch": 0},
            items_key="records",
        )
        assert [item["journal_seq"] for item in seen] == list(range(1, 8))


class TestAlertsPaginationOverHttp:
    def test_alert_walk_is_deterministic_and_complete(self, client, stack):
        _append(stack)  # session must exist for the scope gate
        for index in range(5):
            stack["alerts_store"].save(_alert_record(f"alert-{index}", SESSION))
        seen = _walk(client, f"/api/v1/sessions/{SESSION}/alerts", {"limit": 2})
        assert [item["alert_id"] for item in seen] == [
            "alert-0",
            "alert-1",
            "alert-2",
            "alert-3",
            "alert-4",
        ]

    def test_alert_cursor_replayed_under_changed_filter_is_409(self, client, stack):
        _append(stack)
        for index in range(3):
            stack["alerts_store"].save(_alert_record(f"alert-{index}", SESSION))
        first = client.get(
            f"/api/v1/sessions/{SESSION}/alerts", params={"limit": 1}
        ).json()
        cursor = first["meta"]["next_cursor"]
        assert cursor
        replayed = client.get(
            f"/api/v1/sessions/{SESSION}/alerts",
            params={"limit": 1, "cursor": cursor, "state": "resolved"},
        )
        assert replayed.status_code == 409, replayed.text
        assert replayed.json()["error"]["error_code"] == "OBS_CURSOR_EXPIRED"
