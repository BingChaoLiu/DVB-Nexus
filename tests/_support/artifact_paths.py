"""Artifact-store path support for the ``artifact_store`` fixture
(SPEC-505 §4 → SPEC-503).

Implements the SPEC-503 content-addressed flat layout and the write
protocol's path mechanics:

- ``<root>/artifacts/<sha256[:2]>/<sha256>.<ext>``  (content addressing);
- ``<root>/tmp/`` for in-flight writes, committed via ``os.replace``
  atomic rename ("先文件后索引" ordering is the storage adapter's
  obligation — the index-DB half is the SPEC-502/503 implementation seam,
  not test infra).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

_ARTIFACTS_DIRNAME = "artifacts"
_TMP_DIRNAME = "tmp"

#: sha256 hex digest length.
SHA256_HEX_LENGTH = 64


def compute_sha256(data: bytes) -> str:
    """Lowercase sha256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _validate_sha256(sha256_hex: str) -> str:
    normalized = sha256_hex.strip().lower()
    if len(normalized) != SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(
            f"sha256 must be {SHA256_HEX_LENGTH} lowercase hex chars, got {sha256_hex!r}"
        )
    return normalized


def artifact_relative_path(sha256_hex: str, ext: str) -> str:
    """SPEC-503 content-addressed relative path ``artifacts/<aa>/<sha>.<ext>``."""
    sha = _validate_sha256(sha256_hex)
    if not ext or "/" in ext or "\\" in ext or ext.startswith("."):
        raise ValueError(f"invalid extension: {ext!r}")
    return f"{_ARTIFACTS_DIRNAME}/{sha[:2]}/{sha}.{ext}"


class ArtifactStoreHandle:
    """Handle yielded by the ``artifact_store`` fixture (fresh per test)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.artifacts_dir = self.root / _ARTIFACTS_DIRNAME
        self.tmp_dir = self.root / _TMP_DIRNAME
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def content_path(self, sha256_hex: str, ext: str = "bin") -> Path:
        """Final content-addressed path for a digest (not guaranteed to exist)."""
        return self.root / artifact_relative_path(sha256_hex, ext)

    def stage_bytes(self, data: bytes, ext: str = "bin") -> Path:
        """Write bytes through the tmp + atomic rename protocol.

        SPEC-503 §: create a uniquely-named in-flight file in ``tmp/``,
        then ``os.replace`` it onto the content-addressed final path
        (atomic on same-volume rename; Windows included). Fails loudly
        before committing anything if the rename fails — the in-flight
        file stays in ``tmp/`` for the startup-sweep semantics to clean.
        """
        sha = compute_sha256(data)
        final = self.content_path(sha, ext)
        final.parent.mkdir(parents=True, exist_ok=True)
        in_flight = self.tmp_dir / f"{uuid.uuid4().hex}.{ext}"
        in_flight.write_bytes(data)
        os.replace(in_flight, final)
        return final
