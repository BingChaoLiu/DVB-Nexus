"""SPEC-303 integration: journal → gateway fan-out → recorder → query →
export round-trip with on-disk artifacts (REQ-OBS-303-001/002/003/005).

Real SPEC-502 SQLite journal + real checkpoint store + real gateway drain:
committed envelopes project to timeline records keeping the original
``event_id`` + ``journal_seq`` (evidence chain intact against the journal
itself), the consumer checkpoint lands as a SPEC-303 §5 record, pagination
walks the timeline without gaps, and the export writes files whose digests
verify against the manifest and whose JSONL rehydrates back through
``parse_envelope``.

Integration layer: tmp file SQLite (``journal`` fixture) + ``tmp_path`` for
export artifacts (SPEC-505 §3). All clock values are injected integers.
"""

import csv
import hashlib
import io
import json
import zipfile

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from application.observation.consumer import ConsumerConfig, JournalTailingConsumer
from application.observation.gateway import EventGateway
from application.observation.timeline.export import (
    ExportRequest,
    build_export,
    write_export,
)
from application.observation.timeline.recorder import TimelineRecorder
from application.observation.timeline.service import (
    TimelineFilter,
    TimelineService,
)
from domain.observation import (
    CheckpointRecord,
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
    parse_envelope,
)

SESSION_ID = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SIM_DOMAIN = f"sim:{SESSION_ID}"
WALL = "wall:utc"
OBSERVED_BASE_NS = 1_700_000_000_000_000_000

EVENT_COUNT = 12


def _envelope_doc(seq_value_ns: int, *, event_type="simulation.run_started", severity="info") -> dict:
    return {
        "schema_version": "1.0",
        "event_id": f"aaaaaaaa-bbbb-4ccc-8ddd-{seq_value_ns:012d}",
        "event_type": event_type,
        "producer": {
            "producer_id": "simulation-runtime",
            "producer_version": "0.5.0",
            "instance_id": "instance-1",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": SESSION_ID,
            "run_id": "run-1",
            "scenario_id": "scn-1",
        },
        "time": {
            "source": {
                "value_ns": seq_value_ns,
                "clock_domain": SIM_DOMAIN,
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": OBSERVED_BASE_NS + seq_value_ns,
                "clock_domain": WALL,
                "clock_epoch": 0,
            },
        },
        "correlation": {
            "node_id": "node-1",
            "service_id": None,
            "pid": None,
            "fault_id": None,
        },
        "severity": severity,
        "payload": {"progress_ratio": 0.5},
        "tags": ["training"],
    }


@pytest.fixture
def stack(journal):
    """Journal + gateway + recorder + checkpoint store over one session.

    The connection comes from the PRODUCTION ``adapters.storage.db.connect``
    (row_factory + pragma policy) over the fixture's migrated tmp database —
    the same posture as ``test_gateway_journal_restart.py``."""
    connection = connect(journal.db_path)
    try:
        journal_adapter = SqliteEventJournal(connection)
        gateway = EventGateway(journal_adapter)
        recorder = TimelineRecorder()
        recorder.attach_gateway(gateway)
        checkpoints = SqliteCheckpointStore(connection)
        consumer = JournalTailingConsumer(
            journal_adapter,
            checkpoints,
            SESSION_ID,
            consumer_id="timeline-recorder",
            handler=lambda record: None,
            config=ConsumerConfig(batch_size=5),
        )
        yield {
            "connection": connection,
            "journal": journal_adapter,
            "gateway": gateway,
            "recorder": recorder,
            "checkpoints": checkpoints,
            "consumer": consumer,
        }
    finally:
        connection.close()


def _publish_events(gateway: EventGateway, count: int) -> None:
    for index in range(1, count + 1):
        result = gateway.accept(
            _envelope_doc(1_000 * index, severity="info" if index % 2 else "notice")
        )
        assert result.outcome.name == "ACCEPTED"
    committed = gateway.drain()
    assert committed == count


def _advance_checkpoint(stack) -> CheckpointRecord:
    processed = stack["consumer"].catch_up()
    assert processed == EVENT_COUNT
    checkpoint_seq = stack["consumer"].checkpoint_seq()
    # Injected wall reading (SPEC-201 discipline: no wall clock in tests)
    # and injected virtual time bound to the session clock.
    return CheckpointRecord(
        checkpoint_id="cp-integration-0001",
        session_id=SESSION_ID,
        journal_seq=checkpoint_seq,
        clock_domain=SIM_DOMAIN,
        virtual_time_ns=12_000,
        created_at=TimelineTimepoint(
            value_ns=OBSERVED_BASE_NS + 999_999,
            clock_domain=WALL,
            clock_epoch=0,
            semantics=TimepointSemantics.OBSERVED,
        ),
        integrity_digest=hashlib.sha256(b"state-v1").hexdigest(),
    )


def _walk_all_pages(service: TimelineService) -> list[TimelineRecord]:
    records: list[TimelineRecord] = []
    cursor = None
    while True:
        page = service.query(
            TimelineFilter(session_id=SESSION_ID, clock_domain=SIM_DOMAIN),
            page_size=4,
            cursor=cursor,
        )
        records.extend(page.records)
        if page.next_cursor is None:
            return records
        cursor = page.next_cursor


class TestFullChainTimeline:
    def test_gateway_events_checkpoint_and_operator_records_form_the_timeline(
        self, stack
    ):
        _publish_events(stack["gateway"], EVENT_COUNT)
        recorder = stack["recorder"]
        checkpoint = _advance_checkpoint(stack)
        recorder.record_checkpoint(checkpoint)
        recorder.add_annotation(
            session_id=SESSION_ID,
            source_id="operator-console",
            timepoint=TimelineTimepoint(
                value_ns=6_500,
                clock_domain=SIM_DOMAIN,
                clock_epoch=0,
                semantics=TimepointSemantics.SOURCE,
            ),
            payload={"note": "fault window marker"},
        )

        service = TimelineService(recorder)
        records = _walk_all_pages(service)

        # REQ-OBS-303-002: journal segment first (seq 1..N), then the
        # cross-source segment (checkpoint at virtual 12_000, annotation
        # at 6_500 → annotation before checkpoint).
        assert [r.journal_seq for r in records if r.journal_seq is not None] == list(
            range(1, EVENT_COUNT + 1)
        )
        tail = [r for r in records if r.journal_seq is None]
        assert [r.record_kind for r in tail] == [
            TimelineRecordKind.ANNOTATION,
            TimelineRecordKind.CHECKPOINT,
        ]

    def test_event_records_match_the_journal_evidence(self, stack):
        """REQ-OBS-303-001: event_id/journal_seq agree with the journal."""
        _publish_events(stack["gateway"], EVENT_COUNT)
        recorder = stack["recorder"]
        records = recorder.records(SESSION_ID)
        journal_rows = stack["journal"].query(
            SESSION_ID, after_seq=0, limit=100
        )
        assert len(records) == len(journal_rows) == EVENT_COUNT
        for record, row in zip(records, journal_rows):
            assert record.event_id == row.event_id
            assert record.journal_seq == row.journal_seq

    def test_checkpoint_is_observation_only(self, stack):
        """REQ-OBS-303-003: checkpointing advanced the consumer cursor and
        recorded the §5 fields — the journal holds exactly the published
        events (no checkpoint ever wrote simulation state)."""
        _publish_events(stack["gateway"], EVENT_COUNT)
        before = stack["gateway"].metrics()
        checkpoint = _advance_checkpoint(stack)
        stack["recorder"].record_checkpoint(checkpoint)
        after = stack["gateway"].metrics()
        # The gateway itself observed nothing new: checkpoints consume the
        # journal, they never publish or mutate through it.
        assert after.accepted == before.accepted
        assert after.rejected == before.rejected
        record = [
            r
            for r in stack["recorder"].records(SESSION_ID)
            if r.record_kind is TimelineRecordKind.CHECKPOINT
        ][0]
        assert record.payload["checkpoint_id"] == "cp-integration-0001"
        assert record.payload["journal_seq"] == EVENT_COUNT
        assert record.payload["virtual_time_ns"] == 12_000
        assert record.payload["integrity_digest"] == hashlib.sha256(b"state-v1").hexdigest()
        assert record.timepoint.semantics is TimepointSemantics.SOURCE

    def test_lanes_split_sim_and_wall_views(self, stack):
        """REQ-OBS-303-002: lanes partition incompatible time bases."""
        _publish_events(stack["gateway"], EVENT_COUNT)
        service = TimelineService(stack["recorder"])
        page = service.query(TimelineFilter(session_id=SESSION_ID, lanes=True))
        lane_keys = [(lane.clock_domain, lane.clock_epoch) for lane in page.lanes]
        assert (SIM_DOMAIN, 0) in lane_keys
        for lane in page.lanes:
            domains = {r.timepoint.clock_domain for r in lane.records}
            assert domains == {lane.clock_domain}
        sim_lane = next(
            lane for lane in page.lanes if lane.clock_domain == SIM_DOMAIN
        )
        assert len(sim_lane.records) == EVENT_COUNT

    def test_cursor_walk_is_complete(self, stack):
        _publish_events(stack["gateway"], EVENT_COUNT)
        service = TimelineService(stack["recorder"])
        records = _walk_all_pages(service)
        seqs = [r.journal_seq for r in records if r.journal_seq is not None]
        assert seqs == sorted(set(seqs)) == list(range(1, EVENT_COUNT + 1))


class TestExportRoundTrip:
    def test_export_writes_files_that_verify_and_rehydrate(self, stack, tmp_path):
        """REQ-OBS-303-005: three formats, manifest digests, JSONL rehydration."""
        _publish_events(stack["gateway"], EVENT_COUNT)
        checkpoint = _advance_checkpoint(stack)
        stack["recorder"].record_checkpoint(checkpoint)
        service = TimelineService(stack["recorder"])
        page = service.query(
            TimelineFilter(session_id=SESSION_ID, clock_domain=SIM_DOMAIN)
        )

        request = ExportRequest(
            export_id="export-integration-0001",
            created_at=TimelineTimepoint(
                value_ns=OBSERVED_BASE_NS + 2_000_000,
                clock_domain=WALL,
                clock_epoch=0,
                semantics=TimepointSemantics.OBSERVED,
            ),
            session_id=SESSION_ID,
            formats=("jsonl", "csv", "zip"),
            clock_domain=SIM_DOMAIN,
            record_kinds=("event", "checkpoint"),
        )
        result = build_export(page.records, request)

        written = write_export(result, tmp_path)
        assert {path.name for path in written} == {
            "manifest.json",
            "timeline.jsonl",
            "timeline.csv",
            "timeline-export.zip",
        }

        # 1) every written file's digest matches ExportResult and the manifest
        for name, digest in result.file_digests.items():
            on_disk = (tmp_path / name).read_bytes()
            assert hashlib.sha256(on_disk).hexdigest() == digest
        for entry in result.manifest["files"]:
            on_disk = (tmp_path / entry["name"]).read_bytes()
            assert hashlib.sha256(on_disk).hexdigest() == entry["sha256"]

        # 2) JSONL rehydrates: records validate; envelopes re-parse through
        #    the canonical surface with the evidence chain intact.
        lines = (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(page.records)
        envelope_count = 0
        for line in lines:
            record = TimelineRecord.model_validate(json.loads(line))
            if record.record_kind is TimelineRecordKind.EVENT:
                envelope = parse_envelope(record.payload["envelope"])
                assert envelope.journal_seq == record.journal_seq
                assert envelope.scope.session_id == SESSION_ID
                envelope_count += 1
        assert envelope_count == EVENT_COUNT

        # 3) CSV index rows match the JSONL record count.
        csv_rows = list(
            csv.reader(
                io.StringIO((tmp_path / "timeline.csv").read_text(encoding="utf-8"))
            )
        )
        assert len(csv_rows) == len(lines) + 1

        # 4) ZIP carries the JSONL + manifest members and verifies.
        with zipfile.ZipFile(tmp_path / "timeline-export.zip") as archive:
            assert set(archive.namelist()) == {"timeline.jsonl", "manifest.json"}
            assert (
                archive.read("timeline.jsonl")
                == (tmp_path / "timeline.jsonl").read_bytes()
            )
            assert (
                archive.read("manifest.json")
                == (tmp_path / "manifest.json").read_bytes()
            )
        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["total_records"] == len(page.records)
        assert manifest["record_counts_by_kind"] == {
            "event": EVENT_COUNT,
            "checkpoint": 1,
        }
        assert manifest["export_id"] == "export-integration-0001"

    def test_export_reproducible_across_service_query_and_recorder_snapshot(
        self, stack
    ):
        """SPEC-303 §7: same interval + same options ⇒ identical content
        bytes regardless of whether the source is a fresh query or the
        recorder snapshot (content-derived record ids)."""
        _publish_events(stack["gateway"], 6)
        service = TimelineService(stack["recorder"])
        query_page = service.query(
            TimelineFilter(session_id=SESSION_ID, clock_domain=SIM_DOMAIN)
        )
        snapshot_records = [
            r
            for r in stack["recorder"].records(SESSION_ID)
            if r.timepoint.clock_domain == SIM_DOMAIN
        ]
        snapshot_records.sort(key=lambda r: r.journal_seq or 0)

        def _request(export_id: str) -> ExportRequest:
            return ExportRequest(
                export_id=export_id,
                created_at=TimelineTimepoint(
                    value_ns=OBSERVED_BASE_NS,
                    clock_domain=WALL,
                    clock_epoch=0,
                    semantics=TimepointSemantics.OBSERVED,
                ),
                session_id=SESSION_ID,
                formats=("jsonl",),
                clock_domain=SIM_DOMAIN,
            )

        first = build_export(query_page.records, _request("export-a"))
        second = build_export(snapshot_records, _request("export-b"))
        assert first.files["timeline.jsonl"] == second.files["timeline.jsonl"]

    def test_manifest_conforms_to_the_repo_schema_file(self, stack):
        """The repository manifest schema
        (docs/schemas/timeline-export-manifest.schema.json) and the builder
        must not drift: every schema-required key exists on the produced
        manifest, and file/timepoint sub-shapes match the schema."""
        from tests._support.paths import repo_root

        schema_path = (
            repo_root() / "docs" / "schemas" / "timeline-export-manifest.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$id"].endswith("timeline-export-manifest.schema.json")

        _publish_events(stack["gateway"], 3)
        result = build_export(
            stack["recorder"].records(SESSION_ID),
            ExportRequest(
                export_id="export-schema-check",
                created_at=TimelineTimepoint(
                    value_ns=OBSERVED_BASE_NS,
                    clock_domain=WALL,
                    clock_epoch=0,
                    semantics=TimepointSemantics.OBSERVED,
                ),
                session_id=SESSION_ID,
                formats=("jsonl", "csv", "zip"),
            ),
        )
        manifest = result.manifest
        assert set(schema["required"]) <= set(manifest)
        assert manifest["schema_version"] == schema["properties"]["schema_version"]["const"]
        assert manifest["redaction_policy"] in schema["properties"]["redaction_policy"]["enum"]
        assert manifest["redaction_policy_version"] == (
            schema["properties"]["redaction_policy_version"]["const"]
        )
        timepoint_required = set(schema["$defs"]["timepoint"]["required"])
        assert timepoint_required <= set(manifest["created_at"])
        file_required = set(schema["properties"]["files"]["items"]["required"])
        for entry in manifest["files"]:
            assert file_required <= set(entry)
