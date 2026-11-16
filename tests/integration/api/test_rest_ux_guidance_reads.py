"""SPEC-408 §6 backend read-only increments (ticket #94) through the
PRODUCTION composition root.

The four additive read faces, pinned field-for-field against the approved
§6 wire contract (SPEC-408 §5 new shapes, L183-188):

- ``GET /api/v1/sessions?limit=<1..100, default 20>`` →
  ``SessionListItemDTO[]`` ordered ``created_at`` DESC (newest first);
  out-of-range limit → 400 envelope (SPEC-500 §6 row 400);
- ``GET /api/v1/sessions/{id}`` → the existing view shape additively
  extended with ``scenario_id?`` + ``created_at_ms``; unknown session →
  404 ``SIM_SESSION_NOT_FOUND``;
- ``GET /api/v1/sessions/{id}/runs`` → ``RunListItemDTO[]`` ordered
  ``submitted_at`` ASC (the eight-step narrative order); unknown session
  → 404; a known session without runs answers 200 ``[]``;
- ``GET /api/v1/scenarios/{id}`` gains ``content_hash`` (the loader's
  pinned SHA-256, SPEC-205 §5 semantics).

Discipline (tests/README.md §6): timestamps are asserted as shapes
(``int > 0``, monotonic order) — never pinned to literal wall-clock
values; the ordering proofs use the injectable ``now_wall_ns`` clock with
1 ms steps so strictly-distinguishable stamps make the direction
assertions exact. All four faces are read-only: zero write paths, zero
state migration (SPEC-408 §6); the errors ride the unified SPEC-305 §7
envelope.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from itertools import count
from pathlib import Path

import pytest

from bootstrap import build_production_app
from bootstrap.backends import wire_generator_config
from simulation.scenario.loader import load_scenario_text
from tests.unit.simulation._ts_runtime_builders import make_generator_config

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[2] / "fixtures" / "scenarios" / "fault-lab-cc-discontinuity.json"
SCENARIO_ID = json.loads(FIXTURE.read_text(encoding="utf-8"))["scenario_id"]

#: The §6.1 list wire contract, field-for-field.
SESSION_LIST_KEYS = {
    "session_id",
    "lifecycle",
    "created_at_ms",
    "scenario_id",
    "topology_revision",
}

#: The §6.2 detail additive extension over the existing view shape.
SESSION_DETAIL_EXTENSION = {"scenario_id", "created_at_ms"}

#: The §5 SessionViewDTO wire shape the detail extends (dto/sessions.py).
SESSION_VIEW_KEYS = {
    "session_id",
    "revision",
    "lifecycle",
    "virtual_time_ns",
    "topology_revision",
    "node_states",
    "active_faults",
    "latest_artifact_refs",
}

#: The §6.3 run-list wire contract, field-for-field.
RUN_LIST_KEYS = {
    "run_id",
    "status",
    "submitted_at_ms",
    "fault_plan_present",
    "packet_count",
}

_POLL_BOUND = 2000  # event-driven yield points; no wall-clock waits


def _registry(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "scenario.json").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return root


@contextmanager
def _stack_client(api_client, tmp_path: Path, **kwargs):
    stack = build_production_app(
        db_path=tmp_path / "ux-reads.sqlite3",
        scenario_dir=_registry(tmp_path),
        **kwargs,
    )
    built = api_client.build(stack.app)
    with built.client:
        yield built, stack
    stack.close()


@pytest.fixture
def harness(api_client, tmp_path):
    with _stack_client(api_client, tmp_path) as pair:
        yield pair


@pytest.fixture
def client(harness):
    built, _ = harness
    return built


def _fake_clock():
    """1 ms-step monotonic ns counter: every read is distinguishable."""
    ticks = count(start=1)
    return lambda: next(ticks) * 1_000_000


def _assert_envelope(body: dict) -> None:
    """The unified SPEC-305 §7 envelope shape (SPEC-500 §6)."""
    assert set(body.keys()) == {"error", "request_id"}
    assert set(body["error"].keys()) == {
        "error_code",
        "message",
        "retryable",
        "details",
    }
    assert body["request_id"]


def _plain_session(client, **overrides) -> dict:
    body = {"topology_id": "topo-1", "seed": 20260101}
    body.update(overrides)
    response = client.post("/api/v1/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _running_session(client) -> str:
    session_id = _plain_session(client)["session_id"]
    assert client.post(f"/api/v1/sessions/{session_id}/validate").status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/start").status_code == 200
    return session_id


def _cc_plan_wire(*, packet_index: int = 10, delta: int = 3) -> list[dict]:
    """The SPEC-204 §6.3 CC_DISCONTINUITY fault in wire shape."""
    return [
        {
            "fault_type": "CC_DISCONTINUITY",
            "target_id": "demux-0:pid:0x0100",
            "parameters": {"delta": delta},
            "activation": {"kind": "packet_index", "packet_index": packet_index},
            "expected_observations": ["ts.continuity_error"],
        }
    ]


def _submit_run(client, session_id: str, plan: list[dict] | None = None) -> str:
    payload = {"config": wire_generator_config(make_generator_config())}
    if plan is not None:
        payload["fault_plan"] = plan
    response = client.post(f"/api/v1/sessions/{session_id}/runs", json=payload)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def _wait_terminal(client, session_id: str, run_id: str) -> dict:
    for _ in range(_POLL_BOUND):
        response = client.get(f"/api/v1/sessions/{session_id}/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] != "running":
            return body
        client.get("/api/v1/version")  # yield point: the job task advances
    pytest.fail("run did not reach a terminal state within the poll bound")


class TestSessionListContract:
    def test_wire_fields_exact_and_values(self, client):
        created = _plain_session(client)
        rows = client.get("/api/v1/sessions").json()
        assert len(rows) == 1
        assert set(rows[0].keys()) == SESSION_LIST_KEYS
        assert rows[0]["session_id"] == created["session_id"]
        assert rows[0]["lifecycle"] == created["lifecycle"]
        assert rows[0]["scenario_id"] is None  # plain path: no scenario bound
        assert rows[0]["topology_revision"] == created["topology_revision"]
        assert isinstance(rows[0]["created_at_ms"], int)
        assert rows[0]["created_at_ms"] > 0

    def test_scenario_session_lists_its_scenario_id(self, client):
        created = _plain_session(client, scenario_id=SCENARIO_ID)
        rows = client.get("/api/v1/sessions").json()
        assert rows[0]["session_id"] == created["session_id"]
        assert rows[0]["scenario_id"] == SCENARIO_ID
        assert rows[0]["lifecycle"] == "ready"  # the loader validated to READY

    def test_newest_first_ordering_strict_with_injected_clock(
        self, api_client, tmp_path
    ):
        with _stack_client(api_client, tmp_path, now_wall_ns=_fake_clock()) as (
            built,
            _,
        ):
            ids = [_plain_session(built)["session_id"] for _ in range(3)]
            rows = built.get("/api/v1/sessions").json()
        # created_at DESC: the newest session leads (strict — 1 ms steps).
        assert [row["session_id"] for row in rows] == list(reversed(ids))
        stamps = [row["created_at_ms"] for row in rows]
        assert stamps == sorted(stamps, reverse=True)
        assert len(set(stamps)) == len(stamps)  # distinguishable → strict

    def test_default_limit_answers_every_session_up_to_20(self, client):
        for _ in range(3):
            _plain_session(client)
        rows = client.get("/api/v1/sessions").json()
        assert len(rows) == 3

    def test_limit_is_capped_at_100_keeping_the_newest(
        self, api_client, tmp_path
    ):
        with _stack_client(api_client, tmp_path, now_wall_ns=_fake_clock()) as (
            built,
            _,
        ):
            for _ in range(101):
                _plain_session(built)
            rows = built.get("/api/v1/sessions?limit=100").json()
        assert len(rows) == 100
        stamps = [row["created_at_ms"] for row in rows]
        # The truncation keeps the NEWEST window: the first-created stamp
        # (tick 1) is the one dropped by the 100 cap.
        assert min(stamps) == 2
        assert max(stamps) == 101

    @pytest.mark.parametrize("limit", [0, 101])
    def test_out_of_range_limit_is_400_envelope(self, client, limit):
        response = client.get(f"/api/v1/sessions?limit={limit}")
        assert response.status_code == 400
        body = response.json()
        _assert_envelope(body)
        assert body["error"]["error_code"] == "REQUEST_BODY_INVALID"

    @pytest.mark.parametrize("limit", [1, 100])
    def test_limit_boundaries_are_valid(self, client, limit):
        _plain_session(client)
        response = client.get(f"/api/v1/sessions?limit={limit}")
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestSessionDetailContract:
    def test_detail_extends_the_existing_view_additively(self, client):
        created = _plain_session(client)
        detail = client.get(f"/api/v1/sessions/{created['session_id']}").json()
        assert set(detail.keys()) == SESSION_VIEW_KEYS | SESSION_DETAIL_EXTENSION
        # The base view fields equal the create-time answer verbatim.
        for key in SESSION_VIEW_KEYS:
            assert detail[key] == created[key], key
        assert detail["scenario_id"] is None
        assert isinstance(detail["created_at_ms"], int)
        assert detail["created_at_ms"] > 0
        # Cross-endpoint consistency with the §6.1 list face.
        rows = client.get("/api/v1/sessions").json()
        assert rows[0]["created_at_ms"] == detail["created_at_ms"]

    def test_scenario_detail_carries_the_scenario_id(self, client):
        created = _plain_session(client, scenario_id=SCENARIO_ID)
        detail = client.get(f"/api/v1/sessions/{created['session_id']}").json()
        assert detail["scenario_id"] == SCENARIO_ID
        assert detail["created_at_ms"] > 0

    def test_unknown_session_is_404_envelope(self, client):
        response = client.get("/api/v1/sessions/no-such-session")
        assert response.status_code == 404
        body = response.json()
        _assert_envelope(body)
        assert body["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"


class TestRunListContract:
    def test_wire_fields_exact_on_a_completed_run(self, client):
        session_id = _running_session(client)
        run_id = _submit_run(client, session_id)
        status = _wait_terminal(client, session_id, run_id)
        assert status["status"] == "completed"
        rows = client.get(f"/api/v1/sessions/{session_id}/runs").json()
        assert len(rows) == 1
        assert set(rows[0].keys()) == RUN_LIST_KEYS
        assert rows[0]["run_id"] == run_id
        assert rows[0]["status"] == "completed"
        assert rows[0]["fault_plan_present"] is False
        # packet_count passes through from the completed result face.
        assert rows[0]["packet_count"] == status["packet_count"]

    def test_fault_plan_present_flag_reflects_the_submission(self, client):
        session_id = _running_session(client)
        run_id = _submit_run(client, session_id, plan=_cc_plan_wire())
        status = _wait_terminal(client, session_id, run_id)
        assert status["status"] == "completed"
        rows = client.get(f"/api/v1/sessions/{session_id}/runs").json()
        assert rows[0]["fault_plan_present"] is True
        assert rows[0]["packet_count"] == status["packet_count"]

    def test_submitted_at_ascending_narrative_order_with_injected_clock(
        self, api_client, tmp_path
    ):
        with _stack_client(api_client, tmp_path, now_wall_ns=_fake_clock()) as (
            built,
            _,
        ):
            session_id = _running_session(built)
            submitted = []
            for _ in range(3):
                run_id = _submit_run(built, session_id)
                _wait_terminal(built, session_id, run_id)
                submitted.append(run_id)
            rows = built.get(f"/api/v1/sessions/{session_id}/runs").json()
        # submitted_at ASC: the submission (narrative) order verbatim.
        assert [row["run_id"] for row in rows] == submitted
        stamps = [row["submitted_at_ms"] for row in rows]
        assert stamps == sorted(stamps)
        assert len(set(stamps)) == len(stamps)  # distinguishable → strict

    def test_unknown_session_is_404_envelope(self, client):
        response = client.get("/api/v1/sessions/no-such-session/runs")
        assert response.status_code == 404
        body = response.json()
        _assert_envelope(body)
        assert body["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"

    def test_known_session_without_runs_answers_200_empty(self, client):
        created = _plain_session(client)
        rows = client.get(f"/api/v1/sessions/{created['session_id']}/runs").json()
        assert rows == []


class TestScenarioContentHash:
    def test_detail_carries_the_loader_pinned_hash(self, client):
        """The SPEC-205 §5 version-pinning identity: the wire value equals
        the loader's own ``ScenarioDocument.content_hash`` for the same
        document bytes (equality against the loader authority, never a
        pinned literal)."""
        body = client.get(f"/api/v1/scenarios/{SCENARIO_ID}").json()
        expected = load_scenario_text(
            FIXTURE.read_text(encoding="utf-8")
        ).content_hash
        assert body["content_hash"] == expected
        assert re.fullmatch(r"[0-9a-f]{64}", body["content_hash"])
