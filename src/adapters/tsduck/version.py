"""TSDuck environment probe — SPEC-308 §3 ``version.py`` (ticket #25).

This module is the environment-probe slice of the five-module TSDuck adapter
(ADR-0005 decision 6): ``tsp --version`` regex extraction + cache; executable
discovery PATH-first with fallback probing. The other four modules
(process/client/command_builder/report_parser) and the three operations are
M2 scope; the public result types here are shaped for direct M2 consumption
(``TSDuckVersion`` is the type SPEC-308 §4 uses for ``get_version()``).

Contract anchors:

- Canonical version line (measured asset: docs/research/tsduck-env.md
  §2.1/§6.2, ticket #3):
  ``TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165``;
  extraction regex ``version (\\d+\\.\\d+-\\d+)`` (tsduck-env.md:191).
  Naming discipline: the constant names the canonical line shape; TSDuck
  output itself is never labelled "measured" (CONTEXT.md, observation
  confidence axis).
  Re-measured 2026-11-14 for #25: ``tsp --version`` prints that line to
  **stderr** with stdout empty — the scan covers BOTH streams, stdout first.
- The matched version pattern is the validity gate (ticket #3: garbage input
  still exits 0 — the exit code never proves validity).
- stderr is GBK-localized (SPEC-308 §7): decoded for the probe extraction
  only; non-version content is never parsed, only surfaced via ``detail``
  for display/log.
- Subprocess discipline (ADR-0005 decision 6 + ADR-0003 第 4 条):
  argument-array spawn, no ``shell=True``, explicit timeout, bytes captured
  and decoded explicitly (UTF-8 first, GBK fallback).
- Successful probes are cached per resolved executable (instance-level;
  the module-level :data:`DEFAULT_PROBE` plus :func:`probe_tsduck` provide
  the ADR-0005 process-lifetime cache). Failed probes are never cached.
- Capability-surface interpretation (ticket #25 acceptance reading, made
  durable here as assumption A1): the probe's "能力" surface is
  availability/version/path metadata only — the measured assets contain no
  TSDuck CLI capability enumeration (no subcommand inventory, no feature
  flags). Analyze capability enumeration is the M2 report_parser's scope
  (SPEC-308 §3 five-module layout).
"""

from __future__ import annotations

import os
import re
import shutil
import string
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "DEFAULT_PROBE",
    "CANONICAL_VERSION_LINE",
    "PROBE_TIMEOUT_SECONDS",
    "ResolutionSource",
    "TSDuckProbeResult",
    "TSDuckUnavailableReason",
    "TSDuckVersion",
    "TSDuckVersionProbe",
    "VersionMatch",
    "VersionStream",
    "extract_version",
    "probe_tsduck",
    "scan_for_version",
]

#: Canonical version-line anchor (measured asset: docs/research/tsduck-env.md,
#: ticket #3). The name describes the line shape, not a claim that TSDuck
#: output is "measured" (CONTEXT.md bans that framing).
CANONICAL_VERSION_LINE = (
    "TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165"
)

#: Measured line shape (tsduck-env.md §2.1) — primary extraction tier.
#: Anchoring here defeats the measured runtime noise line
#: ``* new TSDuck version 3.45-4798 is available (yours is 3.40-4165), ...``
#: (tsduck-env.md §2.2), which contains a version-like token for the
#: *upstream* release: matching it would report the wrong version.
VERSION_LINE_PATTERN = re.compile(
    r"TSDuck - The MPEG Transport Stream Toolkit - version (\d+\.\d+-\d+)"
)

#: Measured extraction regex (docs/research/tsduck-env.md:191) — secondary
#: tolerance tier for lines that drop the canonical prefix. Applied only to
#: lines that are not ``*``-prefixed TSDuck log output (the measured
#: message prefix of ``* Error: ...`` and the update-notification noise).
VERSION_PATTERN = re.compile(r"version (\d+\.\d+-\d+)")

#: TSDuck log/noise line prefix (measured: ``* Error: ...``, §4.4;
#: ``* new TSDuck version ...``, §2.2).
_LOG_LINE_PREFIX = "*"

#: Probe subprocess budget (seconds). The version print is instantaneous;
#: generous for cold-start antivirus scans on Windows. Test-pinned
#: interpretation — SPEC-308 §9's 120s default governs adapter operations.
PROBE_TIMEOUT_SECONDS = 30.0


class VersionStream(str, Enum):
    """Which subprocess stream carried the matched version line."""

    STDOUT = "stdout"
    STDERR = "stderr"


class ResolutionSource(str, Enum):
    """How the probe resolved the executable."""

    EXPLICIT = "explicit"
    PATH = "path"
    FALLBACK = "fallback"


class TSDuckUnavailableReason(str, Enum):
    """Structured unavailability reasons (ticket #25 acceptance).

    Maps onto SPEC-308 §9's ``TSDUCK_NOT_FOUND`` family: ``not_installed``
    is the PATH+fallback double-failure case; ``not_executable`` /
    ``version_unparseable`` are found-but-unusable cases. Baseline-version
    enforcement (``TSDUCK_VERSION_UNSUPPORTED``) is the M2 client's concern —
    the probe reports version facts.
    """

    NOT_INSTALLED = "not_installed"
    NOT_EXECUTABLE = "not_executable"
    VERSION_UNPARSEABLE = "version_unparseable"


@dataclass(frozen=True)
class VersionMatch:
    """A regex-validated version line found on one of the two streams."""

    raw_version_line: str
    stream: VersionStream
    version: str
    major: int
    minor: int
    build: int


def extract_version(version_line: str) -> str | None:
    """Extract the version token with the measured regex, else ``None``."""
    match = VERSION_PATTERN.search(version_line)
    return match.group(1) if match else None


def _decode_stream(raw: bytes) -> str:
    """Decode one captured stream: UTF-8 first, GBK fallback (test-pinned).

    SPEC-308 §7 declares TSDuck stderr GBK-localized on Chinese Windows;
    ASCII payload (the version token) decodes identically under both.
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def scan_for_version(stdout: bytes, stderr: bytes) -> VersionMatch | None:
    """Scan both streams for the measured version pattern (stdout first).

    The one sanctioned extraction surface that reads TSDuck stderr
    semantically (ADR-0005 decision 6). Two tiers, each stdout-then-stderr
    with first valid match wins: the measured canonical line shape first,
    then the loose research regex on non-log lines. A stream without a
    match — whatever the exit code was — yields nothing (ticket #3: exit 0
    never proves validity).
    """
    stream_lines: list[tuple[VersionStream, str]] = []
    for stream, raw in ((VersionStream.STDOUT, stdout), (VersionStream.STDERR, stderr)):
        text = _decode_stream(raw)
        for line in text.splitlines():
            stream_lines.append((stream, line))

    for pattern, allow_log_lines in ((VERSION_LINE_PATTERN, True), (VERSION_PATTERN, False)):
        for stream, line in stream_lines:
            if not allow_log_lines and line.startswith(_LOG_LINE_PREFIX):
                continue
            token = _match_token(pattern, line)
            if token is None:
                continue
            components = re.fullmatch(r"(\d+)\.(\d+)-(\d+)", token)
            assert components is not None  # guaranteed by the pattern shapes
            return VersionMatch(
                raw_version_line=line.strip(),
                stream=stream,
                version=token,
                major=int(components.group(1)),
                minor=int(components.group(2)),
                build=int(components.group(3)),
            )
    return None


def _match_token(pattern: re.Pattern[str], line: str) -> str | None:
    match = pattern.search(line)
    return match.group(1) if match else None


@dataclass(frozen=True)
class TSDuckVersion:
    """Found-probe payload: SPEC-308 §4's ``get_version()`` return type.

    Carries the executable path, the version token with parsed components,
    and probe metadata (which stream carried the line, how the executable
    was resolved) so the M2 client can log the SPEC-308 §7 call-record
    fields without re-probing.

    Capability note (ticket #25 assumption A1): this payload IS the probe's
    whole "能力" surface — availability/version/path metadata. It makes no
    claim about TSDuck feature capabilities: no CLI capability enumeration
    exists in the measured assets, and analyze capability enumeration lands
    with the M2 report_parser (SPEC-308 §3).
    """

    executable: Path
    version: str
    major: int
    minor: int
    build: int
    raw_version_line: str
    stream: VersionStream
    resolution: ResolutionSource


@dataclass(frozen=True)
class TSDuckProbeResult:
    """Structured probe outcome — found payload or explicit unavailability.

    Invariants (enforced, consumed by the M2 client): ``available`` is true
    iff ``version`` is set; unavailable results always carry a
    :class:`TSDuckUnavailableReason`. ``detail`` is human-readable
    diagnostics for display/log only (GBK stderr content never parsed).
    """

    available: bool
    version: TSDuckVersion | None
    reason: TSDuckUnavailableReason | None
    detail: str

    def __post_init__(self) -> None:
        if self.available and self.version is None:
            raise ValueError("available probe result must carry a TSDuckVersion")
        if not self.available and self.reason is None:
            raise ValueError("unavailable probe result must carry a reason")
        if self.available and self.reason is not None:
            raise ValueError("available probe result must not carry a reason")


def _default_fallback_roots() -> list[Path]:
    """Fallback probe roots (test-pinned interpretation of ADR-0005 决策 6).

    Anchored to docs/research/tsduck-env.md §6.2: ``%ProgramFiles%\\TSDuck\\bin``
    plus custom-drive installs (the measured machine keeps TSDuck at
    ``D:\\Program Files\\TSDuck\\bin`` off the system drive). Built per probe
    call so environment changes are visible without import-order effects.
    """
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / "TSDuck" / "bin")
    roots.extend(_logical_drive_roots())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _logical_drive_roots() -> list[Path]:
    """``<drive>:\\Program Files\\TSDuck\\bin`` for every existing drive.

    ``GetLogicalDrives`` answers from the OS drive table without probing
    each letter through the filesystem (A:/B: legacy devices stay cold).
    Non-Windows platforms contribute nothing (fallback is the ProgramFiles
    environment roots only).
    """
    if sys.platform != "win32":
        return []
    import ctypes

    mask = ctypes.windll.kernel32.GetLogicalDrives() & 0x3FFFFFF
    roots = []
    for index, letter in enumerate(string.ascii_uppercase):
        if mask >> index & 1:
            roots.append(Path(f"{letter}:\\Program Files\\TSDuck\\bin"))
    return roots


class TSDuckVersionProbe:
    """Environment probe: executable discovery + version extraction + cache.

    One instance owns one cache (successful probes only, keyed by resolved
    executable). Fresh instance = fresh probing, which is how tests observe
    cache behavior; the module-level :data:`DEFAULT_PROBE` (with
    :func:`probe_tsduck`) provides the ADR-0005 process-lifetime cache for
    production callers.

    Resolution order: explicit ``override`` → PATH → fallback roots. An
    override that does not resolve fails immediately with a structured
    ``not_installed`` result (no silent PATH fall-through: the caller
    explicitly configured a location, so silently probing elsewhere would
    be degradation).
    """

    def __init__(
        self,
        *,
        timeout: float = PROBE_TIMEOUT_SECONDS,
        fallback_roots: Sequence[Path] | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._timeout = timeout
        self._fallback_roots = fallback_roots
        self._cache: dict[str, TSDuckProbeResult] = {}

    def probe(self, *, override: str | Path | None = None) -> TSDuckProbeResult:
        """Probe TSDuck availability; never raises for TSDuck-missing states.

        Successful results are cached per resolved executable; failures are
        never cached (a transient timeout must not poison process lifetime).
        """
        failures: list[TSDuckProbeResult] = []

        override_resolution = self._resolve_override(override)
        if isinstance(override_resolution, TSDuckProbeResult):
            return override_resolution
        candidates: list[tuple[Path, ResolutionSource]] = []
        if override_resolution is not None:
            candidates.append((override_resolution, ResolutionSource.EXPLICIT))

        found = shutil.which("tsp")
        if found is not None:
            candidates.append((Path(found), ResolutionSource.PATH))

        for root in self._effective_fallback_roots():
            resolved = shutil.which("tsp", path=str(root))
            if resolved is not None:
                candidates.append((Path(resolved), ResolutionSource.FALLBACK))

        if not candidates:
            return TSDuckProbeResult(
                available=False,
                version=None,
                reason=TSDuckUnavailableReason.NOT_INSTALLED,
                detail=(
                    "TSDuck CLI 'tsp' not found on PATH or fallback locations "
                    f"(fallback roots: {self._effective_fallback_roots()})"
                ),
            )

        for executable, source in candidates:
            cached = self._cache.get(str(executable))
            if cached is not None:
                return cached
            result = self._run_version_probe(executable, source)
            if result.available:
                self._cache[str(executable)] = result
                return result
            failures.append(result)

        return _aggregate_failure(failures)

    def _effective_fallback_roots(self) -> list[Path]:
        if self._fallback_roots is None:
            return _default_fallback_roots()
        return list(self._fallback_roots)

    def _resolve_override(
        self, override: str | Path | None
    ) -> Path | TSDuckProbeResult | None:
        """Resolve an explicit override; structured result when unresolvable."""
        if override is None:
            return None
        override_path = Path(override)
        if override_path.is_file():
            return override_path
        resolved = shutil.which(str(override))
        if resolved is not None:
            return Path(resolved)
        return TSDuckProbeResult(
            available=False,
            version=None,
            reason=TSDuckUnavailableReason.NOT_INSTALLED,
            detail=(
                f"override {str(override)!r} does not resolve to an executable "
                "(file missing and not on PATH); PATH fall-through suppressed "
                "because the override was explicitly configured"
            ),
        )

    def _run_version_probe(
        self, executable: Path, source: ResolutionSource
    ) -> TSDuckProbeResult:
        """``<executable> --version`` with argument-array spawn discipline."""
        try:
            completed = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return TSDuckProbeResult(
                available=False,
                version=None,
                reason=TSDuckUnavailableReason.NOT_EXECUTABLE,
                detail=(
                    f"{str(executable)!r} --version timed out after "
                    f"{self._timeout}s ({error!r}); stderr text is display-only"
                ),
            )
        except OSError as error:
            return TSDuckProbeResult(
                available=False,
                version=None,
                reason=TSDuckUnavailableReason.NOT_EXECUTABLE,
                detail=(
                    f"{str(executable)!r} --version failed to spawn: {error!r} "
                    "(stderr text is display-only)"
                ),
            )

        match = scan_for_version(completed.stdout, completed.stderr)
        if match is None:
            return TSDuckProbeResult(
                available=False,
                version=None,
                reason=TSDuckUnavailableReason.VERSION_UNPARSEABLE,
                detail=(
                    f"{str(executable)!r} exited {completed.returncode} but no "
                    "canonical version line found in stdout/stderr "
                    "(exit 0 never proves validity, ticket #3)"
                ),
            )
        version = TSDuckVersion(
            executable=executable,
            version=match.version,
            major=match.major,
            minor=match.minor,
            build=match.build,
            raw_version_line=match.raw_version_line,
            stream=match.stream,
            resolution=source,
        )
        return TSDuckProbeResult(
            available=True,
            version=version,
            reason=None,
            detail=(
                f"TSDuck {version.version} via {executable} "
                f"(source={source.value}, stream={match.stream.value})"
            ),
        )


#: Most-informative-wins aggregation order (test-pinned interpretation):
#: a candidate that executed but printed no version token says more than
#: one that could not spawn at all.
_REASON_PRIORITY = (
    TSDuckUnavailableReason.VERSION_UNPARSEABLE,
    TSDuckUnavailableReason.NOT_EXECUTABLE,
    TSDuckUnavailableReason.NOT_INSTALLED,
)


def _aggregate_failure(failures: list[TSDuckProbeResult]) -> TSDuckProbeResult:
    reason = next(
        (
            candidate_reason
            for candidate_reason in _REASON_PRIORITY
            if any(failure.reason == candidate_reason for failure in failures)
        ),
        TSDuckUnavailableReason.NOT_INSTALLED,
    )
    return TSDuckProbeResult(
        available=False,
        version=None,
        reason=reason,
        detail=" | ".join(failure.detail for failure in failures if failure.detail),
    )


#: Process-lifetime default probe (ADR-0005 decision 6 cache discipline).
DEFAULT_PROBE = TSDuckVersionProbe()


def probe_tsduck(*, override: str | Path | None = None) -> TSDuckProbeResult:
    """Probe via the process-lifetime default probe instance."""
    return DEFAULT_PROBE.probe(override=override)
