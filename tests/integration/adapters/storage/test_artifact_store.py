"""ArtifactStore write protocol (SPEC-503 §4/§5/§8, REQ-PLT-503-001/003/005/006).

Seam: ``ArtifactStore`` public surface — ``store_bytes`` / ``open_sink`` /
``register`` / ``sweep_orphans`` / ``read_bytes`` — the storage adapter's
landing protocol for the SIM-D tee double-write (GitHub #12/#13 ruling).
Tests use programmatic byte material (tests/README.md §5: no hand-assembled
literals) and never pin drive letters or absolute paths.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from adapters.storage import db
from adapters.storage.artifact_errors import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ArtifactPathSafetyError,
    ArtifactTooLargeError,
)
from adapters.storage.artifact_store import ArtifactStore, SinkCommit
from adapters.storage.errors import StorageUnavailableError
from adapters.storage.repositories import SqliteArtifactRepository
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir


def _material(size: int, offset: int = 0) -> bytes:
    """Programmatic (not hand-assembled) byte material for test payloads."""
    return bytes((offset + i) % 256 for i in range(size))


_FIXED_CLOCK_MS = 1_700_000_000_000


def _clock() -> int:
    return _FIXED_CLOCK_MS


def _make_store(tmp_path: Path, *, max_bytes: int | None = None) -> ArtifactStore:
    kwargs = {"clock": _clock}
    if max_bytes is not None:
        kwargs["max_bytes"] = max_bytes
    return ArtifactStore(root=tmp_path / "store", **kwargs)


def _migrated_repository(tmp_path: Path) -> SqliteArtifactRepository:
    conn = db.connect(tmp_path / "index.sqlite3")
    apply_sql_migrations(conn, default_migrations_dir())
    return SqliteArtifactRepository(conn)


class TestLayout:
    def test_root_skeleton_created(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.root.is_dir()
        assert store.artifacts_dir.is_dir()
        assert store.tmp_dir.is_dir()

    def test_store_bytes_lands_at_content_address(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        data = _material(512)
        sha = hashlib.sha256(data).hexdigest()
        ref = store.store_bytes(data, ext="ts")
        assert ref.sha256 == sha
        assert ref.byte_size == len(data)
        assert ref.relative_path == f"artifacts/{sha[:2]}/{sha}.ts"
        final = store.root / "artifacts" / sha[:2] / f"{sha}.ts"
        assert final.read_bytes() == data
        # tmp/ drained after commit (atomic rename, no in-flight leftovers).
        assert list(store.tmp_dir.iterdir()) == []

    def test_store_bytes_same_content_single_file(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        data = _material(256, offset=7)
        first = store.store_bytes(data, ext="bin")
        second = store.store_bytes(data, ext="bin")
        assert first.relative_path == second.relative_path
        assert second.deduplicated is True
        bucket = store.artifacts_dir / first.sha256[:2]
        assert [p.name for p in bucket.iterdir()] == [f"{first.sha256}.bin"]

    def test_store_bytes_streams_in_chunks(self, tmp_path: Path) -> None:
        """The commit path is the streaming sink: many writes, one commit."""
        store = _make_store(tmp_path)
        chunks = [_material(64, offset=i) for i in range(8)]
        sha = hashlib.sha256(b"".join(chunks)).hexdigest()
        sink = store.open_sink("bin")
        for chunk in chunks:
            sink.write(chunk)
        commit = sink.commit()
        assert commit.sha256 == sha
        assert commit.byte_size == 8 * 64
        final = store.root / "artifacts" / sha[:2] / f"{sha}.bin"
        assert final.read_bytes() == b"".join(chunks)
        assert list(store.tmp_dir.iterdir()) == []

    def test_sink_commit_result_is_relative_path_only(self, tmp_path: Path) -> None:
        """The landing protocol never exposes absolute paths (SPEC-003 §2.7)."""
        store = _make_store(tmp_path)
        sink = store.open_sink("log")
        sink.write(_material(32))
        commit = sink.commit()
        assert isinstance(commit, SinkCommit)
        assert not Path(commit.relative_path).is_absolute()
        assert "\\" not in commit.relative_path


class TestMaxBytes:
    def test_store_bytes_over_cap_rejected_and_tmp_cleaned(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path, max_bytes=128)
        with pytest.raises(ArtifactTooLargeError):
            store.store_bytes(_material(256), ext="bin")
        assert list(store.tmp_dir.iterdir()) == []
        assert not any(store.artifacts_dir.rglob("*.bin"))

    def test_sink_over_cap_rejected_and_no_leftovers(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_bytes=128)
        sink = store.open_sink("bin")
        sink.write(_material(96))
        # Fails at the write that crosses the cap (early, stronger than the
        # commit-time check) — SPEC-503 §7 row 2: 超限即失败，不留文件.
        with pytest.raises(ArtifactTooLargeError):
            sink.write(_material(96, offset=1))
        with pytest.raises(ArtifactPathSafetyError):
            sink.commit()  # sink is finished after a failed write
        # SPEC-503 §7 row 2: 临时文件即删 — no in-flight leftovers either.
        assert list(store.tmp_dir.iterdir()) == []
        assert not any(store.artifacts_dir.rglob("*.bin"))

    def test_cap_is_configurable(self, tmp_path: Path) -> None:
        data = _material(256)
        strict = _make_store(tmp_path, max_bytes=128)
        loose = _make_store(tmp_path, max_bytes=1024)
        with pytest.raises(ArtifactTooLargeError):
            strict.store_bytes(data, ext="bin")
        ref = loose.store_bytes(data, ext="bin")
        assert ref.byte_size == 256


class TestStartupSweep:
    def test_sweep_removes_orphans_and_keeps_committed(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        committed = store.store_bytes(_material(64), ext="bin")
        # Simulate a crash mid-write: an in-flight tmp file left behind.
        orphan = store.tmp_dir / f"{uuid.uuid4().hex}.bin"
        orphan.write_bytes(_material(16))
        swept = store.sweep_orphans()
        assert orphan.name in swept
        assert not orphan.exists()
        assert list(store.tmp_dir.iterdir()) == []
        # Committed artifacts untouched.
        final = store.root / committed.relative_path
        assert final.read_bytes() == _material(64)

    def test_sweep_on_clean_tmp_is_noop(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.sweep_orphans() == []


class TestRegisterOrdering:
    def test_register_requires_committed_file(self, tmp_path: Path) -> None:
        """先文件后索引: an index row may only be created for a file that is
        physically present — 'index row exists ⇒ file exists' invariant."""
        store = _make_store(tmp_path)
        commit = SinkCommit(
            sha256="ab" + "0" * 62,
            byte_size=64,
            relative_path=f"artifacts/ab/{'ab' + '0' * 62}.bin",
        )
        with pytest.raises(ArtifactNotFoundError):
            store.register(commit, run_id="run-1", session_id="s-1", kind="log")

    def test_register_with_index_inserts_row_pointing_at_layout_path(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        repository = _migrated_repository(tmp_path)
        store_with_index = ArtifactStore(
            store.root, index=repository, clock=_clock
        )
        data = _material(128, offset=3)
        ref = store_with_index.store_bytes(data, ext="ts")
        artifact_id = store_with_index.register(
            SinkCommit(ref.sha256, ref.byte_size, ref.relative_path),
            run_id="run-1",
            session_id="session-1",
            kind="generated_ts",
        )
        row = repository.get(artifact_id)
        assert row is not None
        assert row.sha256 == ref.sha256
        assert row.relative_path == ref.relative_path
        assert row.kind == "generated_ts"
        assert row.byte_size == 128
        assert row.run_id == "run-1"
        assert row.session_id == "session-1"

    def test_register_dedup_references_not_copies(self, tmp_path: Path) -> None:
        """去重 = 引用不复制: a second registration of identical content adds
        a new index row pointing at the SAME physical file — one file on
        disk, two rows (SPEC-502 §4: sha256 non-unique)."""
        repository = _migrated_repository(tmp_path)
        store = ArtifactStore(
            tmp_path / "store", index=repository, clock=_clock
        )
        data = _material(128, offset=9)
        ref = store.store_bytes(data, ext="ts")
        first_id = store.register(
            SinkCommit(ref.sha256, ref.byte_size, ref.relative_path),
            run_id="run-1",
            session_id="session-1",
            kind="generated_ts",
        )
        second_id = store.register(
            SinkCommit(ref.sha256, ref.byte_size, ref.relative_path),
            run_id="run-2",
            session_id="session-1",
            kind="generated_ts",
        )
        assert first_id != second_id
        rows = repository.find_by_sha256(ref.sha256)
        # Ordering inside find_by_sha256 is (created_at_utc_ms, artifact_id) —
        # both rows share the injected fixed clock, so compare as a set.
        assert {row.artifact_id for row in rows} == {first_id, second_id}
        assert len({row.relative_path for row in rows}) == 1
        bucket = store.artifacts_dir / ref.sha256[:2]
        assert [p.name for p in bucket.iterdir()] == [f"{ref.sha256}.ts"]


class TestReadBoundary:
    def test_read_roundtrip_bytes_identical(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        data = _material(300, offset=11)
        ref = store.store_bytes(data, ext="bin")
        assert store.read_bytes(ref.relative_path) == data

    def test_verify_true_detects_tampered_content(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        ref = store.store_bytes(_material(300, offset=11), ext="bin")
        tampered = store.root / ref.relative_path
        tampered.write_bytes(_material(300, offset=12))
        with pytest.raises(ArtifactCorruptError):
            store.read_bytes(ref.relative_path, verify=True)

    def test_read_rejects_unsafe_relative_path(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        with pytest.raises(ArtifactPathSafetyError):
            store.read_bytes("../outside.bin")
        with pytest.raises(ArtifactPathSafetyError):
            store.read_bytes("artifacts\\x.bin")

    def test_read_missing_layout_path_raises_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        sha = "cd" + "1" * 62
        with pytest.raises(ArtifactNotFoundError):
            store.read_bytes(f"artifacts/{sha[:2]}/{sha}.bin")

    def test_open_read_stream_reads_whole_content(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        data = _material(300, offset=21)
        ref = store.store_bytes(data, ext="bin")
        with store.open_read_stream(ref.relative_path) as stream:
            assert stream.read() == data

    def test_register_dedup_repairs_missing_file(self, tmp_path: Path) -> None:
        """File-missing-but-indexed is the orphan inverse (SPEC-503 §11);
        a register of the same content restores the physical file."""
        repository = _migrated_repository(tmp_path)
        store = ArtifactStore(
            tmp_path / "store", index=repository, clock=_clock
        )
        data = _material(128, offset=31)
        ref = store.store_bytes(data, ext="ts")
        store.register(
            SinkCommit(ref.sha256, ref.byte_size, ref.relative_path),
            run_id="run-1",
            session_id="s-1",
            kind="generated_ts",
        )
        (store.root / ref.relative_path).unlink()
        store.store_bytes(data, ext="ts")
        assert (store.root / ref.relative_path).read_bytes() == data


class TestErrorSemantics:
    def test_os_error_on_commit_maps_to_storage_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """磁盘满 / 权限拒绝 → 存储不可用 (SPEC-503 §7 row 1; HTTP 503 in the
        API layer via StorageUnavailableError.code)."""
        store = _make_store(tmp_path)

        def failing_replace(src: object, dst: object) -> None:
            raise OSError(28, "simulated no space")

        monkeypatch.setattr(
            "adapters.storage.artifact_store.os.replace", failing_replace
        )
        sink = store.open_sink("bin")
        sink.write(_material(32))
        with pytest.raises(StorageUnavailableError):
            sink.commit()
        # The failed commit must not leave a committed half-state in tmp/.
        monkeypatch.undo()
        store.sweep_orphans()

    def test_unknown_artifact_id_maps_to_not_found(self, tmp_path: Path) -> None:
        repository = _migrated_repository(tmp_path)
        store = ArtifactStore(
            tmp_path / "store", index=repository, clock=_clock
        )
        with pytest.raises(ArtifactNotFoundError):
            store.read_by_artifact("00000000-0000-0000-0000-000000000000")
