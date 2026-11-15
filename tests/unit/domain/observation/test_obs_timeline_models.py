"""SPEC-303 timeline record models + ordering discipline (REQ-OBS-303-001/002).

Domain face of the timeline recorder: the six canonical record kinds
(SPEC-303 §3), the record-level timepoint with explicit ``clock_epoch`` and
``semantics`` (SPEC-300 §6; ticket #12 ruling — the ENVELOPE timepoint stays
without ``semantics``, ``envelope.py`` untouched), the checkpoint record
contract (SPEC-303 §5) and the §4 ordering discipline helpers:

- journal-sourced records order by ``journal_seq``;
- cross-source records (no journal_seq) order by
  ``(clock_domain, timestamp, source_id, source_seq)``;
- records of incompatible clock domains are never merged into one claimed
  time order — they carry their ``(clock_domain, clock_epoch)`` lane key so
  the service can partition lanes.

Unit layer: pure objects, no I/O, no wall clock (SPEC-505 §3).
"""

import json

import pytest
from pydantic import ValidationError

from domain.observation.timeline import (
    DEFAULT_SORT_DESCRIPTOR,
    JOURNAL_SEQ_SORT,
    SOURCE_ORDER_SORT,
    CheckpointRecord,
    ProducerStateVersion,
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
    record_time_domain_key,
    timeline_record_sort_key,
)

SESSION_ID = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SIM_DOMAIN = f"sim:{SESSION_ID}"


def _timepoint(
    value_ns: int,
    clock_domain: str = SIM_DOMAIN,
    clock_epoch: int = 0,
    semantics: TimepointSemantics = TimepointSemantics.SOURCE,
) -> TimelineTimepoint:
    return TimelineTimepoint(
        value_ns=value_ns,
        clock_domain=clock_domain,
        clock_epoch=clock_epoch,
        semantics=semantics,
    )


def _event_record(
    journal_seq: int,
    *,
    value_ns: int = 1_000,
    event_id: str = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
) -> TimelineRecord:
    return TimelineRecord(
        record_kind=TimelineRecordKind.EVENT,
        record_id=f"rec-event-{journal_seq:04d}",
        session_id=SESSION_ID,
        source_id="simulation-runtime",
        source_seq=journal_seq,
        journal_seq=journal_seq,
        event_id=event_id,
        event_type="simulation.run_started",
        severity="info",
        producer_id="simulation-runtime",
        timepoint=_timepoint(value_ns),
        tags=(),
        payload={"envelope": {"event_id": event_id}},
    )


def _annotation_record(
    *,
    value_ns: int,
    source_id: str = "operator-console",
    source_seq: int = 1,
    clock_domain: str = SIM_DOMAIN,
    clock_epoch: int = 0,
) -> TimelineRecord:
    return TimelineRecord(
        record_kind=TimelineRecordKind.ANNOTATION,
        record_id=f"rec-ann-{source_id}-{value_ns}-{source_seq}",
        session_id=SESSION_ID,
        source_id=source_id,
        source_seq=source_seq,
        timepoint=_timepoint(value_ns, clock_domain, clock_epoch),
        tags=(),
        payload={"note": "observed here"},
    )


class TestRecordKinds:
    """SPEC-303 §3: exactly the six canonical record kinds."""

    def test_six_canonical_record_kinds(self):
        assert {kind.value for kind in TimelineRecordKind} == {
            "event",
            "snapshot",
            "annotation",
            "checkpoint",
            "bookmark",
            "export_manifest",
        }

    def test_timepoint_semantics_vocabulary(self):
        """SPEC-300 §6 record-level semantics: source/observed/derived."""
        assert {s.value for s in TimepointSemantics} == {
            "source",
            "observed",
            "derived",
        }

    def test_record_timepoint_requires_explicit_semantics(self):
        """#12 ruling: record-level timepoints carry clock_epoch + semantics."""
        with pytest.raises(ValidationError):
            # missing semantics — silently guessing a meaning is banned
            TimelineTimepoint(value_ns=1, clock_domain=SIM_DOMAIN, clock_epoch=0)  # type: ignore[call-arg]

    def test_record_is_frozen_value_object(self):
        record = _event_record(1)
        with pytest.raises(ValidationError):
            record.journal_seq = 99  # type: ignore[misc]

    def test_record_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            TimelineRecord.model_validate(
                {
                    "record_kind": "annotation",
                    "record_id": "rec-x",
                    "session_id": SESSION_ID,
                    "source_id": "operator-console",
                    "timepoint": {
                        "value_ns": 1,
                        "clock_domain": SIM_DOMAIN,
                        "clock_epoch": 0,
                        "semantics": "observed",
                    },
                    "payload": {},
                    "nonexistent_field": True,
                }
            )


class TestEventRecordKeepsEvidenceChain:
    """REQ-OBS-303-001: records derived from events keep event_id+journal_seq."""

    def test_event_record_requires_event_id_and_journal_seq(self):
        with pytest.raises(ValidationError):
            TimelineRecord(
                record_kind=TimelineRecordKind.EVENT,
                record_id="rec-bad-event",
                session_id=SESSION_ID,
                source_id="simulation-runtime",
                journal_seq=1,
                event_id=None,
                event_type="simulation.run_started",
                timepoint=_timepoint(1),
                tags=(),
                payload={},
            )

    def test_event_record_requires_journal_seq(self):
        with pytest.raises(ValidationError):
            TimelineRecord(
                record_kind=TimelineRecordKind.EVENT,
                record_id="rec-bad-event",
                session_id=SESSION_ID,
                source_id="simulation-runtime",
                event_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                journal_seq=None,
                event_type="simulation.run_started",
                timepoint=_timepoint(1),
                tags=(),
                payload={},
            )

    def test_original_ids_survive_serialization_round_trip(self):
        record = _event_record(7)
        doc = json.loads(record.model_dump_json())
        revived = TimelineRecord.model_validate(doc)
        assert revived.event_id == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        assert revived.journal_seq == 7

    def test_non_event_records_may_omit_journal_seq(self):
        record = _annotation_record(value_ns=5)
        assert record.journal_seq is None
        assert record.event_id is None


class TestCheckpointRecordContract:
    """SPEC-303 §5 checkpoint field contract."""

    def test_checkpoint_fields_match_spec_section_5(self):
        created_at = TimelineTimepoint(
            value_ns=1_700_000_000_000_000_000,
            clock_domain="wall:utc",
            clock_epoch=0,
            semantics=TimepointSemantics.OBSERVED,
        )
        checkpoint = CheckpointRecord(
            checkpoint_id="cp-0001",
            session_id=SESSION_ID,
            journal_seq=42,
            clock_domain=SIM_DOMAIN,
            virtual_time_ns=9_500_000,
            producer_state_versions=(
                ProducerStateVersion(
                    producer_id="simulation-runtime", state_version="v7"
                ),
            ),
            created_at=created_at,
            integrity_digest="d41d8cd98f00b204e9800998ecf8427e",
        )
        doc = checkpoint.model_dump(mode="json")
        assert doc["checkpoint_id"] == "cp-0001"
        assert doc["session_id"] == SESSION_ID
        assert doc["journal_seq"] == 42
        assert doc["clock_domain"] == SIM_DOMAIN
        assert doc["virtual_time_ns"] == 9_500_000
        assert doc["schema_version"] == "1.0"
        assert doc["producer_state_versions"] == [
            {"producer_id": "simulation-runtime", "state_version": "v7"}
        ]
        assert doc["created_at"]["clock_domain"] == "wall:utc"
        assert doc["created_at"]["semantics"] == "observed"
        assert doc["created_at"]["clock_epoch"] == 0
        assert doc["integrity_digest"] == "d41d8cd98f00b204e9800998ecf8427e"

    def test_checkpoint_virtual_time_and_digest_are_optional(self):
        checkpoint = CheckpointRecord(
            checkpoint_id="cp-0002",
            session_id=SESSION_ID,
            journal_seq=1,
            clock_domain=SIM_DOMAIN,
            created_at=_timepoint(1, "wall:utc", 0, TimepointSemantics.OBSERVED),
        )
        assert checkpoint.virtual_time_ns is None
        assert checkpoint.integrity_digest is None
        assert checkpoint.producer_state_versions == ()

    def test_checkpoint_journal_seq_is_non_negative(self):
        with pytest.raises(ValidationError):
            CheckpointRecord(
                checkpoint_id="cp-0003",
                session_id=SESSION_ID,
                journal_seq=-1,
                clock_domain=SIM_DOMAIN,
                created_at=_timepoint(1, "wall:utc", 0, TimepointSemantics.OBSERVED),
            )


class TestOrderingDiscipline:
    """SPEC-303 §4 / REQ-OBS-303-002 sort key discipline."""

    def test_sort_descriptor_constants_are_stable(self):
        assert JOURNAL_SEQ_SORT == "journal_seq"
        assert SOURCE_ORDER_SORT == (
            "source_order(clock_domain,timestamp,source_id,source_seq)"
        )
        assert DEFAULT_SORT_DESCRIPTOR == (
            "journal_seq+source_order(clock_domain,timestamp,source_id,source_seq)"
        )

    def test_journal_segment_orders_by_journal_seq_despite_arrival_order(self):
        records = [_event_record(3), _event_record(1), _event_record(2)]
        ordered = sorted(records, key=timeline_record_sort_key)
        assert [r.journal_seq for r in ordered] == [1, 2, 3]

    def test_source_segment_orders_by_clock_domain_timestamp_source(self):
        records = [
            _annotation_record(value_ns=200, source_id="console-b"),
            _annotation_record(value_ns=100, source_id="console-b"),
            _annotation_record(value_ns=100, source_id="console-a"),
        ]
        ordered = sorted(records, key=timeline_record_sort_key)
        assert [(r.timepoint.value_ns, r.source_id) for r in ordered] == [
            (100, "console-a"),
            (100, "console-b"),
            (200, "console-b"),
        ]

    def test_source_segment_tiebreaks_on_source_seq(self):
        records = [
            _annotation_record(value_ns=100, source_id="console-a", source_seq=2),
            _annotation_record(value_ns=100, source_id="console-a", source_seq=1),
        ]
        ordered = sorted(records, key=timeline_record_sort_key)
        assert [r.source_seq for r in ordered] == [1, 2]

    def test_journal_segment_precedes_source_segment(self):
        """Journal order is the authoritative primary (§4 line 1); the source
        segment never interleaves into it (no claimed cross-source merge)."""
        journal = _event_record(2, value_ns=9_999)
        annotation = _annotation_record(value_ns=1)
        ordered = sorted([annotation, journal], key=timeline_record_sort_key)
        assert [r.record_kind for r in ordered] == [
            TimelineRecordKind.EVENT,
            TimelineRecordKind.ANNOTATION,
        ]

    def test_incompatible_domains_grouped_by_domain_key_not_raw_time(self):
        """§4 line 3: within the source segment, records of different clock
        domains order by the (domain, epoch) KEY — never by raw value_ns
        across incompatible bases (wall ns vs sim ns are not comparable)."""
        wall_late = _annotation_record(
            value_ns=1_790_000_000_000_000_000,
            source_id="console-wall",
            clock_domain="wall:utc",
        )
        sim_early = _annotation_record(
            value_ns=5,
            source_id="console-sim",
            clock_domain=SIM_DOMAIN,
        )
        ordered = sorted([wall_late, sim_early], key=timeline_record_sort_key)
        # "sim:..." < "wall:utc" lexicographically: the key order is
        # deterministic but is NOT a time claim across the two bases.
        assert [r.timepoint.clock_domain for r in ordered] == [SIM_DOMAIN, "wall:utc"]

    def test_record_time_domain_key_is_the_lane_key(self):
        record = _annotation_record(value_ns=1, clock_epoch=3)
        assert record_time_domain_key(record) == (SIM_DOMAIN, 3)
