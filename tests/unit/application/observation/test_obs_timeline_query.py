"""SPEC-303 timeline query face — ordering, lanes, filters, pagination,
cursor binding and expiry (REQ-OBS-303-002 / REQ-OBS-303-004).

Service under test: ``application.observation.timeline.TimelineService``
over an in-memory :class:`TimelineRecorder` store (pure objects, no I/O,
no wall clock — SPEC-505 §3).

Disciplines pinned here:

- §4 ordering: journal segment by ``journal_seq`` (out-of-order arrival
  tolerated), cross-source segment by
  ``(clock_domain, timestamp, source_id, source_seq)``, output labels its
  sort descriptor, and mixed-domain single-order requests are REFUSED
  (caller must pin a clock domain or request lanes).
- §6 pagination: opaque cursor bound to the filter hash + scope; default
  page 500 / hard cap 2000; expiry = ``OBS_CURSOR_EXPIRED`` (ticket #51
  registration per SPEC-300 §13); replaying an old cursor under a changed
  filter or another session must fail; append-only appends keep cursers
  valid; tombstoning the anchor expires them.
"""

import pytest

from application.observation.timeline.cursor import (
    TimelineCursorState,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from application.observation.timeline.errors import TimelineError
from application.observation.timeline.recorder import TimelineRecorder
from application.observation.timeline.service import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_HARD_CAP,
    TimelineFilter,
    TimelineService,
    TimelineServiceConfig,
)
from domain.observation import (
    DEFAULT_SORT_DESCRIPTOR,
    EnvelopeErrorCode,
    TimelineRecordKind,
)
from domain.observation.errors import EnvelopeError

SESSION_A = "1f1e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SESSION_B = "2f2e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
SIM_A = f"sim:{SESSION_A}"
WALL = "wall:utc"
OBSERVED_WALL_NS = 1_700_000_000_000_000_000


def _envelope_doc(
    *,
    event_id,
    session_id=SESSION_A,
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
    payload=None,
):
    correlation = {
        "node_id": node_id,
        "service_id": service_id,
        "pid": pid,
        "fault_id": fault_id,
    }
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
            "session_id": session_id,
            "run_id": run_id,
            "scenario_id": scenario_id,
        },
        "time": {
            "source": {
                "value_ns": value_ns,
                "clock_domain": f"sim:{session_id}",
                "clock_epoch": 0,
            },
            "observed": {
                "value_ns": OBSERVED_WALL_NS + value_ns,
                "clock_domain": WALL,
                "clock_epoch": 0,
            },
        },
        "correlation": correlation,
        "severity": severity,
        "payload": payload or {},
        "tags": list(tags),
    }


def _stamped(seq: int, **kwargs) -> dict:
    doc = _envelope_doc(**kwargs)
    doc["journal_seq"] = seq
    return doc


def _annotation(
    *,
    record_id,
    session_id=SESSION_A,
    value_ns=500,
    source_id="operator-console",
    source_seq=1,
    clock_domain=SIM_A,
    clock_epoch=0,
    tags=(),
):
    from domain.observation import (
        TimelineRecord,
        TimelineRecordKind,
        TimelineTimepoint,
        TimepointSemantics,
    )

    return TimelineRecord(
        record_kind=TimelineRecordKind.ANNOTATION,
        record_id=record_id,
        session_id=session_id,
        source_id=source_id,
        source_seq=source_seq,
        timepoint=TimelineTimepoint(
            value_ns=value_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            semantics=TimepointSemantics.SOURCE,
        ),
        tags=tuple(tags),
        payload={"note": "annotation"},
    )


def _service(session_id: str = SESSION_A) -> TimelineService:
    return TimelineService(TimelineRecorder())


def _service_with_events(session_id: str = SESSION_A) -> tuple[TimelineService, TimelineRecorder]:
    recorder = TimelineRecorder()
    # Out-of-order arrival (seq 3,1,2) with distinct source timestamps.
    recorder.record_event_document(
        _stamped(3, event_id="11111111-1111-4111-8111-111111111111", value_ns=3_000)
    )
    recorder.record_event_document(
        _stamped(1, event_id="22222222-2222-4222-8222-222222222222", value_ns=1_000)
    )
    recorder.record_event_document(
        _stamped(2, event_id="33333333-3333-4333-8333-333333333333", value_ns=1_500)
    )
    return TimelineService(recorder), recorder


class TestPageSizeDiscipline:
    """REQ-OBS-303-004: page default 500, hard cap 2000 (invalid, not clamped)."""

    def test_constants(self):
        assert PAGE_SIZE_DEFAULT == 500
        assert PAGE_SIZE_HARD_CAP == 2000

    def test_default_page_returns_up_to_500(self):
        service, _ = _service_with_events()
        page = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        assert len(page.records) == 3  # store holds fewer than the default page

    def test_page_size_above_hard_cap_is_invalid_not_clamped(self):
        service = _service()
        with pytest.raises(ValueError):
            service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2001)

    def test_page_size_below_one_is_invalid(self):
        service = _service()
        with pytest.raises(ValueError):
            service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=0)


class TestOrderingDiscipline:
    """SPEC-303 §4 / REQ-OBS-303-002."""

    def test_journal_records_sorted_by_seq_despite_arrival_order(self):
        service, _ = _service_with_events()
        page = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        assert [r.journal_seq for r in page.records] == [1, 2, 3]

    def test_page_labels_its_sort_descriptor(self):
        service, _ = _service_with_events()
        page = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        assert page.sort_descriptor == DEFAULT_SORT_DESCRIPTOR

    def test_journal_segment_precedes_source_segment(self):
        service, recorder = _service_with_events()
        recorder.add_record(_annotation(record_id="ann-1", value_ns=1))
        page = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        kinds = [r.record_kind for r in page.records]
        assert kinds == [
            TimelineRecordKind.EVENT,
            TimelineRecordKind.EVENT,
            TimelineRecordKind.EVENT,
            TimelineRecordKind.ANNOTATION,
        ]

    def test_source_segment_ordered_by_timestamp_then_source_id_then_seq(self):
        recorder = TimelineRecorder()
        recorder.add_record(
            _annotation(record_id="a", value_ns=200, source_id="console-b")
        )
        recorder.add_record(
            _annotation(record_id="b", value_ns=100, source_id="console-b")
        )
        recorder.add_record(
            _annotation(record_id="c", value_ns=100, source_id="console-a")
        )
        recorder.add_record(
            _annotation(record_id="d", value_ns=100, source_id="console-a", source_seq=0)
        )
        page = TimelineService(recorder).query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        assert [
            (r.timepoint.value_ns, r.source_id, r.source_seq) for r in page.records
        ] == [
            (100, "console-a", 0),
            (100, "console-a", 1),
            (100, "console-b", 1),
            (200, "console-b", 1),
        ]

    def test_unpinned_domain_without_lanes_is_refused(self):
        """§4: the caller MUST pin a clock domain or request lanes — a
        mixed-domain single time order is never claimed (REQ-OBS-303-002)."""
        service, recorder = _service_with_events()
        recorder.add_record(
            _annotation(record_id="w", clock_domain=WALL, value_ns=OBSERVED_WALL_NS)
        )
        with pytest.raises(TimelineError) as excinfo:
            service.query(TimelineFilter(session_id=SESSION_A))
        assert excinfo.value.code == EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN.value

    def test_domain_pin_excludes_other_domains_from_the_single_order(self):
        service, recorder = _service_with_events()
        recorder.add_record(
            _annotation(record_id="w", clock_domain=WALL, value_ns=OBSERVED_WALL_NS)
        )
        page = service.query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A)
        )
        assert all(r.timepoint.clock_domain == SIM_A for r in page.records)
        assert len(page.records) == 3

    def test_epoch_pin_excludes_other_epochs(self):
        service, recorder = _service_with_events()
        recorder.add_record(
            _annotation(record_id="post-restart", clock_epoch=1, value_ns=5)
        )
        page = service.query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, clock_epoch=0)
        )
        assert [r.record_id for r in page.records if r.record_kind is TimelineRecordKind.ANNOTATION] == []

    def test_lanes_partition_by_domain_and_epoch_and_label_each_lane(self):
        service, recorder = _service_with_events()
        recorder.add_record(
            _annotation(record_id="w", clock_domain=WALL, value_ns=OBSERVED_WALL_NS)
        )
        recorder.add_record(
            _annotation(record_id="post-restart", clock_epoch=1, value_ns=5)
        )
        page = service.query(TimelineFilter(session_id=SESSION_A, lanes=True))
        assert page.records == ()
        lane_keys = [(lane.clock_domain, lane.clock_epoch) for lane in page.lanes]
        assert lane_keys == [(SIM_A, 0), (SIM_A, 1), (WALL, 0)]
        sim_lane = page.lanes[0]
        assert [r.journal_seq for r in sim_lane.records if r.journal_seq] == [1, 2, 3]
        assert sim_lane.sort_descriptor == DEFAULT_SORT_DESCRIPTOR
        wall_lane = page.lanes[2]
        assert [r.timepoint.value_ns for r in wall_lane.records] == [OBSERVED_WALL_NS]

    def test_lanes_never_merge_incompatible_domains_into_one_list(self):
        service, recorder = _service_with_events()
        recorder.add_record(
            _annotation(record_id="w", clock_domain=WALL, value_ns=OBSERVED_WALL_NS)
        )
        page = service.query(TimelineFilter(session_id=SESSION_A, lanes=True))
        for lane in page.lanes:
            assert {r.timepoint.clock_domain for r in lane.records} == {
                lane.clock_domain
            }


class TestRangeFilter:
    """Time ranges bind to the pinned clock domain + epoch (SPEC-300 §6)."""

    def test_range_without_pinned_domain_and_epoch_is_refused(self):
        service, _ = _service_with_events()
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, start_ns=0, end_ns=10)
            )
        assert excinfo.value.code == EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN.value

    def test_range_with_lanes_is_refused(self):
        service, _ = _service_with_events()
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(
                    session_id=SESSION_A,
                    lanes=True,
                    clock_domain=SIM_A,
                    clock_epoch=0,
                    start_ns=0,
                    end_ns=10,
                )
            )
        assert excinfo.value.code == EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN.value

    def test_range_start_must_precede_end(self):
        service = _service()
        with pytest.raises(ValueError):
            service.query(
                TimelineFilter(
                    session_id=SESSION_A,
                    clock_domain=SIM_A,
                    clock_epoch=0,
                    start_ns=10,
                    end_ns=0,
                )
            )

    def test_range_filters_within_the_pinned_time_base(self):
        service, _ = _service_with_events()
        page = service.query(
            TimelineFilter(
                session_id=SESSION_A,
                clock_domain=SIM_A,
                clock_epoch=0,
                start_ns=1_000,
                end_ns=2_000,
            )
        )
        # half-open-style inclusive bounds over source value_ns 1000..2000
        assert [r.journal_seq for r in page.records if r.journal_seq] == [1, 2]

    def test_range_above_configured_limit_is_range_too_large(self):
        service = TimelineService(
            TimelineRecorder(), config=TimelineServiceConfig(max_range_ns=1_000)
        )
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(
                    session_id=SESSION_A,
                    clock_domain=SIM_A,
                    clock_epoch=0,
                    start_ns=0,
                    end_ns=5_000,
                )
            )
        assert excinfo.value.code == "OBS_QUERY_RANGE_TOO_LARGE"
        assert excinfo.value.retryable is False


class TestFilterWhitelist:
    """SPEC-303 §6 filter whitelist (no free-text filters)."""

    def _store(self) -> TimelineRecorder:
        recorder = TimelineRecorder()
        recorder.record_event_document(
            _stamped(
                1,
                event_id="aaaaaaaa-0000-4000-8000-000000000001",
                event_type="simulation.run_started",
                severity="info",
                producer_id="simulation-runtime",
                node_id="node-1",
                service_id="svc-1",
                pid=100,
                fault_id=None,
                run_id="run-1",
                scenario_id="scn-1",
                tags=("training",),
            )
        )
        recorder.record_event_document(
            _stamped(
                2,
                event_id="aaaaaaaa-0000-4000-8000-000000000002",
                event_type="simulation.run_completed",
                severity="notice",
                producer_id="simulation-runtime",
                run_id="run-1",
                scenario_id="scn-1",
                tags=("training", "exam"),
            )
        )
        recorder.record_event_document(
            _stamped(
                3,
                event_id="aaaaaaaa-0000-4000-8000-000000000003",
                event_type="fault.injected",
                severity="warning",
                producer_id="fault-engine",
                fault_id="f-123",
                node_id="node-2",
            )
        )
        return recorder

    def test_filter_by_event_types(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, event_types=("fault.injected",))
        )
        assert [r.event_type for r in page.records] == ["fault.injected"]

    def test_filter_by_severity(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, severities=("warning",))
        )
        assert [r.event_type for r in page.records] == ["fault.injected"]

    def test_filter_by_producer(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, producer_ids=("fault-engine",))
        )
        assert [r.journal_seq for r in page.records] == [3]

    def test_filter_by_node_and_pid_and_service(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, node_id="node-1", pid=100)
        )
        assert [r.journal_seq for r in page.records] == [1]
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, service_id="svc-1")
        )
        assert [r.journal_seq for r in page.records] == [1]

    def test_filter_by_fault_id(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, fault_id="f-123")
        )
        assert [r.journal_seq for r in page.records] == [3]

    def test_filter_by_scenario_and_run(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, scenario_id="scn-1")
        )
        assert [r.journal_seq for r in page.records] == [1, 2]

    def test_filter_by_tags_requires_all_tags_no_free_text(self):
        page = TimelineService(self._store()).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, tags=("training", "exam"))
        )
        assert [r.journal_seq for r in page.records] == [2]

    def test_filter_by_record_kinds(self):
        recorder = self._store()
        recorder.add_record(_annotation(record_id="ann-1"))
        page = TimelineService(recorder).query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A, record_kinds=("annotation",))
        )
        assert {r.record_kind for r in page.records} == {TimelineRecordKind.ANNOTATION}
        assert len(page.records) == 1

    def test_empty_store_returns_empty_page_without_cursor(self):
        page = _service().query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A))
        assert page.records == ()
        assert page.next_cursor is None
        assert page.truncated is False


class TestCursorPagination:
    """REQ-OBS-303-004: opaque token bound to filter hash + scope."""

    def _store(self, count: int) -> TimelineRecorder:
        recorder = TimelineRecorder()
        for seq in range(1, count + 1):
            recorder.record_event_document(
                _stamped(
                    seq,
                    event_id=f"aaaaaaaa-0000-4000-8000-{seq:012d}",
                )
            )
        return recorder

    def test_pagination_walk_has_no_duplicates_and_no_gaps(self):
        service = TimelineService(self._store(7))
        seen: list[int] = []
        cursor = None
        pages = 0
        while True:
            page = service.query(
                TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=3, cursor=cursor
            )
            seen.extend(r.journal_seq for r in page.records)
            pages += 1
            assert page.truncated == (page.next_cursor is not None)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == [1, 2, 3, 4, 5, 6, 7]
        assert pages == 3

    def test_cursor_token_is_opaque_and_round_trips(self):
        state = TimelineCursorState(
            session_id=SESSION_A,
            filter_hash=filter_fingerprint(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A)),
            position=3,
            anchor_record_id="rec-3",
        )
        token = encode_cursor(state)
        assert isinstance(token, str) and "{" not in token
        decoded = decode_cursor(token)
        assert decoded == state

    def test_same_cursor_state_encodes_deterministically(self):
        state = TimelineCursorState(
            session_id=SESSION_A, filter_hash="abc", position=1, anchor_record_id="r"
        )
        assert encode_cursor(state) == encode_cursor(state)

    def test_replaying_cursor_under_changed_filter_is_expired(self):
        """SPEC-303 §10: 换过滤器重放旧 cursor 必须失效."""
        service = TimelineService(self._store(5))
        first = service.query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2
        )
        assert first.next_cursor is not None
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(
                    session_id=SESSION_A, clock_domain=SIM_A, event_types=("simulation.run_completed",)
                ),
                page_size=2,
                cursor=first.next_cursor,
            )
        assert excinfo.value.code == "OBS_CURSOR_EXPIRED"

    def test_replaying_cursor_in_another_session_scope_is_expired(self):
        service = TimelineService(self._store(5))
        first = service.query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2
        )
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(session_id=SESSION_B, clock_domain=SIM_A),
                page_size=2,
                cursor=first.next_cursor,
            )
        assert excinfo.value.code == "OBS_CURSOR_EXPIRED"

    def test_malformed_cursor_token_is_expired(self):
        service = TimelineService(self._store(2))
        for bad in ("not-a-cursor", "eyJ", "", "aGVsbG8="):
            with pytest.raises(TimelineError) as excinfo:
                service.query(
                    TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2, cursor=bad
                )
            assert excinfo.value.code == "OBS_CURSOR_EXPIRED"

    def test_cursor_survives_append_only_growth(self):
        recorder = self._store(4)
        service = TimelineService(recorder)
        first = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2)
        recorder.record_event_document(
            _stamped(5, event_id="aaaaaaaa-0000-4000-8000-000000000005")
        )
        second = service.query(
            TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A),
            page_size=2,
            cursor=first.next_cursor,
        )
        assert [r.journal_seq for r in second.records] == [3, 4]

    def test_cursor_expires_when_anchor_record_is_tombstoned(self):
        recorder = self._store(4)
        service = TimelineService(recorder)
        first = service.query(TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A), page_size=2)
        # The cursor anchor is the FIRST record of the next page (journal seq 3,
        # third in arrival order) — tombstoning it must expire the cursor.
        anchor_id = recorder.records(SESSION_A)[2].record_id
        recorder.delete_records([anchor_id], reason="gdpr-request")
        with pytest.raises(TimelineError) as excinfo:
            service.query(
                TimelineFilter(session_id=SESSION_A, clock_domain=SIM_A),
                page_size=2,
                cursor=first.next_cursor,
            )
        assert excinfo.value.code == "OBS_CURSOR_EXPIRED"

    def test_envelope_error_propagates_domain_code_for_bad_documents(self):
        """A structurally invalid event document reaching the recorder is a
        caller bug — the recorder surfaces the domain vocabulary."""
        recorder = TimelineRecorder()
        bad = _stamped(1, event_id="short")
        del bad["severity"]
        with pytest.raises(EnvelopeError) as excinfo:
            recorder.record_event_document(bad)
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE
