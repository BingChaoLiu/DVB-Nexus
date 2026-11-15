"""Run/Artifact/Diagnosis repositories (SPEC-502 sections 4-5).

Public interfaces are expressed as ``typing.Protocol`` classes with the exact
SPEC-502 §5 signatures (REQ-PLT-502-006); the ``Sqlite*`` classes are the
concrete implementations. Row types are storage-owned value objects — the
SPEC-502 §5 protocol references them by name (``EventRow`` lives in
``journal.py``, ``DiagnosisRecord`` here since ticket #54).

``ArtifactMeta``: SPEC-502 §5 names the register input type but does not
define it. The artifacts table (§4) stores ``run_id / session_id``, while the
domain ``TSArtifact`` (ticket #21, not modifiable here) has no ``session_id``
field — so the register input composes the domain model with the session id.

The remaining §5 protocols (``TopologyRepository`` / ``SessionRepository`` /
``AlertRepository``) are NOT implemented: their signatures depend on domain
types that do not exist yet (``SimulationSessionSpec``, ``AlertRecord``).
The tables themselves exist since migration 0001. Recorded as
out-of-scope-with-evidence in the implementation reports.

Storage-owned row discipline (ticket #54): ``DiagnosisRecord`` is defined
HERE, not in ``domain.diagnosis`` — an adapters → domain.diagnosis edge
would put every importer of this module (e.g. ``simulation`` via the
artifact store) on an indirect ``domain.diagnosis`` chain and break the
frozen import-linter contracts C7/C8. Same posture as ``ArtifactRow``:
plain strings, no domain vocabulary import.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from adapters.storage.errors import StorageConflictError
from domain.observation.artifact import TSArtifact
from domain.observation.run_context import RunContext

#: R9 (ticket #23, review-fixed citation): the status a run is created with.
#: SPEC-502 §4 has a status column but the §5 create protocol takes no status;
#: SPEC-003 §3 LifecycleState's first value is "created".
_INITIAL_RUN_STATUS = "created"

#: SPEC-502 §4 diagnoses.state two-value column (raised/cleared; the
#: SPEC-304 five-state alert lifecycle is the OTHER table).
_DIAGNOSIS_STATES = ("raised", "cleared")


class RunRepository(Protocol):
    """SPEC-502 §5 runs protocol."""

    def create(self, ctx: RunContext) -> None: ...
    def finish(self, run_id: str, *, status: str, ended_at_utc_ms: int) -> None: ...


class ArtifactRepository(Protocol):
    """SPEC-502 §5 artifacts protocol."""

    def register(self, meta: ArtifactMeta) -> None: ...
    def get(self, artifact_id: str) -> Optional[ArtifactRow]: ...
    def find_by_sha256(self, sha256: str) -> list[ArtifactRow]: ...


@dataclass(frozen=True)
class ArtifactMeta:
    """Register input: the domain artifact metadata plus the owning session."""

    artifact: TSArtifact
    session_id: str


@dataclass(frozen=True)
class ArtifactRow:
    """One stored artifacts row (SPEC-502 §5 ``ArtifactRow``)."""

    artifact_id: str
    sha256: str
    kind: str
    relative_path: str
    byte_size: int
    packet_size: Optional[int]
    packet_count: Optional[int]
    generator_version: Optional[str]
    config_hash: Optional[str]
    fault_profile_ids: Optional[list[str]]
    run_id: str
    session_id: str
    created_at_utc_ms: int


class SqliteRunRepository:
    """SQLite implementation of :class:`RunRepository`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, ctx: RunContext) -> None:
        try:
            self._conn.execute(
                "INSERT INTO runs (run_id, session_id, topology_id, topology_revision,"
                " sequence_number, mode, fidelity, started_at_utc_ms, generator_version,"
                " config_hash, seed, status, ended_at_utc_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    ctx.run_id,
                    ctx.session_id,
                    ctx.topology_id,
                    ctx.topology_revision,
                    ctx.sequence_number,
                    ctx.mode.value,
                    ctx.fidelity.value,
                    ctx.started_at_utc_ms,
                    ctx.generator_version,
                    ctx.config_hash,
                    ctx.seed,
                    _INITIAL_RUN_STATUS,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(f"run {ctx.run_id!r} violates a runs constraint") from exc

    def finish(self, run_id: str, *, status: str, ended_at_utc_ms: int) -> None:
        cursor = self._conn.execute(
            "UPDATE runs SET status = ?, ended_at_utc_ms = ? WHERE run_id = ?",
            (status, ended_at_utc_ms, run_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"run {run_id!r} does not exist")


class SqliteArtifactRepository:
    """SQLite implementation of :class:`ArtifactRepository`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def register(self, meta: ArtifactMeta) -> None:
        artifact = meta.artifact
        fault_profile_ids_json = (
            None
            if artifact.fault_profile_ids is None
            else json.dumps(artifact.fault_profile_ids, ensure_ascii=False)
        )
        try:
            self._conn.execute(
                "INSERT INTO artifacts (artifact_id, sha256, kind, relative_path, byte_size,"
                " packet_size, packet_count, generator_version, config_hash,"
                " fault_profile_ids_json, run_id, session_id, created_at_utc_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact.artifact_id,
                    artifact.sha256,
                    artifact.kind.value,
                    artifact.relative_path,
                    artifact.byte_size,
                    artifact.packet_size,
                    artifact.packet_count,
                    artifact.generator_version,
                    artifact.config_hash,
                    fault_profile_ids_json,
                    artifact.run_id,
                    meta.session_id,
                    artifact.created_at_utc_ms,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(
                f"artifact {artifact.artifact_id!r} violates an artifacts constraint"
            ) from exc

    def get(self, artifact_id: str) -> Optional[ArtifactRow]:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return None if row is None else _artifact_row(row)

    def find_by_sha256(self, sha256: str) -> list[ArtifactRow]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE sha256 = ? ORDER BY created_at_utc_ms, artifact_id",
            (sha256,),
        ).fetchall()
        return [_artifact_row(row) for row in rows]


def _artifact_row(row: sqlite3.Row) -> ArtifactRow:
    return ArtifactRow(
        artifact_id=row["artifact_id"],
        sha256=row["sha256"],
        kind=row["kind"],
        relative_path=row["relative_path"],
        byte_size=row["byte_size"],
        packet_size=row["packet_size"],
        packet_count=row["packet_count"],
        generator_version=row["generator_version"],
        config_hash=row["config_hash"],
        fault_profile_ids=(
            None if row["fault_profile_ids_json"] is None else json.loads(row["fault_profile_ids_json"])
        ),
        run_id=row["run_id"],
        session_id=row["session_id"],
        created_at_utc_ms=row["created_at_utc_ms"],
    )


__all__ = [
    "ArtifactMeta",
    "ArtifactRepository",
    "ArtifactRow",
    "DiagnosisRecord",
    "DiagnosisRepository",
    "RunRepository",
    "SqliteArtifactRepository",
    "SqliteDiagnosisRepository",
    "SqliteRunRepository",
]


# --- diagnoses (SPEC-502 §4 row 6 / §5, ticket #54) -----------------------------


@dataclass(frozen=True)
class DiagnosisRecord:
    """One stored diagnoses row (SPEC-502 §4/§5 ``DiagnosisRecord``).

    Storage-owned (see the module docstring): plain strings for the
    severity/confidence vocabularies — the diagnosis enums live in
    ``domain.diagnosis`` and adapters must not import that package (the
    indirect-chain discipline). ``raised_at``/``cleared_at`` are epoch-ms
    integers (ticket #23 R8); the list fields are stored as JSON TEXT.
    """

    diagnosis_id: str
    session_id: str
    run_id: str
    rule_id: str
    rule_version: str
    code: str
    severity: str
    confidence: str
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    affected_node_ids: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    state: str = "raised"
    raised_at: int = 0
    cleared_at: Optional[int] = None


class DiagnosisRepository(Protocol):
    """SPEC-502 §5 diagnoses protocol.

    upsert implements REQ-DIA-306-004 (candidates upsert the table, one
    row per ``diagnosis_id``, state raised/cleared consistent with the
    ``diagnosis.*`` event stream).
    """

    def upsert(self, record: DiagnosisRecord) -> None: ...

    def clear(self, diagnosis_id: str, *, cleared_at_utc_ms: int) -> None: ...

    def query(self, session_id: str) -> list[DiagnosisRecord]: ...


class SqliteDiagnosisRepository:
    """SQLite implementation of :class:`DiagnosisRepository`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, record: DiagnosisRecord) -> None:
        if record.state not in _DIAGNOSIS_STATES:
            raise ValueError(
                f"diagnoses.state must be one of {_DIAGNOSIS_STATES},"
                f" got {record.state!r} (SPEC-502 §4)"
            )
        refs_json = json.dumps(record.observation_refs, ensure_ascii=False)
        node_ids_json = json.dumps(record.affected_node_ids, ensure_ascii=False)
        actions_json = json.dumps(record.suggested_actions, ensure_ascii=False)
        try:
            self._conn.execute(
                "INSERT INTO diagnoses (diagnosis_id, session_id, run_id,"
                " rule_id, rule_version, code, severity, confidence,"
                " observation_refs_json, affected_node_ids_json,"
                " suggested_actions_json, state, raised_at, cleared_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(diagnosis_id) DO UPDATE SET"
                " rule_id=excluded.rule_id, rule_version=excluded.rule_version,"
                " code=excluded.code, severity=excluded.severity,"
                " confidence=excluded.confidence,"
                " observation_refs_json=excluded.observation_refs_json,"
                " affected_node_ids_json=excluded.affected_node_ids_json,"
                " suggested_actions_json=excluded.suggested_actions_json,"
                " state=excluded.state, raised_at=excluded.raised_at,"
                " cleared_at=excluded.cleared_at",
                (
                    record.diagnosis_id,
                    record.session_id,
                    record.run_id,
                    record.rule_id,
                    record.rule_version,
                    record.code,
                    record.severity,
                    record.confidence,
                    refs_json,
                    node_ids_json,
                    actions_json,
                    record.state,
                    record.raised_at,
                    record.cleared_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(
                f"diagnosis {record.diagnosis_id!r} violates a diagnoses constraint"
            ) from exc

    def clear(self, diagnosis_id: str, *, cleared_at_utc_ms: int) -> None:
        cursor = self._conn.execute(
            "UPDATE diagnoses SET state = 'cleared', cleared_at = ?"
            " WHERE diagnosis_id = ?",
            (cleared_at_utc_ms, diagnosis_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"diagnosis {diagnosis_id!r} does not exist")

    def query(self, session_id: str) -> list[DiagnosisRecord]:
        rows = self._conn.execute(
            "SELECT * FROM diagnoses WHERE session_id = ?"
            " ORDER BY raised_at ASC, diagnosis_id ASC",
            (session_id,),
        ).fetchall()
        return [_diagnosis_record(row) for row in rows]


def _diagnosis_record(row: sqlite3.Row) -> DiagnosisRecord:
    return DiagnosisRecord(
        diagnosis_id=row["diagnosis_id"],
        session_id=row["session_id"],
        run_id=row["run_id"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        code=row["code"],
        severity=row["severity"],
        confidence=row["confidence"],
        observation_refs=json.loads(row["observation_refs_json"]),
        affected_node_ids=json.loads(row["affected_node_ids_json"]),
        suggested_actions=json.loads(row["suggested_actions_json"]),
        state=row["state"],
        raised_at=row["raised_at"],
        cleared_at=row["cleared_at"],
    )
