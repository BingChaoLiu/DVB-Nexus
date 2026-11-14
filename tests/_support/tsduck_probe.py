"""TSDuck CLI availability probe (SPEC-505 §4 ``tsduck`` fixture → SPEC-308).

Behavior per SPEC-505 §5 + #14:

- PATH-first executable discovery, optional explicit override via the
  ``DVB_NEXUS_TSP_PATH`` environment variable (Windows-first: ``shutil.which``
  resolves ``tsp.exe`` through PATHEXT natively);
- ``tsp --version`` output parsed with the **measured** regex from
  ``docs/research/tsduck-env.md`` (ticket #3 实测，SPEC-505 §6 禁编造 CLI 行为):
  output line ``TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165``,
  extraction ``version (\\d+\\.\\d+-\\d+)``;
- stderr is the GBK-localized log channel (SPEC-308): decoded
  ``errors="replace"``, surfaced for display only, never parsed;
- probe results are frozen dataclasses — caching them is immutable sharing,
  not mutable fixture state (SPEC-505 §4 隔离纪律).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

#: Env var for an explicit tsp executable override (tests / non-PATH installs).
TSP_ENV_OVERRIDE = "DVB_NEXUS_TSP_PATH"

#: Measured output format anchor (docs/research/tsduck-env.md, ticket #3).
MEASURED_VERSION_LINE = (
    "TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165"
)

#: Measured extraction regex (docs/research/tsduck-env.md:191).
_VERSION_PATTERN = re.compile(r"version (\d+\.\d+-\d+)")

#: Probe subprocess budget (version print is instantaneous; generous for
#: cold-start antivirus scans on Windows).
_PROBE_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class TSDuckProbe:
    """Immutable probe result yielded by the ``tsduck`` fixture."""

    available: bool
    executable: str | None
    version: str | None
    raw_version_line: str | None
    detail: str


def extract_version(version_line: str) -> str | None:
    """Extract the version token with the measured regex, else ``None``."""
    match = _VERSION_PATTERN.search(version_line)
    return match.group(1) if match else None


@lru_cache(maxsize=8)
def _run_version_probe(executable: str) -> tuple[bool, str | None, str | None, str]:
    """Run ``<executable> --version``; cached per executable path.

    Returns ``(ok, version, raw_line, detail)``.

    Measured behavior (this repo's own probe runs, consistent with
    docs/research/tsduck-env.md): ``tsp --version`` emits the version line on
    **stderr** with an empty stdout (rc=0). The version token is therefore
    searched on stdout first, then stderr. This is the dedicated probe
    extraction; adapter-worker stderr remains display-only per SPEC-308.
    """
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return (False, None, None, f"{executable!r} --version failed: {error!r}")

    # Streams decoded explicitly; TSDuck stderr is GBK-localized and
    # display-only (SPEC-308) — replacement chars instead of codepage lies.
    stdout_text = completed.stdout.decode("utf-8", errors="replace")
    stderr_text = completed.stderr.decode("utf-8", errors="replace")

    def first_line(text: str) -> str | None:
        return next(
            (line.strip() for line in text.splitlines() if line.strip()), None
        )

    def version_line(text: str) -> str | None:
        return next(
            (line.strip() for line in text.splitlines() if _VERSION_PATTERN.search(line)),
            None,
        )

    raw_line = version_line(stdout_text) or version_line(stderr_text)
    if raw_line is None:
        raw_line = first_line(stdout_text) or first_line(stderr_text)
    version = extract_version(raw_line) if raw_line else None

    if completed.returncode != 0:
        return (
            False,
            None,
            raw_line,
            f"{executable!r} exited {completed.returncode}; stderr (display-only): "
            f"{stderr_text.strip()[:200]!r}",
        )
    if version is None:
        return (
            True,
            None,
            raw_line,
            f"executed but no measured version token found; first line: {raw_line!r}",
        )
    return (True, version, raw_line, f"version {version} via {executable}")


def probe_tsp(override: str | None = None) -> TSDuckProbe:
    """Probe TSDuck CLI availability (PATH first, then explicit override).

    ``override`` defaults to the ``DVB_NEXUS_TSP_PATH`` environment value.
    """
    explicit = override if override is not None else os.environ.get(TSP_ENV_OVERRIDE)
    if explicit:
        executable = explicit if os.path.isfile(explicit) else shutil.which(explicit)
        if executable is None:
            return TSDuckProbe(
                available=False,
                executable=None,
                version=None,
                raw_version_line=None,
                detail=(
                    f"{TSP_ENV_OVERRIDE}={explicit!r} does not resolve to an "
                    "executable (file missing and not on PATH)"
                ),
            )
    else:
        executable = shutil.which("tsp")
        if executable is None:
            return TSDuckProbe(
                available=False,
                executable=None,
                version=None,
                raw_version_line=None,
                detail=(
                    "TSDuck CLI 'tsp' not found on PATH "
                    f"(set ${TSP_ENV_OVERRIDE} for non-PATH installs; "
                    "CI windows job installs TSDuck.TSDuck via winget per #14)"
                ),
            )

    ok, version, raw_line, detail = _run_version_probe(executable)
    return TSDuckProbe(
        available=ok,
        executable=executable if ok else None,
        version=version,
        raw_version_line=raw_line,
        detail=detail,
    )
