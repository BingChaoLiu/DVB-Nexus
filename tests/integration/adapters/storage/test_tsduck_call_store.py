"""``SqliteTSDuckCallStore`` — SPEC-308 §7 nine-field call-record storage
(ticket #80, REQ-API-500-008).

Migration ``0004_tsduck_calls.sql`` (additive CREATE TABLE — the 002/003
precedent; the SPEC-502 §4 frozen tables stay untouched). Wire/storage
encoding contract pinned here at RAW-SQL level:

- nine SPEC-308 §7 fields + the optional ``run_id`` association + the
  REST scoping key ``session_id`` and a ``record_id`` PK;
- ``started_at_utc_ms`` / ``finished_at_utc_ms`` epoch-ms INTEGER (R8;
  the adapter's epoch-second floats ×1000 at the write seam);
- ``argv_json`` JSON TEXT (the diagnoses list-columns precedent);
  failure-path fields carry explicit NULL (the adapter's no-fabrication
  rule).

The production stack makes no real TSDuck calls (MVP, 裁定 E item 3) —
this store's write face is exercised by tests / future emission wiring;
the read face backs ``GET /sessions/{id}/tsduck/calls``.
"""

import json

import pytest

from adapters.storage.db import connect
from adapters.storage.tsduck_calls import TSDuckCallRecord, SqliteTSDuckCallStore


def _record(**overrides) -> TSDuckCallRecord:
    values = dict(
        record_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        session_id="sess-ts-1",
        run_id="run-ts-1",
        version="3.40",
        executable_path="C:/Program Files/TSDuck/bin/tsp.exe",
        argv=("tsp", "-I", "dvb", "-O", "file"),
        started_at_utc_ms=1_700_000_000_000,
        finished_at_utc_ms=1_700_000_001_500,
        exit_code=0,
        stdout_text='{"ts": {"bytes": 1024}}',
        stderr_text="GBK stderr displayed verbatim",
        input_artifact_sha256="ab" * 32,
    )
    values.update(overrides)
    return TSDuckCallRecord(**values)


@pytest.fixture
def store(journal):
    connection = connect(journal.db_path)
    return SqliteTSDuckCallStore(connection), connection


class TestRecordAndQuery:
    def test_round_trip_nine_fields_plus_run_id(self, store):
        store, _ = store
        store.record(_record())
        rows = store.query("sess-ts-1")
        assert rows == [_record()]

    def test_failure_path_fields_stay_explicit_null(self, store):
        """SPEC-308 §7 / adapter no-fabrication rule: spawn-failure rows
        carry NULL exit/stdout — never fabricated values."""
        store, _ = store
        store.record(
            _record(
                exit_code=None,
                stdout_text=None,
                stderr_text=None,
                input_artifact_sha256=None,
                run_id=None,
            )
        )
        stored = store.query("sess-ts-1")[0]
        assert stored.exit_code is None
        assert stored.stdout_text is None
        assert stored.stderr_text is None
        assert stored.input_artifact_sha256 is None
        assert stored.run_id is None

    def test_query_ordered_by_started_at_utc_ms(self, store):
        store, _ = store
        store.record(_record(record_id="r-late", started_at_utc_ms=2_000))
        store.record(_record(record_id="r-early", started_at_utc_ms=1_000))
        rows = store.query("sess-ts-1")
        assert [row.record_id for row in rows] == ["r-early", "r-late"]

    def test_run_id_filter(self, store):
        store, _ = store
        store.record(_record(record_id="r-1", run_id="run-1"))
        store.record(_record(record_id="r-2", run_id="run-2"))
        rows = store.query("sess-ts-1", run_id="run-2")
        assert [row.record_id for row in rows] == ["r-2"]

    def test_session_scoping(self, store):
        store, _ = store
        store.record(_record(record_id="mine"))
        store.record(_record(record_id="theirs", session_id="other-session"))
        assert [row.record_id for row in store.query("sess-ts-1")] == ["mine"]
        assert store.query("other-session")[0].record_id == "theirs"

    def test_unknown_session_empty_list(self, store):
        store, _ = store
        assert store.query("no-such-session") == []


class TestRawRowEncoding:
    def test_r8_epoch_ms_integer_and_argv_json_text(self, store):
        store, connection = store
        store.record(_record())
        raw = connection.execute(
            "SELECT started_at_utc_ms, finished_at_utc_ms, argv_json,"
            " exit_code FROM tsduck_calls WHERE record_id = '3f2504e0-4f89"
            "-11d3-9a0c-0305e82c3301'"
        ).fetchone()
        assert isinstance(raw["started_at_utc_ms"], int)
        assert isinstance(raw["finished_at_utc_ms"], int)
        assert json.loads(raw["argv_json"]) == list(_record().argv)
        assert isinstance(raw["exit_code"], int)
