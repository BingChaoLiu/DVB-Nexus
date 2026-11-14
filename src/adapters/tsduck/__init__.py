"""TSDuck adapter: CLI subprocess integration (ADR-0005 decision 6).

SPEC-308 §3 five-module layout, complete as of ticket #37:

- ``process.py`` — spawn (asyncio subprocess), timeout/cancel, process-tree
  cleanup, concurrency semaphore (SPEC-308 §9);
- ``client.py`` — the three operations (§4): ``analyze`` enabled,
  ``inject``/``generate`` reserved and explicitly refused
  (``TSDUCK_NOT_ENABLED``);
- ``command_builder.py`` — whitelist argv construction (§5, argument arrays
  only, 禁 shell=True per ADR-0003 第 4 条);
- ``report_parser.py`` — JSON content gate (§7: exit 0 ≠ valid, ticket #3) +
  ``AnalysisReport`` normalization + ``ts.*`` observation marking (§8);
- ``version.py`` — the environment probe slice (ticket #25): executable
  discovery PATH-first with fallback probing, ``tsp --version`` regex
  extraction + cache.

The MVP input face is a file path (ticket #37); SPEC-503/500 run-context
wiring is M3 scope. Error codes and their HTTP mappings live in
``errors.py`` (§9 family, transcribed line by line).

Never imported by ``ts`` (ADR-0005 decision 4 independence contract); TSDuck
output is never treated as absolute truth and never labelled ``measured``
(CONTEXT.md) — findings carry ``source=tsduck``/``confidence=parsed`` from
the ``domain.observation`` vocabularies.
"""

from adapters.tsduck.client import (
    AnalysisResult,
    GenerateSpec,
    InjectSpec,
    TSDuckCallRecord,
    TSDuckClient,
)
from adapters.tsduck.command_builder import (
    ANALYZE_JSON_FLAG,
    ANALYZE_TOOL,
    PLUGIN_WHITELIST,
    build_analyze_argv,
    require_allowed_plugin,
)
from adapters.tsduck.errors import (
    TSDuckAdapterError,
    TSDuckCancelledError,
    TSDuckJsonGateError,
    TSDuckNotFoundError,
    TSDuckNotEnabledError,
    TSDuckPluginNotAllowedError,
    TSDuckSpawnFailedError,
    TSDuckTimeoutError,
    TSDuckVersionUnsupportedError,
)
from adapters.tsduck.process import (
    DEFAULT_CONCURRENCY,
    DEFAULT_TIMEOUT_SECONDS,
    ProcessResult,
    TSDUCK_NO_VERSION_CHECK_ENV,
    TSDuckProcessRunner,
    is_pid_alive,
)
from adapters.tsduck.report_parser import (
    AnalysisReport,
    PidReport,
    ServiceReport,
    TableReport,
    TsduckFinding,
    TsSummary,
    parse_report,
    report_findings,
)
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
    # client
    "AnalysisResult",
    "GenerateSpec",
    "InjectSpec",
    "TSDuckCallRecord",
    "TSDuckClient",
    # command_builder
    "ANALYZE_JSON_FLAG",
    "ANALYZE_TOOL",
    "PLUGIN_WHITELIST",
    "build_analyze_argv",
    "require_allowed_plugin",
    # errors
    "TSDuckAdapterError",
    "TSDuckCancelledError",
    "TSDuckJsonGateError",
    "TSDuckNotFoundError",
    "TSDuckNotEnabledError",
    "TSDuckPluginNotAllowedError",
    "TSDuckSpawnFailedError",
    "TSDuckTimeoutError",
    "TSDuckVersionUnsupportedError",
    # process
    "DEFAULT_CONCURRENCY",
    "DEFAULT_TIMEOUT_SECONDS",
    "ProcessResult",
    "TSDUCK_NO_VERSION_CHECK_ENV",
    "TSDuckProcessRunner",
    "is_pid_alive",
    # report_parser
    "AnalysisReport",
    "PidReport",
    "ServiceReport",
    "TableReport",
    "TsduckFinding",
    "TsSummary",
    "parse_report",
    "report_findings",
    # version (ticket #25 probe slice)
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
