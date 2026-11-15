"""§4.4 diagnosis REST endpoints — 501→wired switch (ticket #54, 裁定 G).

The two diagnosis endpoints switch behind the optional ``diagnosis_port``:
bound port → SPEC-306 service semantics (404 unknown session/run, 503
storage unavailable, 200 report/list); unbound port keeps the frozen-table
501 answer. The SPEC-500 §4 route inventory itself is pinned by
``test_route_table_conformance.py`` — this file pins the SEMANTICS of the
two switched handlers plus the additive wiring posture.
"""

import sqlite3

import pytest

from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteDiagnosisRepository
from api.app import create_app
from api.dto.diagnosis import DiagnosisDTO, DiagnosisReportDTO
from api.routes.pending import ServiceDiagnosisPort, build_pending_router
from application.diagnosis import DiagnosisService
from application.observation.gateway import EventGateway

from tests._support.diagnosis_fixtures import (
    RUN_ID,
    SESSION_ID,
    builtin_fixture_rules,
    fault_observation_program,
    observation_envelope,
)


class _BrokenJournal:
    def query(self, session_id, *, after_seq=0, limit=100):
        raise sqlite3.OperationalError("disk I/O error")

    def max_seq(self, session_id):
        raise sqlite3.OperationalError("disk I/O error")


@pytest.fixture
def wired_stack(journal):
    # check_same_thread=False (ticket #47 posture): TestClient drives the
    # app on the portal thread while the fixture opened the connection.
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    gateway = EventGateway(journal_adapter)
    service = DiagnosisService(
        journal_adapter,
        gateway,
        SqliteDiagnosisRepository(connection),
        rules_provider=builtin_fixture_rules,
        now_utc_ms=lambda: 1_700_000_000_000,
    )
    app = create_app(build_pending_router(diagnosis_port=ServiceDiagnosisPort(service)))
    return {
        "gateway": gateway,
        "journal": journal_adapter,
        "repository": SqliteDiagnosisRepository(connection),
        "service": service,
        "app": app,
    }


@pytest.fixture
def wired_client(api_client, wired_stack):
    return api_client.build(wired_stack["app"])


@pytest.fixture
def stub_client(api_client):
    """The unbound-port posture: §4.4 endpoints stay on the freeze answer."""
    return api_client.build(create_app(build_pending_router()))


def _seed_run(stack, fault_type="PAT_MISSING"):
    """Admit one fault's observations + a terminal run event."""
    for record in fault_observation_program(fault_type):
        assert stack["gateway"].publish(
            observation_envelope(
                event_type=record.event_type,
                payload=record.payload,
                session_id=SESSION_ID,
                run_id=RUN_ID,
                pid=record.pid,
                node_id=record.node_id,
                source_ns=record.source_ns,
            )
        ).accepted
    assert stack["gateway"].publish(
        observation_envelope(
            event_type="simulation.run_completed",
            payload={"lifecycle": "completed"},
            session_id=SESSION_ID,
            run_id=RUN_ID,
        )
    ).accepted
    stack["gateway"].drain()


class TestWiredEndpoints:
    def test_diagnose_returns_report_and_persists(self, wired_stack, wired_client):
        _seed_run(wired_stack)
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{RUN_ID}/diagnose"
        )
        assert response.status_code == 200
        body = response.json()
        report = wired_client.assert_roundtrip(DiagnosisReportDTO, body)
        assert report.run_id == RUN_ID
        assert len(report.candidates) == 1
        candidate = report.candidates[0]
        assert candidate.code == "DIAG_PAT_MISSING"
        assert candidate.severity == "error"
        assert candidate.confidence == "high"
        assert candidate.evidence.artifact_id != ""
        # Idempotent: the row exists exactly once.
        rows = wired_stack["repository"].query(SESSION_ID)
        assert len(rows) == 1 and rows[0].state == "raised"

    def test_diagnose_unknown_run_is_404_envelope(self, wired_client):
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/run-ghost/diagnose"
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["error_code"] == "SIM_RUN_NOT_FOUND"

    def test_list_diagnoses_returns_table_view(self, wired_stack, wired_client):
        _seed_run(wired_stack)
        assert (
            wired_client.post(
                f"/api/v1/sessions/{SESSION_ID}/runs/{RUN_ID}/diagnose"
            ).status_code
            == 200
        )
        response = wired_client.get(f"/api/v1/sessions/{SESSION_ID}/diagnoses")
        assert response.status_code == 200
        rows = wired_client.assert_roundtrip(DiagnosisDTO, response.json()[0])
        assert rows.code == "DIAG_PAT_MISSING"
        assert rows.state == "raised"
        assert rows.observation_refs[0].journal_seq >= 1

    def test_list_unknown_session_is_404(self, wired_client):
        response = wired_client.get("/api/v1/sessions/sess-ghost/diagnoses")
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_journal_failure_is_503_storage_unavailable(self, api_client):
        from api.errors import ERROR_HTTP_MAPPING  # noqa: F401  (mapping table)

        broken_service = DiagnosisService(
            _BrokenJournal(),
            _BrokenJournal(),  # publisher unused before the read fails
            SqliteDiagnosisRepository(connect(":memory:")),
            now_utc_ms=lambda: 1,
        )
        app = create_app(build_pending_router(diagnosis_port=ServiceDiagnosisPort(broken_service)))
        client = api_client.build(app)
        response = client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{RUN_ID}/diagnose"
        )
        assert response.status_code == 503
        assert response.json()["error"]["error_code"] == "OBS_STORAGE_UNAVAILABLE"


class TestStubPosture:
    """Unbound port keeps the frozen 501 answers (additive wiring only)."""

    def test_diagnose_without_port_is_501(self, stub_client):
        response = stub_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{RUN_ID}/diagnose"
        )
        assert response.status_code == 501
        assert response.json()["error"]["error_code"] == "HTTP_501"

    def test_list_without_port_is_501(self, stub_client):
        response = stub_client.get(f"/api/v1/sessions/{SESSION_ID}/diagnoses")
        assert response.status_code == 501

    def test_verify_stays_501_even_with_wired_port(self, wired_client):
        # SPEC-206 verification is ticket #56 — the wired diagnosis port
        # does not switch it.
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{RUN_ID}/verify"
        )
        assert response.status_code == 501
