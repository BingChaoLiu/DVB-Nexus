"""TSDuck call-records REST face (SPEC-500 §4.8, ticket #80 /
REQ-API-500-008) through the PRODUCTION composition root.

The nine SPEC-308 §7 fields + the optional ``run_id`` — the wire contract
is the approved §4.8 amendment table, pinned field-for-field here against
fixture-seeded storage rows (the production stack makes no real TSDuck
calls; 裁定 E item 3). Existence semantics mirror ``GET .../diagnoses``:
no stored rows AND an empty journal → 404 ``SIM_SESSION_NOT_FOUND``;
otherwise 200 (possibly empty).
"""

from __future__ import annotations

import pytest

from adapters.storage.tsduck_calls import TSDuckCallRecord
from bootstrap import build_production_app

pytestmark = pytest.mark.integration

SESSION = "sess-calls-1"
OTHER_SESSION = "sess-calls-2"


def _row(**overrides) -> TSDuckCallRecord:
    values = {
        "record_id": "rec-1",
        "session_id": SESSION,
        "run_id": "run-1",
        "version": "3.40",
        "executable_path": "C:/Program Files/TSDuck/bin/tsp.exe",
        "argv": ("tsp", "-I", "null", "-O", "null"),
        "started_at_utc_ms": 1_700_000_000_000,
        "finished_at_utc_ms": 1_700_000_001_000,
        "exit_code": 0,
        "stdout_text": '{"ts": {"bytes": 1024}}',
        "stderr_text": None,
        "input_artifact_sha256": "ab" * 32,
    }
    values.update(overrides)
    return TSDuckCallRecord(**values)


@pytest.fixture
def harness(api_client, tmp_path):
    stack = build_production_app(db_path=tmp_path / "calls.sqlite3")
    built = api_client.build(stack.app)
    with built.client:
        yield built, stack
    stack.close()


@pytest.fixture
def client(harness):
    built, _ = harness
    return built


class TestNineFieldContract:
    def test_each_wire_field_carries_the_record_value(self, client, harness):
        """The approved §4.8 table, field-for-field: version /
        executable_path / argv / started_at_utc_ms / finished_at_utc_ms /
        exit_code / stdout_text / stderr_text / input_artifact_sha256 (+
        the optional run_id association)."""
        _, stack = harness
        stack.tsduck_call_store.record(_row(record_id="only"))
        rows = client.get(f"/api/v1/sessions/{SESSION}/tsduck/calls").json()
        assert len(rows) == 1
        assert set(rows[0].keys()) == {
            "version",
            "executable_path",
            "argv",
            "started_at_utc_ms",
            "finished_at_utc_ms",
            "exit_code",
            "stdout_text",
            "stderr_text",
            "input_artifact_sha256",
            "run_id",
        }
        assert rows[0]["version"] == "3.40"
        assert rows[0]["executable_path"].endswith("tsp.exe")
        assert rows[0]["argv"] == ["tsp", "-I", "null", "-O", "null"]
        assert rows[0]["started_at_utc_ms"] == 1_700_000_000_000
        assert rows[0]["finished_at_utc_ms"] == 1_700_000_001_000
        assert rows[0]["exit_code"] == 0
        assert rows[0]["stdout_text"] == '{"ts": {"bytes": 1024}}'
        assert rows[0]["stderr_text"] is None
        assert rows[0]["input_artifact_sha256"] == "ab" * 32
        assert rows[0]["run_id"] == "run-1"

    def test_failure_path_fields_are_explicit_null(self, client, harness):
        """SPEC-308 §7 no-fabrication: a spawn-failure record carries
        explicit nulls — exit_code/stdout/stderr never get invented
        values on the wire."""
        _, stack = harness
        stack.tsduck_call_store.record(
            _row(
                record_id="spawn-failure",
                version=None,
                executable_path=None,
                exit_code=None,
                stdout_text=None,
                stderr_text=None,
                input_artifact_sha256=None,
                run_id=None,
            )
        )
        rows = client.get(f"/api/v1/sessions/{SESSION}/tsduck/calls").json()
        assert rows[0]["exit_code"] is None
        assert rows[0]["stdout_text"] is None
        assert rows[0]["stderr_text"] is None
        assert rows[0]["run_id"] is None


class TestListSemantics:
    def test_ordered_by_started_at_utc_ms_asc(self, client, harness):
        _, stack = harness
        stack.tsduck_call_store.record(_row(record_id="late", started_at_utc_ms=2_000))
        stack.tsduck_call_store.record(_row(record_id="early", started_at_utc_ms=1_000))
        rows = client.get(f"/api/v1/sessions/{SESSION}/tsduck/calls").json()
        assert [row["argv"] == ["tsp", "-I", "null", "-O", "null"] for row in rows]
        assert [row["started_at_utc_ms"] for row in rows] == [1_000, 2_000]

    def test_run_id_filter(self, client, harness):
        _, stack = harness
        stack.tsduck_call_store.record(_row(record_id="r1", run_id="run-1"))
        stack.tsduck_call_store.record(_row(record_id="r2", run_id="run-2"))
        rows = client.get(
            f"/api/v1/sessions/{SESSION}/tsduck/calls?run_id=run-2"
        ).json()
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run-2"

    def test_session_scoping(self, client, harness):
        _, stack = harness
        stack.tsduck_call_store.record(_row(record_id="mine"))
        stack.tsduck_call_store.record(
            _row(record_id="theirs", session_id=OTHER_SESSION)
        )
        rows = client.get(f"/api/v1/sessions/{SESSION}/tsduck/calls").json()
        assert [row["run_id"] for row in rows] == ["run-1"]

    def test_unknown_session_is_404_diagnoses_semantics(self, client):
        response = client.get("/api/v1/sessions/no-such-session/tsduck/calls")
        assert response.status_code == 404
        assert (
            response.json()["error"]["error_code"] == "SIM_SESSION_NOT_FOUND"
        )

    def test_known_empty_session_answers_200_empty(self, client, harness):
        """A session with journal events (a real created session) but no
        stored call records answers 200 [] — the diagnoses existence
        distinction (rows empty AND journal empty → 404). The session
        events commit on the driver face (drain_gateway), the #58 pump
        discipline."""
        _, stack = harness
        created = client.post(
            "/api/v1/sessions", json={"topology_id": "topo-1", "seed": 7}
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        stack.drain_gateway()
        assert stack.journal.max_seq(session_id) > 0
        rows = client.get(f"/api/v1/sessions/{session_id}/tsduck/calls").json()
        assert rows == []


class TestUnboundComposition:
    def test_unbound_rest_stack_keeps_the_501_freeze_answer(self, api_client, tmp_path):
        from rest_stack import build_rest_stack

        built = api_client.build(build_rest_stack(tmp_path).app)
        with built.client:
            response = built.get("/api/v1/sessions/s-1/tsduck/calls")
        assert response.status_code == 501
        assert response.json()["error"]["error_code"] == "HTTP_501"
