"""Storage adapter: SQLite persistence per SPEC-502.

The platform's single SQLite persistence contract: schema v1 via
``PRAGMA user_version`` numbered migrations, WAL mode, the journal stamp/dedup
protocol (``journal_seq`` is stamped ONLY inside the append transaction, per
session monotonic — SPEC-502 §6, ADR-0006 decision 2) and the runs/artifacts
repositories (ADR-0005 decision 4: ``adapters/`` owns storage). stdlib
``sqlite3``, no ORM; all SQL lives in this package.

Domain packages must not import this adapter (import-linter contracts); the
legal direction is one-way: this package consumes ``domain.observation``
models (``RunContext``, ``TSArtifact``) for row↔model mapping.

Public surface:
- :func:`adapters.storage.db.connect` / :func:`adapters.storage.db.migrate`
- ``SqliteEventJournal`` (``EventJournal`` Protocol, SPEC-502 §5)
- ``SqliteRunRepository`` / ``SqliteArtifactRepository`` (§5 Protocols)
- error types in :mod:`adapters.storage.errors` (SPEC-502 §7 semantics)
"""

from adapters.storage.db import BUSY_TIMEOUT_MS, connect, migrate
from adapters.storage.errors import (
    InvalidEnvelopeError,
    MigrationError,
    StorageConflictError,
    StorageError,
    StorageUnavailableError,
    StorageWriteFailure,
)
from adapters.storage.journal import (
    QUERY_LIMIT_DEFAULT,
    QUERY_LIMIT_HARD_CAP,
    EventJournal,
    EventRow,
    SqliteEventJournal,
)
from adapters.storage.repositories import (
    ArtifactMeta,
    ArtifactRepository,
    ArtifactRow,
    RunRepository,
    SqliteArtifactRepository,
    SqliteRunRepository,
)

__all__ = [
    "BUSY_TIMEOUT_MS",
    "QUERY_LIMIT_DEFAULT",
    "QUERY_LIMIT_HARD_CAP",
    "ArtifactMeta",
    "ArtifactRepository",
    "ArtifactRow",
    "EventJournal",
    "EventRow",
    "InvalidEnvelopeError",
    "MigrationError",
    "RunRepository",
    "SqliteArtifactRepository",
    "SqliteEventJournal",
    "SqliteRunRepository",
    "StorageConflictError",
    "StorageError",
    "StorageUnavailableError",
    "StorageWriteFailure",
    "connect",
    "migrate",
]
