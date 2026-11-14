"""Migration lifecycle (SPEC-502 section 3, REQ-PLT-502-001).

Seam (delegator-approved, public API): ``db.connect`` + ``db.migrate`` over a
file-backed database. ``PRAGMA user_version`` is the spec's migration tracker;
version state is asserted via ``PRAGMA user_version`` directly (that pragma IS
the mechanism per SPEC-502, not an implementation detail).

File-backed on purpose: migration durability across open/close is the behavior
under test, and the tests run on Windows paths via pytest ``tmp_path``.
"""

import sqlite3
from pathlib import Path

import pytest

from adapters.storage import db
from adapters.storage.errors import MigrationError, StorageUnavailableError


def _write_script(directory: Path, name: str, sql: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(sql, encoding="utf-8")


def _user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_migrate_applies_pending_scripts_in_order(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")
    _write_script(scripts, "0002_extra.sql", "CREATE TABLE extra (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert _user_version(conn) == 0
        assert db.migrate(conn, migrations_dir=scripts) == 2
        assert _user_version(conn) == 2
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"sample", "extra"} <= names
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert db.migrate(conn, migrations_dir=scripts) == 1
        assert db.migrate(conn, migrations_dir=scripts) == 1
        assert _user_version(conn) == 1
    finally:
        conn.close()


def test_migrate_resumes_from_partial_version(tmp_path: Path) -> None:
    scripts_v1 = tmp_path / "v1"
    _write_script(scripts_v1, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")
    scripts_v2 = tmp_path / "v2"
    _write_script(scripts_v2, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")
    _write_script(scripts_v2, "0002_extra.sql", "CREATE TABLE extra (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        assert db.migrate(conn, migrations_dir=scripts_v1) == 1
        # Only 0002 is pending now; re-running 0001 would fail if it were applied twice.
        assert db.migrate(conn, migrations_dir=scripts_v2) == 2
        assert _user_version(conn) == 2
    finally:
        conn.close()


def test_migrate_failure_rolls_back_and_fails_fast(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0001_good.sql", "CREATE TABLE good (id INTEGER PRIMARY KEY);")
    _write_script(scripts, "0002_bad.sql", "CREATE TABLE broken (missing_semicolon INTEGER")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        with pytest.raises(MigrationError):
            db.migrate(conn, migrations_dir=scripts)
        # Fail-fast per SPEC-502 section 7: nothing applied, version unchanged.
        assert _user_version(conn) == 0
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "good" not in names
    finally:
        conn.close()


def test_migrate_rejects_database_ahead_of_scripts(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        conn.execute("PRAGMA user_version = 7")
        with pytest.raises(MigrationError):
            db.migrate(conn, migrations_dir=scripts)
    finally:
        conn.close()


def test_migrate_rejects_numbering_gap(tmp_path: Path) -> None:
    # SPEC-502 section 3 "顺序编号脚本": numbering is contiguous from 001.
    # A gap (0001 + 0003, no 0002) is a structural configuration error —
    # fail-fast before any script runs (review-fix #2: enforcement ported
    # from the test-support runner so production and fixture share one
    # policy).
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0001_sample.sql", "CREATE TABLE sample (id INTEGER PRIMARY KEY);")
    _write_script(scripts, "0003_extra.sql", "CREATE TABLE extra (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        with pytest.raises(MigrationError):
            db.migrate(conn, migrations_dir=scripts)
        assert _user_version(conn) == 0
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "sample" not in names and "extra" not in names
    finally:
        conn.close()


def test_migrate_rejects_numbering_not_starting_at_001(tmp_path: Path) -> None:
    # The contiguous sequence starts at 001: a lone 0007 script is a gap at
    # position 0 (same strict policy the fixture applier always enforced).
    scripts = tmp_path / "migrations"
    _write_script(scripts, "0007_late.sql", "CREATE TABLE late (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "db.sqlite3")
    try:
        with pytest.raises(MigrationError):
            db.migrate(conn, migrations_dir=scripts)
    finally:
        conn.close()


def test_connect_raises_unavailable_when_target_cannot_open(tmp_path: Path) -> None:
    # Parent directory does not exist -> sqlite cannot open the file (SPEC-502
    # section 7 "库不可用" surfaces as the 503-mapped storage error).
    with pytest.raises(StorageUnavailableError):
        db.connect(tmp_path / "missing_dir" / "db.sqlite3")
