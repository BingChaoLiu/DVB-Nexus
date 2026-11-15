"""Observation query service — SPEC-305 §4/§5/§6 faces (ticket #53).

Unit layer: pure in-memory (``:memory:`` SQLite journal — the house-legal
form), no wall clock, no threads. The seams under test are the application
query-plane public faces the REST router consumes:

- ``ObservationQueryService.query_events`` — the journal-backed event
  query face (SPEC-305 §4 events row, §5 flat baseline, §6 envelope);
- ``ObservationQueryService.get_session_summary`` — the SPEC-300 §12
  frozen ``ObservationQueryService.get_session_summary`` name;
- the error-translation matrix (service-plane structured errors keep
  their registry codes and land on the frozen application categories).

REQ-OBS-305-002/003/004 slices live here; the HTTP envelope shapes are
pinned at the integration layer (``tests/integration/api/``).
"""

from __future__ import annotations

import pytest

from adapters.storage import db
from adapters.storage.alerts import SqliteAlertStore
from adapters.storage.journal import SqliteEventJournal
from application.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    SemanticValidationError,
    ServiceUnavailableError,
)
from application.observation.alerts.rules import HealthRuleSet, default_rule_set
from application.observation.alerts.service import AlertService
from application.observation.metrics.engine import MetricsEngine
from application.observation.metrics.service import MetricsService
from application.observation.query.errors import (
    OBS_INVALID_TIME_DOMAIN,
    OBS_QUERY_RANGE_TOO_LARGE,
)
from application.observation.query import (
    EventsQueryRequest,
    ObservationQueryService,
    translate_service_error,
)
from application.observation.query.exports import (
    ExportTaskRegistry,
    ExportTaskRequest,
)
from application.observation.timeline.recorder import TimelineRecorder
from application.observation.timeline.service import TimelineService
from domain.observation import TimepointSemantics, TimelineTimepoint
from tests.unit.application.observation.alerts._alerts_fixtures import (
    CannedReader,
    make_rule,
    sample_at,
)

from tests.unit.application.observation.test_gateway_accept import _raw_envelope


def _journal() -> SqliteEventJournal:
    conn = db.connect(":memory:")
    db.migrate(conn)
    return SqliteEventJournal(conn)


def _append(
    journal: SqliteEventJournal,
    *,
    event_type: str = "simulation.run_started",
    session_id: str = "sess-1",
    severity: str = "info",
    producer_id: str = "sim-engine",
    value_ns: int = 1,
    run_id: str | None = None,
) -> int:
    envelope = _raw_envelope(
        event_type=event_type,
        session_id=session_id,
        producer_id=producer_id,
    )
    envelope["severity"] = severity
    envelope["time"]["source"]["value_ns"] = value_ns
    envelope["scope"]["run_id"] = run_id
    seq, duplicate = journal.append(envelope)
    assert duplicate is False
    return seq


class TestQueryEventsTracerBullet:
    """REQ-OBS-305-003: the journal is the order authority (CONTEXT.md 流水号)."""

    def test_query_events_returns_stamped_envelopes_in_journal_order(self) -> None:
        journal = _journal()
        for index in range(3):
            _append(journal, value_ns=index)
        service = ObservationQueryService(journal=journal)

        page = service.query_events(EventsQueryRequest(session_id="sess-1"))

        assert [item["journal_seq"] for item in page.items] == [1, 2, 3]
        assert [item["event_type"] for item in page.items] == [
            "simulation.run_started"
        ] * 3
        assert page.next_cursor is None
        assert page.truncated is False
        assert page.sort == "journal_asc"

    def test_query_events_unknown_session_is_scope_not_found(self) -> None:
        """REQ-OBS-305-001: every endpoint is session-scoped; an unknown
        session (no specs, no journal rows) is the 404 family."""
        service = ObservationQueryService(journal=_journal())
        with pytest.raises(NotFoundError) as excinfo:
            service.query_events(EventsQueryRequest(session_id="ghost"))
        assert excinfo.value.error_code == "SIM_SESSION_NOT_FOUND"


class TestFlatShapeBaseline:
    """REQ-OBS-305-002: the SPEC-305 §5 flat-scalar baseline on the events
    face (clock-domain validation + shape rules; 缝合批准 #12)."""

    def test_time_bounded_query_without_clock_domain_is_domain_semantic_422(
        self,
    ) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(SemanticValidationError) as excinfo:
            service.query_events(
                EventsQueryRequest(session_id="sess-1", start_ns=0, end_ns=10)
            )
        assert excinfo.value.error_code == "OBS_INVALID_TIME_DOMAIN"

    def test_mixed_ns_and_iso_shapes_in_one_request_rejected_422(self) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(SemanticValidationError) as excinfo:
            service.query_events(
                EventsQueryRequest(
                    session_id="sess-1",
                    clock_domain="wall:utc",
                    start_ns=0,
                    end_ns="2026-01-01T00:00:00Z",
                )
            )
        assert excinfo.value.error_code == "OBS_INVALID_TIME_DOMAIN"

    def test_iso_string_outside_wall_domain_rejected_422(self) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(SemanticValidationError) as excinfo:
            service.query_events(
                EventsQueryRequest(
                    session_id="sess-1",
                    clock_domain="sim:sess-1",
                    start_ns="2026-01-01T00:00:00Z",
                    end_ns="2026-01-02T00:00:00Z",
                )
            )
        assert excinfo.value.error_code == "OBS_INVALID_TIME_DOMAIN"

    def test_wall_domain_iso_bounds_parse_and_filter(self) -> None:
        journal = _journal()
        # 2026-01-01T00:00:00Z = 1767225600 s epoch; the event sits at 1 ns.
        _append(journal, value_ns=1)
        service = ObservationQueryService(journal=journal)
        page = service.query_events(
            EventsQueryRequest(
                session_id="sess-1",
                clock_domain="wall:utc",
                start_ns="2025-12-31T00:00:00Z",
                end_ns="2026-01-02T00:00:00Z",
            )
        )
        assert len(page.items) == 0  # event source time is sim-domain ns, not wall

    def test_unparseable_bound_is_request_shape_400(self) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(BadRequestError):
            service.query_events(
                EventsQueryRequest(
                    session_id="sess-1",
                    clock_domain="wall:utc",
                    start_ns="not-a-time",
                )
            )

    def test_timepoint_object_shape_refused_as_query_parameter(self) -> None:
        """SPEC-305 §5: the timepoint object shape is record/response-only."""
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(BadRequestError):
            service.query_events(
                EventsQueryRequest(
                    session_id="sess-1",
                    clock_domain="wall:utc",
                    start_ns={"value_ns": 0},  # type: ignore[arg-type]
                )
            )


class TestFiltersAndSorts:
    """REQ-OBS-305-003/004: server-side filters BEFORE pagination; the four
    §5 sort values; single-domain time orders (SPEC-300 §6 rule 1/3)."""

    def test_whitelist_filters_apply_before_pagination(self) -> None:
        journal = _journal()
        _append(journal, event_type="simulation.run_started", severity="info")
        _append(journal, event_type="simulation.run_completed", severity="info")
        _append(journal, event_type="simulation.run_completed", severity="error")
        service = ObservationQueryService(journal=journal)

        page = service.query_events(
            EventsQueryRequest(
                session_id="sess-1",
                event_types=("simulation.run_completed",),
                severities=("error",),
            )
        )
        assert [item["journal_seq"] for item in page.items] == [3]

    def test_time_range_is_half_open(self) -> None:
        journal = _journal()
        _append(journal, value_ns=10)
        _append(journal, value_ns=20)
        _append(journal, value_ns=30)
        service = ObservationQueryService(journal=journal)
        page = service.query_events(
            EventsQueryRequest(
                session_id="sess-1",
                clock_domain="sim:sess-1",
                start_ns=10,
                end_ns=30,
            )
        )
        assert [item["time"]["source"]["value_ns"] for item in page.items] == [10, 20]

    def test_journal_desc_reverses_the_stamped_order(self) -> None:
        journal = _journal()
        for index in range(3):
            _append(journal, value_ns=index)
        service = ObservationQueryService(journal=journal)
        page = service.query_events(
            EventsQueryRequest(session_id="sess-1", sort="journal_desc")
        )
        assert [item["journal_seq"] for item in page.items] == [3, 2, 1]

    def test_time_sort_is_single_domain_and_ordered(self) -> None:
        journal = _journal()
        # Two sim-domain events inserted out of time order + one wall event.
        _append(journal, value_ns=30)
        _append(journal, value_ns=10)
        wall = _raw_envelope(event_type="simulation.run_started")
        wall["time"]["source"] = {
            "value_ns": 999,
            "clock_domain": "wall:utc",
            "clock_epoch": 0,
        }
        journal.append(wall)
        service = ObservationQueryService(journal=journal)

        page = service.query_events(
            EventsQueryRequest(
                session_id="sess-1",
                sort="time_asc",
                clock_domain="sim:sess-1",
            )
        )
        assert [item["time"]["source"]["value_ns"] for item in page.items] == [10, 30]

    def test_unknown_sort_value_is_request_shape_400(self) -> None:
        service = ObservationQueryService(journal=_journal())
        with pytest.raises(BadRequestError):
            service.query_events(
                EventsQueryRequest(session_id="sess-1", sort="alphabetical")
            )

    def test_run_id_filter_narrows_to_scope_run(self) -> None:
        journal = _journal()
        _append(journal, run_id="run-a")
        _append(journal, run_id="run-b")
        service = ObservationQueryService(journal=journal)
        page = service.query_events(
            EventsQueryRequest(session_id="sess-1", run_id="run-b")
        )
        assert [item["scope"]["run_id"] for item in page.items] == ["run-b"]


class TestCursorPagination:
    """REQ-OBS-305-003: cursor pagination consistent (no duplicates, no
    gaps), expired/bound-mismatch semantics correct."""

    def test_pages_walk_the_whole_journal_without_duplicates_or_gaps(self) -> None:
        journal = _journal()
        total = 7
        for index in range(total):
            _append(journal, value_ns=index)
        service = ObservationQueryService(journal=journal)

        seen: list[int] = []
        cursor = None
        pages = 0
        while True:
            page = service.query_events(
                EventsQueryRequest(session_id="sess-1", limit=3, cursor=cursor)
            )
            pages += 1
            seen.extend(item["journal_seq"] for item in page.items)
            if page.next_cursor is None:
                assert page.truncated is False
                break
            assert page.truncated is True
            cursor = page.next_cursor
        assert seen == list(range(1, total + 1))
        assert pages == 3

    def test_limit_bounds_are_invalid_not_clamped(self) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        for bad in (0, -1, 2001, 100_000):
            with pytest.raises(BadRequestError):
                service.query_events(
                    EventsQueryRequest(session_id="sess-1", limit=bad)
                )
        page = service.query_events(
            EventsQueryRequest(session_id="sess-1", limit=2000)
        )
        assert page.items

    def test_cursor_replayed_under_changed_filter_is_expired(self) -> None:
        journal = _journal()
        _append(journal, severity="info")
        _append(journal, severity="error")
        _append(journal, severity="error")
        service = ObservationQueryService(journal=journal)
        first = service.query_events(
            EventsQueryRequest(
                session_id="sess-1", limit=1, severities=("error",)
            )
        )
        assert first.next_cursor is not None
        with pytest.raises(ConflictError) as excinfo:
            service.query_events(
                EventsQueryRequest(session_id="sess-1", limit=1, cursor=first.next_cursor)
            )
        assert excinfo.value.error_code == "OBS_CURSOR_EXPIRED"

    def test_garbage_cursor_is_expired_not_crash(self) -> None:
        journal = _journal()
        _append(journal)
        service = ObservationQueryService(journal=journal)
        with pytest.raises(ConflictError) as excinfo:
            service.query_events(
                EventsQueryRequest(session_id="sess-1", cursor="garbage-token")
            )
        assert excinfo.value.error_code == "OBS_CURSOR_EXPIRED"

    def test_cursor_of_another_session_is_expired(self) -> None:
        journal = _journal()
        _append(journal, session_id="sess-1")
        _append(journal, session_id="sess-1", value_ns=5)
        _append(journal, session_id="sess-2", value_ns=2)
        service = ObservationQueryService(journal=journal)
        first = service.query_events(
            EventsQueryRequest(session_id="sess-1", limit=1)
        )
        assert first.next_cursor is not None
        with pytest.raises(ConflictError):
            service.query_events(
                EventsQueryRequest(
                    session_id="sess-2", limit=1, cursor=first.next_cursor
                )
            )

    def test_time_sort_pages_are_position_stable(self) -> None:
        journal = _journal()
        stamps = (50, 10, 40, 20, 30, 60, 70)
        for stamp in stamps:
            _append(journal, value_ns=stamp)
        service = ObservationQueryService(journal=journal)
        request = EventsQueryRequest(
            session_id="sess-1",
            sort="time_asc",
            clock_domain="sim:sess-1",
            limit=3,
        )
        seen: list[int] = []
        cursor = None
        while True:
            page = service.query_events(
                EventsQueryRequest(
                    session_id=request.session_id,
                    sort=request.sort,
                    clock_domain=request.clock_domain,
                    limit=request.limit,
                    cursor=cursor,
                )
            )
            seen.extend(item["time"]["source"]["value_ns"] for item in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == sorted(stamps)


class TestScanBudget:
    """REQ-OBS-305-004: 范围超限拒 — bounded scan budget."""

    def test_scan_over_budget_is_range_too_large(self) -> None:
        journal = _journal()
        for index in range(12):
            _append(journal, value_ns=index)
        service = ObservationQueryService(journal=journal, max_scan_rows=10)
        with pytest.raises(SemanticValidationError) as excinfo:
            service.query_events(
                EventsQueryRequest(session_id="sess-1", limit=2000)
            )
        assert excinfo.value.error_code == OBS_QUERY_RANGE_TOO_LARGE


class TestSessionSummary:
    """SPEC-300 §12: ``get_session_summary`` frozen name."""

    def test_summary_reports_watermark_and_event_count(self) -> None:
        journal = _journal()
        for index in range(5):
            _append(journal, value_ns=index)
        service = ObservationQueryService(journal=journal)
        summary = service.get_session_summary("sess-1")
        assert summary.tenant_id == "local"
        assert summary.session_id == "sess-1"
        assert summary.journal_seq_watermark == 5
        assert summary.event_count == 5

    def test_summary_of_unknown_session_is_404(self) -> None:
        service = ObservationQueryService(journal=_journal())
        with pytest.raises(NotFoundError):
            service.get_session_summary("ghost")


class TestErrorTranslation:
    """Service-plane structured errors → frozen categories, codes intact."""

    def test_metric_not_found_translates_to_404_category(self) -> None:
        from application.observation.metrics.errors import MetricError

        translated = translate_service_error(
            MetricError("OBS_METRIC_NOT_FOUND", "unknown metric")
        )
        assert isinstance(translated, NotFoundError)
        assert translated.error_code == "OBS_METRIC_NOT_FOUND"

    def test_metric_range_error_translates_to_422_category(self) -> None:
        from application.observation.metrics.errors import MetricError

        translated = translate_service_error(
            MetricError("OBS_QUERY_RANGE_TOO_LARGE", "too large")
        )
        assert isinstance(translated, SemanticValidationError)
        assert translated.error_code == "OBS_QUERY_RANGE_TOO_LARGE"

    def test_dimension_rejected_translates_to_422_category(self) -> None:
        from application.observation.metrics.errors import MetricError

        translated = translate_service_error(
            MetricError("OBS_METRIC_DIMENSION_REJECTED", "bad dimension")
        )
        assert isinstance(translated, SemanticValidationError)

    def test_timeline_cursor_expired_translates_to_409_category(self) -> None:
        from application.observation.timeline.errors import TimelineError

        translated = translate_service_error(
            TimelineError("OBS_CURSOR_EXPIRED", "stale cursor")
        )
        assert isinstance(translated, ConflictError)
        assert translated.error_code == "OBS_CURSOR_EXPIRED"

    def test_cursor_expired_code_is_the_timeline_registered_constant(self) -> None:
        """M4 review fix F1: the query plane must NOT redeclare
        ``OBS_CURSOR_EXPIRED`` — it reuses the #51 registration-place
        constant object, so a spelling fork cannot silently unhook the
        409 translation row."""
        import application.observation.query.errors as query_errors
        import application.observation.timeline.errors as timeline_errors
        from application.observation.timeline.errors import TimelineError

        assert query_errors.OBS_CURSOR_EXPIRED is (
            timeline_errors.OBS_CURSOR_EXPIRED
        )
        # And the raised-then-translated chain runs on that same object.
        translated = translate_service_error(
            TimelineError(timeline_errors.OBS_CURSOR_EXPIRED, "stale cursor")
        )
        assert isinstance(translated, ConflictError)
        assert translated.error_code is query_errors.OBS_CURSOR_EXPIRED

    def test_sqlite_failure_translates_to_503_storage_unavailable(self) -> None:
        import sqlite3

        translated = translate_service_error(
            sqlite3.OperationalError("disk I/O error")
        )
        assert isinstance(translated, ServiceUnavailableError)
        assert translated.error_code == "OBS_STORAGE_UNAVAILABLE"
        assert translated.retryable is True

    def test_journal_limit_guard_translates_to_400(self) -> None:
        translated = translate_service_error(ValueError("limit out of range"))
        assert isinstance(translated, BadRequestError)

    def test_application_error_passes_through_unchanged(self) -> None:
        original = BadRequestError("REQUEST_BODY_INVALID", "shape")
        assert translate_service_error(original) is original


class _RecordingHints:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict]] = []

    def publish(self, session_id: str, topic: str, data: dict) -> None:
        self.published.append((session_id, topic, data))


def _records_provider(journal: SqliteEventJournal):
    """Timeline records over the journal via the #51 recorder projection."""

    def provider(session_id: str, **_: object):
        recorder = TimelineRecorder()
        for row in journal.query(session_id, after_seq=0, limit=2000):
            recorder.record_event_document(row.envelope)
        return recorder.records(session_id)

    return provider


class TestExportTasks:
    """SPEC-305 §4 export rows: POST creates an Observation export task
    ONLY (read-only discipline); GET reads status/manifest; 限流 + scope."""

    def _registry(self, journal, **kwargs) -> ExportTaskRegistry:
        hints = _RecordingHints()
        registry = ExportTaskRegistry(
            records_provider=_records_provider(journal),
            hint_publisher=hints,
            export_id_factory=lambda: "export-0001",
            created_at_factory=lambda: TimelineTimepoint(
                value_ns=1_000,
                clock_domain="wall:utc",
                clock_epoch=0,
                semantics=TimepointSemantics.OBSERVED,
            ),
            **kwargs,
        )
        registry._hints = hints  # test observation handle
        return registry

    def test_create_export_builds_manifest_and_emits_progress_hint(self) -> None:
        journal = _journal()
        _append(journal, value_ns=10)
        _append(journal, value_ns=20)
        registry = self._registry(journal)

        task = registry.create(
            ExportTaskRequest(session_id="sess-1", formats=("jsonl",))
        )

        assert task.status == "completed"
        assert task.export_id == "export-0001"
        assert task.manifest["scope"]["session_id"] == "sess-1"
        assert task.manifest["total_records"] == 2
        assert task.file_digests
        hints = registry._hints
        assert hints.published[0][1] == "observation.export_progress"
        assert hints.published[0][2]["export_id"] == "export-0001"

    def test_get_export_returns_task(self) -> None:
        journal = _journal()
        _append(journal)
        registry = self._registry(journal)
        created = registry.create(ExportTaskRequest(session_id="sess-1"))
        fetched = registry.get("sess-1", created.export_id)
        assert fetched is not None
        assert fetched.export_id == created.export_id

    def test_unknown_export_is_artifact_not_found_404(self) -> None:
        journal = _journal()
        _append(journal)
        registry = self._registry(journal)
        with pytest.raises(NotFoundError) as excinfo:
            registry.get("sess-1", "missing-export")
        assert excinfo.value.error_code == "PLT_ARTIFACT_NOT_FOUND"

    def test_cross_session_export_access_is_scope_forbidden_403(self) -> None:
        journal = _journal()
        _append(journal, session_id="sess-1")
        _append(journal, session_id="sess-2", value_ns=5)
        registry = self._registry(journal)
        created = registry.create(ExportTaskRequest(session_id="sess-1"))
        with pytest.raises(ForbiddenError) as excinfo:
            registry.get("sess-2", created.export_id)
        assert excinfo.value.error_code == "OBS_SCOPE_FORBIDDEN"

    def test_export_rate_limit_is_429_retryable(self) -> None:
        journal = _journal()
        _append(journal)
        registry = self._registry(journal, max_exports_per_session=2)
        registry.create(ExportTaskRequest(session_id="sess-1"))
        with pytest.raises(RateLimitedError) as excinfo:
            registry.create(ExportTaskRequest(session_id="sess-1"))
            registry.create(ExportTaskRequest(session_id="sess-1"))
        assert excinfo.value.error_code == "HTTP_429"
        assert excinfo.value.retryable is True


class TestDelegationFaces:
    """The §12 orchestrator delegates to the #50/#51/#52 faces and
    translates their structured errors onto the frozen categories."""

    def _wired_service(self, journal=None, *, reader=None, hints=None, rule_set=None):
        journal = journal or _journal()
        recorder = TimelineRecorder()
        engine = MetricsEngine()
        conn = db.connect(":memory:")
        db.migrate(conn)
        store = SqliteAlertStore(conn)
        rules = rule_set if rule_set is not None else default_rule_set()
        alerts = AlertService(store, rules)
        service = ObservationQueryService(
            journal=journal,
            session_exists=lambda sid: False,
            metrics=MetricsService(engine),
            timeline=TimelineService(recorder),
            alerts=alerts,
            reader=reader if reader is not None else CannedReader(),
            hint_publisher=hints,
        )
        return service, journal, recorder, engine, store, alerts

    def test_timeline_delegation_returns_records_single_domain(self) -> None:
        service, journal, recorder, *_ = self._wired_service()
        _append(journal, value_ns=10)
        for row in journal.query("sess-1", after_seq=0, limit=100):
            recorder.record_event_document(row.envelope)
        page = service.query_timeline(
            "sess-1", clock_domain="sim:sess-1", clock_epoch=0
        )
        assert len(page.records) == 1
        assert page.records[0].journal_seq == 1

    def test_timeline_cursor_error_translates_to_conflict(self) -> None:
        service, journal, recorder, *_ = self._wired_service()
        _append(journal)
        with pytest.raises(ConflictError) as excinfo:
            service.query_timeline(
                "sess-1",
                clock_domain="sim:sess-1",
                clock_epoch=0,
                cursor="definitely-not-a-timeline-cursor",
            )
        assert excinfo.value.error_code == "OBS_CURSOR_EXPIRED"

    def test_metrics_known_metric_without_series_answers_empty(self) -> None:
        service, journal, *_ = self._wired_service()
        _append(journal)
        result = service.query_metrics(
            "sess-1",
            metric_names=("simulation.virtual_time_ns",),
            start_ns=0,
            end_ns=1_000,
            step_ns=500,
            clock_domain="sim:sess-1",
        )
        assert result.clock_domain == "sim:sess-1"
        assert result.series == ()  # no derived samples yet — honest emptiness

    def test_metrics_really_unknown_metric_is_404_category(self) -> None:
        service, journal, *_ = self._wired_service()
        _append(journal)
        with pytest.raises(NotFoundError) as excinfo:
            service.query_metrics(
                "sess-1",
                metric_names=("no.such.metric",),
                start_ns=0,
                end_ns=1_000,
                step_ns=500,
                clock_domain="sim:sess-1",
            )
        assert excinfo.value.error_code == "OBS_METRIC_NOT_FOUND"

    def test_metrics_dimension_filter_rejection_is_422_category(self) -> None:
        service, journal, *_ = self._wired_service()
        _append(journal)
        with pytest.raises(SemanticValidationError) as excinfo:
            service.query_metrics(
                "sess-1",
                metric_names=("simulation.virtual_time_ns",),
                start_ns=0,
                end_ns=1_000,
                step_ns=500,
                clock_domain="sim:sess-1",
                filters={"not_a_dimension": 1},
            )
        assert excinfo.value.error_code == "OBS_METRIC_DIMENSION_REJECTED"

    def test_alerts_delegation_lists_saved_records(self) -> None:
        service, journal, _, _, store, _ = self._wired_service()
        _append(journal)
        record = _alert_record("alert-1", "sess-1")
        store.save(record)
        page = service.list_alerts("sess-1")
        assert page.total == 1
        assert page.items[0].alert_id == "alert-1"

    def test_alerts_cursor_pagination_walks_offset_windows(self) -> None:
        service, journal, _, _, store, _ = self._wired_service()
        _append(journal)
        for index in range(3):
            store.save(_alert_record(f"alert-{index}", "sess-1"))
        page1 = service.list_alerts("sess-1", limit=2)
        assert [item.alert_id for item in page1.items] == ["alert-0", "alert-1"]
        assert page1.next_cursor is not None
        page2 = service.list_alerts("sess-1", limit=2, cursor=page1.next_cursor)
        assert [item.alert_id for item in page2.items] == ["alert-2"]
        assert page2.next_cursor is None

    def test_alerts_cursor_under_changed_filter_is_expired(self) -> None:
        service, journal, _, _, store, _ = self._wired_service()
        _append(journal)
        for index in range(3):
            store.save(_alert_record(f"alert-{index}", "sess-1"))
        page1 = service.list_alerts("sess-1", limit=2)
        with pytest.raises(ConflictError):
            service.list_alerts(
                "sess-1", limit=2, cursor=page1.next_cursor, state="firing"
            )

    def test_health_delegates_and_emits_change_hint_once(self) -> None:
        hints = _RecordingHints()
        reader = CannedReader()
        rule_set = HealthRuleSet(
            ruleset_id="s", version="1", profile="p", rules=(make_rule(),)
        )
        service, journal, _, _, _, _ = self._wired_service(
            reader=reader, hints=hints, rule_set=rule_set
        )
        _append(journal)
        first = service.health("sess-1", clock_domain="sim:sess-1", now_ns=1_000)
        assert first.overall.value == "unknown"
        assert len(hints.published) == 1
        assert hints.published[0][1] == "observation.health_changed"
        # Same outcome again → NO new hint.
        service.health("sess-1", clock_domain="sim:sess-1", now_ns=2_000)
        assert len(hints.published) == 1
        # Outcome changes (rule fires) → second hint.
        reader.add(sample_at(500, 500.0))
        changed = service.health("sess-1", clock_domain="sim:sess-1", now_ns=3_000)
        assert changed.overall.value != "unknown"
        assert len(hints.published) == 2


def _alert_record(alert_id: str, session_id: str):
    from domain.observation import (
        AlertRecord,
        AlertScope,
        AlertSeverity,
        AlertState,
        MetricSampleTimepoint,
        SampleSemantics,
    )

    return AlertRecord(
        alert_id=alert_id,
        fingerprint=f"fp-{alert_id}",
        rule_id="TEST_RULE",
        rule_version="1.0.0",
        state=AlertState.FIRING,
        severity=AlertSeverity.WARNING,
        scope=AlertScope(tenant_id="local", session_id=session_id),
        time=MetricSampleTimepoint(
            value_ns=1_000,
            clock_domain="sim:sess-1",
            clock_epoch=0,
            semantics=SampleSemantics.SOURCE,
        ),
        summary="deterministic fixture record",
    )
