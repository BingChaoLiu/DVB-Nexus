"""SQLite support for the ``journal`` fixture (SPEC-505 §4 → SPEC-502).

Provides the fixture-level infrastructure SPEC-502 mandates:

- pragma policy: WAL journal mode + ``foreign_keys=ON`` on every connection;
- numbered ``NNN_*.sql`` migrations applied pending-only inside a single
  explicit transaction, stamping ``PRAGMA user_version`` (idempotent).

Consolidation note (review-fix #2): the formerly duplicated test-side
migration runner (``_migration_files`` / ``_split_statements`` /
``apply_sql_migrations``) is gone — :func:`apply_sql_migrations` is a thin
delegate to the PRODUCTION runner :func:`adapters.storage.db.migrate`
(SPEC-502 §3), which now carries the strict contiguous-numbering
enforcement the test copy pioneered. Production and fixture therefore share
one policy: single transaction, ``user_version`` stamping, numbering gaps
and duplicate prefixes fail fast with :class:`MigrationError`. The fixture
默认目录 remains SPEC-502 §11 建议落点 ``src/adapters/storage/migrations``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from adapters.storage.db import migrate as _production_migrate

from tests._support.paths import repo_root

#: Default migrations home (SPEC-502 §11 建议文件: adapters/storage/migrations).
DEFAULT_MIGRATIONS_SUBPATH = ("src", "adapters", "storage", "migrations")


def default_migrations_dir() -> Path | None:
    """SPEC-502 suggested migrations home if it exists, else ``None``."""
    candidate = repo_root().joinpath(*DEFAULT_MIGRATIONS_SUBPATH)
    return candidate if candidate.is_dir() else None


def apply_sql_migrations(
    connection: sqlite3.Connection, migrations_dir: Path
) -> int:
    """Apply pending ``NNN_*.sql`` migrations via the production runner.

    Thin delegate to :func:`adapters.storage.db.migrate` (SPEC-502 §3:
    启动时在单事务内执行未应用脚本). Returns the resulting ``user_version``;
    idempotent on re-run. The connection must be in autocommit mode
    (``isolation_level=None`` — as returned by
    :func:`adapters.storage.db.connect`) so the production runner's explicit
    ``BEGIN IMMEDIATE`` / ``COMMIT`` envelope is the only transaction
    boundary. Invalid trees (naming, duplicate prefix, numbering gap) raise
    :class:`adapters.storage.errors.MigrationError` — fail-fast, no degraded
    operation (SPEC-505 §7 不降级跳过).
    """
    return _production_migrate(connection, migrations_dir)


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
