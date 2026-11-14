"""TSDuck CLI sibling resolution for the conformance cross-verification
modules (SPEC-506 §5 L2, ticket #38).

Moved here from ``tests/conformance/test_tsduck_cross_verification.py``
(review fix B6): the adapter cross module was importing its sibling test
module's underscore-private helper — cross-module private imports are a
layering smell, and ``tests/_support/`` is the sanctioned home for shared
test helpers. The function is renamed ``resolve_tool`` (public support
surface); both consumer modules call it, neither re-implements it.

Why a sibling lookup instead of ``shutil.which`` alone: TSDuck installs all
CLI tools into one bin directory next to ``tsp`` (tsduck-env.md §2.1), so
resolving from the already-probed executable is the authoritative location.
Disk names are matched case-insensitively (#69: CI winget layouts differ
from the reference machine's on-disk casing); ``PATH`` is the fallback for
nonstandard layouts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def resolve_tool(tsp_path: str, name: str) -> str:
    """Resolve a TSDuck CLI sibling (case-insensitive disk names, #69)."""
    directory = Path(tsp_path).parent
    for entry in directory.iterdir():
        if entry.name.lower() == f"{name}.exe" or entry.stem.lower() == name.lower():
            return str(entry)
    found = shutil.which(name)
    if found is None:
        pytest.fail(f"TSDuck CLI tool {name!r} not found next to {tsp_path!r}")
    return found
