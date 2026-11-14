"""TSDuck environment probe — SPEC-308 §3 ``version.py`` (ticket #25).

This module is the environment-probe slice of the five-module TSDuck adapter
(ADR-0005 decision 6): ``tsp --version`` regex extraction + cache; executable
discovery PATH-first with fallback probing. The other four modules
(process/client/command_builder/report_parser) and the three operations are
M2 scope; the public result types here are shaped for direct M2 consumption
(``TSDuckVersion`` is the type SPEC-308 §4 uses for ``get_version()``).

Contract anchors:

- Measured version line (docs/research/tsduck-env.md §2.1/§6.2, ticket #3):
  ``TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165``;
  extraction regex ``version (\\d+\\.\\d+-\\d+)`` (tsduck-env.md:191).
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
"""

from __future__ import annotations

import os
import re
import shutil
import string
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "DEFAULT_PROBE",
    "MEASURED_VERSION_LINE",
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

#: Measured version-line anchor (docs/research/tsduck-env.md, ticket #3).
MEASURED_VERSION_LINE = (
    "TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165"
)

#: Measured extraction regex (docs/research/tsduck-env.md:191).
VERSION_PATTERN = re.compile(r"version (\d+\.\d+-\d+)")

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
    semantically (ADR-0005 decision 6). First regex-valid line wins; a
    stream without a match — whatever the exit code was — yields nothing
    (ticket #3: exit 0 never proves validity).
    """
    for stream, raw in ((VersionStream.STDOUT, stdout), (VersionStream.STDERR, stderr)):
        text = _decode_stream(raw)
        for line in text.splitlines():
            token = extract_version(line)
            if token is None:
                continue
            components = re.fullmatch(r"(\d+)\.(\d+)-(\d+)", token)
            assert components is not None  # guaranteed by VERSION_PATTERN shape
            return VersionMatch(
                raw_version_line=line.strip(),
                stream=stream,
                version=token,
                major=int(components.group(1)),
                minor=int(components.group(2)),
                build=int(components.group(3)),
            )
    return None
