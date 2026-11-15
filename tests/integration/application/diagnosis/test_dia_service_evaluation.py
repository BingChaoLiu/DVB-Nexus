"""DiagnosisService — journal-to-lifecycle orchestration (ticket #54).

REQ-DIA-306-001 (evaluate face + run-end trigger path) and REQ-DIA-306-004
(lifecycle events consistent with the diagnoses table) over the REAL
stack: tmp SQLite journal (``journal`` fixture) + ``SqliteEventJournal`` +
``EventGateway``/``EventPublisher`` + ``SqliteDiagnosisRepository``.
"""

import sqlite3

import pytest

from adapters.storage.checkpoints import SqliteCheckpointStore
from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteDiagnosisRepository
from application.diagnosis import (
    DiagnosisService,
    bind_run_completion_trigger,
)
from application.errors import NotFoundError, ServiceUnavailableError
from application.observation.gateway import EventGateway

from tests._support.diagnosis_fixtures import (
    RUN_ID,
    SESSION_ID,
    builtin_fixture_rules,
    fault_observation_program,
    observation_envelope,
)


class _BrokenJournal:
    """Journal double whose reads fail at the storage layer."""

    def query(self, session_id, *, after_seq=0, limit=100):
        raise sqlite3.OperationalError("disk I/O error")

    def max_seq(self, session_id):
        raise sqlite3.OperationalError("disk I/O error")


class _RejectedPublisher:
    """Publisher double that refuses every event (gateway down posture)."""

    class _Receipt:
        accepted = False
        error_code = "OBS_QUEUE_FULL"

    def publish(self, event):
        return self._Receipt()


def _publish_observations(gateway, fault_type="PAT_MISSING", session_id=SESSION_ID):
    """Admit the fault's observation program through the real gateway."""
    for record in fault_observation_program(fault_type):
        receipt = gateway.publish(
            observation_envelope(
                event_type=record.event_type,
                payload=record.payload,
                session_id=session_id,
                run_id=RUN_ID,
                pid=record.pid,
                node_id=record.node_id,
                source_ns=record.source_ns,
            )
        )
        assert receipt.accepted
    gateway.drain()


def _publish_run_event(gateway, event_type="simulation.run_completed", session_id=SESSION_ID, run_id=RUN_ID):
    receipt = gateway.publish(
        observation_envelope(
            event_type=event_type,
            payload={"lifecycle": "completed"},
            session_id=session_id,
            run_id=run_id,
            observed_ns=2_000,
        )
    )
    assert receipt.accepted
    gateway.drain()


@pytest.fixture
def stack(journal):
    connection = connect(journal.db_path)
    journal_adapter = SqliteEventJournal(connection)
    gateway = EventGateway(journal_adapter)
    return {
        "gateway": gateway,
        "publisher": gateway,
        "repository": SqliteDiagnosisRepository(connection),
        "journal": journal_adapter,
        "connection": connection,
    }


@pytest.fixture
def service(stack):
    return DiagnosisService(
        stack["journal"],
        stack["publisher"],
        stack["repository"],
        now_utc_ms=lambda: 1_700_000_000_000,
    )


def _drain(gateway) -> int:
    """Commit the queue: diagnosis events ride the same at-least-once
    gateway path as every producer (publish = admission, drain = commit)."""
    return gateway.drain()


class TestEvaluateFace:
    def test_evaluate_raises_publishes_and_upserts(self, stack, service):
        _publish_observations(stack["gateway"], "PAT_MISSING")
        report = service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        _drain(stack["gateway"])

        assert len(report.candidates) == 1
        candidate = report.candidates[0]
        assert candidate.code == "DIAG_PAT_MISSING"

        # The raised event is in the journal (stamped, payload conformance).
        events = stack["journal"].query(SESSION_ID, limit=100)
        raised = [e for e in events if e.event_type == "diagnosis.raised"]
        assert len(raised) == 1
        payload = raised[0].envelope["payload"]
        assert payload["code"] == "DIAG_PAT_MISSING"
        # The ref carries the REAL stamped journal_seq of the observation
        # (first admitted event of the session) — not the fixture's
        # unit-posture placeholder.
        assert payload["observation_refs"] == [
            {"journal_seq": 1, "event_type": "ts.psi_section_observed"}
        ]
        assert raised[0].envelope["scope"]["run_id"] == RUN_ID

        # The diagnoses table row is consistent with the event
        # (REQ-DIA-306-004).
        rows = stack["repository"].query(SESSION_ID)
        assert len(rows) == 1
        assert rows[0].diagnosis_id == candidate.diagnosis_id
        assert rows[0].state == "raised"

    def test_suppression_one_raised_one_updated_across_hits(self, stack, service):
        _publish_observations(stack["gateway"], "PMT_INVALID_CRC")
        service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        _drain(stack["gateway"])
        events = stack["journal"].query(SESSION_ID, limit=100)
        kinds = [e.event_type for e in events if e.event_type.startswith("diagnosis.")]
        assert kinds == ["diagnosis.raised", "diagnosis.updated"]
        updated_payload = [
            e.envelope["payload"] for e in events if e.event_type == "diagnosis.updated"
        ][0]
        # The two persistent hits stamp as the session's first two events.
        assert [ref["journal_seq"] for ref in updated_payload["observation_refs"]] == [1, 2]

    def test_idempotent_reevaluation_emits_no_new_events(self, stack, service):
        _publish_observations(stack["gateway"], "PAT_MISSING")
        first = service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        watermark = stack["journal"].max_seq(SESSION_ID)
        second = service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        assert stack["journal"].max_seq(SESSION_ID) == watermark
        assert second.candidates == first.candidates
        assert second.candidates[0].diagnosis_id == first.candidates[0].diagnosis_id

    def test_unknown_run_is_404_not_empty_report(self, stack, service):
        with pytest.raises(NotFoundError) as excinfo:
            service.evaluate(SESSION_ID, "run-unknown", rules=builtin_fixture_rules())
        assert excinfo.value.error_code == "SIM_RUN_NOT_FOUND"

    def test_no_registered_ruleset_is_honest_empty_report(self, stack, service):
        """rules=None + no provider → empty report, no rows, no events
        (SPEC-306 §8 row 1) — the trigger path without #55."""
        _publish_observations(stack["gateway"], "PAT_MISSING")
        _publish_run_event(stack["gateway"])  # run must exist
        report = service.evaluate(SESSION_ID, RUN_ID)
        assert report.candidates == ()
        assert stack["repository"].query(SESSION_ID) == []

    def test_explicit_empty_ruleset_clears_stored_rows(self, stack, service):
        _publish_observations(stack["gateway"], "PAT_MISSING")
        service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        _drain(stack["gateway"])
        service.evaluate(SESSION_ID, RUN_ID, rules=())
        _drain(stack["gateway"])
        events = stack["journal"].query(SESSION_ID, limit=100)
        cleared = [e for e in events if e.event_type == "diagnosis.cleared"]
        assert len(cleared) == 1
        assert cleared[0].envelope["payload"]["reason"]
        rows = stack["repository"].query(SESSION_ID)
        assert rows[0].state == "cleared"
        assert rows[0].cleared_at == 1_700_000_000_000

    def test_rules_none_does_not_clear_stored_rows(self, stack, service):
        _publish_observations(stack["gateway"], "PAT_MISSING")
        service.evaluate(SESSION_ID, RUN_ID, rules=builtin_fixture_rules())
        service.evaluate(SESSION_ID, RUN_ID)  # no ruleset registered
        rows = stack["repository"].query(SESSION_ID)
        assert rows[0].state == "raised"


class TestErrorMapping:
    """SPEC-306 §8: journal read failure = storage unavailable (503)."""

    def test_journal_failure_maps_to_503_service_unavailable(self, stack):
        broken_service = DiagnosisService(
            _BrokenJournal(),
            stack["publisher"],
            stack["repository"],
            now_utc_ms=lambda: 1,
        )
        with pytest.raises(ServiceUnavailableError) as excinfo:
            broken_service.evaluate(SESSION_ID, RUN_ID)
        assert excinfo.value.error_code == "OBS_STORAGE_UNAVAILABLE"

    def test_rejected_publication_becomes_report_warning(self, stack):
        rejecting_service = DiagnosisService(
            stack["journal"],
            _RejectedPublisher(),
            stack["repository"],
            now_utc_ms=lambda: 1_700_000_000_000,
        )
        _publish_observations(stack["gateway"], "PAT_MISSING")
        report = rejecting_service.evaluate(
            SESSION_ID, RUN_ID, rules=builtin_fixture_rules()
        )
        assert any(
            "was not accepted" in warning for warning in report.warnings
        )
        # The table row stays authoritative even when the stream event is
        # refused (table = query authority; warning surfaces the loss).
        assert stack["repository"].query(SESSION_ID)[0].state == "raised"

    def test_list_unknown_session_is_404(self, stack, service):
        with pytest.raises(NotFoundError) as excinfo:
            service.list_diagnoses("sess-never-seen")
        assert excinfo.value.error_code == "SIM_SESSION_NOT_FOUND"


class TestRunCompletionTrigger:
    """REQ-DIA-306-001: run_completed/run_failed commits drive evaluation.

    The subscriber runs on the drain thread, so the diagnosis events it
    publishes are committed by the FOLLOWING drain (at-least-once
    producer posture). The trigger service resolves its ruleset through
    the injectable ``rules_provider`` (the SPEC-307 registry stand-in
    until ticket #55).
    """

    @pytest.fixture
    def provided_service(self, stack):
        return DiagnosisService(
            stack["journal"],
            stack["publisher"],
            stack["repository"],
            rules_provider=builtin_fixture_rules,
            now_utc_ms=lambda: 1_700_000_000_000,
        )

    def test_run_completed_triggers_evaluation(self, stack, provided_service):
        bind_run_completion_trigger(stack["gateway"], provided_service)
        _publish_observations(stack["gateway"], "PAT_MISSING")
        _publish_run_event(stack["gateway"], "simulation.run_completed")
        _drain(stack["gateway"])

        events = stack["journal"].query(SESSION_ID, limit=100)
        raised = [e for e in events if e.event_type == "diagnosis.raised"]
        assert len(raised) == 1
        assert stack["repository"].query(SESSION_ID)[0].code == "DIAG_PAT_MISSING"

    def test_run_failed_triggers_evaluation_too(self, stack, provided_service):
        bind_run_completion_trigger(stack["gateway"], provided_service)
        _publish_observations(stack["gateway"], "CC_DISCONTINUITY")
        _publish_run_event(stack["gateway"], "simulation.run_failed")
        _drain(stack["gateway"])
        events = stack["journal"].query(SESSION_ID, limit=100)
        assert any(e.event_type == "diagnosis.raised" for e in events)

    def test_non_terminal_events_do_not_trigger(self, stack, provided_service):
        bind_run_completion_trigger(stack["gateway"], provided_service)
        _publish_observations(stack["gateway"], "PAT_MISSING")
        _publish_run_event(stack["gateway"], "simulation.run_progress")
        _drain(stack["gateway"])
        events = stack["journal"].query(SESSION_ID, limit=100)
        assert not [
            e for e in events if e.event_type.startswith("diagnosis.")
        ]
        assert stack["repository"].query(SESSION_ID) == []
