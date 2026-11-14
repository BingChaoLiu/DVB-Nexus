"""Windows-first path helpers for the test tree (ADR-0004, ticket #22).

Rules baked in here (mirrored in tests/README.md):

- pathlib everywhere; no ``/tmp`` style assumptions — native Windows Python
  resolves ``/tmp`` to the current drive root, not the MSYS tmp.
- Repo locations are derived from ``__file__``, never from the process cwd,
  so pytest runs from any working directory agree on repo layout.
- Every file read/write in the test tree passes an explicit
  ``encoding="utf-8"`` (Windows default code page is cp936 and would
  silently corrupt CJK text).
"""

from __future__ import annotations

from pathlib import Path

#: tests/ root (this file lives at tests/_support/paths.py).
TESTS_DIR: Path = Path(__file__).resolve().parent.parent

#: Repository root (tests/ sits directly below it).
REPO_ROOT: Path = TESTS_DIR.parent

#: Static test data root (SPEC-505 §6: 静态数据入 tests/data/).
TESTS_DATA_DIR: Path = TESTS_DIR / "data"

#: Malformed-input assets (SPEC-506 §8 via #14: 畸形输入集不入 golden,
#: 落 tests/data/malformed/，unit 层测试).
TESTS_DATA_MALFORMED_DIR: Path = TESTS_DATA_DIR / "malformed"

#: Registered golden vector root (SPEC-506 §3 via #14 Q4: repo-level
#: docs/test-vectors/golden/). SPEC-505 §11: golden loader 与 SPEC-506
#: 共享测试资产根。
GOLDEN_ROOT: Path = REPO_ROOT / "docs" / "test-vectors" / "golden"


def repo_root() -> Path:
    """Absolute repository root (Windows path under ADR-0004)."""
    return REPO_ROOT


def tests_data_dir() -> Path:
    """Absolute static test-data root (may not exist yet; created on demand)."""
    return TESTS_DATA_DIR


def malformed_data_dir() -> Path:
    """Absolute malformed-input asset directory (may not exist yet)."""
    return TESTS_DATA_MALFORMED_DIR


def golden_root() -> Path:
    """Absolute root of SPEC-506 registered golden vectors."""
    return GOLDEN_ROOT


def registered_golden_ids() -> list[str]:
    """Vector ids currently registered under the golden root.

    A vector is registered iff its three-piece set directory exists
    (``<root>/<vector_id>/`` with ``manifest.json``); the loader enforces
    the rest of the trio (SPEC-506 §3 三件套缺一不予登记).
    """
    root = GOLDEN_ROOT
    if not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "manifest.json").is_file()
    )
