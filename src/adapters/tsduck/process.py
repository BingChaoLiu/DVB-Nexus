"""Process runner — SPEC-308 §3 ``process.py`` (§9 discipline).

Async subprocess management for TSDuck CLI tools (ADR-0005 decision 6:
``asyncio.create_subprocess_exec``-shaped spawns; chatgpt-v04 §7 asyncio
subprocess discipline):

- **Argument arrays only** — the builder produced the argv; this module
  never joins, quotes or shells it (禁 ``shell=True``, ADR-0003 第 4 条).
- **Timeout** (default 120s, §9) → kill the **process tree**
  (``taskkill /PID … /T /F`` on Windows — no orphans, REQ-TSK-308-005) →
  ``TSDUCK_TIMEOUT`` with the partial output attached (partial 日志保留,
  排查依据).
- **Cancellation** → tree kill → ``TSDUCK_CANCELLED`` with partial output.
- **Exit code is data, never a signal** (ticket #3): a started process that
  exits nonzero produces a normal :class:`ProcessResult`; validity is the
  JSON content gate's job (report_parser), never this module's.
- **Concurrency**: semaphore (default 1, configurable, §9), FIFO admission
  per the asyncio semaphore's waiter order.
- **Environment**: every spawn gets ``TSDUCK_NO_VERSION_CHECK=1`` (§7 —
  kills the measured online-version-check stderr noise, tsduck-env.md §2.2).

The exit-code-nonzero-is-not-an-error stance has one consequence worth
stating: this module raises ONLY for spawn failure, timeout and
cancellation — never for a CLI's own failure exit.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Mapping, NoReturn, Sequence

from adapters.tsduck.errors import (
    TSDuckCancelledError,
    TSDuckSpawnFailedError,
    TSDuckTimeoutError,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_CONCURRENCY",
    "TSDUCK_NO_VERSION_CHECK_ENV",
    "ProcessResult",
    "TSDuckProcessRunner",
    "is_pid_alive",
]

#: SPEC-308 §9 default operation timeout (seconds).
DEFAULT_TIMEOUT_SECONDS = 120.0

#: SPEC-308 §9 default concurrency semaphore size (OPEN-006 复核归后续票).
DEFAULT_CONCURRENCY = 1

#: SPEC-308 §7 mandated environment injection (value non-empty = enabled).
TSDUCK_NO_VERSION_CHECK_ENV: Mapping[str, str] = {"TSDUCK_NO_VERSION_CHECK": "1"}


@dataclass(frozen=True)
class ProcessResult:
    """One completed/killed process run — the raw call-record material."""

    argv: tuple[str, ...]
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    pid: int | None = None
    timed_out: bool = False
    cancelled: bool = False

    @property
    def stdout_text(self) -> str:
        """UTF-8 display decode (JSON content parsing is report_parser's job)."""
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        """GBK-tolerant display decode — never parsed semantically (SPEC-308 §7)."""
        return self.stderr.decode("utf-8", errors="replace")


def _kill_tree(pid: int) -> None:
    """Kill the whole Windows process tree (taskkill /T /F).

    ``terminate()``/``SIGKILL`` on Windows kills only the direct child; TSDuck
    pipelines (``tsp`` → plugins) must not leave orphans (SPEC-308 §9,
    REQ-TSK-308-005). Best effort: a tree that already exited makes taskkill
    fail harmlessly.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def is_pid_alive(pid: int) -> bool:
    """Windows-first liveness probe (``tasklist /FI`` — no third-party deps)."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True,
        check=False,
    )
    # "INFO: No tasks are running..." (localized) vs. a task row naming the PID.
    return f" {pid} " in completed.stdout.decode("utf-8", errors="replace")


async def _partial_result(
    argv: Sequence[str],
    process: asyncio.subprocess.Process,
    started: float,
    *,
    timed_out: bool = False,
    cancelled: bool = False,
) -> ProcessResult:
    """Build the partial :class:`ProcessResult` of a killed run.

    Shared by the timeout and cancellation branches (tree kill → drain the
    streams → record what was captured): one construction site instead of
    twin blocks drifting apart.
    """
    stdout, stderr = await process.communicate()
    return ProcessResult(
        argv=tuple(argv),
        exit_code=process.returncode,
        stdout=stdout or b"",
        stderr=stderr or b"",
        duration_seconds=time.monotonic() - started,
        pid=process.pid,
        timed_out=timed_out,
        cancelled=cancelled,
    )


def _raise_partial(
    error: TSDuckTimeoutError | TSDuckCancelledError,
    partial: ProcessResult,
) -> NoReturn:
    """Attach the partial run to the §9 error and raise it (from None — the
    asyncio.TimeoutError/CancelledError frame is transport noise, not cause)."""
    error.partial_result = partial
    raise error from None


class TSDuckProcessRunner:
    """Semaphore-serialized async runner for TSDuck CLI subprocesses."""

    def __init__(
        self,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self._semaphore = asyncio.Semaphore(concurrency)
        self._default_timeout = default_timeout

    async def run_async(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        on_start: Callable[[int], None] | None = None,
    ) -> ProcessResult:
        """Run one argv; argument-array spawn, tree-killed on timeout/cancel.

        Raises ``TSDuckSpawnFailedError`` (OSError at spawn),
        ``TSDuckTimeoutError`` (tree killed, partial output attached) or
        ``TSDuckCancelledError`` (task cancelled, tree killed, partial
        output attached). A CLI's own nonzero exit is NOT an error (ticket #3).
        """
        effective_timeout = self._default_timeout if timeout is None else timeout
        merged_env = dict(os.environ)
        merged_env.update(TSDUCK_NO_VERSION_CHECK_ENV)
        if env is not None:
            merged_env.update(env)

        started = time.monotonic()
        async with self._semaphore:
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    env=merged_env,
                )
            except OSError as error:
                raise TSDuckSpawnFailedError(
                    f"failed to spawn {argv[0]!r}: {error!r}"
                ) from error
            if on_start is not None:
                on_start(process.pid)

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=effective_timeout
                )
            except asyncio.TimeoutError:
                _kill_tree(process.pid)
                partial = await _partial_result(
                    argv, process, started, timed_out=True
                )
                _raise_partial(
                    TSDuckTimeoutError(
                        f"process tree killed after {effective_timeout}s timeout "
                        f"(pid={process.pid}, argv={list(argv)!r}); "
                        "partial output attached"
                    ),
                    partial,
                )
            except asyncio.CancelledError:
                _kill_tree(process.pid)
                partial = await _partial_result(
                    argv, process, started, cancelled=True
                )
                _raise_partial(
                    TSDuckCancelledError(
                        f"process tree killed on cancellation (pid={process.pid}); "
                        "partial output attached"
                    ),
                    partial,
                )

        return ProcessResult(
            argv=tuple(argv),
            exit_code=process.returncode,
            stdout=stdout or b"",
            stderr=stderr or b"",
            duration_seconds=time.monotonic() - started,
            pid=process.pid,
        )
