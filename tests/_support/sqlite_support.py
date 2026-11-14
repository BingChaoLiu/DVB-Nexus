"""SQLite support for the ``journal`` fixture (SPEC-505 §4 → SPEC-502).

Provides the fixture-level infrastructure SPEC-502 mandates:

- pragma policy: WAL journal mode + ``foreign_keys=ON`` on every connection;
- numbered ``NNN_*.sql`` migrations applied pending-only inside a single
  explicit transaction, stamping ``PRAGMA user_version`` with the highest
  applied number (idempotent on re-run).

Seam note (ticket #22 report): the production migration runner belongs to
the SPEC-502 adapter implementation (``adapters/storage``); this module is
the test-side generic applier so ``journal`` already behaves per SPEC-502
against whatever ``migrations/`` tree exists. When the SPEC-502 ticket
lands, its runner replaces/feeds this seam (fixture 参数/默认目录已对齐
SPEC-502 §11 建议落点 ``src/adapters/storage/migrations``).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from tests._support.paths import repo_root

#: SPEC-502 migration file naming: sequential numeric prefix (§5 pattern
#: "NNN_*.sql"; the §11 example "migrations/0001_init.sql" uses four digits,
#: so any ≥3-digit zero-padded prefix is accepted and numeric order enforced).
_MIGRATION_NAME = re.compile(r"^(\d{3,})_[A-Za-z0-9_-]+\.sql$")

#: Default migrations home (SPEC-502 §11 建议文件: adapters/storage/migrations).
DEFAULT_MIGRATIONS_SUBPATH = ("src", "adapters", "storage", "migrations")


def default_migrations_dir() -> Path | None:
    """SPEC-502 suggested migrations home if it exists, else ``None``."""
    candidate = repo_root().joinpath(*DEFAULT_MIGRATIONS_SUBPATH)
    return candidate if candidate.is_dir() else None


def _migration_files(migrations_dir: Path) -> list[tuple[int, Path, str]]:
    """Parse and strictly order the migration scripts in ``migrations_dir``."""
    entries: list[tuple[int, Path]] = []
    for path in migrations_dir.iterdir():
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            raise ValueError(
                f"unexpected file in migrations dir {migrations_dir}: {path.name} "
                f"(expected NNN_name.sql per SPEC-502)"
            )
        entries.append((int(match.group(1)), path))
    entries.sort(key=lambda entry: entry[0])
    scripts: list[tuple[int, Path, str]] = []
    for position, (number, path) in enumerate(entries):
        expected = position + 1
        if number != expected:
            raise ValueError(
                f"migration numbering gap: expected {expected:03d} at position "
                f"{position}, found {number:03d} ({path.name})"
            )
        scripts.append((number, path, path.read_text(encoding="utf-8")))
    return scripts


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into complete statements.

    ``sqlite3.complete_statement`` understands string literals containing
    ``;`` and trigger ``BEGIN...END`` bodies. Note: ``executescript`` cannot
    be used here — CPython commits any open transaction before running a
    script, which would break the single-transaction envelope.
    """
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            text = buffer.strip()
            if text:
                statements.append(text)
            buffer = ""
    tail = buffer.strip()
    if tail:
        statements.append(tail)
    return statements


def apply_sql_migrations(
    connection: sqlite3.Connection, migrations_dir: Path
) -> int:
    """Apply pending ``NNN_*.sql`` migrations in one explicit transaction.

    Returns the resulting ``user_version``. Idempotent: scripts numbered
    ≤ current ``user_version`` are skipped. The connection is used in
    autocommit mode (``isolation_level=None``) so the explicit
    ``BEGIN IMMEDIATE`` / ``COMMIT`` envelope is the only transaction
    boundary (SPEC-502: 启动时在单事务内执行未应用脚本).
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations dir not found: {directory}")

    scripts = _migration_files(directory)
    if not scripts:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])

    saved_isolation = connection.isolation_level
    connection.isolation_level = None  # explicit transaction control
    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        pending = [(number, sql) for number, _path, sql in scripts if number > current]
        if not pending:
            return current
        connection.execute("BEGIN IMMEDIATE")
        try:
            for number, sql in pending:
                for statement in _split_statements(sql):
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {number}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.isolation_level = saved_isolation


def apply_pragma_policy(connection: sqlite3.Connection) -> sqlite3.Connection:
    """SPEC-502 pragma policy for journal connections: WAL + foreign_keys."""
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class JournalHandle:
    """Handle yielded by the ``journal`` fixture."""

    def __init__(self, db_path: Path, migrations_dir: Path | None) -> None:
        self.db_path = Path(db_path)
        self.root = self.db_path.parent
        self.migrations_dir = migrations_dir
        self._open_connections: list[sqlite3.Connection] = []
        self._migrated = False

    def connect(self) -> sqlite3.Connection:
        """Open a connection with the SPEC-502 pragma policy applied."""
        if not self._migrated:
            self.migrate()
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        apply_pragma_policy(connection)
        self._open_connections.append(connection)
        return connection

    def migrate(self) -> int:
        """Apply pending migrations (no-op when no migrations dir exists)."""
        if self.migrations_dir is not None:
            bootstrap = sqlite3.connect(self.db_path, isolation_level=None)
            try:
                apply_sql_migrations(bootstrap, self.migrations_dir)
            finally:
                bootstrap.close()
        self._migrated = True
        return self.user_version()

    def user_version(self) -> int:
        bootstrap = sqlite3.connect(self.db_path)
        try:
            return int(bootstrap.execute("PRAGMA user_version").fetchone()[0])
        finally:
            bootstrap.close()

    def close_all(self) -> None:
        """Close connections opened through this handle (fixture teardown)."""
        for connection in self._open_connections:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.ProgrammingError:  # already closed by test
                    pass
        self._open_connections.clear()
