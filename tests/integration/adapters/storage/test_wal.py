"""WAL mode and foreign_keys pragmas (SPEC-502 section 3).

Seam (delegator-approved): the pragma state is observable via
``PRAGMA journal_mode`` / ``PRAGMA foreign_keys`` on a file-backed database
after ``db.connect``. File-backed on purpose — WAL is a persistent property of
the database file and this verifies it works on Windows paths.
"""

import sqlite3
from pathlib import Path

import pytest

from adapters.storage import db


def test_connect_enables_wal_on_file_database(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


def test_wal_persists_for_a_second_connection(tmp_path: Path) -> None:
    first = db.connect(tmp_path / "db.sqlite3")
    first.close()
    second = db.connect(tmp_path / "db.sqlite3")
    try:
        assert second.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        second.close()


def test_connect_enables_foreign_keys(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_keys_are_enforced_against_declared_fk(tmp_path: Path) -> None:
    """The single declared FK (runs.session_id -> sessions, SPEC-502 §4) must
    actually block orphan runs with foreign_keys=ON."""
    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO sessions (session_id, topology_id, topology_revision, deterministic,"
            " clock_config_json, resource_limits_json, lifecycle_state, revision,"
            " virtual_time_ns, created_at_utc, updated_at_utc)"
            " VALUES ('sess-1', 'topo-1', 1, 1, '{}', '{}', 'created', 0, 0,"
            " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO runs (run_id, session_id, topology_id, topology_revision,"
                " sequence_number, mode, fidelity, started_at_utc_ms, status)"
                " VALUES ('run-orphan', 'no-such-session', 'topo-1', 1, 0,"
                " 'sandbox', 'SIM_STATE', 1, 'created')"
            )
    finally:
        conn.close()
