"""Tee double-write landing protocol (SPEC-503 §4 + ADR-0007 item 2,
REQ-PLT-503-002; ruling authority: GitHub #12/#13).

The store is the *landing point* provider for the tee; SIM-D wires the
legs. Per ADR-0007 item 2, a run with a fault plan produces:

- pre-filter stream → baseline sink (kind ``generated_ts``);
- post-filter stream → faulted sink (kind ``faulted_ts``);
- mutation log artifact (kind ``log``, the AC-204-04 evidence locator
  carrier).

All three legs go through the SAME tmp → atomic-rename → index protocol;
a repeated baseline (identical content) dedups by SHA-256 — one physical
file, a new index row per run (去重 = 引用不复制, SPEC-503 §3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from adapters.storage import db
from adapters.storage.artifact_store import ArtifactStore, SinkCommit
from adapters.storage.repositories import SqliteArtifactRepository
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir

_KINDS = ("generated_ts", "faulted_ts", "log")


def _ts_like(size: int, seed: int) -> bytes:
    """Programmatic payload material (tests/README.md §5: no hand-assembled
    literals) — deterministic per seed, mimicking a generated stream leg."""
    return bytes((seed + (i * 7) % 251) % 256 for i in range(size))


def _mutation_log(run_id: str) -> bytes:
    """Programmatic mutation-log payload (the kind=log evidence carrier)."""
    return ("mutation-log:" + run_id).encode("utf-8")


_FIXED_CLOCK_MS = 1_700_000_100_000


def _clock() -> int:
    return _FIXED_CLOCK_MS


def _store_with_index(
    tmp_path: Path, dirname: str
) -> tuple[ArtifactStore, SqliteArtifactRepository]:
    connection = db.connect(tmp_path / f"{dirname}.sqlite3")
    apply_sql_migrations(connection, default_migrations_dir())
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(tmp_path / dirname, index=repository, clock=_clock)
    return store, repository


class TestTeeLandingProtocol:
    def test_three_legs_produce_three_kinds(self, tmp_path: Path) -> None:
        """One fault-plan run: three sinks committed and registered → three
        index rows with kinds generated_ts / faulted_ts / log (ADR-0007 §2)."""
        store, repository = _store_with_index(tmp_path, "tee-run-1")
        session_id, run_id = "session-1", "run-1"
        baseline_bytes = _ts_like(376, seed=1)  # 2 × 188-packet-like payload
        faulted_bytes = _ts_like(376, seed=2)
        log_bytes = _mutation_log(run_id)

        # The tee legs: pre-filter → baseline; post-filter → faulted + log.
        baseline_commit = _land(store, baseline_bytes, "ts")
        faulted_commit = _land(store, faulted_bytes, "ts")
        log_commit = _land(store, log_bytes, "log")

        ids = [
            store.register(
                commit,
                run_id=run_id,
                session_id=session_id,
                kind=kind,
                packet_size=188,
                packet_count=2 if kind != "log" else None,
            )
            for commit, kind in zip(
                (baseline_commit, faulted_commit, log_commit), _KINDS
            )
        ]
        rows = [repository.get(artifact_id) for artifact_id in ids]
        assert [row.kind for row in rows] == list(_KINDS)
        assert {row.run_id for row in rows} == {run_id}
        assert {row.session_id for row in rows} == {session_id}
        # Kind → extension follows the SPEC-503 §3 mapping.
        assert rows[0].relative_path.endswith(".ts")
        assert rows[1].relative_path.endswith(".ts")
        assert rows[2].relative_path.endswith(".log")
        # tmp/ drained — no in-flight legs left after commit.
        assert list(store.tmp_dir.iterdir()) == []

    def test_repeated_baseline_dedups_to_one_file(self, tmp_path: Path) -> None:
        """Second run with the SAME baseline content: the SHA-256 hit means
        no second physical file — a new index row references the original
        (SPEC-503 §3 去重 = 引用不复制; ADR-0007 §2 重复 baseline 去重)."""
        store, repository = _store_with_index(tmp_path, "tee-run-2")
        baseline_bytes = _ts_like(376, seed=1)
        first_commit = _land(store, baseline_bytes, "ts")
        first_id = store.register(
            first_commit,
            run_id="run-1",
            session_id="session-1",
            kind="generated_ts",
            packet_size=188,
            packet_count=2,
        )

        # Run 2: identical pre-filter stream. Content-addressed hit on
        # store_bytes — the file is referenced, not copied.
        second_ref = store.store_bytes(baseline_bytes, ext="ts")
        assert second_ref.deduplicated is True
        assert second_ref.relative_path == first_commit.relative_path
        second_id = store.register(
            SinkCommit(
                sha256=second_ref.sha256,
                byte_size=second_ref.byte_size,
                relative_path=second_ref.relative_path,
            ),
            run_id="run-2",
            session_id="session-1",
            kind="generated_ts",
            packet_size=188,
            packet_count=2,
        )

        assert first_id != second_id
        rows = repository.find_by_sha256(first_commit.sha256)
        assert {row.artifact_id for row in rows} == {first_id, second_id}
        assert {row.run_id for row in rows} == {"run-1", "run-2"}
        assert len({row.relative_path for row in rows}) == 1
        bucket = store.artifacts_dir / first_commit.sha256[:2]
        assert [p.name for p in bucket.iterdir()] == [
            f"{first_commit.sha256}.ts"
        ]

    def test_read_back_baseline_matches_bytes(self, tmp_path: Path) -> None:
        """Round-trip: the registered baseline reads back byte-identical and
        passes verify=True (digest equals the content address)."""
        store, repository = _store_with_index(tmp_path, "tee-run-3")
        baseline_bytes = _ts_like(376, seed=1)
        commit = _land(store, baseline_bytes, "ts")
        artifact_id = store.register(
            commit, run_id="run-1", session_id="s-1", kind="generated_ts"
        )
        assert store.read_by_artifact(artifact_id) == baseline_bytes
        assert store.read_bytes(commit.relative_path, verify=True) == baseline_bytes
        assert (
            hashlib.sha256(store.read_bytes(commit.relative_path)).hexdigest()
            == commit.sha256
        )


def _land(store: ArtifactStore, data: bytes, ext: str) -> SinkCommit:
    """Land one tee leg through the streaming sink protocol."""
    sink = store.open_sink(ext)
    # Stream in two chunks to keep the protocol streaming-shaped.
    half = len(data) // 2
    sink.write(data[:half])
    sink.write(data[half:])
    return sink.commit()
