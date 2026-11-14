"""Pytest configuration surface, verified through real pytest runs.

Seam 1 of ticket #22 (delegator-approved): marker enforcement — an
unregistered marker is a hard collection failure; the four layers collect;
the CI gate marker expressions parse and select/deselect as designed.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests._support.paths import REPO_ROOT

#: The seven SPEC-505 §5 markers, parsed from pyproject (single source of
#: truth) so this test fails if registration drifts.
_MARKER_LINE = re.compile(r'^\s*"([a-z_0-9]+):')


def registered_markers() -> set[str]:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.pytest.ini_options]", 1)[1]
    names: set[str] = set()
    for line in section.splitlines():
        match = _MARKER_LINE.match(line)
        if match:
            names.add(match.group(1))
        if line.strip().startswith("[") and not line.strip().startswith('"'):
            break
    return names


def _run_pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )


class TestMarkerRegistration:
    def test_all_seven_spec505_markers_registered(self):
        assert registered_markers() == {
            "unit",
            "integration",
            "conformance",
            "e2e",
            "slow",
            "tsduck",
            "windows_only",
        }

    def test_pytest_markers_cli_lists_registered_markers(self):
        result = _run_pytest("--markers")
        assert result.returncode == 0
        for name in registered_markers():
            assert f"@pytest.mark.{name}" in result.stdout

    def test_unregistered_marker_is_hard_collection_failure(self):
        probe = (
            REPO_ROOT
            / "tests"
            / "unit"
            / f"_tmp_unknown_marker_{uuid.uuid4().hex[:8]}_test.py"
        )
        probe.write_text(
            "import pytest\n\n\n@pytest.mark.not_a_marker\ndef test_x():\n"
            "    assert True\n",
            encoding="utf-8",
        )
        try:
            result = _run_pytest("--collect-only", "-q", str(probe))
        finally:
            probe.unlink(missing_ok=True)
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "not_a_marker" in combined


class TestLayerCollection:
    def test_four_layers_collect_from_bare_run(self):
        result = _run_pytest("--collect-only", "-q")
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for layer in ("unit", "integration", "conformance", "e2e"):
            assert f"tests/{layer}/" in combined.replace("\\", "/")

    @pytest.mark.parametrize(
        "expression",
        [
            "(unit or integration or conformance or e2e) and not (tsduck or slow)",
            "windows_only or tsduck",
            "slow",
        ],
    )
    def test_ci_gate_marker_expressions_parse(self, expression: str):
        result = _run_pytest("-m", expression, "--collect-only", "-q")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gate_expression_excludes_slow_and_tsduck(self):
        result = _run_pytest(
            "-m",
            "(unit or integration or conformance or e2e) and not (tsduck or slow)",
            "--collect-only",
            "-q",
        )
        assert result.returncode == 0
        assert "deselected" in (result.stdout + result.stderr)
