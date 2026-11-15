"""SPEC-303 timeline export — JSONL/CSV/ZIP, manifest completeness, digest
integrity, reproducibility, redaction and secret scanning (REQ-OBS-303-005).

The export core (:func:`build_export`) is PURE: it assembles bytes in
memory (no disk I/O — unit layer, SPEC-505 §3); the file-writing half is
covered by the integration round-trip test. Determinism discipline:
``created_at`` / ``export_id`` are injected generation metadata; the same
record interval + the same options must byte-reproduce every content
artifact (SPEC-303 §7), with ZIP member timestamps pinned to the fixed
1980 epoch so the container itself reproduces.
"""

import csv
import hashlib
import io
import json
import zipfile

import pytest

from application.observation.timeline.export import (
    REDACTION_POLICY_NONE,
    REDACTION_POLICY_STRIP_PAYLOADS,
    TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION,
    ExportRequest,
    build_export,
    secret_scan_violations,
)
from application.observation.timeline.errors import TimelineError
from domain.observation import (
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
    parse_envelope,
)

SESSION_ID = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SIM_DOMAIN = f"sim:{SESSION_ID}"
WALL = "wall:utc"
EVENT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _source_timepoint(value_ns: int, clock_domain: str = SIM_DOMAIN) -> TimelineTimepoint:
    return TimelineTimepoint(
        value_ns=value_ns,
        clock_domain=clock_domain,
        clock_epoch=0,
        semantics=TimepointSemantics.SOURCE,
    )


def _wall_timepoint(value_ns: int = 1_700_000_000_000_000_000) -> TimelineTimepoint:
    return TimelineTimepoint(
        value_ns=value_ns,
        clock_domain=WALL,
        clock_epoch=0,
        semantics=TimepointSemantics.OBSERVED,
    )


def _envelope_doc(seq: int, payload: dict | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": EVENT_ID,
        "event_type": "simulation.run_started",
        "producer": {
            "producer_id": "simulation-runtime",
            "producer_version": "0.5.0",
            "instance_id": "instance-1",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": SESSION_ID,
            "run_id": "run-1",
            "scenario_id": None,
        },
        "time": {
            "source": {
                "value_ns": 1_000 * seq,
                "clock_domain": SIM_DOMAIN,
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 1_700_000_000_000_000_000 + seq,
                "clock_domain": WALL,
                "clock_epoch": 0,
            },
        },
        "correlation": {
            "node_id": None,
            "service_id": None,
            "pid": None,
            "fault_id": None,
        },
        "severity": "info",
        "payload": payload or {},
        "tags": [],
        "journal_seq": seq,
    }


def _event_record(seq: int, payload: dict | None = None) -> TimelineRecord:
    return TimelineRecord(
        record_kind=TimelineRecordKind.EVENT,
        record_id=f"rec-event-{seq}",
        session_id=SESSION_ID,
        run_id="run-1",
        source_id="simulation-runtime",
        source_seq=seq,
        journal_seq=seq,
        event_id=EVENT_ID,
        event_type="simulation.run_started",
        severity="info",
        producer_id="simulation-runtime",
        timepoint=_source_timepoint(1_000 * seq),
        tags=(),
        payload={"envelope": _envelope_doc(seq, payload)},
    )


def _annotation_record(value_ns: int = 700) -> TimelineRecord:
    return TimelineRecord(
        record_kind=TimelineRecordKind.ANNOTATION,
        record_id="rec-annotation-1",
        session_id=SESSION_ID,
        source_id="operator-console",
        source_seq=1,
        timepoint=_source_timepoint(value_ns),
        tags=("training",),
        payload={"note": "fault window starts here"},
    )


def _request(**overrides) -> ExportRequest:
    values = dict(
        export_id="export-0001",
        created_at=_wall_timepoint(),
        session_id=SESSION_ID,
        formats=("jsonl", "csv"),
    )
    values.update(overrides)
    return ExportRequest(**values)


class TestJsonlExport:
    def test_one_canonical_document_per_line(self):
        records = [_event_record(1), _annotation_record(), _event_record(2)]
        result = build_export(records, _request())
        lines = result.files["timeline.jsonl"].decode("utf-8").splitlines()
        assert len(lines) == 3
        for line, record in zip(lines, records):
            document = json.loads(line)
            assert line == json.dumps(
                document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
            assert TimelineRecord.model_validate(document) == record

    def test_event_envelope_round_trips_through_parse_envelope(self):
        """REQ-OBS-303-001: the exported JSONL preserves the evidence chain."""
        result = build_export([_event_record(7)], _request())
        line = result.files["timeline.jsonl"].decode("utf-8").splitlines()[0]
        envelope = parse_envelope(json.loads(line)["payload"]["envelope"])
        assert envelope.event_id == EVENT_ID
        assert envelope.journal_seq == 7


class TestCsvExport:
    def test_csv_is_the_event_index_with_embedded_payload_json(self):
        records = [_event_record(1), _annotation_record()]
        result = build_export(records, _request())
        rows = list(
            csv.reader(io.StringIO(result.files["timeline.csv"].decode("utf-8")))
        )
        header = rows[0]
        assert "record_kind" in header
        assert "journal_seq" in header
        assert "event_id" in header
        assert "payload_json" in header
        assert len(rows) == 3  # header + 2 records
        payload_col = header.index("payload_json")
        embedded = json.loads(rows[1][payload_col])
        assert embedded["envelope"]["event_id"] == EVENT_ID


class TestManifest:
    def test_manifest_contains_all_required_fields(self):
        """REQ-OBS-303-005 manifest obligations (SPEC-303 §7)."""
        records = [_event_record(1), _annotation_record(), _event_record(2)]
        result = build_export(records, _request(clock_domain=SIM_DOMAIN))
        manifest = result.manifest
        assert manifest["schema_version"] == TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION
        assert manifest["export_id"] == "export-0001"
        assert manifest["created_at"]["clock_domain"] == WALL
        assert manifest["scope"] == {"tenant_id": "local", "session_id": SESSION_ID}
        assert manifest["clock_domain"] == SIM_DOMAIN
        assert manifest["start_ns"] is None and manifest["end_ns"] is None
        assert manifest["record_counts_by_kind"] == {"event": 2, "annotation": 1}
        assert manifest["total_records"] == 3
        assert manifest["redaction_policy"] == REDACTION_POLICY_NONE
        assert manifest["redaction_policy_version"] == "1"

    def test_manifest_file_digests_match_file_bytes(self):
        result = build_export([_event_record(1)], _request())
        for entry in result.manifest["files"]:
            name = entry["name"]
            digest = hashlib.sha256(result.files[name]).hexdigest()
            assert entry["sha256"] == digest

    def test_file_digests_cover_every_file_including_zip(self):
        result = build_export([_event_record(1)], _request(formats=("jsonl", "zip")))
        assert set(result.file_digests) >= {
            "manifest.json",
            "timeline.jsonl",
            "timeline-export.zip",
        }
        for name, digest in result.file_digests.items():
            assert hashlib.sha256(result.files[name]).hexdigest() == digest

    def test_manifest_document_is_a_valid_export_manifest_record_payload(self):
        """The manifest closes the six-kind loop: it is itself exportable as
        an ``export_manifest`` timeline record payload (SPEC-303 §3)."""
        result = build_export([_event_record(1)], _request())
        record = TimelineRecord(
            record_kind=TimelineRecordKind.EXPORT_MANIFEST,
            record_id="rec-export-0001",
            session_id=SESSION_ID,
            source_id="timeline-exporter",
            source_seq=1,
            timepoint=_wall_timepoint(),
            tags=(),
            payload=result.manifest,
        )
        assert record.record_kind is TimelineRecordKind.EXPORT_MANIFEST


class TestReproducibility:
    def test_same_interval_same_options_byte_reproduce(self):
        """SPEC-303 §7: only generation metadata (export_id/created_at)
        may differ between two exports of the same interval."""
        records = [_event_record(1), _annotation_record(), _event_record(2)]
        first = build_export(records, _request())
        second = build_export(
            records,
            _request(
                export_id="export-0002",
                created_at=_wall_timepoint(1_700_000_000_100_000_000),
            ),
        )
        assert first.files["timeline.jsonl"] == second.files["timeline.jsonl"]
        assert first.files["timeline.csv"] == second.files["timeline.csv"]
        stripped_first = _without_generation_metadata(first.manifest)
        stripped_second = _without_generation_metadata(second.manifest)
        assert stripped_first == stripped_second

    def _zip_helper_guard(self):  # pragma: no cover - documentation stub
        raise NotImplementedError


def _without_generation_metadata(manifest: dict) -> dict:
    stripped = dict(manifest)
    stripped.pop("export_id", None)
    stripped.pop("created_at", None)
    return stripped


class TestZipExport:
    def test_zip_members_manifest_and_fixed_timestamps(self):
        result = build_export(
            [_event_record(1), _annotation_record()],
            _request(formats=("jsonl", "zip")),
        )
        raw = result.files["timeline-export.zip"]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = set(archive.namelist())
            assert members == {"timeline.jsonl", "manifest.json"}
            for info in archive.infolist():
                assert info.date_time == (1980, 1, 1, 0, 0, 0)
            embedded_manifest = archive.read("manifest.json")
            jsonl_bytes = archive.read("timeline.jsonl")
        assert embedded_manifest == result.files["manifest.json"]
        assert jsonl_bytes == result.files["timeline.jsonl"]

    def test_zip_reproducible_for_same_interval_and_options(self):
        """SPEC-303 §10: 同区间同选项重复导出，除生成元数据外逐字节一致.
        The ZIP embeds the manifest, so a changed export_id propagates into
        the container bytes — everything else must be byte-identical, and
        with identical generation metadata the whole ZIP reproduces."""
        records = [_event_record(1)]
        first = build_export(records, _request(formats=("zip",)))
        second = build_export(
            records, _request(formats=("zip",), export_id="export-0002")
        )

        def _members(raw: bytes) -> dict:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                return {name: archive.read(name) for name in archive.namelist()}

        first_members = _members(first.files["timeline-export.zip"])
        second_members = _members(second.files["timeline-export.zip"])
        assert first_members["timeline.jsonl"] == second_members["timeline.jsonl"]
        first_manifest = json.loads(first_members["manifest.json"])
        second_manifest = json.loads(second_members["manifest.json"])
        assert (
            _without_generation_metadata(first_manifest)
            == _without_generation_metadata(second_manifest)
        )

        # With identical generation metadata the container reproduces byte
        # for byte (fixed member timestamps + deterministic deflate).
        third = build_export(records, _request(formats=("zip",)))
        again = build_export(records, _request(formats=("zip",)))
        assert third.files["timeline-export.zip"] == again.files["timeline-export.zip"]


class TestSecretScanAndRedaction:
    def test_scan_finds_secret_like_keys(self):
        document = {"payload": {"biss_key": "0123456789abcdef"}}
        violations = secret_scan_violations(document)
        assert violations == ["payload.biss_key"]

    def test_clean_document_has_no_violations(self):
        assert secret_scan_violations(
            {"payload": {"keyframe_count": 4, "bitrate_bps": 1_000}}
        ) == []

    def test_policy_none_refuses_export_on_secret_detection(self):
        """密钥扫描: a secret-like key in exported content refuses the export
        with the envelope-contract code (SPEC-301 §7 policy)."""
        leaky = _event_record(1, payload={"credential_token": "hunter2"})
        with pytest.raises(TimelineError) as excinfo:
            build_export([leaky], _request())
        assert excinfo.value.code == "OBS_INVALID_ENVELOPE"
        assert "credential_token" in excinfo.value.details["violations"][0]

    def test_strip_payloads_policy_redacts_and_reports(self):
        leaky = _event_record(1, payload={"credential_token": "hunter2"})
        plain = _annotation_record()
        result = build_export(
            [leaky, plain],
            _request(
                formats=("jsonl",),
                redaction_policy=REDACTION_POLICY_STRIP_PAYLOADS,
            ),
        )
        line = result.files["timeline.jsonl"].decode("utf-8").splitlines()[0]
        document = json.loads(line)
        redacted_envelope = document["payload"]["envelope"]
        assert redacted_envelope["payload"] == {
            "redacted": True,
            "policy": REDACTION_POLICY_STRIP_PAYLOADS,
            "policy_version": "1",
        }
        assert redacted_envelope["event_id"] == EVENT_ID  # evidence chain kept
        report = json.loads(result.files["redaction-report.json"].decode("utf-8"))
        assert report["policy"] == REDACTION_POLICY_STRIP_PAYLOADS
        assert leaky.record_id in report["redacted_record_ids"]
        assert plain.record_id in report["redacted_record_ids"]
        assert result.manifest["redaction_policy"] == REDACTION_POLICY_STRIP_PAYLOADS

    def test_redaction_keeps_ids_and_seq_intact(self):
        """REQ-OBS-303-001 survives redaction: event_id/journal_seq stay."""
        leaky = _event_record(3, payload={"biss": "k"})
        result = build_export(
            [leaky],
            _request(
                formats=("jsonl",),
                redaction_policy=REDACTION_POLICY_STRIP_PAYLOADS,
            ),
        )
        document = json.loads(
            result.files["timeline.jsonl"].decode("utf-8").splitlines()[0]
        )
        assert document["event_id"] == EVENT_ID
        assert document["journal_seq"] == 3


class TestTombstonedExport:
    def test_tombstoned_records_export_without_original_payload(self):
        """SPEC-303 §8: deleted records never leak their content via exports."""
        tombstone = TimelineRecord(
            record_kind=TimelineRecordKind.EVENT,
            record_id="rec-tombstone",
            session_id=SESSION_ID,
            source_id="simulation-runtime",
            journal_seq=5,
            event_id=None,
            event_type="simulation.run_started",
            timepoint=_source_timepoint(5_000),
            tags=(),
            payload={
                "tombstone": True,
                "replaces_record_id": "rec-event-5",
                "reason": "gdpr",
            },
        )
        result = build_export([tombstone], _request())
        document = json.loads(
            result.files["timeline.jsonl"].decode("utf-8").splitlines()[0]
        )
        assert document["payload"]["tombstone"] is True
        assert "envelope" not in document["payload"]


class TestRequestValidation:
    def test_unsupported_format_is_refused(self):
        with pytest.raises(ValueError):
            build_export([_event_record(1)], _request(formats=("parquet",)))

    def test_records_outside_the_request_session_are_refused(self):
        other = _annotation_record()
        foreign = other.model_copy(update={"session_id": "other-session"})
        with pytest.raises(ValueError):
            build_export([foreign], _request())
