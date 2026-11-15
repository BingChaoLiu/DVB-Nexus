"""SPEC-303 export manifest structural conformance (REQ-OBS-303-005).

Unit-layer shape checks for the manifest document produced by
``build_export`` — the required-key set, the record-level timepoint shape
(clock_epoch + explicit semantics per the #12 ruling) and the per-file
digest entries must match the repository authority
``docs/schemas/timeline-export-manifest.schema.json`` (the schema file
itself is cross-checked against this builder in the integration round-trip
test; no disk reads here — SPEC-505 §3 unit posture).
"""

import json

from application.observation.timeline.export import ExportRequest, build_export
from domain.observation import TimelineRecord, TimelineRecordKind, TimelineTimepoint, TimepointSemantics

SESSION_ID = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"

#: Mirrors ``required`` in docs/schemas/timeline-export-manifest.schema.json.
MANIFEST_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "export_id",
        "created_at",
        "scope",
        "filters",
        "clock_domain",
        "start_ns",
        "end_ns",
        "record_counts_by_kind",
        "total_records",
        "redaction_policy",
        "redaction_policy_version",
        "files",
    }
)

FILE_ENTRY_REQUIRED_KEYS = frozenset({"name", "record_format", "bytes", "sha256"})

TIMEPOINT_REQUIRED_KEYS = frozenset(
    {"value_ns", "clock_domain", "clock_epoch", "semantics"}
)

KINDS = {kind.value for kind in TimelineRecordKind}


def _timepoint(value_ns: int, clock_domain: str, semantics: str) -> TimelineTimepoint:
    return TimelineTimepoint(
        value_ns=value_ns,
        clock_domain=clock_domain,
        clock_epoch=0,
        semantics=TimepointSemantics(semantics),
    )


def _event_record(seq: int) -> TimelineRecord:
    return TimelineRecord(
        record_kind=TimelineRecordKind.EVENT,
        record_id=f"rec-{seq}",
        session_id=SESSION_ID,
        source_id="simulation-runtime",
        source_seq=seq,
        journal_seq=seq,
        event_id=f"aaaaaaaa-bbbb-4ccc-8ddd-{seq:012d}",
        event_type="simulation.run_started",
        severity="info",
        producer_id="simulation-runtime",
        timepoint=_timepoint(1_000 * seq, f"sim:{SESSION_ID}", "source"),
        tags=(),
        payload={"envelope": {"event_id": f"aaaaaaaa-bbbb-4ccc-8ddd-{seq:012d}"}},
    )


def test_manifest_carries_every_required_key():
    result = build_export(
        [_event_record(1)],
        ExportRequest(
            export_id="e",
            created_at=_timepoint(1, "wall:utc", "observed"),
            session_id=SESSION_ID,
        ),
    )
    assert MANIFEST_REQUIRED_KEYS <= set(result.manifest)


def test_created_at_is_a_record_level_timepoint():
    result = build_export(
        [_event_record(1)],
        ExportRequest(
            export_id="e",
            created_at=_timepoint(1, "wall:utc", "observed"),
            session_id=SESSION_ID,
        ),
    )
    created_at = result.manifest["created_at"]
    assert TIMEPOINT_REQUIRED_KEYS <= set(created_at)
    assert created_at["semantics"] in {"source", "observed", "derived"}
    assert isinstance(created_at["clock_epoch"], int)


def test_file_entries_carry_name_format_bytes_and_sha256():
    result = build_export(
        [_event_record(1)],
        ExportRequest(
            export_id="e",
            created_at=_timepoint(1, "wall:utc", "observed"),
            session_id=SESSION_ID,
            formats=("jsonl", "csv"),
        ),
    )
    for entry in result.manifest["files"]:
        assert FILE_ENTRY_REQUIRED_KEYS <= set(entry)
        digest = entry["sha256"]
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_record_counts_are_keyed_by_canonical_kinds():
    result = build_export(
        [_event_record(1), _event_record(2)],
        ExportRequest(
            export_id="e",
            created_at=_timepoint(1, "wall:utc", "observed"),
            session_id=SESSION_ID,
        ),
    )
    counts = result.manifest["record_counts_by_kind"]
    assert set(counts) <= KINDS
    assert counts == {"event": 2}
    assert result.manifest["total_records"] == sum(counts.values())


def test_manifest_json_serialization_is_canonical_and_reparseable():
    result = build_export(
        [_event_record(1)],
        ExportRequest(
            export_id="e",
            created_at=_timepoint(1, "wall:utc", "observed"),
            session_id=SESSION_ID,
        ),
    )
    raw = result.files["manifest.json"]
    document = json.loads(raw.decode("utf-8"))
    assert document == result.manifest
    canonical = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    assert raw == canonical
