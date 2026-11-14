"""``tsduck`` fixture behavior (SPEC-505 §4, serving SPEC-308).

Integration layer: the probe launches a real subprocess (``--version``) or
detects PATH absence. The unmarked tests here validate the probe **result
structure** regardless of whether TSDuck is installed (branching asserts).
The marked test (``tsduck`` marker) runs only where the CLI exists: local
with TSDuck installed, or the Windows CI job after the winget install
(#14: tsduck 标记测试 CI 全量跑，安装失败 = CI 失败).
"""

from __future__ import annotations

import sys

from tests._support.tsduck_probe import TSP_ENV_OVERRIDE, probe_tsp


class TestProbeStructure:
    def test_probe_returns_immutable_result(self):
        probe = probe_tsp()
        assert isinstance(probe.available, bool)
        assert probe.detail  # always a human-readable reason
        if probe.available:
            assert probe.executable
            assert probe.version  # measured regex per SPEC-308
        else:
            assert probe.executable is None
            assert "tsp" in probe.detail

    def test_missing_override_path_is_unavailable(self):
        probe = probe_tsp(override=r"Z:\definitely\not\here\tsp.exe")
        assert probe.available is False
        assert probe.executable is None
        assert TSP_ENV_OVERRIDE in probe.detail or "override" in probe.detail.lower()

    def test_python_interpreter_as_fake_cli(self):
        # Hermetic positive path: any executable with a --version works;
        # `python --version` prints "Python 3.x.y" which has no version
        # token matching the measured TSDuck regex → available with
        # version=None and the raw line surfaced.
        probe = probe_tsp(override=sys.executable)
        assert probe.available is True
        assert probe.executable == sys.executable
        assert probe.raw_version_line.startswith("Python ")
        assert probe.version is None
