"""Storage exception hierarchy (SPEC-502 section 7 error semantics).

Each class carries the SPEC-301/SPEC-300-style error code that the API layer
maps to its HTTP semantics (SPEC-502 section 7: storage unavailable -> 503,
non-dedup unique-constraint conflict -> 409). The HTTP mapping itself lives in
the API layer (SPEC-305), not here.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base class for every error raised by the storage adapter."""


class StorageUnavailableError(StorageError):
    """Storage backend cannot be opened/reached (SPEC-502 section 7 row 1).

    API-layer mapping: HTTP 503 (SPEC-305 section 7).
    """

    code = "OBS_STORAGE_UNAVAILABLE"


class MigrationError(StorageError):
    """Migration application failed (SPEC-502 section 7 row 4: fail-fast at
    startup, no degraded operation)."""


class StorageWriteFailure(StorageError):
    """Journal append failed (SPEC-502 section 7 row 2)."""

    code = "OBS_STORAGE_WRITE_FAILURE"


class StorageConflictError(StorageError):
    """Unique-constraint conflict outside the dedup path (SPEC-502 section 7
    row 3). API-layer mapping: HTTP 409."""

    code = "OBS_STORAGE_CONFLICT"


class InvalidEnvelopeError(StorageError):
    """Malformed event envelope rejected before journal commit
    (SPEC-301 section 9: OBS_INVALID_ENVELOPE)."""

    code = "OBS_INVALID_ENVELOPE"


__all__ = [
    "InvalidEnvelopeError",
    "MigrationError",
    "StorageConflictError",
    "StorageError",
    "StorageUnavailableError",
    "StorageWriteFailure",
]
