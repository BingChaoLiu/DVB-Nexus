"""Run/Artifact repository semantics (SPEC-502 sections 4-5, §9 CRUD).

Seams (delegator-approved): the repository public API plus stored-row
inspection (the delegator's seam list explicitly includes "stamped seq
observable via returned value + stored row"; runs have no read API in the §5
protocol, so row inspection is the agreed observation point). Domain models
(``RunContext``, ``TSArtifact``) are consumed read-only — ticket #21 owns them.

Runs carry the one FK SPEC-502 §4 declares (runs.session_id -> sessions), so
the fixture seeds a parent session row with raw SQL — tests may touch SQL
directly; the API/Application layers may not (REQ-PLT-502-006).
"""

import json
import sqlite3

import pytest

from adapters.storage import db
from adapters.storage.errors import StorageConflictError
from adapters.storage.repositories import (
    ArtifactMeta,
    ArtifactRow,
    SqliteArtifactRepository,
    SqliteRunRepository,
)
from domain.observation.artifact import ArtifactKind, TSArtifact
from domain.observation.run_context import Fidelity, RunContext, RunMode


def _migrated_conn() -> sqlite3.Connection:
    conn = db.connect(":memory:")
    db.migrate(conn)
    return conn


def _seed_session(conn: sqlite3.Connection, session_id: str = "sess-1") -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, topology_id, topology_revision, seed, deterministic,"
        " clock_config_json, resource_limits_json, lifecycle_state, revision, virtual_time_ns,"
        " scenario_json, created_at_utc, updated_at_utc)"
        " VALUES (?, 'topo-1', 3, 42, 1, '{}', '{}', 'created', 0, 0, NULL,"
        " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (session_id,),
    )


def _run_context(session_id: str = "sess-1", run_id: str = "run-1") -> RunContext:
    return RunContext(
        run_id=run_id,
        session_id=session_id,
        topology_id="topo-1",
        topology_revision=3,
        sequence_number=7,
        mode=RunMode.SANDBOX,
        fidelity=Fidelity.SIM_STATE,
        started_at_utc_ms=1_700_000_000_000,
        generator_version="ts-core-0.1.0",
        config_hash="abc123",
        seed=42,
    )


def _run_row(conn: sqlite3.Connection, run_id: str = "run-1") -> sqlite3.Row:
    return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()


# --- RunRepository (SPEC-502 §5 runs protocol) -------------------------------


def test_create_stores_every_run_context_field() -> None:
    """R1: 'RunContext 全字段' — a row stores all RunContext fields so the
    model can be reconstructed; plus status (R9: 'created') and NULL ended."""
    conn = _migrated_conn()
    try:
        _seed_session(conn)
        repo = SqliteRunRepository(conn)
        repo.create(_run_context())
        row = _run_row(conn)
        assert row["run_id"] == "run-1"
        assert row["session_id"] == "sess-1"
        assert row["topology_id"] == "topo-1"
        assert row["topology_revision"] == 3
        assert row["sequence_number"] == 7
        assert row["mode"] == "sandbox"
        assert row["fidelity"] == "SIM_STATE"
        assert row["started_at_utc_ms"] == 1_700_000_000_000
        assert row["generator_version"] == "ts-core-0.1.0"
        assert row["config_hash"] == "abc123"
        assert row["seed"] == 42
        assert row["status"] == "created"
        assert row["ended_at_utc_ms"] is None
    finally:
        conn.close()


def test_finish_sets_status_and_ended_at() -> None:
    conn = _migrated_conn()
    try:
        _seed_session(conn)
        repo = SqliteRunRepository(conn)
        repo.create(_run_context())
        repo.finish("run-1", status="completed", ended_at_utc_ms=1_700_000_060_000)
        row = _run_row(conn)
        assert row["status"] == "completed"
        assert row["ended_at_utc_ms"] == 1_700_000_060_000
    finally:
        conn.close()


def test_create_with_unknown_session_is_a_conflict() -> None:
    """SPEC-502 §7 row 3: constraint conflict outside the dedup path -> the
    409-mapped storage error (here: the declared FK)."""
    conn = _migrated_conn()
    try:
        repo = SqliteRunRepository(conn)
        with pytest.raises(StorageConflictError):
            repo.create(_run_context(session_id="no-such-session"))
        assert _run_row(conn) is None
    finally:
        conn.close()


def test_finish_unknown_run_raises_lookup_error() -> None:
    """R10: spec defines no not-found semantics; a missing run is a caller
    bug surfaced as LookupError."""
    conn = _migrated_conn()
    try:
        repo = SqliteRunRepository(conn)
        with pytest.raises(LookupError):
            repo.finish("ghost-run", status="completed", ended_at_utc_ms=1)
    finally:
        conn.close()


# --- ArtifactRepository (SPEC-502 §5 artifacts protocol) ---------------------


def _ts_artifact(artifact_id: str = "art-1", run_id: str = "run-1") -> TSArtifact:
    return TSArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        kind=ArtifactKind.GENERATED_TS,
        relative_path="runs/run-1/stream.ts",
        packet_size=188,
        packet_count=1000,
        byte_size=188_000,
        sha256="deadbeef",
        generator_version="ts-core-0.1.0",
        config_hash="abc123",
        fault_profile_ids=["fault-1", "fault-2"],
        created_at_utc_ms=1_700_000_000_000,
    )


def _artifact_repo(conn: sqlite3.Connection) -> SqliteArtifactRepository:
    return SqliteArtifactRepository(conn)


def test_register_stores_artifact_with_session_id() -> None:
    """§4 stores run_id / session_id; ArtifactMeta composes TSArtifact (no
    session_id on the domain model) with the owning session."""
    conn = _migrated_conn()
    try:
        repo = _artifact_repo(conn)
        repo.register(ArtifactMeta(artifact=_ts_artifact(), session_id="sess-1"))
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = 'art-1'").fetchone()
        assert row["artifact_id"] == "art-1"
        assert row["sha256"] == "deadbeef"
        assert row["kind"] == "generated_ts"
        assert row["relative_path"] == "runs/run-1/stream.ts"
        assert row["byte_size"] == 188_000
        assert row["packet_size"] == 188
        assert row["packet_count"] == 1000
        assert row["generator_version"] == "ts-core-0.1.0"
        assert row["config_hash"] == "abc123"
        assert json.loads(row["fault_profile_ids_json"]) == ["fault-1", "fault-2"]
        assert row["run_id"] == "run-1"
        assert row["session_id"] == "sess-1"
        assert row["created_at_utc_ms"] == 1_700_000_000_000
    finally:
        conn.close()


def test_register_optional_fields_stay_null() -> None:
    conn = _migrated_conn()
    try:
        repo = _artifact_repo(conn)
        minimal = TSArtifact(
            artifact_id="art-min",
            run_id="run-1",
            kind=ArtifactKind.REPORT,
            relative_path="runs/run-1/report.md",
            byte_size=10,
            sha256="cafebabe",
            created_at_utc_ms=1,
        )
        repo.register(ArtifactMeta(artifact=minimal, session_id="sess-1"))
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = 'art-min'").fetchone()
        assert row["packet_size"] is None
        assert row["packet_count"] is None
        assert row["generator_version"] is None
        assert row["config_hash"] is None
        assert row["fault_profile_ids_json"] is None
    finally:
        conn.close()


def test_get_returns_row_or_none() -> None:
    conn = _migrated_conn()
    try:
        repo = _artifact_repo(conn)
        repo.register(ArtifactMeta(artifact=_ts_artifact(), session_id="sess-1"))
        row = repo.get("art-1")
        assert isinstance(row, ArtifactRow)
        assert (row.artifact_id, row.sha256, row.kind, row.run_id, row.session_id) == (
            "art-1",
            "deadbeef",
            "generated_ts",
            "run-1",
            "sess-1",
        )
        assert row.fault_profile_ids == ["fault-1", "fault-2"]
        assert repo.get("ghost") is None
    finally:
        conn.close()


def test_find_by_sha256_returns_all_content_matches() -> None:
    """§4: sha256 非唯一 — 同内容可被多个 run 引用."""
    conn = _migrated_conn()
    try:
        repo = _artifact_repo(conn)
        repo.register(ArtifactMeta(artifact=_ts_artifact(artifact_id="art-1"), session_id="sess-1"))
        repo.register(ArtifactMeta(artifact=_ts_artifact(artifact_id="art-2"), session_id="sess-1"))
        repo.register(
            ArtifactMeta(
                artifact=TSArtifact(
                    artifact_id="art-3",
                    run_id="run-1",
                    kind=ArtifactKind.FAULTED_TS,
                    relative_path="runs/run-1/faulted.ts",
                    byte_size=5,
                    sha256="different",
                    created_at_utc_ms=3,
                ),
                session_id="sess-1",
            )
        )
        matches = repo.find_by_sha256("deadbeef")
        assert [row.artifact_id for row in matches] == ["art-1", "art-2"]
        assert repo.find_by_sha256("no-such-hash") == []
    finally:
        conn.close()
