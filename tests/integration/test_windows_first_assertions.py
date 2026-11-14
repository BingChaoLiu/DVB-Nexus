"""``windows_only`` assertions — ADR-0004 Windows-first discipline
(SPEC-505 §5 REQ-TST-505-005).

These run on the Windows CI job (必跑) and skip with an explicit reason
elsewhere (root conftest guard) — never silently degraded. They anchor the
Windows-first path handling that the whole test infrastructure relies on:
pathlib everywhere, repo paths derived from ``__file__``, explicit UTF-8,
no ``/tmp`` assumptions.
"""

from __future__ import annotations

import os

import pytest

from tests._support.paths import GOLDEN_ROOT, REPO_ROOT, TESTS_DIR

pytestmark = [pytest.mark.windows_only]


class TestWindowsPathInvariants:
    def test_path_separator_is_native_windows(self):
        assert os.sep == "\\"

    def test_repo_root_is_absolute_windows_path(self):
        assert REPO_ROOT.is_absolute()
        assert REPO_ROOT.drive  # e.g. "D:" — a real Windows drive path
        assert not str(REPO_ROOT).startswith("/tmp")

    def test_support_path_constants_resolve_on_real_fs(self):
        assert TESTS_DIR.is_dir()
        assert GOLDEN_ROOT.is_dir()

    def test_tmp_path_is_windows_native_and_utf8_safe(self, tmp_path):
        assert tmp_path.drive
        probe = tmp_path / "probe.txt"
        probe.write_text("windows-first 路径", encoding="utf-8")
        assert probe.read_text(encoding="utf-8") == "windows-first 路径"
