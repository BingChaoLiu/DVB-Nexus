"""``tsduck`` fixture behavior (SPEC-505 §4, serving SPEC-308).

Integration layer: the probe launches a real subprocess (``--version``) or
detects absence. The probe itself is the PRODUCTION implementation
(``adapters.tsduck.version``, review-fix #3 consolidation): PATH-first
discovery with fallback roots, two-tier version-line scan, UTF-8→GBK decode,
both-streams search. The unmarked tests here validate the fixture **result
structure** regardless of whether TSDuck is installed (branching asserts).
The marked tests (``tsduck`` marker) run only where the CLI exists: local
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
            assert probe.version  # canonical version line per SPEC-308
        else:
            assert probe.executable is None
            assert "tsp" in probe.detail

    def test_missing_override_path_is_unavailable(self):
        probe = probe_tsp(override=r"Z:\definitely\not\here\tsp.exe")
        assert probe.available is False
        assert probe.executable is None
        assert TSP_ENV_OVERRIDE in probe.detail or "override" in probe.detail.lower()

    def test_non_tsduck_executable_output_never_yields_a_version(self):
        # Unified production policy (review-fix #3): the version pattern,
        # not the exit code, is the validity gate (ticket #3). `python
        # --version` prints a Python version — never the canonical TSDuck
        # version token — so the interpreter itself is never reported as a
        # usable TSDuck with a version. (The scaffold-era claim "any
        # executable with a --version is available with version=None" is
        # gone: exit-0 output without the canonical line is
        # version_unparseable, pinned at the production API by
        # test_probe_fakes.py::TestVersionGate.) An explicit override that
        # fails falls through to PATH/fallback candidates (production
        # override semantics), so on TSDuck-equipped machines the probe can
        # still end up available — via the real TSDuck, never via python.
        probe = probe_tsp(override=sys.executable)
        python_version = sys.version.split()[0]
        assert probe.version != python_version
        if probe.available:
            assert probe.raw_version_line is not None
            assert "TSDuck" in probe.raw_version_line
        else:
            assert probe.version is None
