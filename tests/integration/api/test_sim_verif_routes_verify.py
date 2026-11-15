"""§4.4 verify REST endpoint — 501→wired switch (ticket #56, 裁定 G).

``POST /sessions/{id}/runs/{run_id}/verify`` switches behind the optional
``verification_port``: bound port → SPEC-206 service semantics (200
three-state verdict, 400 missing body, 404 unknown session, 409 run
mismatch, 422 criterion invalid); unbound port keeps the frozen-table 501
answer. The route inventory is pinned by ``test_route_table_conformance``
(methods/paths unchanged — this file pins the SEMANTICS of the switched
handler and the additive wiring posture).

The verdict flows over the REAL chain (real faulted tee run with the
production filter + real recovery run + journal; the fixture posture only
supplies the normalized ``ts.*`` observations — 裁定 A) and the answer is
checked with the DTO round-trip discipline (``assert_roundtrip``).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteVerificationRepository
from api.app import create_app
from api.dto.verification import (
    PassCriterionDTO,
    ScenarioIdentityDTO,
    VerifyRunRequest,
    VerificationResultDTO,
)
from api.routes.pending import ServiceVerificationPort, build_pending_router
from application.observation import EventGateway
from faults.factory import build_semantic_filter_factory
from simulation.runtime import SimulationRuntime
from simulation.ts_runtime import TSRuntime
from simulation.verification.service import VerificationService

from tests._support.diagnosis_fixtures import observation_envelope
from tests.integration.simulation.test_sim_verif_service_journal import (
    _cc_plan,
    _recovery_observations,
)
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)

SESSION_ID = "sess-verif-rest"
SCENARIO = {
    "scenario_id": "9c0f0000-0000-4000-8000-0000000000b2",
    "version": "1.0.0",
    "content_hash": "dd" * 32,
}
PASS_CRITERIA = [
    {
        "criterion_id": "sc-01",
        "kind": "fault_inactive",
        "mandatory": True,
        "fault_id": "fd000000-0000-4000-8000-0000000000c1",
    },
    {"criterion_id": "sc-02", "kind": "cc_continuous", "mandatory": True},
]


def _verify_body(baseline_run_id: str) -> dict:
    return {
        "baseline_run_id": baseline_run_id,
        "scenario": SCENARIO,
        "pass_criteria": PASS_CRITERIA,
    }


@pytest.fixture
def wired_stack(journal):
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    gateway = EventGateway(journal_adapter)
    runtime = SimulationRuntime(event_sink=gateway)
    ts_runtime = TSRuntime(
        runtime=runtime, filter_factory=build_semantic_filter_factory()
    )
    service = VerificationService(
        journal_adapter,
        gateway,
        SqliteVerificationRepository(connection),
        now_utc_ms=lambda: 1_700_000_000_000,
    )
    spec = make_session_spec(session_id=SESSION_ID)

    async def bootstrap() -> None:
        await runtime.create_session(spec)
        await runtime.validate_session(SESSION_ID)
        await runtime.start(SESSION_ID)

    import asyncio

    asyncio.run(bootstrap())

    def run(fault_plan=()) -> str:
        from tests.integration.simulation.test_sim_verif_service_journal import (
            _MemorySink,
        )

        prepared = ts_runtime.prepare(spec, make_generator_config(), fault_plan)

        async def main() -> str:
            result = await ts_runtime.run(prepared, _MemorySink())
            gateway.drain()
            return result.run_id

        return asyncio.run(main())

    app = create_app(
        build_pending_router(verification_port=ServiceVerificationPort(service))
    )
    return {
        "gateway": gateway,
        "journal": journal_adapter,
        "repository": SqliteVerificationRepository(connection),
        "service": service,
        "app": app,
        "run": run,
    }


@pytest.fixture
def wired_client(api_client, wired_stack):
    return api_client.build(wired_stack["app"])


@pytest.fixture
def stub_client(api_client):
    """The unbound-port posture: the verify endpoint stays on the freeze."""
    return api_client.build(create_app(build_pending_router()))


class TestWiredVerifyEndpoint:
    def test_verify_returns_the_three_state_verdict(self, wired_stack, wired_client):
        baseline_run_id = wired_stack["run"](_cc_plan())
        recovery_run_id = wired_stack["run"]()
        for document in _recovery_observations(SESSION_ID, recovery_run_id):
            assert wired_stack["gateway"].publish(document).accepted
        wired_stack["gateway"].drain()

        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{recovery_run_id}/verify",
            json=_verify_body(baseline_run_id),
        )

        assert response.status_code == 200
        body = response.json()
        result = wired_client.assert_roundtrip(VerificationResultDTO, body)
        assert result.verdict == "PASS"
        assert result.recovery_run_id == recovery_run_id
        assert result.baseline_run_id == baseline_run_id
        assert result.scenario.scenario_id == SCENARIO["scenario_id"]
        assert result.scenario.content_hash == SCENARIO["content_hash"]
        assert len(result.criteria) == len(PASS_CRITERIA)
        assert all(entry.result == "PASS" for entry in result.criteria)

    def test_verdict_is_persisted_behind_the_endpoint(self, wired_stack, wired_client):
        baseline_run_id = wired_stack["run"](_cc_plan())
        recovery_run_id = wired_stack["run"]()
        for document in _recovery_observations(SESSION_ID, recovery_run_id):
            assert wired_stack["gateway"].publish(document).accepted
        wired_stack["gateway"].drain()
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{recovery_run_id}/verify",
            json=_verify_body(baseline_run_id),
        )
        assert response.status_code == 200
        rows = wired_stack["repository"].query(SESSION_ID)
        assert len(rows) == 1
        assert rows[0].verdict == "PASS"
        assert rows[0].scenario_content_hash == SCENARIO["content_hash"]

    def test_baseline_reused_is_inconclusive_not_an_error(self, wired_stack, wired_client):
        baseline_run_id = wired_stack["run"](_cc_plan())
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{baseline_run_id}/verify",
            json=_verify_body(baseline_run_id),
        )
        assert response.status_code == 200
        assert response.json()["verdict"] == "INCONCLUSIVE"

    def test_missing_body_is_request_body_invalid(self, wired_stack, wired_client):
        recovery_run_id = wired_stack["run"]()
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{recovery_run_id}/verify"
        )
        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "REQUEST_BODY_INVALID"

    def test_unknown_session_is_404_envelope(self, wired_client):
        response = wired_client.post(
            f"/api/v1/sessions/sess-ghost/runs/run-ghost/verify",
            json=_verify_body("run-ghost"),
        )
        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_unknown_run_is_409_run_mismatch(self, wired_stack, wired_client):
        baseline_run_id = wired_stack["run"](_cc_plan())
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/run-ghost/verify",
            json=_verify_body(baseline_run_id),
        )
        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "SIM_VERIF_RUN_MISMATCH"

    def test_unknown_criterion_kind_is_422(self, wired_stack, wired_client):
        recovery_run_id = wired_stack["run"]()
        body = _verify_body("run-x")
        body["pass_criteria"] = [
            {
                "criterion_id": "sc-99",
                "kind": "ui_state_green",
                "mandatory": True,
            }
        ]
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/{recovery_run_id}/verify",
            json=body,
        )
        assert response.status_code == 422
        assert (
            response.json()["error"]["error_code"]
            == "SIM_VERIF_CRITERION_INVALID"
        )


class TestStubPosture:
    """Unbound port keeps the frozen 501 answers (additive wiring only)."""

    def test_verify_without_port_is_501(self, stub_client):
        response = stub_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/run-1/verify"
        )
        assert response.status_code == 501
        assert response.json()["error"]["error_code"] == "HTTP_501"

    def test_verify_with_port_and_malformed_body_is_400(self, wired_client):
        response = wired_client.post(
            f"/api/v1/sessions/{SESSION_ID}/runs/run-1/verify", json={}
        )
        assert response.status_code == 400

    def test_route_table_conformance_still_pins_the_inventory(self):
        from api.routes import build_spec500_routers

        import inspect

        signature = inspect.signature(build_spec500_routers)
        assert "verification_port" in signature.parameters
        assert signature.parameters["verification_port"].default is None


class TestRequestDtoShape:
    """The wire request validates against the frozen DTO round-trip."""

    def test_verify_run_request_roundtrip(self, api_client):
        client = api_client.build(create_app())
        request = VerifyRunRequest(
            baseline_run_id="run-b",
            scenario=ScenarioIdentityDTO(
                scenario_id="scn-1", version="1.0.0", content_hash="ab" * 32
            ),
            pass_criteria=[
                PassCriterionDTO(
                    criterion_id="sc-01",
                    kind="fault_inactive",
                    mandatory=True,
                    fault_id="fd000000-0000-4000-8000-0000000000c1",
                )
            ],
            ui_state={"panel": "green"},  # accepted, never consulted
        )
        client.assert_roundtrip(VerifyRunRequest, request)
