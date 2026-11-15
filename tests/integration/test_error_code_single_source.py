"""Error-code single-source gate (M4 retro finding A3).

Platform error/event codes are registry facts: one code, one defining
module. M4 shipped ``OBS_CURSOR_EXPIRED`` as parallel definitions
(``application/observation/timeline/errors.py`` canonical, ``query/
errors.py`` a re-typed literal) — a spelling fork would silently break
every comparison (fixed in the M4 review round F1 by importing the
canonical constant). This gate makes the class mechanical: scan every
registry-named source file (``*errors*.py`` / ``codes*.py``) under
``src/``, collect compile-time ``UPPER_SNAKE`` string constants (module
level and class members — covers both ``StrEnum``-style tables and plain
module constants), and fail when one string value is defined in more
than one file.

Scope honesty (conservative boundary, same philosophy as the other AST
rules): code strings assembled dynamically (``f"HTTP_{status}"`` in
``api/errors.py``) and literals in non-registry files (route stubs
rendering ``"HTTP_501"``) are rendering sites, not definitions, and stay
review-visible rather than machine-caught here.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

from tests._support.paths import repo_root

pytestmark = pytest.mark.integration

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _registry_files() -> list[Path]:
    src_root = repo_root() / "src"
    return sorted(
        path
        for path in src_root.rglob("*.py")
        if "errors" in path.name or path.name.startswith("codes")
    )


def _defined_code_values(source: str) -> set[str]:
    tree = ast.parse(source)
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.AST] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        text = value.value
        if not _CODE_RE.match(text):
            continue
        if any(isinstance(target, ast.Name) and _CODE_RE.match(target.id) for target in targets):
            values.add(text)
    return values


class TestErrorCodeSingleSource:
    def test_no_code_string_defined_in_two_registry_files(self) -> None:
        locations: dict[str, set[str]] = defaultdict(set)
        for path in _registry_files():
            for value in _defined_code_values(
                path.read_text(encoding="utf-8")
            ):
                locations[value].add(str(path.relative_to(repo_root())))
        duplicated = {
            value: sorted(files)
            for value, files in locations.items()
            if len(files) > 1
        }
        assert duplicated == {}, (
            "error/event code strings defined in more than one registry "
            "file — import the canonical constant instead of re-typing "
            "(spelling forks break comparisons silently):\n"
            + "\n".join(
                f"{value}: {', '.join(files)}"
                for value, files in sorted(duplicated.items())
            )
        )
