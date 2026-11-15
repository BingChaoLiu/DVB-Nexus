"""Path safety matrix, one test per matrix cell (SPEC-503 §6, REQ-PLT-503-004).

Matrix authority: GitHub issue #13 (SPEC-503 approval resolution) —
``relative_path`` whitelist ``^[a-z0-9][a-z0-9/_.-]*$``; ``..`` segments,
absolute paths and backslashes rejected; ``resolve()`` must stay inside the
store root (symlink escape); Windows semantics per ADR-0004 (case
insensitivity, reserved device names, drive letters, separators) — asserted
as *shape* rejections, never pinned to a concrete drive or on-disk casing
(tests/README.md §6).

The store never hands out absolute paths (SPEC-003 §2.7): the store-produced
relative path surface is the whitelist, so on-disk casing ambiguity cannot
arise from store output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.storage.artifact_errors import ArtifactPathSafetyError
from adapters.storage.paths import resolve_within_root, validate_relative_path

#: (relative_path, rejected-because) — one matrix cell per row. All inputs are
#: synthetic strings; none is an environment assumption (no real drive paths).
UNSAFE_RELATIVE_PATHS: list[tuple[str, str]] = [
    ("artifacts/../evil.bin", "parent segment escapes the root"),
    ("..", "bare parent segment"),
    ("artifacts/aa/../bb.bin", "parent segment mid-path"),
    ("/etc/passwd", "absolute path (leading separator)"),
    ("C:/artifacts/x.ts", "drive-letter absolute path"),
    ("artifacts\\aa\\x.ts", "backslash separator"),
    ("ARTIFACTS/AA/x.ts", "uppercase outside whitelist (Windows case-insensitivity)"),
    ("Artifacts/aa/x.ts", "mixed-case segment stem"),
    ("artifacts/CON.ts", "Windows reserved device name (CON)"),
    ("con.ts", "reserved device name bare"),
    ("tmp/nul.bin", "reserved device name, lowercase form"),
    ("artifacts/COM1.ts", "reserved COM port name"),
    ("artifacts/LPT4.log", "reserved LPT port name"),
    ("artifacts/./x.bin", "dot segment"),
    ("artifacts//x.bin", "empty segment (double separator)"),
    ("artifacts/", "trailing separator"),
    ("artifacts/x.bin.", "trailing dot (Windows strips trailing dots)"),
    ("", "empty path"),
    ("artifacts/\x00.bin", "embedded null byte"),
    (" artifacts/x.bin", "leading whitespace outside whitelist"),
    ("artifacts/x bin.bin", "space inside segment outside whitelist"),
    ("artifacts/x.bin ", "trailing whitespace outside whitelist"),
    ("**/x.bin", "glob characters outside whitelist"),
    ("artifacts/x.bin:ads", "NTFS alternate data stream separator"),
]

#: Layout-legal relative paths the whitelist must keep accepting.
SAFE_RELATIVE_PATHS = [
    "artifacts/ab/" + "0" * 62 + ".ts",
    "artifacts/cd/" + "1" * 62 + ".json",
    "artifacts/ef/" + "2" * 62 + ".log",
    "artifacts/01/" + "3" * 62 + ".bin",
    "artifacts/aa/deep/nested/x.bin",
]


@pytest.mark.parametrize(("relative_path", "reason"), UNSAFE_RELATIVE_PATHS)
def test_validate_relative_path_rejects_matrix_cell(
    relative_path: str, reason: str
) -> None:
    with pytest.raises(ArtifactPathSafetyError) as excinfo:
        validate_relative_path(relative_path)
    # Rejection never leaks a resolved absolute path (SPEC-003 §2.7: the API
    # layer never returns absolute paths — errors echo the *repr* of the
    # input, if anything).
    assert repr(relative_path) in str(excinfo.value)


@pytest.mark.parametrize("relative_path", SAFE_RELATIVE_PATHS)
def test_validate_relative_path_accepts_layout_paths(relative_path: str) -> None:
    assert validate_relative_path(relative_path) == relative_path


def test_resolve_within_root_keeps_layout_path_inside_root(tmp_path: Path) -> None:
    sha = "ab" + "0" * 62
    relative = f"artifacts/{sha[:2]}/{sha}.ts"
    resolved = resolve_within_root(tmp_path, relative)
    expected = tmp_path / Path(*relative.split("/"))
    assert resolved == expected.resolve()
    assert resolved.is_relative_to(tmp_path.resolve())


def test_resolve_within_root_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink planted inside artifacts/ must not let reads leave the root."""
    outside_file = tmp_path.parent / "outside-of-store-target.bin"
    outside_file.write_bytes(b"outside")
    link = tmp_path / "artifacts" / "escape.bin"
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip(
            "symlink creation unsupported on this filesystem/account "
            "(Windows without symlink privilege) — explicit skip, not silent"
        )
    with pytest.raises(ArtifactPathSafetyError):
        resolve_within_root(tmp_path, "artifacts/escape.bin")
