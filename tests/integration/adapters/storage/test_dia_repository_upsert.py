"""``SqliteDiagnosisRepository`` — SPEC-502 §4/§5 diagnoses-table storage
(ticket #54, REQ-DIA-306-004).

Integration layer: real tmp-file SQLite through the ``journal`` fixture
(WAL + 0001 migrations, SPEC-502 §4 frozen table — no schema changes).
The R3 encoding contract (ticket #23): ``raised_at``/``cleared_at`` are
epoch-ms INTEGER columns; ``observation_refs_json`` /
``affected_node_ids_json`` / ``suggested_actions_json`` are JSON TEXT —
asserted here at RAW-SQL level so the wire encoding cannot drift.
"""

import json

import pytest

from adapters.storage.db import connect
from adapters.storage.repositories import DiagnosisRecord, SqliteDiagnosisRepository


def _record(**overrides) -> DiagnosisRecord:
    """A storage-owned row: plain strings (no domain vocabulary import —
    the adapters layer stays off the indirect domain.diagnosis chains)."""
    values = dict(
        diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        session_id="sess-r1",
        run_id="run-r1",
        rule_id="DIA-PAT-MISSING",
        rule_version="1.0.0",
        code="DIAG_PAT_MISSING",
        severity="error",
        confidence="high",
        observation_refs=[{"journal_seq": 42, "event_type": "ts.psi_section_observed"}],
        affected_node_ids=["mux-0"],
        suggested_actions=["Restore PAT emission on PID 0"],
        state="raised",
        raised_at=1_700_000_000_000,
        cleared_at=None,
    )
    values.update(overrides)
    return DiagnosisRecord(**values)


@pytest.fixture
def repository(journal):
    connection = connect(journal.db_path)
    return SqliteDiagnosisRepository(connection), connection


class TestUpsert:
    def test_insert_and_query_round_trip(self, repository):
        repo, _ = repository
        repo.upsert(_record())
        rows = repo.query("sess-r1")
        assert len(rows) == 1
        stored = rows[0]
        assert stored == _record()

    def test_r3_column_encoding_raw_sql(self, repository):
        """R8/R3: raised_at epoch-ms INTEGER; list columns JSON TEXT."""
        repo, connection = repository
        repo.upsert(_record())
        raw = connection.execute(
            "SELECT raised_at, cleared_at, observation_refs_json,"
            " affected_node_ids_json, suggested_actions_json, state,"
            " severity, confidence FROM diagnoses"
        ).fetchone()
        assert isinstance(raw["raised_at"], int) and raw["raised_at"] > 0
        assert raw["cleared_at"] is None
        assert isinstance(raw["observation_refs_json"], str)
        assert json.loads(raw["observation_refs_json"]) == [
            {"journal_seq": 42, "event_type": "ts.psi_section_observed"}
        ]
        assert json.loads(raw["affected_node_ids_json"]) == ["mux-0"]
        assert json.loads(raw["suggested_actions_json"]) == [
            "Restore PAT emission on PID 0"
        ]
        assert raw["state"] == "raised"
        assert raw["severity"] == "error"
        assert raw["confidence"] == "high"

    def test_upsert_updates_in_place_same_primary_key(self, repository):
        """REQ-DIA-306-004: updated/accumulated candidates UPSERT the same
        row — one diagnoses row per diagnosis_id, never a twin."""
        repo, connection = repository
        repo.upsert(_record())
        accumulated = _record(
            observation_refs=[
                {"journal_seq": 42, "event_type": "ts.psi_section_observed"},
                {"journal_seq": 43, "event_type": "ts.psi_section_observed"},
            ],
        )
        repo.upsert(accumulated)
        count = connection.execute(
            "SELECT COUNT(*) FROM diagnoses"
        ).fetchone()[0]
        assert count == 1
        stored = repo.query("sess-r1")[0]
        assert len(stored.observation_refs) == 2

    def test_invalid_state_is_refused(self, repository):
        repo, _ = repository
        with pytest.raises(ValueError):
            repo.upsert(_record(state="firing"))


class TestClear:
    def test_clear_sets_state_and_cleared_at(self, repository):
        repo, _ = repository
        repo.upsert(_record())
        repo.clear("3f2504e0-4f89-11d3-9a0c-0305e82c3301", cleared_at_utc_ms=1_700_000_050_000)
        stored = repo.query("sess-r1")[0]
        assert stored.state == "cleared"
        assert stored.cleared_at == 1_700_000_050_000

    def test_clear_unknown_id_raises(self, repository):
        repo, _ = repository
        with pytest.raises(LookupError):
            repo.clear("unknown", cleared_at_utc_ms=1)

    def test_cleared_at_stays_epoch_ms_integer(self, repository):
        repo, connection = repository
        repo.upsert(_record())
        repo.clear("3f2504e0-4f89-11d3-9a0c-0305e82c3301", cleared_at_utc_ms=1_700_000_050_000)
        raw = connection.execute(
            "SELECT cleared_at, state FROM diagnoses"
        ).fetchone()
        assert isinstance(raw["cleared_at"], int)
        assert raw["state"] == "cleared"


class TestQuery:
    def test_query_scopes_to_session_and_orders_by_raise_time(self, repository):
        repo, _ = repository
        repo.upsert(_record(raised_at=2_000))
        repo.upsert(_record(diagnosis_id="id-earlier", code="DIAG_A", raised_at=1_000))
        repo.upsert(_record(diagnosis_id="other-session", session_id="sess-r2"))
        rows = repo.query("sess-r1")
        assert [row.raised_at for row in rows] == [1_000, 2_000]
        assert all(row.session_id == "sess-r1" for row in rows)

    def test_query_empty_session_is_empty_list(self, repository):
        repo, _ = repository
        assert repo.query("no-such-session") == []
