"""Timeline export pipeline — JSONL / CSV / ZIP + manifest with redaction
and secret scanning (SPEC-303 §7, REQ-OBS-303-005).

Pipeline: redact (policy) → secret scan (defense in depth; the journal
already rejected secret-like payload keys at ingest, SPEC-301 §7) →
serialize content artifacts → hash each file → build the manifest.

Determinism (SPEC-303 §7: 同一不可变 journal 区间 + 相同导出选项 ⇒ 可复现,
生成元数据除外):

- ``export_id`` / ``created_at`` are caller-injected GENERATION metadata —
  the only manifest fields allowed to differ between reproducible exports;
- every content byte is canonical: JSONL lines use the canonical JSON form
  (sorted keys, compact, ASCII), CSV cells are fixed-order with the
  embedded payload as canonical JSON, and ZIP members carry the fixed
  1980-01-01 timestamp with an explicit compression level so the container
  byte-reproduces too;
- record identity is content-derived (see ``recorder.py``), so re-deriving
  a timeline from the same journal interval yields the same ids and hence
  the same export bytes across restarts.

Manifest contents (REQ-OBS-303-005): export ID, creation time, scope +
filters, clock domain and start/end, per-kind record counts, schema
version, redaction policy + version, per-file SHA-256. The manifest lists
the CONTENT files (timeline.jsonl / timeline.csv / redaction-report.json);
the ZIP embeds the manifest bytes verbatim, and the caller-facing
``ExportResult.file_digests`` covers every produced file (ZIP included)
without a circular self-hash.

Redaction policies: ``none`` (export as stored — a secret-scan violation
REFUSES the export with the SPEC-301 §7 envelope-contract code) and
``strip_payloads`` (payload bodies replaced by a redaction marker; the
evidence chain — event_id/journal_seq — always survives redaction,
REQ-OBS-303-001). Every non-``none`` export ships a ``redaction-report.json``.

Export writes no disk itself (pure bytes); ``write_export`` is the
filesystem half for callers that materialize the artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from application.context import LOCAL_TENANT_ID
from application.observation.timeline.errors import TimelineError
from domain.observation import (
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
)

#: Export manifest schema version (repo authority:
#: docs/schemas/timeline-export-manifest.schema.json).
TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION = "1.0"

EXPORT_FORMAT_JSONL = "jsonl"
EXPORT_FORMAT_CSV = "csv"
EXPORT_FORMAT_ZIP = "zip"
EXPORT_FORMATS = (EXPORT_FORMAT_JSONL, EXPORT_FORMAT_CSV, EXPORT_FORMAT_ZIP)

JSONL_FILENAME = "timeline.jsonl"
CSV_FILENAME = "timeline.csv"
ZIP_FILENAME = "timeline-export.zip"
MANIFEST_FILENAME = "manifest.json"
REDACTION_REPORT_FILENAME = "redaction-report.json"

REDACTION_POLICY_NONE = "none"
REDACTION_POLICY_STRIP_PAYLOADS = "strip_payloads"
REDACTION_POLICY_VERSION = "1"

REDACTION_POLICIES = (REDACTION_POLICY_NONE, REDACTION_POLICY_STRIP_PAYLOADS)

#: ZIP member timestamps are pinned to the MS-DOS epoch so identical
#: content produces identical archive bytes (SPEC-303 §7 reproducibility).
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_COMPRESSLEVEL = 9

_REDACTED_MARKER = {
    "redacted": True,
    "policy": REDACTION_POLICY_STRIP_PAYLOADS,
    "policy_version": REDACTION_POLICY_VERSION,
}

#: Canonical JSON serialization shared by every exported document.
_JSON_DUMP = {
    "ensure_ascii": True,
    "sort_keys": True,
    "separators": (",", ":"),
}

#: CSV index columns (SPEC-303 §7: 事件索引表；嵌套 payload 压缩为 JSON 字符串).
CSV_COLUMNS = (
    "record_kind",
    "record_id",
    "schema_version",
    "session_id",
    "run_id",
    "scenario_id",
    "journal_seq",
    "event_id",
    "event_type",
    "severity",
    "producer_id",
    "source_id",
    "source_seq",
    "clock_domain",
    "clock_epoch",
    "timestamp_ns",
    "time_semantics",
    "node_id",
    "service_id",
    "pid",
    "fault_id",
    "tags_json",
    "payload_json",
)


@dataclass(frozen=True)
class ExportRequest:
    """One export job's options + generation metadata (SPEC-303 §7).

    ``export_id`` and ``created_at`` are generation metadata (injected —
    never a wall-clock read inside this module); everything else is part of
    the reproducibility contract.
    """

    export_id: str
    created_at: TimelineTimepoint
    session_id: str
    tenant_id: str = LOCAL_TENANT_ID
    formats: tuple[str, ...] = (EXPORT_FORMAT_JSONL,)
    redaction_policy: str = REDACTION_POLICY_NONE
    clock_domain: Optional[str] = None
    start_ns: Optional[int] = None
    end_ns: Optional[int] = None
    record_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportResult:
    """Pure export output: manifest + artifact bytes + every file digest."""

    manifest: dict
    files: dict[str, bytes]
    file_digests: dict[str, str]


def build_export(
    records: Iterable[TimelineRecord], request: ExportRequest
) -> ExportResult:
    """Assemble the export artifacts in memory (SPEC-303 §7).

    ``records`` must be the ordered snapshot of the exported interval (the
    caller's query order — the §4 ordering discipline lives in the service
    face). Raises ValueError for scope/option violations and
    :class:`TimelineError` (code ``OBS_INVALID_ENVELOPE``) when secret-like
    payload material survives into a ``none``-policy export.
    """
    record_list = list(records)
    _validate_request(request, record_list)

    documents: list[dict] = []
    redacted_ids: list[str] = []
    for record in record_list:
        document = record.model_dump(mode="json")
        if request.redaction_policy == REDACTION_POLICY_STRIP_PAYLOADS:
            _redact_document(document)
            redacted_ids.append(document["record_id"])
        documents.append(document)

    jsonl_bytes = _build_jsonl_bytes(documents)
    files: dict[str, bytes] = {}
    if request.redaction_policy == REDACTION_POLICY_NONE:
        violations = secret_scan_violations(documents)
        if violations:
            raise TimelineError(
                "OBS_INVALID_ENVELOPE",
                "export content carries secret-like payload keys (SPEC-301 "
                "§7): refusing the export — use a redaction policy or fix "
                "the source records",
                details={"violations": violations[:20]},
            )

    counts: dict[str, int] = {}
    for document in documents:
        kind = document["record_kind"]
        counts[kind] = counts.get(kind, 0) + 1

    manifest = {
        "schema_version": TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION,
        "export_id": request.export_id,
        "created_at": request.created_at.model_dump(mode="json"),
        "scope": {
            "tenant_id": request.tenant_id,
            "session_id": request.session_id,
        },
        "filters": {
            "record_kinds": list(request.record_kinds),
            "clock_domain": request.clock_domain,
            "start_ns": request.start_ns,
            "end_ns": request.end_ns,
        },
        "clock_domain": request.clock_domain,
        "start_ns": request.start_ns,
        "end_ns": request.end_ns,
        "record_counts_by_kind": counts,
        "total_records": len(documents),
        "redaction_policy": request.redaction_policy,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
    }

    # Content files first, then finalize the manifest (the manifest cannot
    # hash itself — the ZIP's digest rides on ExportResult.file_digests),
    # and only then build the ZIP around the FINAL manifest bytes.
    content_entries: list[dict] = []
    if EXPORT_FORMAT_JSONL in request.formats:
        files[JSONL_FILENAME] = jsonl_bytes
        content_entries.append(
            _file_entry(JSONL_FILENAME, jsonl_bytes, record_format="jsonl")
        )
    if EXPORT_FORMAT_CSV in request.formats:
        csv_bytes = _build_csv_bytes(documents)
        files[CSV_FILENAME] = csv_bytes
        content_entries.append(
            _file_entry(CSV_FILENAME, csv_bytes, record_format="csv_index")
        )
    if request.redaction_policy != REDACTION_POLICY_NONE:
        report = {
            "policy": request.redaction_policy,
            "policy_version": REDACTION_POLICY_VERSION,
            "redacted_record_count": len(redacted_ids),
            "redacted_record_ids": redacted_ids,
        }
        report_bytes = json.dumps(report, **_JSON_DUMP).encode("utf-8") + b"\n"
        files[REDACTION_REPORT_FILENAME] = report_bytes
        content_entries.append(
            _file_entry(
                REDACTION_REPORT_FILENAME,
                report_bytes,
                record_format="redaction_report",
            )
        )

    manifest["files"] = content_entries
    files[MANIFEST_FILENAME] = (
        json.dumps(manifest, **_JSON_DUMP).encode("utf-8") + b"\n"
    )

    if EXPORT_FORMAT_ZIP in request.formats:
        # ZIP = JSONL + 元数据 (SPEC-303 §7): the JSONL member is always
        # embedded even when the outer artifact set does not include a
        # standalone JSONL file.
        files[ZIP_FILENAME] = _build_zip_bytes(files, jsonl_bytes)

    file_digests = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in files.items()
    }
    return ExportResult(
        manifest=manifest, files=files, file_digests=file_digests
    )


def write_export(result: ExportResult, destination_dir: Path) -> list[Path]:
    """Materialize the export artifacts under ``destination_dir`` (I/O half).

    Returns the written paths. Filesystem work stays in this explicit
    function (domain models never touch pathlib — import contract C3);
    callers own the destination lifecycle.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in sorted(result.files.items()):
        path = destination_dir / name
        path.write_bytes(content)
        written.append(path)
    return written


def secret_scan_violations(document: object) -> list[str]:
    """Walk a JSON document and report secret-like key paths (SPEC-301 §7).

    Reuses the envelope layer's key policy implementation
    (``domain.observation.envelope``) — no parallel token lists are kept
    here, so the export scan and the ingest scan can never drift apart.
    """
    from domain.observation.envelope import _check_key  # reuse, not a copy

    violations: list[str] = []

    def _walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_path = f"{path}.{key}" if path else str(key)
                try:
                    _check_key(str(key))
                except Exception:
                    violations.append(key_path)
                _walk(value, key_path)
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")

    _walk(document, "")
    return violations


# --- internals -----------------------------------------------------------------


def _validate_request(request: ExportRequest, records: list[TimelineRecord]) -> None:
    for fmt in request.formats:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(
                f"unsupported export format {fmt!r}; one of {EXPORT_FORMATS}"
            )
    if request.redaction_policy not in REDACTION_POLICIES:
        raise ValueError(
            f"unsupported redaction policy {request.redaction_policy!r}; "
            f"one of {REDACTION_POLICIES}"
        )
    for record in records:
        if record.session_id != request.session_id:
            raise ValueError(
                "export scope violation: record "
                f"{record.record_id!r} belongs to session "
                f"{record.session_id!r}, not {request.session_id!r} "
                "(SPEC-300 §9: exports are scope-bound)"
            )


def _redact_document(document: dict) -> None:
    """Apply ``strip_payloads`` in place (evidence refs always survive)."""
    payload = document.get("payload")
    if isinstance(payload, dict) and payload.get("tombstone") is True:
        return  # a tombstone carries no content to redact (SPEC-303 §8)
    if document.get("record_kind") == TimelineRecordKind.EVENT.value and isinstance(
        payload, dict
    ):
        envelope = payload.get("envelope")
        if isinstance(envelope, dict):
            redacted = dict(envelope)
            redacted["payload"] = dict(_REDACTED_MARKER)
            document["payload"] = {"envelope": redacted}
            return
    document["payload"] = dict(_REDACTED_MARKER)


def _build_jsonl_bytes(documents: list[dict]) -> bytes:
    lines = [json.dumps(document, **_JSON_DUMP) for document in documents]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_csv_bytes(documents: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for document in documents:
        timepoint = document["timepoint"]
        writer.writerow(
            [
                document["record_kind"],
                document["record_id"],
                document["schema_version"],
                document["session_id"],
                document.get("run_id") or "",
                document.get("scenario_id") or "",
                _cell(document.get("journal_seq")),
                _cell(document.get("event_id")),
                _cell(document.get("event_type")),
                _cell(document.get("severity")),
                _cell(document.get("producer_id")),
                document["source_id"],
                _cell(document.get("source_seq")),
                timepoint["clock_domain"],
                timepoint["clock_epoch"],
                timepoint["value_ns"],
                timepoint["semantics"],
                _cell(document.get("node_id")),
                _cell(document.get("service_id")),
                _cell(document.get("pid")),
                _cell(document.get("fault_id")),
                json.dumps(document.get("tags", []), **_JSON_DUMP),
                json.dumps(document.get("payload", {}), **_JSON_DUMP),
            ]
        )
    return buffer.getvalue().encode("utf-8")


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _build_zip_bytes(existing: dict[str, bytes], jsonl_bytes: bytes) -> bytes:
    """ZIP = JSONL + 元数据 (+ 脱敏报告), fixed timestamps (SPEC-303 §7)."""
    members: dict[str, bytes] = {
        JSONL_FILENAME: jsonl_bytes,
        MANIFEST_FILENAME: existing[MANIFEST_FILENAME],
    }
    if REDACTION_REPORT_FILENAME in existing:
        members[REDACTION_REPORT_FILENAME] = existing[REDACTION_REPORT_FILENAME]
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=_ZIP_COMPRESSLEVEL
    ) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[name], compresslevel=_ZIP_COMPRESSLEVEL)
    return buffer.getvalue()


def _file_entry(name: str, content: bytes, *, record_format: str) -> dict:
    return {
        "name": name,
        "record_format": record_format,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


__all__ = [
    "CSV_COLUMNS",
    "CSV_FILENAME",
    "EXPORT_FORMATS",
    "EXPORT_FORMAT_CSV",
    "EXPORT_FORMAT_JSONL",
    "EXPORT_FORMAT_ZIP",
    "JSONL_FILENAME",
    "MANIFEST_FILENAME",
    "REDACTION_POLICIES",
    "REDACTION_POLICY_NONE",
    "REDACTION_POLICY_STRIP_PAYLOADS",
    "REDACTION_POLICY_VERSION",
    "REDACTION_REPORT_FILENAME",
    "TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION",
    "ZIP_FILENAME",
    "ExportRequest",
    "ExportResult",
    "build_export",
    "secret_scan_violations",
    "write_export",
]
