"""Builtin-rule cross-validation over the real stack (ticket #55,
REQ-DIA-307-003 + REQ-DIA-307-005).

The four SPEC-307 §6 rules run END TO END against the shared-fixture
fault observation programs committed through the real #47 gateway into
the real SPEC-502 SQLite journal, evaluated by the #54
``DiagnosisService`` with the ticket #55 ``builtin_rules_provider``
seam: envelope → journal commit → observation read-back → evaluator →
``diagnoses``-table upsert + ``diagnosis.*`` publication.

Pins: the paired candidate per fault (single attributable symptom),
``rule_version`` traceability in BOTH the table row and the event
payload (REQ-DIA-307-005), the suppression event granularity over the
real journal (one raised + one updated per extra hit; idempotent
re-evaluation emits nothing) and the runtime disable switch.
"""

import pytest

from adapters.storage.db import connect
from adapters.storage.journal import SqliteEventJournal
from adapters.storage.repositories import SqliteDiagnosisRepository
from application.diagnosis import DiagnosisService
from application.observation.gateway import EventGateway
from domain.diagnosis.rules import BuiltinRuleSet, builtin_rules_provider

from tests._support.diagnosis_fixtures import (
    NODE_ID,
    RUN_ID,
    SESSION_ID,
    fault_observation_program,
    observation_envelope,
)

NOW_MS = 1_700_000_000_000

#: The fixture observation programs' record → envelope view (journal_seq
#: is stamped by the journal at durable append, ADR-0006 decision 2).


def _envelopes_for(fault_type: str) -> list[dict]:
    envelopes = []
    for record in fault_observation_program(fault_type):
        envelopes.append(
            observation_envelope(
                event_type=record.event_type,
                payload=dict(record.payload),
                session_id=SESSION_ID,
                run_id=RUN_ID,
                pid=record.pid,
                node_id=record.node_id,
                source_ns=record.source_ns,
            )
        )
    return envelopes


@pytest.fixture
def dia_stack(journal):
    connection = connect(journal.db_path, check_same_thread=False)
    journal_adapter = SqliteEventJournal(connection)
    gateway = EventGateway(journal_adapter)
    repository = SqliteDiagnosisRepository(connection)
    service = DiagnosisService(
        journal_adapter,
        gateway,
        repository,
        rules_provider=builtin_rules_provider,
        now_utc_ms=lambda: NOW_MS,
    )
    return {
        "connection": connection,
        "journal": journal_adapter,
        "gateway": gateway,
        "repository": repository,
        "service": service,
    }


def _commit_observations(stack, fault_type: str) -> None:
    for document in _envelopes_for(fault_type):
        assert stack["gateway"].publish(document).accepted
    stack["gateway"].drain()


def _published_diagnosis_events(stack) -> dict[str, list[dict]]:
    events = stack["journal"].query(SESSION_ID, limit=100)
    by_type: dict[str, list[dict]] = {}
    for row in events:
        if row.event_type.startswith("diagnosis."):
            by_type.setdefault(row.event_type, []).append(row.envelope)
    return by_type


class TestFourFaultInterlockEndToEnd:
    """One fault's observation program through the real journal yields
    exactly the paired diagnosis (SPEC-307 §9 shared-fixture row)."""

    @pytest.mark.parametrize(
        "fault_type",
        ["PAT_MISSING", "PMT_INVALID_CRC", "CC_DISCONTINUITY", "PMT_PID_MISMATCH"],
    )
    def test_paired_candidate_from_journal_to_table(self, dia_stack, fault_type):
        stack = dia_stack
        _commit_observations(stack, fault_type)
        report = stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()

        expected_code = {
            "PAT_MISSING": "DIAG_PAT_MISSING",
            "PMT_INVALID_CRC": "DIAG_PMT_CRC_BAD",
            "CC_DISCONTINUITY": "DIAG_CC_DISCONTINUITY",
            "PMT_PID_MISMATCH": "DIAG_PMT_PID_MISMATCH",
        }[fault_type]
        assert len(report.candidates) == 1
        candidate = report.candidates[0]
        assert candidate.code == expected_code

        # The raised event is committed and carries the rule identity.
        raised = _published_diagnosis_events(stack).get("diagnosis.raised", [])
        assert len(raised) == 1
        payload = raised[0]["payload"]
        assert payload["code"] == expected_code
        assert payload["rule_version"] == "1.0.0"

        # The table row is the record authority (SPEC-502 §4 row 6).
        rows = stack["repository"].query(SESSION_ID)
        assert len(rows) == 1
        assert rows[0].code == expected_code
        assert rows[0].rule_version == "1.0.0"
        assert rows[0].state == "raised"
        assert rows[0].affected_node_ids == [NODE_ID]

    def test_table_and_event_payload_agree_on_rule_version(self, dia_stack):
        """REQ-DIA-307-005: rule_version is traceable in BOTH the
        diagnoses row and the diagnosis.* payload — and identical."""
        stack = dia_stack
        _commit_observations(stack, "PAT_MISSING")
        stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()
        payload = _published_diagnosis_events(stack)["diagnosis.raised"][0]["payload"]
        row = stack["repository"].query(SESSION_ID)[0]
        assert payload["rule_version"] == row.rule_version == "1.0.0"
        assert payload["rule_id"] == row.rule_id
        # Observation refs resolve back to the committed journal order.
        observation_seqs = {
            row_.journal_seq
            for row_ in stack["journal"].query(SESSION_ID, limit=100)
            if row_.event_type.startswith("ts.")
        }
        for ref in payload["observation_refs"]:
            assert ref["journal_seq"] in observation_seqs


class TestAllFaultsTogether:
    def test_four_candidates_in_spec5_order_and_four_rows(self, dia_stack):
        stack = dia_stack
        for fault_type in (
            "PAT_MISSING",
            "PMT_INVALID_CRC",
            "CC_DISCONTINUITY",
            "PMT_PID_MISMATCH",
        ):
            _commit_observations(stack, fault_type)
        report = stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()
        assert [candidate.code for candidate in report.candidates] == [
            "DIAG_PAT_MISSING",
            "DIAG_PMT_CRC_BAD",
            "DIAG_CC_DISCONTINUITY",
            "DIAG_PMT_PID_MISMATCH",
        ]
        rows = stack["repository"].query(SESSION_ID)
        assert {row.code for row in rows} == {
            candidate.code for candidate in report.candidates
        }


class TestSuppressionEventGranularity:
    """One raised + one updated per extra hit over the real journal;
    idempotent re-evaluation emits nothing further."""

    def test_persistent_crc_emits_raised_then_updated(self, dia_stack):
        stack = dia_stack
        _commit_observations(stack, "PMT_INVALID_CRC")
        stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()
        events = _published_diagnosis_events(stack)
        assert len(events.get("diagnosis.raised", [])) == 1
        assert len(events.get("diagnosis.updated", [])) == 1
        raised_refs = events["diagnosis.raised"][0]["payload"]["observation_refs"]
        updated_refs = events["diagnosis.updated"][0]["payload"]["observation_refs"]
        assert len(raised_refs) == 1  # raised anchors hit 0
        assert len(updated_refs) == 2  # updated accumulates cumulatively

    def test_reevaluation_is_idempotent_no_twin_events(self, dia_stack):
        stack = dia_stack
        _commit_observations(stack, "PMT_INVALID_CRC")
        stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()
        before = len(stack["journal"].query(SESSION_ID, limit=100))
        stack["service"].evaluate(SESSION_ID, RUN_ID)
        stack["gateway"].drain()
        after = stack["journal"].query(SESSION_ID, limit=100)
        assert len(after) == before  # same refs → no new lifecycle events
        events = _published_diagnosis_events(stack)
        assert len(events.get("diagnosis.raised", [])) == 1


class TestDisabledRuleEndToEnd:
    def test_disabled_rule_yields_no_candidate_or_row(self, dia_stack):
        stack = dia_stack
        _commit_observations(stack, "PAT_MISSING")
        _commit_observations(stack, "CC_DISCONTINUITY")
        stack["service"].evaluate(
            SESSION_ID,
            RUN_ID,
            rules=BuiltinRuleSet(disabled_rule_ids=["DIA-PAT-MISSING"]).rules(),
        )
        stack["gateway"].drain()
        assert [
            candidate.code for candidate in stack["service"].evaluate(
                SESSION_ID, RUN_ID,
                rules=BuiltinRuleSet(disabled_rule_ids=["DIA-PAT-MISSING"]).rules(),
            ).candidates
        ] == ["DIAG_CC_DISCONTINUITY"]
        assert {row.code for row in stack["repository"].query(SESSION_ID)} == {
            "DIAG_CC_DISCONTINUITY"
        }
