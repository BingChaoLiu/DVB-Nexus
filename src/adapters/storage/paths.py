"""Path safety for the artifact store (SPEC-503 §6, REQ-PLT-503-004).

Two independent gates, both mandatory for every relative path that reaches
the filesystem:

1. **Whitelist gate** (:func:`validate_relative_path`): the SPEC-503 §6
   pattern ``^[a-z0-9][a-z0-9/_.-]*$`` plus structural rejections the
   pattern alone cannot express — ``..`` / ``.`` segments, empty segments,
   trailing separators/dots, and Windows reserved device names
   (case-insensitive, ADR-0004). Absolute paths, drive letters, backslash
   separators, uppercase and whitespace all fall outside the whitelist by
   construction, so Windows path-shape attacks are rejected before any
   filesystem call.
2. **Containment gate** (:func:`resolve_within_root`): the fully resolved
   path must stay inside the store root — defeats symlink escapes planted
   inside ``artifacts/`` (SPEC-503 §6: ``artifacts/`` 内禁符号链接).

Store output is relative-path-only (SPEC-003 §2.7: the API layer never
returns absolute paths); error messages echo the rejected input, never a
resolved absolute path.
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

from adapters.storage.artifact_errors import ArtifactPathSafetyError

__all__ = [
    "ALLOWED_EXTENSIONS",
    "RELATIVE_PATH_PATTERN",
    "artifact_layout_relative_path",
    "resolve_within_root",
    "validate_relative_path",
]

#: SPEC-503 §6 whitelist: lowercase alphanumeric start, then lowercase
#: alphanumerics with / _ . - only. Everything else (uppercase, backslash,
#: drive letters, whitespace, null bytes, ``:`` ADS separators) is rejected.
RELATIVE_PATH_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/_.-]*$")

#: Windows reserved device names (Win32 namespace), compared per segment
#: stem case-insensitively — ADR-0004 Windows-first hardening; a path the
#: store writes must never collide with a device name on any Windows volume.
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in "123456789"}
    | {f"lpt{digit}" for digit in "123456789"}
)

#: Content-addressed extensions (SPEC-503 §3: kind → ts / json / log / bin).
ALLOWED_EXTENSIONS = frozenset({"ts", "json", "log", "bin"})

_SHA256_HEX_LENGTH = 64
_ARTIFACTS_DIRNAME = "artifacts"


def _reject(relative_path: str, reason: str) -> None:
    raise ArtifactPathSafetyError(
        f"unsafe artifact relative_path {relative_path!r}: {reason}"
    )


def _segment_stem(segment: str) -> str:
    """Name before the first dot (Windows treats the pre-dot part as the
    device name for reserved-name matching, e.g. ``CON.ts`` ≡ ``CON``)."""
    return segment.split(".", 1)[0]


def validate_relative_path(relative_path: str) -> str:
    """Whitelist gate. Returns the path unchanged when safe; raises
    :class:`ArtifactPathSafetyError` otherwise."""
    if not relative_path:
        _reject(relative_path, "empty path")
    if "\\" in relative_path:
        _reject(relative_path, "backslash separator (Windows path confusion)")
    if not RELATIVE_PATH_PATTERN.match(relative_path):
        _reject(
            relative_path,
            "outside whitelist ^[a-z0-9][a-z0-9/_.-]*$ (absolute path, drive "
            "letter, uppercase or illegal character)",
        )
    segments = relative_path.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            _reject(
                relative_path,
                f"illegal {segment!r} segment (parent/dot/empty traversal)",
            )
        if segment.endswith("."):
            _reject(relative_path, f"segment {segment!r} ends with a dot")
        if _segment_stem(segment).lower() in _WINDOWS_RESERVED_STEMS:
            _reject(
                relative_path,
                f"segment {segment!r} is a Windows reserved device name",
            )
    # Belt-and-braces for the Windows namespace: PureWindowsPath flags
    # drive-relative and UNC shapes even when the regex let an odd form by.
    if PureWindowsPath(relative_path).is_absolute():
        _reject(relative_path, "absolute path in Windows semantics")
    return relative_path


def artifact_layout_relative_path(sha256_hex: str, ext: str) -> str:
    """SPEC-503 §3 content-addressed layout path
    ``artifacts/<sha256[:2]>/<sha256>.<ext>`` (filename = content digest)."""
    sha = sha256_hex.strip().lower()
    if (
        len(sha) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in sha)
    ):
        raise ArtifactPathSafetyError(
            f"sha256 must be {_SHA256_HEX_LENGTH} lowercase hex chars, got {sha256_hex!r}"
        )
    if ext not in ALLOWED_EXTENSIONS:
        raise ArtifactPathSafetyError(
            f"extension {ext!r} outside the SPEC-503 §3 set {sorted(ALLOWED_EXTENSIONS)}"
        )
    return f"{_ARTIFACTS_DIRNAME}/{sha[:2]}/{sha}.{ext}"


def resolve_within_root(root: Path, relative_path: str) -> Path:
    """Containment gate: validate, then resolve under ``root`` and require
    the result to stay inside it (symlink escape defense, SPEC-503 §6)."""
    validate_relative_path(relative_path)
    resolved_root = Path(root).resolve()
    resolved = (Path(root) / Path(*relative_path.split("/"))).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise ArtifactPathSafetyError(
            f"unsafe artifact relative_path {relative_path!r}: "
            "resolves outside the store root"
        ) from None
    return resolved
