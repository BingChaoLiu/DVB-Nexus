"""Real-TSDuck acceptance tests (ticket #25 acceptance, seam 1).

Found-path on this machine — TSDuck measured (docs/research/tsduck-env.md §2;
re-measured for #25 on 2026-11-14: stdout empty, one stderr line with the
``tsp: `` program prefix). These tests need the real CLI and carry the
``tsduck`` marker + the conftest ``tsduck`` fixture (explicit skip with a
visible reason when TSDuck is absent — the CI Windows job installs
TSDuck.TSDuck via winget per #14).

Real-environment tests assert the SHAPE of the probe result (a parsed
``X.Y-Z`` version internally consistent with its raw measured line, an
existing executable, the documented resolution/stream contract), never the
literal version of the machine they run on: the first CI run proved the
point by installing 3.45-4798 via winget where the reference machine has
3.40-4165. Literal ``3.40-4165`` pins stay in the unit/fake fixtures
(locked test baseline per tsduck-env.md §3.3), where they are synthetic
inputs, not environment assumptions.
"""

import re
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

#: A parsed version token must be the measured shape ``X.Y-Z``.
VERSION_SHAPE = re.compile(r"^\d+\.\d+-\d+$")


def _components_consistent(version_str: str, components: tuple[int, int, int]) -> bool:
    """The parsed (major, minor, build) must re-derive from ``X.Y-Z``."""
    parts = tuple(int(p) for p in version_str.replace("-", ".").split("."))
    return parts == components


class TestRealFoundPath:
    def test_probe_finds_local_tsduck_with_parsed_components(self, tsduck):
        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.reason is None
        assert result.version is not None
        assert VERSION_SHAPE.match(result.version.version)
        assert _components_consistent(
            result.version.version,
            (result.version.major, result.version.minor, result.version.build),
        )
        # Measured on the reference machine: `where tsp` hits PATH →
        # PATH-first wins (the CI winget install also lands on PATH).
        assert result.version.resolution is ResolutionSource.PATH
        # Measured (×3: tsduck-env.md §2.1, ticket #22 probe scaffold, #25
        # re-measurement): `tsp --version` prints the line to STDERR with
        # stdout empty. The probe contract is dual-stream by design; assert
        # the measured default while tolerating either stream.
        assert result.version.stream in (VersionStream.STDERR, VersionStream.STDOUT)
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
        # With PATH stripped to an empty dir, the default fallback roots must
        # still find the installation through the documented roots
        # (tsduck-env.md §6.2: ProgramFiles / ProgramFiles(x86) / logical-drive
        # scan of `<drive>:\Program Files\TSDuck\bin`). The drive letter is
        # environment-dependent (D: on the reference machine, C: on the winget
        # CI runner) — assert the shape, not the drive.
        empty_path_dir = tmp_path / "empty_path"
        empty_path_dir.mkdir()
        monkeypatch.setenv("PATH", str(empty_path_dir))

        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.version is not None
        assert VERSION_SHAPE.match(result.version.version)
        assert _components_consistent(
            result.version.version,
            (result.version.major, result.version.minor, result.version.build),
        )
        assert result.version.resolution is ResolutionSource.FALLBACK
        executable = result.version.executable
        # Case-insensitive: Windows filesystems return the on-disk casing
        # (measured both `tsp.exe` and `tsp.EXE` across machines).
        assert executable.name.lower() == "tsp.exe"
        assert executable.parent.name.lower() == "bin"
        assert executable.parent.parent.name.lower() == "tsduck"
        assert executable.exists()


class TestDefaultProbeFunction:
    def test_probe_tsduck_default_instance_serves_version(self, tsduck):
        result = probe_tsduck()

        assert result.available is True
        assert result.version is not None
        assert VERSION_SHAPE.match(result.version.version)
