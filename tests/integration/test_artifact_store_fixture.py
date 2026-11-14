"""``artifact_store`` fixture behavior (SPEC-505 §4, serving SPEC-503).

Integration layer: real tmp filesystem resources. Content-addressed flat
layout per SPEC-503 §: ``<root>/artifacts/<sha256[:2]>/<sha256>.<ext>`` with
``<root>/tmp/`` for in-flight writes and atomic rename commit.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests._support.artifact_paths import (
    artifact_relative_path,
    compute_sha256,
)

_STAGED_ROOTS: list[Path] = []

_SAMPLE_BYTES = bytes(range(256))  # programmatic material, not TS payload


class TestStoreLayout:
    def test_root_skeleton_created(self, artifact_store):
        assert artifact_store.root.is_dir()
        assert artifact_store.artifacts_dir.is_dir()
        assert artifact_store.tmp_dir.is_dir()

    def test_content_addressed_relative_path(self):
        sha = "ab" + "0" * 62
        assert artifact_relative_path(sha, "ts") == f"artifacts/ab/{sha}.ts"

    def test_malformed_sha_rejected(self):
        with pytest.raises(ValueError):
            artifact_relative_path("zz" + "0" * 62, "ts")
        with pytest.raises(ValueError):
            artifact_relative_path("abcd", "ts")

    def test_compute_sha256_matches_hashlib(self):
        import hashlib

        assert compute_sha256(_SAMPLE_BYTES) == hashlib.sha256(_SAMPLE_BYTES).hexdigest()


class TestStaging:
    def test_stage_writes_final_content_and_empties_tmp(self, artifact_store):
        sha = compute_sha256(_SAMPLE_BYTES)
        final = artifact_store.stage_bytes(_SAMPLE_BYTES, ext="bin")
        assert final.read_bytes() == _SAMPLE_BYTES
        assert final == artifact_store.artifacts_dir / sha[:2] / f"{sha}.bin"
        assert list(artifact_store.tmp_dir.iterdir()) == []

    def test_same_content_stages_to_same_path_no_duplicate_file(self, artifact_store):
        first = artifact_store.stage_bytes(_SAMPLE_BYTES, ext="bin")
        second = artifact_store.stage_bytes(_SAMPLE_BYTES, ext="bin")
        assert first == second
        bucket = artifact_store.artifacts_dir / _SAMPLE_SHA[:2]
        files = list(bucket.iterdir())
        assert len(files) == 1

    def test_stage_uses_atomic_rename_protocol(self, artifact_store, monkeypatch):
        # os.replace is the commit primitive (SPEC-503 §): fail the final
        # rename and assert the tmp file still exists (no partial commit).
        calls = {"n": 0}
        real_replace = os.replace

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated crash before commit")
            return real_replace(src, dst)

        monkeypatch.setattr(
            "tests._support.artifact_paths.os.replace", flaky_replace
        )
        sha = compute_sha256(_SAMPLE_BYTES)
        with pytest.raises(OSError):
            artifact_store.stage_bytes(_SAMPLE_BYTES, ext="bin")
        assert calls["n"] == 1
        # no committed file, but the in-flight bytes survive in tmp/
        assert not (artifact_store.artifacts_dir / sha[:2] / f"{sha}.bin").exists()
        assert any(artifact_store.tmp_dir.iterdir())


class TestStoreIsolation:
    def test_first_store_root_recorded(self, artifact_store):
        _STAGED_ROOTS.append(artifact_store.root)

    def test_second_store_root_is_fresh(self, artifact_store):
        assert _STAGED_ROOTS, "first isolate test must run before this one"
        assert artifact_store.root not in _STAGED_ROOTS


_SAMPLE_SHA = compute_sha256(_SAMPLE_BYTES)
