"""Schema v1 fidelity against the SPEC-502 section 4 frozen tables.

Seam (delegator-approved): after the packaged migration, introspect
``PRAGMA table_info`` / ``sqlite_master`` / ``PRAGMA foreign_key_list`` and
compare against expected literals typed by hand from the spec text — the test
is the independent truth source, NOT generated from the DDL.

Interpretations R1..R8/R11 referenced below are recorded in
``.scratch/task-23/IMPLEMENTATION_PLAN.md`` section 7.
"""

import sqlite3
from pathlib import Path

from adapters.storage import db

# (name, declared_type, notnull, pk_position) — literals from SPEC-502 §4.
EXPECTED_COLUMNS: dict[str, list[tuple[str, str, int, int]]] = {
    # "(topology_id, revision) 复合唯一；spec_json…；created_at_utc / updated_at_utc"
    # R6: *_utc timestamps are ISO-8601 TEXT. R7: composite uniqueness = PK.
    "topologies": [
        ("topology_id", "TEXT", 1, 1),
        ("revision", "INTEGER", 1, 2),
        ("spec_json", "TEXT", 1, 0),
        ("created_at_utc", "TEXT", 1, 0),
        ("updated_at_utc", "TEXT", 1, 0),
    ],
    # "session_id PK（uuid4）；topology_id + topology_revision；seed；deterministic；
    #  clock_config_json；resource_limits_json；lifecycle_state；revision；
    #  scenario_json（nullable）；时间戳" — R5 adds virtual_time_ns (§5
    #  update_state protocol), R6 names the "时间戳" columns.
    "sessions": [
        ("session_id", "TEXT", 1, 1),
        ("topology_id", "TEXT", 1, 0),
        ("topology_revision", "INTEGER", 1, 0),
        ("seed", "INTEGER", 0, 0),
        ("deterministic", "INTEGER", 1, 0),
        ("clock_config_json", "TEXT", 1, 0),
        ("resource_limits_json", "TEXT", 1, 0),
        ("lifecycle_state", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0),
        ("virtual_time_ns", "INTEGER", 1, 0),
        ("scenario_json", "TEXT", 0, 0),
        ("created_at_utc", "TEXT", 1, 0),
        ("updated_at_utc", "TEXT", 1, 0),
    ],
    # "run_id PK（uuid4）；session_id FK；RunContext 全字段（mode/fidelity/
    #  started_at_utc_ms/generator_version/config_hash/seed）；status；
    #  ended_at_utc_ms" — R1: 全字段 read literally = every RunContext field
    #  (domain/observation/run_context.py field order), else a row could not
    #  reconstruct its RunContext.
    "runs": [
        ("run_id", "TEXT", 1, 1),
        ("session_id", "TEXT", 1, 0),
        ("topology_id", "TEXT", 1, 0),
        ("topology_revision", "INTEGER", 1, 0),
        ("sequence_number", "INTEGER", 1, 0),
        ("mode", "TEXT", 1, 0),
        ("fidelity", "TEXT", 1, 0),
        ("started_at_utc_ms", "INTEGER", 1, 0),
        ("generator_version", "TEXT", 0, 0),
        ("config_hash", "TEXT", 0, 0),
        ("seed", "INTEGER", 0, 0),
        ("status", "TEXT", 1, 0),
        ("ended_at_utc_ms", "INTEGER", 0, 0),
    ],
    # "(session_id, journal_seq) 复合 PK；event_type / severity / producer_id
    #  查询列展开；envelope_json 全量单列（权威内容）" — R2: event_id column is
    #  materialized because the (producer_id, event_id) unique index needs it.
    "events": [
        ("session_id", "TEXT", 1, 1),
        ("journal_seq", "INTEGER", 1, 2),
        ("event_type", "TEXT", 1, 0),
        ("severity", "TEXT", 1, 0),
        ("producer_id", "TEXT", 1, 0),
        ("event_id", "TEXT", 1, 0),
        ("envelope_json", "TEXT", 1, 0),
    ],
    # "artifact_id PK（uuid4）；sha256（非唯一）；kind；relative_path；byte_size；
    #  packet_size / packet_count / generator_version / config_hash /
    #  fault_profile_ids_json；run_id / session_id；created_at_utc_ms"
    "artifacts": [
        ("artifact_id", "TEXT", 1, 1),
        ("sha256", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0),
        ("relative_path", "TEXT", 1, 0),
        ("byte_size", "INTEGER", 1, 0),
        ("packet_size", "INTEGER", 0, 0),
        ("packet_count", "INTEGER", 0, 0),
        ("generator_version", "TEXT", 0, 0),
        ("config_hash", "TEXT", 0, 0),
        ("fault_profile_ids_json", "TEXT", 0, 0),
        ("run_id", "TEXT", 1, 0),
        ("session_id", "TEXT", 1, 0),
        ("created_at_utc_ms", "INTEGER", 1, 0),
    ],
    # "diagnosis_id PK（uuid4）；session_id / run_id；rule_id + rule_version；
    #  code；severity；confidence（三档枚举）；observation_refs_json；
    #  affected_node_ids_json；suggested_actions_json；state；raised_at /
    #  cleared_at" — R8: raised_at/cleared_at are epoch-ms INTEGER.
    "diagnoses": [
        ("diagnosis_id", "TEXT", 1, 1),
        ("session_id", "TEXT", 1, 0),
        ("run_id", "TEXT", 1, 0),
        ("rule_id", "TEXT", 1, 0),
        ("rule_version", "TEXT", 1, 0),
        ("code", "TEXT", 1, 0),
        ("severity", "TEXT", 1, 0),
        ("confidence", "TEXT", 1, 0),
        ("observation_refs_json", "TEXT", 1, 0),
        ("affected_node_ids_json", "TEXT", 1, 0),
        ("suggested_actions_json", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("raised_at", "INTEGER", 1, 0),
        ("cleared_at", "INTEGER", 0, 0),
    ],
    # "alert-record.schema.json 全字段（alert_id PK、fingerprint、rule_id、state
    #  五态、severity、scope、time、evidence_refs_json、suppression_json）"
    #  R8: 全字段 read literally → all 11 alert-record.schema.json fields
    #  (adds rule_version, summary beyond the parenthetical); object/list
    #  fields stored as JSON TEXT with the §4 text's own _json convention.
    "alerts": [
        ("alert_id", "TEXT", 1, 1),
        ("fingerprint", "TEXT", 1, 0),
        ("rule_id", "TEXT", 1, 0),
        ("rule_version", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("severity", "TEXT", 1, 0),
        ("scope", "TEXT", 1, 0),
        ("time", "TEXT", 1, 0),
        ("summary", "TEXT", 0, 0),
        ("evidence_refs_json", "TEXT", 1, 0),
        ("suppression_json", "TEXT", 0, 0),
    ],
}


def _migrated_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "db.sqlite3")
    db.migrate(conn)
    return conn


def test_fresh_database_reaches_schema_v1(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.migrate(conn) == 1  # one-click upgrade, REQ-PLT-502-001
    finally:
        conn.close()
    # Version state is durable across connections.
    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_all_frozen_tables_exist(tmp_path: Path) -> None:
    conn = _migrated_conn(tmp_path)
    try:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert set(EXPECTED_COLUMNS) <= names
    finally:
        conn.close()


def test_column_literals_match_spec(tmp_path: Path) -> None:
    conn = _migrated_conn(tmp_path)
    try:
        for table, expected in EXPECTED_COLUMNS.items():
            actual = [
                (row["name"], row["type"], row["notnull"], row["pk"])
                for row in conn.execute(f"PRAGMA table_info({table})")
            ]
            assert actual == expected, f"table {table} diverges from SPEC-502 §4"
    finally:
        conn.close()


def test_events_indexes_per_spec(tmp_path: Path) -> None:
    """§4: (producer_id, event_id) 部分唯一索引; §8: event_type 上索引供过滤查询."""
    conn = _migrated_conn(tmp_path)
    try:
        indexes = [
            (row["name"], row["sql"] or "")
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'events'"
            )
        ]
        unique = [(name, sql) for name, sql in indexes if "UNIQUE" in sql.upper()]
        assert len(unique) == 1, "events must carry exactly one unique index (the dedup pair)"
        name, sql = unique[0]
        assert "producer_id" in sql and "event_id" in sql
        assert "WHERE" in sql.upper(), "the dedup index is a partial unique index (R3)"
        non_unique = [sql for _, sql in indexes if "UNIQUE" not in sql.upper()]
        assert any("event_type" in sql for sql in non_unique), "event_type filter index missing"
    finally:
        conn.close()


def test_artifacts_sha256_is_deliberately_not_unique(tmp_path: Path) -> None:
    """§4: sha256 非唯一 — 同内容可被多个 run 引用."""
    conn = _migrated_conn(tmp_path)
    try:
        indexes = [
            row["sql"] or ""
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'artifacts'"
            )
        ]
        assert not any("UNIQUE" in sql.upper() for sql in indexes)
        conn.execute(
            "INSERT INTO artifacts (artifact_id, sha256, kind, relative_path, byte_size,"
            " run_id, session_id, created_at_utc_ms)"
            " VALUES ('a1', 'samehash', 'generated_ts', 'p/one.ts', 1, 'r1', 's1', 1),"
            " ('a2', 'samehash', 'generated_ts', 'p/two.ts', 2, 'r1', 's1', 2)"
        )
        count = conn.execute("SELECT COUNT(*) FROM artifacts WHERE sha256 = 'samehash'").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_runs_session_fk_and_no_undeclared_fks(tmp_path: Path) -> None:
    """§4 names exactly one FK (runs.session_id FK); R11: no FK where §4 is silent."""
    conn = _migrated_conn(tmp_path)
    try:
        runs_fk = list(conn.execute("PRAGMA foreign_key_list(runs)"))
        assert [(row["from"], row["table"], row["to"]) for row in runs_fk] == [
            ("session_id", "sessions", "session_id")
        ]
        for table in ("events", "artifacts", "diagnoses", "alerts", "sessions", "topologies"):
            assert list(conn.execute(f"PRAGMA foreign_key_list({table})")) == []
    finally:
        conn.close()
