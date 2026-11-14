"""TSDuck adapter: CLI subprocess integration (ADR-0005 decision 6).

SPEC-308 §3 five-module layout: process management (spawn/timeout/cancel),
client for analyze/inject/generate, whitelisted command builder, report
parser (JSON to Observation) and version detection. This package currently
exports the environment-probe slice (``version.py``, ticket #25): executable
discovery PATH-first with fallback probing, ``tsp --version`` regex
extraction + cache, structured unavailable results. The other four modules
and the three operations are M2 scope — the probe's public surface is shaped
for direct M2 client consumption (``TSDuckVersion`` is SPEC-308 §4's
``get_version()`` return type).

Never imported by ``ts`` (ADR-0005 decision 4 independence contract); TSDuck
output is never treated as absolute truth and never labelled ``measured``
(CONTEXT.md).
"""

from adapters.tsduck.version import (
    DEFAULT_PROBE,
    CANONICAL_VERSION_LINE,
    PROBE_TIMEOUT_SECONDS,
    ResolutionSource,
    TSDuckProbeResult,
    TSDuckUnavailableReason,
    TSDuckVersion,
    TSDuckVersionProbe,
    VersionMatch,
    VersionStream,
    extract_version,
    probe_tsduck,
    scan_for_version,
)

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
