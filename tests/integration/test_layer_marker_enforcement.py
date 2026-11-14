"""End-to-end enforcement of layer marker discipline via real pytest runs.

Integration layer: real subprocesses + temporary in-tree files (SPEC-505 §3
integration I/O class). The root conftest hook must (a) inject the layer
marker for unmarked tests so directory stays the layer source of truth, and
(b) hard-fail collection when a test carries a layer marker contradicting
its directory — a structural violation per SPEC-505 §8.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from tests._support.paths import repo_root


def _run_pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )


def _in_tree_test_file(layer_dir: str, body: str) -> Path:
    """Unique in-tree test file; caller MUST remove it (try/finally)."""
    path = repo_root() / "tests" / layer_dir / f"_tmp_probe_{uuid.uuid4().hex[:8]}_test.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_unmarked_layer_test_is_injected_and_collects():
    body = "def test_injected():\n    assert True\n"
    path = _in_tree_test_file("unit", body)
    try:
        result = _run_pytest("--collect-only", "-q", str(path))
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no tests collected" not in result.stdout


def test_contradictory_layer_marker_hard_fails_collection():
    body = 'import pytest\n\n\n@pytest.mark.integration\ndef test_wrong_layer():\n    assert True\n'
    path = _in_tree_test_file("unit", body)
    try:
        result = _run_pytest("--collect-only", "-q", str(path))
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode != 0, "structural violation must not collect silently"
    combined = result.stdout + result.stderr
    assert "integration" in combined
    assert "unit" in combined


def test_matching_layer_marker_collects_cleanly():
    body = 'import pytest\n\n\n@pytest.mark.unit\ndef test_matching():\n    assert True\n'
    path = _in_tree_test_file("unit", body)
    try:
        result = _run_pytest("--collect-only", "-q", str(path))
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr
