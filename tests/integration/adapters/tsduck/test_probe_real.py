"""Real-TSDuck acceptance tests (ticket #25 acceptance, seam 1).

Delegator seam 1: found-path on this machine — TSDuck 3.40-4165 measured
(docs/research/tsduck-env.md §2; re-measured for #25 on 2026-11-14: stdout
empty, one stderr line with the ``tsp: `` program prefix). These tests need
the real CLI and carry the ``tsduck`` marker + the conftest ``tsduck``
fixture (explicit skip with a visible reason when TSDuck is absent — the
CI Windows job installs TSDuck.TSDuck via winget per #14).

The version pin ``3.40-4165`` is the repo's locked test baseline
(tsduck-env.md §3.3 建议锁定测试基线版本); upgrading the local TSDuck
requires a conscious baseline bump of these literals.
"""

import shutil
from pathlib import Path

import pytest

from adapters.tsduck.version import (
    ResolutionSource,
    TSDuckVersionProbe,
    VersionStream,
    probe_tsduck,
)

pytestmark = [pytest.mark.tsduck, pytest.mark.windows_only]

#: Measured install root of the reference machine (tsduck-env.md §2.1).
MEASURED_INSTALL_BIN = Path("D:\\Program Files\\TSDuck\\bin")
MEASURED_VERSION = "3.40-4165"


class TestRealFoundPath:
    def test_probe_finds_local_tsduck_with_parsed_components(self, tsduck):
        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.reason is None
        assert result.version is not None
        assert result.version.version == MEASURED_VERSION
        assert (result.version.major, result.version.minor, result.version.build) == (
            3,
            40,
            4165,
        )
        # Measured: `where tsp` hits PATH on this machine → PATH-first wins.
        assert result.version.resolution is ResolutionSource.PATH
        # Measured (×3: tsduck-env.md §2.1, ticket #22 probe scaffold, #25
        # re-measurement): `tsp --version` prints the line to STDERR with
        # stdout empty.
        assert result.version.stream is VersionStream.STDERR
        assert (
            "TSDuck - The MPEG Transport Stream Toolkit" in result.version.raw_version_line
        )
        assert result.version.executable == Path(shutil.which("tsp"))
        assert result.detail

    def test_probe_consistent_with_spec505_fixture(self, tsduck):
        # The SPEC-505 §4 fixture probe (tests/_support, ticket #22) and the
        # production probe must agree on the version token on this machine.
        result = TSDuckVersionProbe().probe()
        assert result.version is not None
        assert tsduck.version == result.version.version


class TestRealFallback:
    def test_drive_scan_fallback_finds_off_path_install(self, tsduck, tmp_path, monkeypatch):
        # The reference machine keeps TSDuck at D:\Program Files\TSDuck\bin
        # (tsduck-env.md §2.1, "自定义盘安装路径" §6.2). With PATH stripped to
        # an empty dir, the default fallback roots must find it through the
        # logical-drive scan.
        empty_path_dir = tmp_path / "empty_path"
        empty_path_dir.mkdir()
        monkeypatch.setenv("PATH", str(empty_path_dir))

        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.version is not None
        assert result.version.version == MEASURED_VERSION
        assert result.version.resolution is ResolutionSource.FALLBACK
        assert result.version.executable == MEASURED_INSTALL_BIN / "tsp.exe"


class TestDefaultProbeFunction:
    def test_probe_tsduck_default_instance_serves_version(self, tsduck):
        result = probe_tsduck()

        assert result.available is True
        assert result.version is not None
        assert result.version.version == MEASURED_VERSION
