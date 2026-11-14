"""SQLite connection and migration runner (SPEC-502 sections 3 and 7).

Technical posture (SPEC-502 section 3): stdlib ``sqlite3``, no ORM, explicit
parameterized SQL; migrations are sequentially numbered SQL scripts tracked by
``PRAGMA user_version``; pending scripts are executed inside a single
transaction at startup, fail-fast on error (no degraded operation).

Windows-first: database paths go through ``pathlib``/the caller's string as
given (never ``/tmp`` assumptions) and migration scripts are read with an
explicit ``encoding="utf-8"``.
"""

from __future__ import annotations

import re
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Iterator, Optional, Union

from adapters.storage.errors import MigrationError, StorageUnavailableError

#: How long a writer waits for the single-writer lock before failing
#: (SPEC-502 section 8: SQLite single-writer semantics; value not spec-pinned,
#: recorded as interpretation R14 in the implementation plan).
BUSY_TIMEOUT_MS = 10_000

_MIGRATIONS_SUBDIR = "migrations"
_SCRIPT_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def connect(path: Union[str, Path]) -> sqlite3.Connection:
    """Open a SQLite connection in explicit-transaction mode.

    ``isolation_level=None`` (autocommit) so every transaction boundary is
    written explicitly (``BEGIN IMMEDIATE`` / ``COMMIT`` / ``ROLLBACK``) —
    the journal stamp transaction of SPEC-502 section 6 depends on that.
    """
    try:
        conn = sqlite3.connect(str(path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    except sqlite3.Error as exc:
        raise StorageUnavailableError(f"cannot open database {path!r}") from exc
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Optional[Union[str, Path]] = None) -> int:
    """Apply all pending migrations, then return the resulting user_version.

    Idempotent: with an up-to-date database this is a no-op. All pending
    scripts run inside one transaction (SPEC-502 section 3); any failure
    rolls everything back and raises :class:`MigrationError` (fail-fast).
    """
    current = _user_version(conn)
    scripts = _available_scripts(migrations_dir)
    if scripts and current > scripts[-1].version:
        raise MigrationError(
            f"database user_version {current} is ahead of the newest migration "
            f"{scripts[-1].version:03d}; refusing to run older code against a newer schema"
        )
    pending = [script for script in scripts if script.version > current]
    if not pending:
        return current

    conn.execute("BEGIN IMMEDIATE")
    try:
        for script in pending:
            for statement in _split_statements(script.sql):
                conn.execute(statement)
        # user_version participates in the transaction, so the version bump is
        # atomic with the DDL; the value is a validated int (pragma assignment
        # cannot be parameterized).
        conn.execute(f"PRAGMA user_version = {pending[-1].version}")
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        _safe_rollback(conn)
        raise MigrationError(
            f"migration to version {pending[-1].version:03d} failed; transaction rolled back"
        ) from exc
    except BaseException:
        _safe_rollback(conn)
        raise
    return pending[-1].version


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:  # pragma: no cover - rollback of a dead transaction
        pass


class _MigrationScript:
    __slots__ = ("version", "name", "sql")

    def __init__(self, version: int, name: str, sql: str) -> None:
        self.version = version
        self.name = name
        self.sql = sql


def _available_scripts(migrations_dir: Optional[Union[str, Path]]) -> list[_MigrationScript]:
    """Read and order migration scripts, ``NNN_*.sql`` ascending.

    Files not matching the ``NNN_*.sql`` naming are ignored; duplicate version
    prefixes are a configuration error (fail-fast).
    """
    if migrations_dir is None:
        root: Union[Path, resources.abc.Traversable] = resources.files(
            "adapters.storage"
        ).joinpath(_MIGRATIONS_SUBDIR)
    else:
        root = Path(migrations_dir)

    found: dict[int, _MigrationScript] = {}
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        match = _SCRIPT_NAME_RE.match(entry.name)
        if match is None:
            continue
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"duplicate migration version {version:03d}")
        with entry.open("r", encoding="utf-8") as handle:
            sql = handle.read()
        found[version] = _MigrationScript(version, entry.name, sql)
    return [found[version] for version in sorted(found)]


def _split_statements(sql: str) -> Iterator[str]:
    """Split a script into individual statements.

    ``Cursor.executescript`` would implicitly COMMIT any open transaction,
    which would break the spec's single-transaction migration; statements are
    therefore executed one by one. ``sqlite3.complete_statement`` is the same
    completeness logic the sqlite3 CLI uses, so semicolons inside string
    literals or comments do not split incorrectly.
    """
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    leftover = buffer.strip()
    if leftover:  # incomplete trailing statement: let execute() surface it
        yield leftover


__all__ = ["BUSY_TIMEOUT_MS", "connect", "migrate"]
