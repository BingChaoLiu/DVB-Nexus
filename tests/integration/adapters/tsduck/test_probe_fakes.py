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
    CANONICAL_VERSION_LINE,
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
    stderr_line: str = CANONICAL_VERSION_LINE,
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
    # Batch-script text is ordinary test text (not TS byte streams); the
    # bytes material is produced by str.encode, per the 禁手拼字节 gate's
    # constructor-zone discipline (tests/_support/data_rules.py).
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
        assert result.version.raw_version_line == CANONICAL_VERSION_LINE
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


class TestNotExecutable:
    def test_non_pe_candidate_yields_not_executable(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # A PATHEXT-visible file whose bytes are not a valid executable:
        # resolution finds it, CreateProcess refuses it (measured:
        # OSError WinError 216, GBK-localized message). fallback_roots=[]
        # keeps the candidate environment hermetic on machines whose real
        # fallback roots contain a working TSDuck.
        (bin_dir / "tsp.exe").write_bytes("not a real PE payload \x00\x01\x02".encode("utf-8"))
        monkeypatch.setenv("PATH", str(bin_dir))

        result = TSDuckVersionProbe(fallback_roots=[]).probe()

        assert result.available is False
        assert result.version is None
        assert result.reason is TSDuckUnavailableReason.NOT_EXECUTABLE
        assert result.detail

    def test_unusable_path_candidate_falls_through_to_fallback(
        self, tmp_path, monkeypatch
    ):
        broken_dir = tmp_path / "broken"
        broken_dir.mkdir()
        (broken_dir / "tsp.exe").write_bytes("not a real PE payload".encode("utf-8"))
        monkeypatch.setenv("PATH", str(broken_dir))
        install_dir = tmp_path / "tsduck-install" / "bin"
        expected_script = _write_fake_tsp(install_dir)

        result = TSDuckVersionProbe(fallback_roots=[install_dir]).probe()

        assert result.available is True
        assert result.version is not None
        assert result.version.resolution is ResolutionSource.FALLBACK
        assert result.version.executable == expected_script


class TestVersionGate:
    def test_exit0_garbage_output_is_version_unparseable(self, tmp_path, monkeypatch):
        # Ticket #3 measured fact: garbage in, exit 0 out — the version
        # pattern, not the exit code, is the validity gate.
        bin_dir = tmp_path / "bin"
        _write_fake_tsp(bin_dir, stderr_line="hello garbage world")
        monkeypatch.setenv("PATH", str(bin_dir))

        result = TSDuckVersionProbe(fallback_roots=[]).probe()

        assert result.available is False
        assert result.version is None
        assert result.reason is TSDuckUnavailableReason.VERSION_UNPARSEABLE
        assert "exit 0 never proves validity" in result.detail

    def test_version_line_on_stdout_beats_noise_stderr(self, tmp_path, monkeypatch):
        # Both-streams seam end-to-end: version token on stdout, GBK-style
        # noise on stderr — stdout match wins, stderr is never parsed.
        bin_dir = tmp_path / "bin"
        _write_fake_tsp(
            bin_dir, stdout_line=CANONICAL_VERSION_LINE, stderr_line="* Error: noise"
        )
        monkeypatch.setenv("PATH", str(bin_dir))

        result = TSDuckVersionProbe().probe()

        assert result.available is True
        assert result.version is not None
        assert result.version.version == "3.40-4165"
        assert result.version.stream is VersionStream.STDOUT


class TestProbeTimeout:
    def test_blocking_candidate_yields_not_executable(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "tsp.cmd"
        # ping -n 5 blocks ~4 seconds on the loopback (no network needed).
        # Absolute path: the test strips PATH to the fake bin dir, so ping
        # must be resolved explicitly. Batch text via str.encode (禁手拼字节
        # gate: bytes literals only for golden/deterministic TS material).
        script.write_bytes(
            (
                "@echo off\r\n"
                "%SystemRoot%\\System32\\ping.exe -n 5 127.0.0.1 >nul\r\n"
                f"echo {CANONICAL_VERSION_LINE} 1>&2\r\n"
            ).encode("utf-8")
        )
        monkeypatch.setenv("PATH", str(bin_dir))
        probe = TSDuckVersionProbe(timeout=1.0, fallback_roots=[])

        result = probe.probe()

        assert result.available is False
        assert result.version is None
        assert result.reason is TSDuckUnavailableReason.NOT_EXECUTABLE
        assert "timed out" in result.detail


def _write_counting_tsp(bin_dir: Path) -> Path:
    """Fake tsp that appends one marker line to calls.log per invocation.

    The call-count file is the observable subprocess counter for the cache
    seam (delegator seam 4): real spawn, real count, no mocking.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "tsp.cmd"
    script.write_bytes(
        (
            "@echo off\r\n"
            'echo called >>"%~dp0calls.log"\r\n'
            f"echo {CANONICAL_VERSION_LINE} 1>&2\r\n"
        ).encode("utf-8")
    )
    return script


def _call_count(bin_dir: Path) -> int:
    log = bin_dir / "calls.log"
    if not log.exists():
        return 0
    return len([line for line in log.read_text(encoding="utf-8").splitlines() if line])


class TestCache:
    def test_second_probe_within_instance_served_from_cache(
        self, tmp_path: Path, monkeypatch
    ):
        bin_dir = tmp_path / "bin"
        _write_counting_tsp(bin_dir)
        monkeypatch.setenv("PATH", str(bin_dir))
        probe = TSDuckVersionProbe(fallback_roots=[])

        first = probe.probe()
        second = probe.probe()

        assert first.available and second.available
        assert first.version == second.version  # same cached payload object
        assert _call_count(bin_dir) == 1  # second call spawned nothing

    def test_fresh_instance_probes_again(self, tmp_path: Path, monkeypatch):
        bin_dir = tmp_path / "bin"
        _write_counting_tsp(bin_dir)
        monkeypatch.setenv("PATH", str(bin_dir))

        first = TSDuckVersionProbe(fallback_roots=[]).probe()
        second = TSDuckVersionProbe(fallback_roots=[]).probe()

        assert first.available and second.available
        assert _call_count(bin_dir) == 2  # no cross-instance cache leakage

    def test_failed_probe_is_not_cached(self, tmp_path: Path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "tsp.exe").write_bytes("not a real PE payload".encode("utf-8"))
        monkeypatch.setenv("PATH", str(bin_dir))
        probe = TSDuckVersionProbe(fallback_roots=[])

        broken = probe.probe()
        assert broken.available is False

        # Environment is repaired; the same instance must re-probe (failures
        # are never cached — a transient timeout must not poison lifetime).
        (bin_dir / "tsp.exe").unlink()
        _write_fake_tsp(bin_dir)
        repaired = probe.probe()

        assert repaired.available is True
        assert repaired.version is not None
        assert repaired.version.version == "3.40-4165"
