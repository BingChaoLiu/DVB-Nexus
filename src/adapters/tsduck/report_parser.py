"""Report parser — SPEC-308 §3 ``report_parser.py`` (§7/§8 duties).

``tsanalyze --json`` stdout → validated, normalized :class:`AnalysisReport`.

Two duties pinned by the measured environment facts (ticket #3,
docs/research/tsduck-env.md §4.2/§4.4):

- **JSON content gate** (SPEC-308 §7): ``ts.bytes > 0`` AND
  ``ts.services.total >= 1``. The gate is the adapter's ONLY validity
  arbiter — exit 0 does not prove validity (garbage input still exits 0
  and prints well-formed JSON), and this module never even sees the exit
  code unless the caller forwards it for diagnostics. Gate failure raises
  ``TSDUCK_JSON_GATE_FAILED`` (§9 row 6, HTTP 500 at the API layer).
- **Observation marking** (SPEC-308 §8, REQ-TSK-308-004): anomalous
  findings map ONLY onto registered SPEC-301 §4 ``ts.*`` event types, each
  carrying ``source=tsduck`` / ``confidence=parsed`` from the
  ``domain.observation`` vocabularies (no parallel enum copies — the hub
  import is the ADR-0005 sanctioned edge). Unmapped anomalies (duplicates,
  invalid syncs, …) stay in the report artifact and never become findings.

Schema-drift defense (SPEC-308 §12): every field extraction is defensive
(absent optional keys → ``None``/0 defaults), the source document is kept
verbatim for the report artifact, and the gate still governs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.observation import ConfidenceKind, ObservationSource

from adapters.tsduck.errors import TSDuckJsonGateError

__all__ = [
    "GATE_TS_BYTES_POSITIVE",
    "GATE_SERVICES_TOTAL_AT_LEAST_ONE",
    "REGISTERED_EVENT_TYPES",
    "TsSummary",
    "PidReport",
    "ServiceReport",
    "TableReport",
    "TsduckFinding",
    "AnalysisReport",
    "parse_report",
    "report_findings",
]

#: Ticket #3 / SPEC-308 §7 content gate, condition 1: the stream was really
#: read (garbage input reports bytes=0 despite exit 0).
GATE_TS_BYTES_POSITIVE = "ts_bytes_positive"

#: Ticket #3 / SPEC-308 §7 content gate, condition 2: at least one service
#: was identified (PAT→PMT association succeeded).
GATE_SERVICES_TOTAL_AT_LEAST_ONE = "services_total_at_least_one"

#: SPEC-301 §4 registered ``ts.*`` observation event types (the only values
#: :func:`report_findings` may emit — SPEC-308 §8: 扩注册表须走 SPEC-301 §4
#: 兼容评审, this module never invents types).
REGISTERED_EVENT_TYPES = frozenset(
    {
        "ts.continuity_error",
    }
)


def _int(source: Mapping[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _int_or_zero(source: Mapping[str, Any], key: str) -> int:
    value = _int(source, key)
    return value if value is not None else 0


def _count_value(source: Mapping[str, Any], key: str) -> int:
    """Read a count field that varies by TSDuck version shape (§12 defense):
    either a plain int (measured on 3.40-4165: ``services[].packets``) or a
    nested ``{total: …}`` object (``pids[].packets``)."""
    value = source.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        return _int_or_zero(value, "total")
    return 0


@dataclass(frozen=True)
class TsSummary:
    """Normalized transport-stream summary (``ts`` section, §4.2 anchors)."""

    bytes: int
    packets_total: int
    invalid_syncs: int
    transport_errors: int
    suspect_ignored: int
    services_total: int
    services_clear: int
    services_scrambled: int
    pids_total: int
    pids_clear: int
    pids_scrambled: int
    pids_pcr: int
    pids_unreferenced: int
    bitrate: int | None
    transport_stream_id: int | None

    def to_dict(self) -> dict[str, Any]:
        """Projection in the tsanalyze wire vocabulary (round-trip input)."""
        payload: dict[str, Any] = {
            "bytes": self.bytes,
            "packets": {
                "total": self.packets_total,
                "invalid-syncs": self.invalid_syncs,
                "transport-errors": self.transport_errors,
                "suspect-ignored": self.suspect_ignored,
            },
            "pids": {
                "total": self.pids_total,
                "clear": self.pids_clear,
                "scrambled": self.pids_scrambled,
                "pcr": self.pids_pcr,
                "unreferenced": self.pids_unreferenced,
            },
            "services": {
                "total": self.services_total,
                "clear": self.services_clear,
                "scrambled": self.services_scrambled,
            },
        }
        if self.bitrate is not None:
            payload["bitrate"] = self.bitrate
        if self.transport_stream_id is not None:
            payload["id"] = self.transport_stream_id
        return payload


@dataclass(frozen=True)
class PidReport:
    """One PID's normalized analysis row."""

    pid: int
    description: str | None
    packets_total: int
    clear: int
    scrambled: int
    discontinuities: int
    duplicated: int
    pcr: int
    pts: int
    is_scrambled: bool | None
    service_ids: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.pid,
            "packets": {
                "total": self.packets_total,
                "clear": self.clear,
                "scrambled": self.scrambled,
                "discontinuities": self.discontinuities,
                "duplicated": self.duplicated,
                "pcr": self.pcr,
                "pts": self.pts,
            },
            "services": list(self.service_ids),
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.is_scrambled is not None:
            payload["is-scrambled"] = self.is_scrambled
        return payload


@dataclass(frozen=True)
class ServiceReport:
    """One service's normalized analysis row."""

    service_id: int
    pmt_pid: int | None
    pcr_pid: int | None
    name: str | None
    packets_total: int
    components_total: int
    components_scrambled: int

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.service_id,
            "packets": {"total": self.packets_total},
            "components": {
                "total": self.components_total,
                "scrambled": self.components_scrambled,
            },
        }
        if self.pmt_pid is not None:
            payload["pmt-pid"] = self.pmt_pid
        if self.pcr_pid is not None:
            payload["pcr-pid"] = self.pcr_pid
        if self.name is not None:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True)
class TableReport:
    """One watched-table row's normalized analysis data."""

    pid: int
    table_id: int | None
    tid_ext: int | None
    table_count: int
    section_count: int
    versions: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pid": self.pid,
            "tables": self.table_count,
            "sections": self.section_count,
            "versions": list(self.versions),
        }
        if self.table_id is not None:
            payload["tid"] = self.table_id
        if self.tid_ext is not None:
            payload["tid-ext"] = self.tid_ext
        return payload


@dataclass(frozen=True)
class TsduckFinding:
    """One normalized observation finding (SPEC-308 §8).

    ``source``/``confidence`` use the ``domain.observation`` vocabularies —
    TSDuck output is parsed, never ``measured`` (CONTEXT.md 禁混标).
    """

    event_type: str
    source: ObservationSource
    confidence: ConfidenceKind
    pid: int | None
    value: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisReport:
    """Normalized ``tsanalyze`` report (SPEC-308 §8 归一化报告).

    ``source_document`` keeps the validated raw JSON verbatim (report
    artifact provenance); it is excluded from equality so the normalized
    round-trip (``from_document(to_dict())``) is lossless.
    """

    ts: TsSummary
    pids: tuple[PidReport, ...]
    services: tuple[ServiceReport, ...]
    tables: tuple[TableReport, ...]
    source_document: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """The normalized projection (round-trip input for :meth:`from_document`)."""
        return {
            "ts": self.ts.to_dict(),
            "pids": [pid.to_dict() for pid in self.pids],
            "services": [service.to_dict() for service in self.services],
            "tables": [table.to_dict() for table in self.tables],
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "AnalysisReport":
        """Normalize a tsanalyze-shaped document (gate NOT applied here —
        the gate belongs to :func:`parse_report`; this classmethod is the
        pure normalization half the round-trip reuses)."""
        ts_section = document.get("ts") or {}
        packets = ts_section.get("packets") or {}
        pids_summary = ts_section.get("pids") or {}
        services_summary = ts_section.get("services") or {}

        ts = TsSummary(
            bytes=_int_or_zero(ts_section, "bytes"),
            packets_total=_int_or_zero(packets, "total"),
            invalid_syncs=_int_or_zero(packets, "invalid-syncs"),
            transport_errors=_int_or_zero(packets, "transport-errors"),
            suspect_ignored=_int_or_zero(packets, "suspect-ignored"),
            services_total=_int_or_zero(services_summary, "total"),
            services_clear=_int_or_zero(services_summary, "clear"),
            services_scrambled=_int_or_zero(services_summary, "scrambled"),
            pids_total=_int_or_zero(pids_summary, "total"),
            pids_clear=_int_or_zero(pids_summary, "clear"),
            pids_scrambled=_int_or_zero(pids_summary, "scrambled"),
            pids_pcr=_int_or_zero(pids_summary, "pcr"),
            pids_unreferenced=_int_or_zero(pids_summary, "unreferenced"),
            bitrate=_int(ts_section, "bitrate"),
            transport_stream_id=_int(ts_section, "id"),
        )

        pids = tuple(
            PidReport(
                pid=_int_or_zero(raw_pid, "id"),
                description=raw_pid.get("description"),
                packets_total=_int_or_zero(pid_packets, "total"),
                clear=_int_or_zero(pid_packets, "clear"),
                scrambled=_int_or_zero(pid_packets, "scrambled"),
                discontinuities=_int_or_zero(pid_packets, "discontinuities"),
                duplicated=_int_or_zero(pid_packets, "duplicated"),
                pcr=_int_or_zero(pid_packets, "pcr"),
                pts=_int_or_zero(pid_packets, "pts"),
                is_scrambled=raw_pid.get("is-scrambled"),
                service_ids=tuple(raw_pid.get("services") or ()),
            )
            # one packets-dict extraction per PID row (absent → empty dict),
            # shared by all seven packet counters below (review fix B4).
            for raw_pid in document.get("pids") or ()
            for pid_packets in (raw_pid.get("packets") or {},)
        )

        services = tuple(
            ServiceReport(
                service_id=_int_or_zero(raw_service, "id"),
                pmt_pid=_int(raw_service, "pmt-pid"),
                pcr_pid=_int(raw_service, "pcr-pid"),
                name=raw_service.get("name"),
                packets_total=_count_value(raw_service, "packets"),
                components_total=_int_or_zero(
                    raw_service.get("components") or {}, "total"
                ),
                components_scrambled=_int_or_zero(
                    raw_service.get("components") or {}, "scrambled"
                ),
            )
            for raw_service in document.get("services") or ()
        )

        tables = tuple(
            TableReport(
                pid=_int_or_zero(raw_table, "pid"),
                table_id=_int(raw_table, "tid"),
                tid_ext=_int(raw_table, "tid-ext"),
                table_count=_int_or_zero(raw_table, "tables"),
                section_count=_int_or_zero(raw_table, "sections"),
                versions=tuple(raw_table.get("versions") or ()),
            )
            for raw_table in document.get("tables") or ()
        )

        return cls(
            ts=ts,
            pids=pids,
            services=services,
            tables=tables,
            source_document=dict(document),
        )


def _decode_stdout(stdout: bytes | str) -> str:
    if isinstance(stdout, bytes):
        # tsanalyze stdout JSON is UTF-8 (#3 measured); errors="replace"
        # keeps the gate (not a decode crash) as the failure mode.
        return stdout.decode("utf-8", errors="replace")
    return stdout


def parse_report(stdout: bytes | str, *, exit_code: int | None = None) -> AnalysisReport:
    """Validate + normalize ``tsanalyze --json`` stdout (SPEC-308 §7).

    The content gate is the validity arbiter; ``exit_code`` is diagnostics
    only (recorded into the failure detail when given — the #3 discipline
    is that the exit code never decides validity in EITHER direction).
    """
    text = _decode_stdout(stdout)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise TSDuckJsonGateError(_gate_detail("stdout is not valid JSON", exit_code, error)) from error
    if not isinstance(document, dict) or not isinstance(document.get("ts"), dict):
        raise TSDuckJsonGateError(
            _gate_detail("stdout JSON has no 'ts' object (unexpected report shape)", exit_code)
        )

    ts_section = document["ts"]
    failures: list[str] = []
    if _int_or_zero(ts_section, "bytes") <= 0:
        failures.append(f"{GATE_TS_BYTES_POSITIVE}: ts.bytes must be > 0")
    services = ts_section.get("services") or {}
    if _int_or_zero(services, "total") < 1:
        failures.append(f"{GATE_SERVICES_TOTAL_AT_LEAST_ONE}: ts.services.total must be >= 1")
    if failures:
        raise TSDuckJsonGateError(_gate_detail("; ".join(failures), exit_code))

    return AnalysisReport.from_document(document)


def _gate_detail(reason: str, exit_code: int | None, error: Exception | None = None) -> str:
    parts = [f"JSON content gate failed: {reason}"]
    if exit_code is not None:
        parts.append(f"(exit_code={exit_code}; the exit code never decides validity, ticket #3)")
    if error is not None:
        parts.append(f"({error})")
    return " ".join(parts)


def report_findings(report: AnalysisReport) -> tuple[TsduckFinding, ...]:
    """Map report anomalies onto registered ``ts.*`` event types (§8).

    MVP mapping (conservative — only the unambiguous registered type):
    per-PID ``discontinuities`` → ``ts.continuity_error``. Everything else
    (duplicates, invalid syncs, bitrates, table versions) has no registered
    mapping and stays in the report artifact — never emitted as a finding.
    """
    findings: list[TsduckFinding] = []
    for pid in report.pids:
        if pid.discontinuities > 0:
            findings.append(
                TsduckFinding(
                    event_type="ts.continuity_error",
                    source=ObservationSource.TSDUCK,
                    confidence=ConfidenceKind.PARSED,
                    pid=pid.pid,
                    value={"count": pid.discontinuities},
                )
            )
    return tuple(findings)
