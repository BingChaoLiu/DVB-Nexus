"""``SqliteTopologyRepository`` — SPEC-502 §4/§5 topologies-table storage
(ticket #80, REQ-API-500-001).

The ``topologies`` table has been part of migration ``0001_init.sql``
since the M3 slice (SPEC-502 §4 row 1, frozen schema): ``(topology_id,
revision)`` composite PK, ``spec_json`` (the SPEC-003 §2.1 configuration
model verbatim — opaque TEXT here), ``created_at_utc``/``updated_at_utc``
ISO-8601 TEXT (R6). Every revision is one immutable row — the repository
exposes **no update/delete path**: PUT is the next ``save`` with
``revision = latest + 1`` (不可变追加), and a composite-key repeat save
raises :class:`StorageConflictError` (the 409 family) instead of
overwriting.

The ``get(topology_id, revision=None)`` Protocol face is SPEC-502 §5
verbatim; ``list_latest()`` (latest-revision row per topology_id, id ASC)
is the additive read face the §4.1 list endpoint consumes. Domain
rehydration (spec_json → ``TopologyGraph``) is a composition-root concern
(``bootstrap.topologies``) — the repository stays schema-agnostic.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional, Protocol

from adapters.storage.errors import StorageConflictError

__all__ = [
    "TopologyRepository",
    "TopologyRow",
    "SqliteTopologyRepository",
]


class TopologyRow:
    """One stored ``topologies`` row (SPEC-502 §4 row 1)."""

    __slots__ = (
        "topology_id",
        "revision",
        "spec_json",
        "created_at_utc",
        "updated_at_utc",
    )

    def __init__(
        self,
        *,
        topology_id: str,
        revision: int,
        spec_json: str,
        created_at_utc: str,
        updated_at_utc: str,
    ) -> None:
        self.topology_id = topology_id
        self.revision = revision
        self.spec_json = spec_json
        self.created_at_utc = created_at_utc
        self.updated_at_utc = updated_at_utc

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TopologyRow):
            return NotImplemented
        return (
            self.topology_id == other.topology_id
            and self.revision == other.revision
            and self.spec_json == other.spec_json
            and self.created_at_utc == other.created_at_utc
            and self.updated_at_utc == other.updated_at_utc
        )

    def __repr__(self) -> str:
        return (
            f"TopologyRow(topology_id={self.topology_id!r},"
            f" revision={self.revision!r})"
        )


class TopologyRepository(Protocol):
    """The SPEC-502 §5 topology persistence face (+ the additive list face
    the §4.1 list endpoint consumes)."""

    def save(self, topology_id: str, revision: int, spec_json: str) -> None: ...

    def get(
        self, topology_id: str, revision: Optional[int] = None
    ) -> Optional[TopologyRow]: ...

    def list_latest(self) -> list[TopologyRow]: ...


def _utc_now_iso() -> str:
    """R6 operational stamp: ISO-8601 UTC TEXT (row-creation fact; rows
    are immutable so ``updated_at_utc`` mirrors it)."""
    return datetime.now(timezone.utc).isoformat()


class SqliteTopologyRepository:
    """SQLite implementation of :class:`TopologyRepository`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, topology_id: str, revision: int, spec_json: str) -> None:
        now = _utc_now_iso()
        try:
            self._conn.execute(
                "INSERT INTO topologies (topology_id, revision, spec_json,"
                " created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?)",
                (topology_id, revision, spec_json, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(
                f"topology {topology_id!r} revision {revision!r} violates a"
                " topologies constraint (the composite key is immutable —"
                " modify = the next revision row, SPEC-502 §4)"
            ) from exc

    def get(
        self, topology_id: str, revision: Optional[int] = None
    ) -> Optional[TopologyRow]:
        if revision is None:
            row = self._conn.execute(
                "SELECT * FROM topologies WHERE topology_id = ?"
                " ORDER BY revision DESC LIMIT 1",
                (topology_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM topologies WHERE topology_id = ? AND revision = ?",
                (topology_id, revision),
            ).fetchone()
        return None if row is None else _topology_row(row)

    def list_latest(self) -> list[TopologyRow]:
        """The latest-revision row per topology_id, topology_id ASC."""
        rows = self._conn.execute(
            "SELECT t.* FROM topologies t"
            " JOIN (SELECT topology_id, MAX(revision) AS revision"
            "       FROM topologies GROUP BY topology_id) m"
            " ON t.topology_id = m.topology_id AND t.revision = m.revision"
            " ORDER BY t.topology_id ASC"
        ).fetchall()
        return [_topology_row(row) for row in rows]


def _topology_row(row: sqlite3.Row) -> TopologyRow:
    return TopologyRow(
        topology_id=row["topology_id"],
        revision=row["revision"],
        spec_json=row["spec_json"],
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
    )
