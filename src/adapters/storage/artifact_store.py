"""Artifact storage: content-addressed store with the tee double-write
landing protocol (SPEC-503, REQ-PLT-503-001..006).

This module owns the *physical file half* of the artifact contract; the
index half lives in the SPEC-502 ``artifacts`` table
(``SqliteArtifactRepository``). The write protocol per sink
(baseline / faulted / mutation log — ADR-0007 item 2) is fixed and shared:

1. create a uniquely-named in-flight file in ``<root>/tmp/``, stream bytes
   into it, computing SHA-256 incrementally (never load whole content);
2. after close, check the ``max_bytes`` cap (over-limit ⇒ fail, tmp file
   deleted, nothing registered — SPEC-503 §7 row 2);
3. ``os.replace`` the tmp file onto ``artifacts/<aa>/<sha256>.<ext>``
   (atomic rename — concurrent writers of the same content converge,
   SPEC-503 §8);
4. register the SPEC-502 index row (``relative_path`` = layout path). The
   registration gate enforces 先文件后索引: an index row is only ever
   created for a physically present file, so "index row exists ⇒ file
   exists" (SPEC-503 §4).

去重 = 引用不复制 (SPEC-503 §3): identical content lands on one
content-addressed file; every run registers its own index row pointing at
that single file. MVP has no refcounting and no auto-deletion.

Crash recovery: at startup, :meth:`ArtifactStore.sweep_orphans` removes
in-flight leftovers in ``tmp/`` — tmp paths are never indexed, so every
tmp entry is an orphan by construction.

Read boundary (SPEC-503 §5): ``relative_path`` → content-addressed file →
local stream; optional ``verify=True`` recomputes the digest and treats a
mismatch as corruption (:class:`ArtifactCorruptError`, HTTP-503 semantics +
alert record for SPEC-304 ``OBS_STORAGE_WRITE_FAILURE``-class rules).
Unknown ``artifact_id`` (with an index attached) →
:class:`ArtifactNotFoundError` (HTTP 404 semantics). Absolute paths are
never produced or accepted; all path handling goes through
:mod:`adapters.storage.paths` (SPEC-503 §6).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from adapters.storage.artifact_errors import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ArtifactPathSafetyError,
    ArtifactTooLargeError,
)
from adapters.storage.errors import StorageUnavailableError
from adapters.storage.paths import (
    ALLOWED_EXTENSIONS,
    artifact_layout_relative_path,
    resolve_within_root,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "ArtifactStore",
    "ArtifactWriteSink",
    "IndexRepository",
    "SinkCommit",
    "StoredRef",
]

#: MVP default single-artifact cap; the pinned value lands with OPEN-006
#: (GitHub #16) — configurable per store instance (REQ-PLT-503-006).
DEFAULT_MAX_BYTES = 256 * 1024 * 1024

_ARTIFACTS_DIRNAME = "artifacts"
_TMP_DIRNAME = "tmp"

#: Streaming chunk size — SHA-256 is computed incrementally, content is
#: never loaded whole (SPEC-503 §8 流式写入不整载内存).
_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class SinkCommit:
    """Result of committing one sink: the content-address landing data.

    ``relative_path`` is layout-relative only (never absolute — SPEC-003
    §2.7; the API layer forwards it to clients verbatim).
    """

    sha256: str
    byte_size: int
    relative_path: str


@dataclass(frozen=True)
class StoredRef:
    """One completed store_bytes landing (file half)."""

    sha256: str
    byte_size: int
    relative_path: str
    #: True when the content-addressed file already existed and was
    #: referenced, not rewritten (去重 = 引用不复制).
    deduplicated: bool = False


class IndexRepository(Protocol):
    """The SPEC-502 index half the store optionally cooperates with.

    Structural subset of :class:`adapters.storage.repositories.ArtifactRepository`
    (kept as a Protocol so the file half stays decoupled from SQLite).
    """

    def register(self, meta: object) -> None: ...

    def get(self, artifact_id: str) -> Optional[object]: ...

    def find_by_sha256(self, sha256: str) -> list[object]: ...


def _stream_to_tmp(target: Path, chunks: "object") -> tuple[str, int]:
    """Write chunks to ``target``, returning (sha256, byte_size).

    ``chunks`` is any iterable of ``bytes``; hashing is incremental.
    """
    digest = hashlib.sha256()
    size = 0
    with open(target, "wb") as stream:
        for chunk in chunks:
            stream.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class ArtifactWriteSink:
    """Streaming write half of the landing protocol (steps 1-3).

    One sink per stream leg. SIM-D wires the tee: pre-filter stream → the
    baseline sink (kind ``generated_ts``), post-filter stream → the faulted
    sink (kind ``faulted_ts``) + mutation-log sink (kind ``log``) — the
    store provides the landing points, ADR-0007 item 2. Chunks are written
    straight to the in-flight tmp file and hashed incrementally — content
    is never buffered whole in memory (SPEC-503 §8).
    """

    def __init__(self, store: "ArtifactStore", ext: str) -> None:
        ext = store._validate_ext(ext)
        self._store = store
        self._ext = ext
        self._in_flight = store.tmp_dir / f"{uuid.uuid4().hex}.{ext}"
        self._handle = open(self._in_flight, "wb")
        self._digest = hashlib.sha256()
        self._bytes_written = 0
        self._finished = False

    def write(self, chunk: bytes) -> None:
        """Stream one chunk into the in-flight tmp file (SHA-256 边写边算)."""
        if self._finished:
            raise ArtifactPathSafetyError(
                "sink already committed/aborted; create a new sink"
            )
        try:
            self._handle.write(chunk)
        except OSError as exc:
            self._finished = True
            self._discard()
            raise StorageUnavailableError(f"artifact tmp write failed: {exc}") from exc
        self._digest.update(chunk)
        self._bytes_written += len(chunk)
        if self._bytes_written > self._store.max_bytes:
            self._finished = True
            self._discard()
            raise ArtifactTooLargeError(
                f"sink exceeded max_bytes={self._store.max_bytes} "
                f"after {self._bytes_written} bytes"
            )

    def commit(self) -> SinkCommit:
        """Close, cap-check, then atomically rename onto the
        content-addressed final path (step 3)."""
        if self._finished:
            raise ArtifactPathSafetyError(
                "sink already committed/aborted; create a new sink"
            )
        self._handle.close()
        self._finished = True
        size = self._bytes_written
        if size > self._store.max_bytes:
            self._discard()
            raise ArtifactTooLargeError(
                f"artifact byte_size {size} exceeds max_bytes={self._store.max_bytes}"
            )
        sha = self._digest.hexdigest()
        relative = artifact_layout_relative_path(sha, self._ext)
        final = resolve_within_root(self._store.root, relative)
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(self._in_flight, final)
        except OSError as exc:
            self._discard()
            raise StorageUnavailableError(
                f"artifact commit rename failed: {exc}"
            ) from exc
        return SinkCommit(sha256=sha, byte_size=size, relative_path=relative)

    def _discard(self) -> None:
        try:
            self._handle.close()
        except OSError:
            pass
        try:
            self._in_flight.unlink()
        except FileNotFoundError:
            pass

    def abort(self) -> None:
        """Explicitly drop the in-flight file (caller-side cancellation)."""
        self._finished = True
        self._discard()


class ArtifactStore:
    """Filesystem asset store per SPEC-503 §3 layout:

    ``<root>/artifacts/<sha256[:2]>/<sha256>.<ext>``, ``<root>/tmp/`` for
    in-flight writes committed by atomic rename.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        index: Optional[IndexRepository] = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}")
        self.root = Path(root)
        self.max_bytes = max_bytes
        self._index = index
        self._clock = clock
        self.artifacts_dir = self.root / _ARTIFACTS_DIRNAME
        self.tmp_dir = self.root / _TMP_DIRNAME
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # write protocol
    # ------------------------------------------------------------------

    def _validate_ext(self, ext: str) -> str:
        if ext not in ALLOWED_EXTENSIONS:
            raise ArtifactPathSafetyError(
                f"extension {ext!r} outside the SPEC-503 §3 set "
                f"{sorted(ALLOWED_EXTENSIONS)}"
            )
        return ext

    def open_sink(self, ext: str) -> ArtifactWriteSink:
        """Open a streaming sink (one tee leg) for ``ext`` content."""
        return ArtifactWriteSink(self, ext)

    def store_bytes(self, data: bytes, *, ext: str) -> StoredRef:
        """In-memory convenience for the full file half (steps 1-3)."""
        self._validate_ext(ext)
        if len(data) > self.max_bytes:
            raise ArtifactTooLargeError(
                f"artifact byte_size {len(data)} exceeds "
                f"max_bytes={self.max_bytes}"
            )
        sha = hashlib.sha256(data).hexdigest()
        relative = artifact_layout_relative_path(sha, ext)
        final = resolve_within_root(self.root, relative)
        if final.exists():
            # Content-addressed hit: reference, don't copy. A size mismatch
            # means the existing file is not the named content (corruption /
            # leftover) — rewrite it through the atomic protocol.
            if final.stat().st_size == len(data):
                return StoredRef(
                    sha256=sha, byte_size=len(data), relative_path=relative,
                    deduplicated=True,
                )
        final.parent.mkdir(parents=True, exist_ok=True)
        in_flight = self.tmp_dir / f"{uuid.uuid4().hex}.{ext}"
        try:
            written_sha, written_size = _stream_to_tmp(in_flight, (data,))
            os.replace(in_flight, final)
        except OSError as exc:
            try:
                in_flight.unlink()
            except FileNotFoundError:
                pass
            raise StorageUnavailableError(
                f"artifact write failed: {exc}"
            ) from exc
        if written_sha != sha or written_size != len(data):  # pragma: no cover
            raise ArtifactCorruptError(
                f"tmp write digest {written_sha!r} != input digest {sha!r}"
            )
        return StoredRef(sha256=sha, byte_size=written_size, relative_path=relative)

    def register(
        self,
        commit: SinkCommit,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        packet_size: Optional[int] = None,
        packet_count: Optional[int] = None,
        generator_version: Optional[str] = None,
        config_hash: Optional[str] = None,
        fault_profile_ids: Optional[list[str]] = None,
    ) -> str:
        """Index half (step 4): create the SPEC-502 row for a committed file.

        先文件后索引 gate: refuses when the physical file is absent, so an
        index row can never reference a half-written state (REQ-PLT-503-003).
        Dedup is NOT applied to rows — every call adds a row pointing at the
        same content-addressed file (引用不复制).
        """
        relative = artifact_layout_relative_path(commit.sha256, self._ext_of(commit))
        if relative != commit.relative_path or not resolve_within_root(
            self.root, commit.relative_path
        ).exists():
            raise ArtifactNotFoundError(
                f"no committed file for relative_path {commit.relative_path!r} "
                "(先文件后索引: register requires the committed file)"
            )
        if self._index is None:
            raise ArtifactNotFoundError(
                "no index repository attached to this ArtifactStore"
            )
        from adapters.storage.repositories import ArtifactMeta
        from domain.observation.artifact import ArtifactKind, TSArtifact

        artifact = TSArtifact(
            artifact_id=str(uuid.uuid4()),
            run_id=run_id,
            kind=ArtifactKind(kind),
            relative_path=commit.relative_path,
            byte_size=commit.byte_size,
            packet_size=packet_size,
            packet_count=packet_count,
            sha256=commit.sha256,
            generator_version=generator_version,
            config_hash=config_hash,
            fault_profile_ids=fault_profile_ids,
            created_at_utc_ms=self._clock(),
        )
        self._index.register(ArtifactMeta(artifact=artifact, session_id=session_id))
        return artifact.artifact_id

    def _ext_of(self, commit: SinkCommit) -> str:
        suffix = commit.relative_path.rsplit(".", 1)[-1]
        return self._validate_ext(suffix)

    # ------------------------------------------------------------------
    # crash recovery
    # ------------------------------------------------------------------

    def sweep_orphans(self) -> list[str]:
        """Startup sweep: remove all in-flight leftovers in ``tmp/``.

        tmp paths are never indexed (index rows are created only after the
        atomic rename), so every tmp entry is an orphan by construction
        (SPEC-503 §4 崩溃恢复). Committed content under ``artifacts/`` is
        never touched. Returns the swept names.
        """
        swept: list[str] = []
        for entry in sorted(self.tmp_dir.iterdir()):
            if entry.is_file():
                entry.unlink()
                swept.append(entry.name)
            elif entry.is_dir():
                shutil.rmtree(entry)
                swept.append(entry.name + "/")
        return swept

    # ------------------------------------------------------------------
    # read boundary
    # ------------------------------------------------------------------

    def read_bytes(self, relative_path: str, *, verify: bool = False) -> bytes:
        """Read whole content for a layout-relative path.

        ``verify=True`` recomputes SHA-256 and treats a mismatch as
        corruption (SPEC-503 §7 row 4).
        """
        with self.open_read_stream(relative_path) as stream:
            data = stream.read()
        if verify:
            actual = hashlib.sha256(data).hexdigest()
            if actual != relative_path.rsplit("/", 1)[-1].split(".")[0]:
                raise ArtifactCorruptError(
                    f"stored content digest {actual!r} does not match the "
                    f"content address in {relative_path!r}"
                )
        return data

    def open_read_stream(self, relative_path: str):
        """Local streaming read (SPEC-503 §5: 本模块只提供本地流接口)."""
        final = resolve_within_root(self.root, relative_path)
        if not final.exists() or not final.is_file():
            raise ArtifactNotFoundError(
                f"no artifact file at relative_path {relative_path!r}"
            )
        return open(final, "rb")

    def read_by_artifact(self, artifact_id: str) -> bytes:
        """artifact_id → index row → relative_path → stream (SPEC-503 §5).

        Unknown ``artifact_id`` → :class:`ArtifactNotFoundError` (HTTP 404).
        """
        if self._index is None:
            raise ArtifactNotFoundError(
                "no index repository attached to this ArtifactStore"
            )
        row = self._index.get(artifact_id)
        if row is None:
            raise ArtifactNotFoundError(f"unknown artifact_id {artifact_id!r}")
        return self.read_bytes(row.relative_path)  # type: ignore[attr-defined]
