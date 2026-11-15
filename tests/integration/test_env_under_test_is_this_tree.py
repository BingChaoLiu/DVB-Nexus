"""Guard: the imported project packages resolve under this checkout's src.

M3 retro finding: worktrees share the main checkout's ``.venv``, whose
editable install points at the main repo's ``src`` — a bare ``pytest`` in
a worktree then silently verifies the main tree while reporting green
(observed on M3 #40: ``lint-imports`` analyzed 107 files instead of 108
and passed). The pyproject ``pythonpath`` entry (rootdir-relative
``src``) makes pytest self-correct — insert(0) semantics outrank the
stale .pth entry and any PYTHONPATH; this test is the standing detection
if that entry regresses or a future runner bypasses pytest config.

CI is immune by construction: ``.github/workflows/tests.yml`` installs
``-e .`` from the same checkout, so imports already resolve under this
tree. The lint-imports path (grimp, not pytest) still needs
``PYTHONPATH=$PWD/src`` in worktrees — docs/agents/windows-shell.md.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from tests._support.paths import REPO_ROOT

#: The project's root packages (mirrors [tool.importlinter] root_packages:
#: the names a worktree run could silently resolve to another checkout).
ROOT_PACKAGES = (
    "adapters",
    "api",
    "application",
    "domain",
    "faults",
    "knowledge",
    "simulation",
    "ts",
)


@pytest.mark.parametrize("package", ROOT_PACKAGES)
def test_imported_package_resolves_under_this_tree(package: str) -> None:
    module = importlib.import_module(package)
    module_file = Path(module.__file__).resolve()
    expected_root = (REPO_ROOT / "src").resolve()
    assert expected_root in module_file.parents, (
        f"`{package}` resolved to `{module_file}`, which is not under this "
        f"tree's src ({expected_root}). A shared .venv editable install is "
        "pointing at another checkout; run worktree checks with "
        "PYTHONPATH=$PWD/src (docs/agents/windows-shell.md)."
    )
