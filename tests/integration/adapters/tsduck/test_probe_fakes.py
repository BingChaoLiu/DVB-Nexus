"""Probe resolution and unavailability paths with fake executables (#25).

Seams 2/3/4 of the delegator-approved seam list, exercised at the probe's
public API (``TSDuckVersionProbe.probe`` / ``probe_tsduck``). No real TSDuck
required: fake ``tsp`` executables are small ``.cmd`` batch scripts in tmp
dirs (list-argv spawn works for batch files via CreateProcess — verified
2026-11-14) whose version lines are anchored to the measured assets in
``docs/research/tsduck-env.md``. These are ordinary test text, not TS byte
streams (禁手拼字节 rule governs TS byte payloads only).

Windows mechanics (PATHEXT resolution, non-PE spawn failure, cmd batch
semantics) make this file ``windows_only`` — explicit skip elsewhere per
SPEC-505 §5, never silent degradation.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from adapters.tsduck.version import (
    MEASURED_VERSION_LINE,
    ResolutionSource,
    TSDuckUnavailableReason,
    TSDuckVersionProbe,
    VersionStream,
)

pytestmark = [pytest.mark.windows_only]

#: PATHEXT suffix the fakes use (`.cmd` — batch files spawn fine via list argv).
FAKE_SUFFIX = ".cmd"


def _write_fake_tsp(
    bin_dir: Path,
    *,
    stderr_line: str = MEASURED_VERSION_LINE,
    stdout_line: str | None = None,
) -> Path:
    """Write a batch ``tsp`` printing the given lines; returns the script."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / f"tsp{FAKE_SUFFIX}"
    lines = ["@echo off"]
    if stdout_line is not None:
        lines.append(f"echo {stdout_line}")
    if stderr_line is not None:
        lines.append(f"echo {stderr_line} 1>&2")
    script.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return script


class TestPathResolution:
    def test_probe_finds_fake_tsp_on_path(self, tmp_path: Path, monkeypatch):
        bin_dir = tmp_path / "bin"
        _write_fake_tsp(bin_dir)
        monkeypatch.setenv("PATH", str(bin_dir))

        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.reason is None
        assert result.version is not None
        assert result.version.version == "3.40-4165"
        assert (result.version.major, result.version.minor, result.version.build) == (
            3,
            40,
            4165,
        )
        assert result.version.resolution is ResolutionSource.PATH
        assert result.version.stream is VersionStream.STDERR
        assert result.version.executable == Path(shutil.which("tsp"))
        assert result.version.raw_version_line == MEASURED_VERSION_LINE
        assert result.detail  # display-only diagnostics always present


class TestOverrideResolution:
    def test_explicit_override_beats_path_and_marks_source(
        self, tmp_path: Path, monkeypatch
    ):
        override_script = _write_fake_tsp(tmp_path / "override")
        path_dir = tmp_path / "on_path"
        _write_fake_tsp(path_dir)
        monkeypatch.setenv("PATH", str(path_dir))

        result = TSDuckVersionProbe().probe(override=override_script)

        assert result.available is True
        assert result.version is not None
        assert result.version.resolution is ResolutionSource.EXPLICIT
        assert result.version.executable == override_script


class TestFallbackResolution:
    def test_fallback_root_used_when_path_misses(self, tmp_path: Path, monkeypatch):
        empty_path_dir = tmp_path / "empty_path"
        empty_path_dir.mkdir()
        monkeypatch.setenv("PATH", str(empty_path_dir))
        install_dir = tmp_path / "tsduck-install" / "bin"
        expected_script = _write_fake_tsp(install_dir)
        probe = TSDuckVersionProbe(fallback_roots=[install_dir])

        result = probe.probe()

        assert result.available is True
        assert result.version is not None
        assert result.version.resolution is ResolutionSource.FALLBACK
        assert result.version.executable == expected_script


class TestNotInstalled:
    def test_double_failure_yields_structured_unavailable(self, tmp_path, monkeypatch):
        empty_path_dir = tmp_path / "empty_path"
        empty_path_dir.mkdir()
        monkeypatch.setenv("PATH", str(empty_path_dir))
        empty_fallback = tmp_path / "empty_fallback"
        empty_fallback.mkdir()
        probe = TSDuckVersionProbe(fallback_roots=[empty_fallback])

        result = probe.probe()

        assert result.available is False
        assert result.version is None
        assert result.reason is TSDuckUnavailableReason.NOT_INSTALLED
        assert result.detail
