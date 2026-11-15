"""Storage adapter: SQLite persistence per SPEC-502 + artifact storage per
SPEC-503.

The platform's single SQLite persistence contract: schema v1 via
``PRAGMA user_version`` numbered migrations, WAL mode, the journal stamp/dedup
protocol (``journal_seq`` is stamped ONLY inside the append transaction, per
session monotonic — SPEC-502 §6, ADR-0006 decision 2) and the runs/artifacts
repositories (ADR-0005 decision 4: ``adapters/`` owns storage). stdlib
``sqlite3``, no ORM; all SQL lives in this package.

The SPEC-503 artifact storage surface (content-addressed store, tee
double-write landing protocol, tmp atomic commit, startup sweep, path
safety) lives in :mod:`adapters.storage.artifact_store` /
:mod:`adapters.storage.paths` / :mod:`adapters.storage.artifact_errors`.

Domain packages must not import this adapter (import-linter contracts); the
legal direction is one-way: this package consumes ``domain.observation``
models (``RunContext``, ``TSArtifact``) for row↔model mapping.

Public surface:
- :func:`adapters.storage.db.connect` / :func:`adapters.storage.db.migrate`
- ``SqliteEventJournal`` (``EventJournal`` Protocol, SPEC-502 §5)
- ``SqliteRunRepository`` / ``SqliteArtifactRepository`` (§5 Protocols)
- ``ArtifactStore`` / ``ArtifactWriteSink`` (SPEC-503 §4 write protocol)
- error types in :mod:`adapters.storage.errors` (SPEC-502 §7 semantics)
  and :mod:`adapters.storage.artifact_errors` (SPEC-503 §7 semantics)
"""

from adapters.storage.artifact_errors import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ArtifactPathSafetyError,
    ArtifactTooLargeError,
)
from adapters.storage.artifact_store import (
    DEFAULT_MAX_BYTES,
    ArtifactStore,
    ArtifactWriteSink,
    SinkCommit,
    StoredRef,
)
from adapters.storage.checkpoints import CheckpointStore, SqliteCheckpointStore
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
    "DEFAULT_MAX_BYTES",
    "QUERY_LIMIT_DEFAULT",
    "QUERY_LIMIT_HARD_CAP",
    "ArtifactCorruptError",
    "ArtifactMeta",
    "ArtifactNotFoundError",
    "ArtifactPathSafetyError",
    "ArtifactRepository",
    "ArtifactRow",
    "ArtifactStore",
    "ArtifactTooLargeError",
    "ArtifactWriteSink",
    "CheckpointStore",
    "EventJournal",
    "EventRow",
    "InvalidEnvelopeError",
    "MigrationError",
    "RunRepository",
    "SinkCommit",
    "SqliteArtifactRepository",
    "SqliteCheckpointStore",
    "SqliteEventJournal",
    "SqliteRunRepository",
    "StoredRef",
    "StorageConflictError",
    "StorageError",
    "StorageUnavailableError",
    "StorageWriteFailure",
    "connect",
    "migrate",
]
