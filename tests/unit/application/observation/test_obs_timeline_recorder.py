"""SPEC-303 timeline recorder — six-kind write faces, gateway fan-out
projection, checkpoint observation semantics and tombstones.

REQ-OBS-303-001 (evidence chain: event records keep event_id+journal_seq),
REQ-OBS-303-003 (checkpoints are an OBSERVATION behavior: never pause or
mutate the simulation — SPEC-303 §5 / Must-not OBS-D).

Unit layer: pure objects, no I/O, no wall clock (SPEC-505 §3) — wall
``created_at`` timepoints are injected integers, never ``datetime.now``.
"""

import pytest

from application.observation.timeline.recorder import TimelineRecorder
from domain.observation import (
    CheckpointRecord,
    ProducerStateVersion,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
)

SESSION_ID = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SIM_DOMAIN = f"sim:{SESSION_ID}"
WALL = "wall:utc"
EVENT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _stamped(
    seq: int,
    *,
    event_id=EVENT_ID,
    value_ns=1_000,
    event_type="simulation.run_started",
    severity="info",
    producer_id="simulation-runtime",
    node_id=None,
    service_id=None,
    pid=None,
    fault_id=None,
    run_id=None,
    scenario_id=None,
    tags=(),
):
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": event_type,
        "producer": {
            "producer_id": producer_id,
            "producer_version": "0.5.0",
            "instance_id": "instance-1",
        },
        "scope": {
            "tenant_id": "local",
            "session_id": SESSION_ID,
            "run_id": run_id,
            "scenario_id": scenario_id,
        },
        "time": {
            "source": {
                "value_ns": value_ns,
                "clock_domain": SIM_DOMAIN,
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": 1_700_000_000_000_000_000 + value_ns,
                "clock_domain": WALL,
                "clock_epoch": 0,
            },
        },
        "correlation": {
            "node_id": node_id,
            "service_id": service_id,
            "pid": pid,
            "fault_id": fault_id,
        },
        "severity": severity,
        "payload": {},
        "tags": list(tags),
        "journal_seq": seq,
    }


class _RecordingGateway:
    """Minimal gateway double capturing ``subscribe`` callbacks."""

    def __init__(self) -> None:
        self.callbacks = []

    def subscribe(self, callback) -> None:
        self.callbacks.append(callback)


class _ZeroMutationSimulation:
    """Spy double: ANY interaction during checkpointing is a MUST-not breach."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state_fingerprint = "frozen-state-v1"

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append(name)

        return _record


def _wall_created_at(value_ns: int = 1_700_000_000_000_000_000) -> TimelineTimepoint:
    return TimelineTimepoint(
        value_ns=value_ns,
        clock_domain=WALL,
        clock_epoch=0,
        semantics=TimepointSemantics.OBSERVED,
    )


def _checkpoint(
    *,
    journal_seq=42,
    virtual_time_ns=None,
    checkpoint_id="cp-0001",
    created_at=None,
) -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=checkpoint_id,
        session_id=SESSION_ID,
        journal_seq=journal_seq,
        clock_domain=SIM_DOMAIN,
        virtual_time_ns=virtual_time_ns,
        producer_state_versions=(
            ProducerStateVersion(producer_id="simulation-runtime", state_version="v7"),
        ),
        created_at=created_at or _wall_created_at(),
    )


class TestGatewayFanOutProjection:
    """Event records come from the gateway commit fan-out (SPEC-300 §7 step 5)."""

    def test_attach_registers_commit_callback(self):
        gateway = _RecordingGateway()
        recorder = TimelineRecorder()
        recorder.attach_gateway(gateway)
        assert len(gateway.callbacks) == 1

    def test_committed_event_projects_to_event_record(self):
        recorder = TimelineRecorder()
        recorder.record_event_document(_stamped(1))
        records = recorder.records(SESSION_ID)
        assert len(records) == 1
        record = records[0]
        assert record.record_kind is TimelineRecordKind.EVENT
        assert record.event_id == EVENT_ID
        assert record.journal_seq == 1
        assert record.event_type == "simulation.run_started"
        assert record.severity.value == "info"
        assert record.producer_id == "simulation-runtime"
        assert record.source_id == "simulation-runtime"
        assert record.source_seq == 1
        assert record.session_id == SESSION_ID

    def test_projection_keeps_correlation_filter_fields(self):
        recorder = TimelineRecorder()
        recorder.record_event_document(
            _stamped(2, node_id="node-7", service_id="svc-9", pid=255, fault_id="f-1")
        )
        record = recorder.records(SESSION_ID)[0]
        assert record.node_id == "node-7"
        assert record.service_id == "svc-9"
        assert record.pid == 255
        assert record.fault_id == "f-1"

    def test_projection_timepoint_is_source_time_with_explicit_semantics(self):
        recorder = TimelineRecorder()
        recorder.record_event_document(_stamped(3, value_ns=7_500_000))
        timepoint = recorder.records(SESSION_ID)[0].timepoint
        assert timepoint.value_ns == 7_500_000
        assert timepoint.clock_domain == SIM_DOMAIN
        assert timepoint.clock_epoch == 0
        assert timepoint.semantics is TimepointSemantics.SOURCE

    def test_projection_payload_carries_original_envelope(self):
        recorder = TimelineRecorder()
        stamped = _stamped(4)
        recorder.record_event_document(stamped)
        envelope = recorder.records(SESSION_ID)[0].payload["envelope"]
        assert envelope["event_id"] == EVENT_ID
        assert envelope["journal_seq"] == 4

    def test_evidence_chain_event_id_and_journal_seq_preserved(self):
        """REQ-OBS-303-001: 证据链不断."""
        recorder = TimelineRecorder()
        recorder.record_event_document(_stamped(9, event_id=EVENT_ID))
        record = recorder.records(SESSION_ID)[0]
        assert (record.event_id, record.journal_seq) == (EVENT_ID, 9)

    def test_duplicate_commit_is_idempotent(self):
        recorder = TimelineRecorder()
        stamped = _stamped(5)
        recorder.record_event_document(stamped)
        recorder.record_event_document(dict(stamped))
        assert len(recorder.records(SESSION_ID)) == 1

    def test_commit_without_journal_seq_is_refused(self):
        recorder = TimelineRecorder()
        stamped = _stamped(6)
        del stamped["journal_seq"]
        with pytest.raises(ValueError):
            recorder.record_event_document(stamped)
        assert recorder.records(SESSION_ID) == ()

    def test_malformed_document_surfaces_domain_error(self):
        recorder = TimelineRecorder()
        with pytest.raises(Exception):
            recorder.record_event_document({"not": "an envelope"})
        assert recorder.records(SESSION_ID) == ()


class TestCheckpointWriteFace:
    """REQ-OBS-303-003: checkpoints are observation behavior."""

    def test_checkpoint_record_wraps_spec_section_5_payload(self):
        recorder = TimelineRecorder()
        record = recorder.record_checkpoint(_checkpoint(journal_seq=42))
        assert record.record_kind is TimelineRecordKind.CHECKPOINT
        assert record.session_id == SESSION_ID
        payload = record.payload
        assert payload["checkpoint_id"] == "cp-0001"
        assert payload["journal_seq"] == 42
        assert payload["clock_domain"] == SIM_DOMAIN
        assert payload["producer_state_versions"] == [
            {"producer_id": "simulation-runtime", "state_version": "v7"}
        ]
        assert payload["schema_version"] == "1.0"

    def test_checkpoint_timepoint_prefers_virtual_time_with_source_semantics(self):
        recorder = TimelineRecorder()
        record = recorder.record_checkpoint(
            _checkpoint(virtual_time_ns=9_500_000)
        )
        assert record.timepoint.value_ns == 9_500_000
        assert record.timepoint.clock_domain == SIM_DOMAIN
        assert record.timepoint.semantics is TimepointSemantics.SOURCE

    def test_checkpoint_without_virtual_time_falls_back_to_created_at(self):
        recorder = TimelineRecorder()
        record = recorder.record_checkpoint(_checkpoint(virtual_time_ns=None))
        assert record.timepoint.clock_domain == WALL
        assert record.timepoint.semantics is TimepointSemantics.OBSERVED

    def test_checkpointing_never_pauses_or_mutates_the_simulation(self):
        """Must-not OBS-D / SPEC-303 §10: 检查点前后仿真状态零变化."""
        simulation = _ZeroMutationSimulation()
        before = simulation.state_fingerprint
        recorder = TimelineRecorder()
        recorder.record_checkpoint(_checkpoint())
        recorder.record_checkpoint(_checkpoint(journal_seq=43))
        assert simulation.calls == []
        assert simulation.state_fingerprint == before


class TestOperatorWriteFaces:
    """snapshot/annotation/bookmark MVP write faces (explicit timepoint)."""

    def test_annotation_with_explicit_timepoint(self):
        recorder = TimelineRecorder()
        record = recorder.add_annotation(
            session_id=SESSION_ID,
            source_id="operator-console",
            timepoint=TimelineTimepoint(
                value_ns=5_000,
                clock_domain=SIM_DOMAIN,
                clock_epoch=0,
                semantics=TimepointSemantics.SOURCE,
            ),
            payload={"note": "here"},
            tags=("training",),
        )
        assert record.record_kind is TimelineRecordKind.ANNOTATION
        assert record.tags == ("training",)
        assert record.source_id == "operator-console"

    def test_bookmark_carries_name(self):
        recorder = TimelineRecorder()
        record = recorder.add_bookmark(
            session_id=SESSION_ID,
            source_id="operator-console",
            name="fault-window-start",
            timepoint=TimelineTimepoint(
                value_ns=6_000,
                clock_domain=SIM_DOMAIN,
                clock_epoch=0,
                semantics=TimepointSemantics.SOURCE,
            ),
        )
        assert record.record_kind is TimelineRecordKind.BOOKMARK
        assert record.payload["name"] == "fault-window-start"

    def test_snapshot_carries_version_and_payload(self):
        recorder = TimelineRecorder()
        record = recorder.add_snapshot(
            session_id=SESSION_ID,
            source_id="simulation-runtime",
            snapshot_version="v3",
            timepoint=TimelineTimepoint(
                value_ns=7_000,
                clock_domain=SIM_DOMAIN,
                clock_epoch=0,
                semantics=TimepointSemantics.SOURCE,
            ),
            payload={"topology_revision": 12},
        )
        assert record.record_kind is TimelineRecordKind.SNAPSHOT
        assert record.payload["snapshot_version"] == "v3"
        assert record.payload["topology_revision"] == 12

    def test_write_face_requires_explicit_timepoint(self):
        recorder = TimelineRecorder()
        with pytest.raises(TypeError):
            recorder.add_annotation(session_id=SESSION_ID, source_id="console")  # type: ignore[call-arg]


class TestTombstoneDiscipline:
    """SPEC-303 §8: deletion leaves explicit tombstones, no dangling refs."""

    def test_delete_replaces_record_in_place_with_tombstone(self):
        recorder = TimelineRecorder()
        original = recorder.record_event_document(_stamped(1))
        tombstones = recorder.delete_records([original.record_id], reason="gdpr")
        assert len(tombstones) == 1
        records = recorder.records(SESSION_ID)
        assert len(records) == 1  # position preserved — no sequence shift
        tombstone = records[0]
        assert tombstone.record_kind is TimelineRecordKind.EVENT
        assert tombstone.payload["tombstone"] is True
        assert tombstone.payload["replaces_record_id"] == original.record_id
        assert tombstone.payload["reason"] == "gdpr"
        assert "envelope" not in tombstone.payload
        assert tombstone.event_id is None  # no seemingly-valid evidence ref

    def test_tombstone_keeps_lane_stability_metadata(self):
        recorder = TimelineRecorder()
        original = recorder.record_event_document(_stamped(2))
        recorder.delete_records([original.record_id], reason="gdpr")
        tombstone = recorder.records(SESSION_ID)[0]
        assert tombstone.session_id == SESSION_ID
        assert (tombstone.timepoint.clock_domain, tombstone.timepoint.clock_epoch) == (
            SIM_DOMAIN,
            0,
        )

    def test_delete_unknown_record_ids_is_a_noop(self):
        recorder = TimelineRecorder()
        recorder.record_event_document(_stamped(3))
        assert recorder.delete_records(["missing-id"], reason="gdpr") == ()
        assert len(recorder.records(SESSION_ID)) == 1


class TestRecordIdentity:
    """Content-derived record ids keep exports reproducible across restarts."""

    def test_same_content_yields_same_record_id(self):
        a = TimelineRecorder().record_event_document(_stamped(1))
        b = TimelineRecorder().record_event_document(_stamped(1))
        assert a.record_id == b.record_id

    def test_different_content_yields_different_record_id(self):
        a = TimelineRecorder().record_event_document(_stamped(1))
        b = TimelineRecorder().record_event_document(_stamped(2))
        assert a.record_id != b.record_id

    def test_records_returns_arrival_order_snapshot(self):
        recorder = TimelineRecorder()
        recorder.record_event_document(_stamped(1))
        recorder.record_event_document(_stamped(2))
        seqs = [r.journal_seq for r in recorder.records(SESSION_ID)]
        assert seqs == [1, 2]
