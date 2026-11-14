"""Process runner tests — real subprocesses (SPEC-308 §9, REQ-TSK-308-005).

Real spawn/timeout/cancel/tree-kill behavior against throwaway fake
executables (``.cmd`` batch scripts and ``ping.exe`` as the sleeper — both
proven spawnable via argument-array CreateProcess by the #25 probe fakes).
No TSDuck required.

Discipline: assertions are event-driven (file marker content), never
wall-clock waits; the only real waits are the timeout under test itself.
Windows mechanics (``taskkill /T /F`` tree kill, batch-file spawning) make
this ``windows_only`` — explicit skip elsewhere (SPEC-505 §5).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.tsduck.errors import (
    TSDuckCancelledError,
    TSDuckSpawnFailedError,
    TSDuckTimeoutError,
)
from adapters.tsduck.process import (
    DEFAULT_CONCURRENCY,
    DEFAULT_TIMEOUT_SECONDS,
    TSDUCK_NO_VERSION_CHECK_ENV,
    TSDuckProcessRunner,
    is_pid_alive,
)

pytestmark = pytest.mark.windows_only

SLEEPER_PINGS = 30  # ping -n N ≈ N-1 seconds on Windows


def _write_marker_cmd(bin_dir: Path, name: str, marker: Path, sleep_pings: int) -> Path:
    """A fake executable: appends begin/end markers around a real sleep."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / f"{name}.cmd"
    script.write_bytes(
        (
            "@echo off\r\n"
            f">> \"{marker}\" echo begin %1\r\n"
            f"ping -n {sleep_pings} 127.0.0.1 >nul\r\n"
            f">> \"{marker}\" echo end %1\r\n"
        ).encode("utf-8")
    )
    return script


def _read_markers(marker: Path) -> list[str]:
    return [line.strip() for line in marker.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestConstants:
    def test_defaults_match_spec_308_section_9(self):
        assert DEFAULT_TIMEOUT_SECONDS == 120.0
        assert DEFAULT_CONCURRENCY == 1

    def test_version_check_suppression_env_is_injected(self):
        # SPEC-308 §7: TSDUCK_NO_VERSION_CHECK=1 — value non-empty is what
        # TSDuck reads (tsduck-env.md §2.2); the exact value is adapter policy.
        assert TSDUCK_NO_VERSION_CHECK_ENV["TSDUCK_NO_VERSION_CHECK"] == "1"


class TestRunShape:
    def test_argument_array_spawn_captures_streams_and_exit(self, tmp_path):
        script = tmp_path / "hello.cmd"
        script.write_bytes(("@echo off\r\necho out-payload\r\necho err-payload 1>&2\r\n").encode("utf-8"))

        runner = TSDuckProcessRunner()
        result = asyncio.run(runner.run_async([str(script), "arg1"]))

        assert result.exit_code == 0
        assert "out-payload" in result.stdout_text
        assert "err-payload" in result.stderr_text
        assert result.argv == (str(script), "arg1")
        assert result.timed_out is False
        assert result.cancelled is False
        assert result.duration_seconds >= 0

    def test_nonzero_exit_recorded_never_raises(self, tmp_path):
        """Ticket #3 discipline at the process seam: the exit code is data.
        Raising here would pre-empt the JSON content gate's authority."""
        script = tmp_path / "fail.cmd"
        script.write_bytes(("@echo off\r\nexit /b 3\r\n").encode("utf-8"))

        result = asyncio.run(TSDuckProcessRunner().run_async([str(script)]))
        assert result.exit_code == 3

    def test_no_version_check_env_reaches_the_child(self, tmp_path):
        """SPEC-308 §7: TSDUCK_NO_VERSION_CHECK=1 injected into every spawn
        (kills the measured online-version-check stderr noise, #3 §2.2)."""
        script = tmp_path / "showenv.cmd"
        script.write_bytes(("@echo off\r\necho %TSDUCK_NO_VERSION_CHECK%\r\n").encode("utf-8"))

        result = asyncio.run(TSDuckProcessRunner().run_async([str(script)]))
        assert result.stdout_text.strip() == "1"

    def test_spawn_failure_raises_tsduck_spawn_failed(self):
        # A directory is not executable — CreateProcess fails at spawn time.
        with pytest.raises(TSDuckSpawnFailedError) as excinfo:
            asyncio.run(TSDuckProcessRunner().run_async([str(Path(sys.executable).parent)]))
        assert excinfo.value.code == "TSDUCK_SPAWN_FAILED"


class TestTimeout:
    def test_timeout_kills_process_tree_and_raises_with_partial_output(self, tmp_path):
        marker = tmp_path / "marker.log"
        script = _write_marker_cmd(tmp_path, "slow", marker, SLEEPER_PINGS)

        runner = TSDuckProcessRunner()
        with pytest.raises(TSDuckTimeoutError) as excinfo:
            asyncio.run(runner.run_async([str(script), "jobA"], timeout=2.0))

        assert excinfo.value.code == "TSDUCK_TIMEOUT"
        # Partial logs survive for triage (SPEC-308 §9: partial 日志保留).
        partial = excinfo.value.partial_result
        assert partial is not None
        assert partial.timed_out is True

    def test_killed_process_leaves_no_orphan(self, tmp_path):
        """REQ-TSK-308-005: after the tree kill the spawned process is gone."""
        script = _write_marker_cmd(tmp_path, "slow", tmp_path / "m.log", SLEEPER_PINGS)

        seen_pids = []
        runner = TSDuckProcessRunner()
        try:
            asyncio.run(runner.run_async([str(script)], timeout=2.0, on_start=seen_pids.append))
        except TSDuckTimeoutError:
            pass
        assert seen_pids, "on_start hook must record the spawned PID"
        assert not is_pid_alive(seen_pids[0]), "process tree survived the timeout kill"


class TestCancellation:
    def test_cancelled_run_kills_process_and_raises_cancelled(self, tmp_path):
        script = _write_marker_cmd(tmp_path, "slow", tmp_path / "m.log", SLEEPER_PINGS)

        async def scenario():
            runner = TSDuckProcessRunner()
            task = asyncio.ensure_future(runner.run_async([str(script)]))
            await asyncio.sleep(0.3)  # let the process actually start
            task.cancel()
            with pytest.raises(TSDuckCancelledError) as excinfo:
                await task
            return excinfo.value

        error = asyncio.run(scenario())
        assert error.code == "TSDUCK_CANCELLED"
        partial = error.partial_result
        assert partial is not None
        assert partial.cancelled is True
        assert not is_pid_alive(partial.pid), "cancelled process must be killed"


class TestConcurrencySemaphore:
    """Semaphore admission proven by a deterministic flag-file protocol:

    The first gathered run is a *waiter* (bounded loop: if the flag file
    exists → RELEASED, else ping-wait, max 5 rounds → TIMEOUT); the second
    is a *setter* (creates the flag immediately). Fully event-driven — no
    wall-clock comparison, no shared-append race (each run writes its own
    output file).
    """

    @staticmethod
    def _write_flag_scripts(bin_dir: Path) -> tuple[Path, Path, Path]:
        bin_dir.mkdir(parents=True, exist_ok=True)
        flag = bin_dir.parent / "flag.sentinel"
        waiter = bin_dir / "waiter.cmd"
        waiter.write_bytes(
            (
                "@echo off\r\n"
                "set /a n=0\r\n"
                ":loop\r\n"
                f"if exist \"{flag}\" (echo RELEASED> \"%~1\" & exit /b 0)\r\n"
                "ping -n 1 127.0.0.1 >nul\r\n"
                "set /a n+=1\r\n"
                "if %n% GEQ 5 (echo TIMEOUT> \"%~1\" & exit /b 0)\r\n"
                "goto loop\r\n"
            ).encode("utf-8")
        )
        setter = bin_dir / "setter.cmd"
        setter.write_bytes(
            (
                "@echo off\r\n"
                f"type nul> \"{flag}\"\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
            ).encode("utf-8")
        )
        return waiter, setter, flag

    def test_default_semaphore_serializes_runs(self, tmp_path):
        """concurrency=1 (SPEC-308 §9 default): the first gathered run is
        admitted alone — the waiter never sees the flag the second run
        would set, so it reports TIMEOUT."""
        waiter, setter, flag = self._write_flag_scripts(tmp_path)
        waiter_out = tmp_path / "waiter.out"

        async def scenario():
            runner = TSDuckProcessRunner()  # concurrency=1
            await asyncio.gather(
                runner.run_async([str(waiter), str(waiter_out)]),
                runner.run_async([str(setter)]),
            )

        asyncio.run(scenario())
        assert waiter_out.read_text(encoding="utf-8").strip() == "TIMEOUT"

    def test_configurable_concurrency_admits_parallel_runs(self, tmp_path):
        """concurrency=2: both runs admitted — the waiter observes the flag
        the setter created while itself still running → RELEASED."""
        waiter, setter, flag = self._write_flag_scripts(tmp_path)
        waiter_out = tmp_path / "waiter.out"
        if flag.exists():
            flag.unlink()

        async def scenario():
            runner = TSDuckProcessRunner(concurrency=2)
            await asyncio.gather(
                runner.run_async([str(waiter), str(waiter_out)]),
                runner.run_async([str(setter)]),
            )

        asyncio.run(scenario())
        assert waiter_out.read_text(encoding="utf-8").strip() == "RELEASED"


class TestPidProbe:
    def test_is_pid_alive_true_for_running_process_false_after_exit(self):
        proc = subprocess.Popen(["ping", "-n", "5", "127.0.0.1"], stdout=subprocess.DEVNULL)
        try:
            assert is_pid_alive(proc.pid) is True
        finally:
            proc.kill()
            proc.wait()
        assert is_pid_alive(proc.pid) is False

    def test_is_pid_alive_bogus_pid_false(self):
        assert is_pid_alive(4_000_000) is False
