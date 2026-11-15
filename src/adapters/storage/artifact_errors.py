"""Artifact-specific storage errors (SPEC-503 §7 error semantics).

Sibling of the M0-frozen :mod:`adapters.storage.errors` hierarchy: these
classes subclass :class:`~adapters.storage.errors.StorageError` so the API
layer can catch the whole storage family with one base type, while this
module stays a NEW file (journal/db/repositories/migrations are the frozen
M0 seam, ticket #23/#42 boundary).

HTTP mapping lives in the API layer (SPEC-305 §7), as for the M0 errors:

- :class:`ArtifactPathSafetyError` — caller misuse, never a storage fault;
  API maps to a 400-class client error.
- :class:`ArtifactTooLargeError` — SPEC-503 §7 row 2: over ``max_bytes`` →
  write failed, registration rejected, tmp file deleted.
- :class:`ArtifactCorruptError` — SPEC-503 §7 row 4: read-back ``verify``
  mismatch → 损坏处理 (HTTP 503 + alert record, consumable by SPEC-304
  ``OBS_STORAGE_WRITE_FAILURE``-class rules — hence that code).
- :class:`ArtifactNotFoundError` — SPEC-503 §7 row 3: unknown ``artifact_id``
  → HTTP 404.

Disk-full / permission failures reuse
:class:`~adapters.storage.errors.StorageUnavailableError` (HTTP 503) —
SPEC-503 §7 row 1 对齐 SPEC-305 §7 storage-unavailable semantics, and the
code already exists in the frozen module.
"""

from __future__ import annotations

from adapters.storage.errors import StorageError

__all__ = [
    "ArtifactCorruptError",
    "ArtifactNotFoundError",
    "ArtifactPathSafetyError",
    "ArtifactTooLargeError",
]


class ArtifactPathSafetyError(StorageError):
    """``relative_path`` rejected by the SPEC-503 §6 whitelist/resolve checks."""


class ArtifactTooLargeError(StorageError):
    """Write exceeded the configured ``max_bytes`` cap (SPEC-503 §8)."""


class ArtifactCorruptError(StorageError):
    """Stored content does not match its digest on verified read
    (SPEC-503 §7 row 4). code: SPEC-304 alert-rule family token."""

    code = "OBS_STORAGE_WRITE_FAILURE"


class ArtifactNotFoundError(StorageError):
    """Unknown ``artifact_id`` (SPEC-503 §7 row 3; API maps to HTTP 404)."""
