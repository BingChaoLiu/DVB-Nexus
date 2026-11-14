"""``journal`` fixture behavior (SPEC-505 §4, serving SPEC-502).

Integration layer: real tmp SQLite file resources. Chosen file-DB over
in-memory per SPEC-505 §4 "二选一实现期定" — WAL and migration semantics
are only observable on a file database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._support.paths import repo_root
from tests._support.sqlite_support import apply_sql_migrations

_MIGRATIONS_ENV = "DVB_NEXUS_TEST_JOURNAL_MIGRATIONS"


class TestJournalPragmaPolicy:
    def test_db_file_created_under_tmp_path(self, journal):
        assert journal.db_path.exists()
        assert journal.db_path.parent == journal.root

    def test_wal_mode_active(self, journal):
        connection = journal.connect()
        try:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            connection.close()
        assert mode.lower() == "wal"

    def test_foreign_keys_on_every_connection(self, journal):
        first = journal.connect()
        second = journal.connect()
        try:
            for connection in (first, second):
                enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
                assert enabled == 1
        finally:
            first.close()
            second.close()


class TestJournalMigrations:
    @pytest.fixture
    def journal_migrations_dir(self, tmp_path: Path) -> Path:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "0001_init.sql").write_text(
            "CREATE TABLE probe (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
        )
        (migrations / "0002_add_column.sql").write_text(
            "ALTER TABLE probe ADD COLUMN note TEXT;\n", encoding="utf-8"
        )
        return migrations

    def test_pending_migrations_applied_and_version_stamped(self, journal):
        connection = journal.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(probe)").fetchall()
            }
        finally:
            connection.close()
        assert version == 2
        assert {"id", "note"} <= columns

    def test_migrate_is_idempotent(self, journal):
        journal.migrate()
        journal.migrate()
        connection = journal.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        finally:
            connection.close()
        assert version == 2

    def test_default_migrations_dir_is_spec502_home_if_present(self):
        default = repo_root() / "src" / "adapters" / "storage" / "migrations"
        from tests._support.sqlite_support import default_migrations_dir

        resolved = default_migrations_dir()
        if default.is_dir():
            assert resolved == default
        else:
            assert resolved is None


class TestJournalIsolation:
    def test_each_test_gets_a_fresh_database(self, journal):
        connection = journal.connect()
        try:
            connection.execute("CREATE TABLE marker (x INTEGER)")
            connection.commit()
        finally:
            connection.close()

    def test_previous_test_table_is_gone(self, journal):
        connection = journal.connect()
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            connection.close()
        assert "marker" not in names


class TestMigrationApplier:
    def test_out_of_order_and_non_numbered_files_rejected(self, tmp_path: Path):
        migrations = tmp_path / "m"
        migrations.mkdir()
        (migrations / "10_late.sql").write_text("SELECT 1;\n", encoding="utf-8")
        (migrations / "readme.txt").write_text("not sql\n", encoding="utf-8")
        connection = sqlite3.connect(":memory:")
        try:
            with pytest.raises(ValueError):
                apply_sql_migrations(connection, migrations)
        finally:
            connection.close()

    def test_gap_in_numbering_rejected(self, tmp_path: Path):
        migrations = tmp_path / "m"
        migrations.mkdir()
        (migrations / "0001_a.sql").write_text("SELECT 1;\n", encoding="utf-8")
        (migrations / "0003_c.sql").write_text("SELECT 2;\n", encoding="utf-8")
        connection = sqlite3.connect(":memory:")
        try:
            with pytest.raises(ValueError):
                apply_sql_migrations(connection, migrations)
        finally:
            connection.close()
