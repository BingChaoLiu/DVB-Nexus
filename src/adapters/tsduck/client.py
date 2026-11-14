"""TSDuck client — SPEC-308 §3 ``client.py`` (§4 three-operation orchestration).

The adapter's public operation surface (SPEC-308 §4):

- ``get_version()`` — delegates to the #25 probe (``adapters.tsduck.version``,
  reused, never re-implemented), then enforces the MVP minimum baseline 3.40
  (§9 row 2, parsed components — never string-literal versions).
- ``analyze()`` — the ONLY enabled operation (MVP): build the whitelist argv
  (command_builder), run the process (process.py), apply the JSON content
  gate + normalization (report_parser), and produce a complete nine-field
  call record (§7).
- ``inject()`` / ``generate()`` — signature-reserved, explicitly refused
  (``TSDUCK_NOT_ENABLED``); the refusal happens before any probing so a
  reserved operation never touches the environment (防静默半实现, §4).

The analyze input face for this ticket is a **file path** (ticket #37: the
SPEC-503 artifact / run-context wiring is M3 scope). The nine-field call
record (§7): version, executable path, argv, start/finish time, exit code,
stdout, stderr, input-artifact SHA-256 — plus the optional ``run_id``
association. Every analyze attempt is recorded, including gate failures
(the record travels on the raised ``TSDUCK_JSON_GATE_FAILED`` error).

stderr handling: the process runner decodes both streams display-only
(errors="replace"); the call record stores that text verbatim — GBK
stderr content is never parsed semantically (§7, ticket #3).
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.tsduck import command_builder, report_parser
from adapters.tsduck.errors import (
    TSDuckNotFoundError,
    TSDuckNotEnabledError,
    TSDuckJsonGateError,
    TSDuckVersionUnsupportedError,
)
from adapters.tsduck.process import (
    DEFAULT_TIMEOUT_SECONDS,
    ProcessResult,
    TSDuckProcessRunner,
)
from adapters.tsduck.version import (
    TSDuckProbeResult,
    TSDuckVersion,
    TSDuckVersionProbe,
)

__all__ = [
    "MVP_MINIMUM_BASELINE",
    "InjectSpec",
    "GenerateSpec",
    "TSDuckCallRecord",
    "AnalysisResult",
    "TSDuckClient",
]

#: SPEC-308 §9: 版本低于最低基线（3.40，#3 实测版本）→ TSDUCK_VERSION_UNSUPPORTED.
MVP_MINIMUM_BASELINE = (3, 40)

#: Hash chunk size for the input-artifact SHA-256 (streams; MVP artifact
#: ceiling is 200 万包 = 376MB per ADR-0008, never materialized whole).
_SHA256_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class InjectSpec:
    """Reserved operation signature (SPEC-308 §4). MVP calls refuse; the
    real shape lands with the传输级路由启用决策 (#14)."""


@dataclass(frozen=True)
class GenerateSpec:
    """Reserved operation signature (SPEC-308 §4). MVP calls refuse; the
    real shape lands with the golden-streams/conformance 策略 (#14)."""


@dataclass(frozen=True)
class TSDuckCallRecord:
    """One TSDuck invocation's mandatory record (SPEC-308 §7, SPEC-001 §7).

    Nine fields — version / executable path / argv / start + finish time /
    exit code / stdout / stderr / input-artifact SHA-256 — plus the optional
    ``run_id`` association (有则填). ``stdout_text``/``stderr_text`` are
    display-only decodes; GBK stderr content is never parsed (§7).
    """

    version: str | None
    executable_path: str | None
    argv: tuple[str, ...]
    started_at: float
    finished_at: float
    exit_code: int | None
    stdout_text: str
    stderr_text: str
    input_artifact_sha256: str | None
    run_id: str | None = None


@dataclass(frozen=True)
class AnalysisResult:
    """SPEC-308 §4 ``analyze`` return: normalized report + the call record."""

    report: report_parser.AnalysisReport
    call_record: TSDuckCallRecord


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_SHA256_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _tsanalyze_sibling(tsp_executable: Path) -> Path:
    """``tsanalyze`` lives next to the probed ``tsp`` (one install per bin
    directory — tsduck-env.md §2.1, #35 ts_e2e seam-3 layout)."""
    name = "tsanalyze.exe" if sys.platform == "win32" else "tsanalyze"
    return tsp_executable.parent / name


class TSDuckClient:
    """Three-operation TSDuck client (SPEC-308 §4); analyze is MVP-enabled.

    Seam-injected collaborators (probe/runner) keep the orchestration
    testable without the real CLI; defaults wire the production probe
    (process-lifetime cache) and the semaphore-serialized runner.
    """

    def __init__(
        self,
        *,
        probe: TSDuckVersionProbe | None = None,
        runner: TSDuckProcessRunner | None = None,
        minimum_baseline: tuple[int, int] = MVP_MINIMUM_BASELINE,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._probe = probe if probe is not None else TSDuckVersionProbe()
        self._runner = runner if runner is not None else TSDuckProcessRunner(
            default_timeout=default_timeout
        )
        self._minimum_baseline = minimum_baseline

    # --- reserved operations (SPEC-308 §4: 显式拒绝) ------------------------

    async def inject(self, spec: InjectSpec) -> Any:
        """Reserved: MVP 调用即拒绝 — never a silent half-implementation."""
        raise TSDuckNotEnabledError(
            "inject is reserved (MVP only enables analyze; 传输级故障路由 "
            "启用决策归 ticket #14 / SPEC-204 ADR-0007)"
        )

    async def generate(self, spec: GenerateSpec) -> Any:
        """Reserved: MVP 调用即拒绝 — never a silent half-implementation."""
        raise TSDuckNotEnabledError(
            "generate is reserved (MVP only enables analyze; 使用策略归 "
            "ticket #14 golden streams / conformance)"
        )

    # --- version -------------------------------------------------------------

    async def get_version(self) -> TSDuckVersion:
        """Probe + baseline check (SPEC-308 §9 rows 1-2).

        The probe (ticket #25) reports structured facts; this method turns
        them into the §9 error family: double-miss → ``TSDUCK_NOT_FOUND``,
        below-baseline → ``TSDUCK_VERSION_UNSUPPORTED`` (parsed components,
        never version-string literals).
        """
        result = await asyncio.to_thread(self._probe.probe)
        return self._version_from_probe(result)

    def _version_from_probe(self, result: TSDuckProbeResult) -> TSDuckVersion:
        if not result.available or result.version is None:
            raise TSDuckNotFoundError(
                f"TSDuck CLI not available ({result.reason.value if result.reason else '?'}); "
                f"{result.detail}"
            )
        version = result.version
        if (version.major, version.minor) < self._minimum_baseline:
            raise TSDuckVersionUnsupportedError(
                f"TSDuck {version.version} is below the MVP minimum baseline "
                f"{self._minimum_baseline[0]}.{self._minimum_baseline[1]} "
                "(SPEC-308 §9; #3 measured floor)"
            )
        return version

    # --- analyze (the only enabled operation) ---------------------------------

    async def analyze(
        self,
        input_path: str | Path,
        *,
        run_id: str | None = None,
        timeout: float | None = None,
    ) -> AnalysisResult:
        """Analyze one TS file: argv → spawn → gate → normalized report.

        The input face for this ticket is a file path (M3 wires SPEC-503
        artifact IDs / run context). Every attempt produces the nine-field
        call record: success returns it inside :class:`AnalysisResult`; a
        gate failure attaches it to the raised ``TSDUCK_JSON_GATE_FAILED``
        (as ``call_record``) so the invocation is never lost (§7 义务).
        """
        started = time.time()
        version = await self.get_version()
        executable = _tsanalyze_sibling(version.executable)
        if not executable.is_file():
            raise TSDuckNotFoundError(
                f"tsanalyze not found next to the probed tsp at {version.executable} "
                f"(looked for {executable})"
            )

        argv = command_builder.build_analyze_argv(input_path)
        result = await self._runner.run_async(argv, timeout=timeout)

        input_sha256: str | None
        try:
            input_sha256 = _file_sha256(Path(input_path))
        except OSError:
            # Unreadable input (e.g. deleted between spawn and hash): the
            # §7 sha field carries None and the gate still governs validity
            # — tsanalyze has already failed on the same file (exit 1, #3).
            input_sha256 = None
        record = self._call_record(
            version=version,
            executable=executable,
            argv=argv,
            result=result,
            started=started,
            input_sha256=input_sha256,
            run_id=run_id,
        )

        try:
            report = report_parser.parse_report(result.stdout, exit_code=result.exit_code)
        except TSDuckJsonGateError as error:
            error.call_record = record
            raise
        return AnalysisResult(report=report, call_record=record)

    def _call_record(
        self,
        *,
        version: TSDuckVersion,
        executable: Path,
        argv: tuple[str, ...],
        result: ProcessResult,
        started: float,
        input_sha256: str,
        run_id: str | None,
    ) -> TSDuckCallRecord:
        return TSDuckCallRecord(
            version=version.version,
            executable_path=str(executable),
            argv=tuple(argv),
            started_at=started,
            finished_at=time.time(),
            exit_code=result.exit_code,
            stdout_text=result.stdout_text,
            stderr_text=result.stderr_text,
            input_artifact_sha256=input_sha256,
            run_id=run_id,
        )
