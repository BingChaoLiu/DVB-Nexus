"""``diagnosis.raised/updated/cleared`` envelope construction tests
(ticket #54, REQ-DIA-306-004).

Every builder returns a parse_envelope-validated canonical document
(construction guarantee, same posture as the #41 emitter): a payload that
violates the SPEC-306 §7 shape can never leave the module, so the journal
only ever sees conforming diagnosis events.
"""

import pytest

from domain.diagnosis.events import (
    PRODUCER_ID,
    cleared_envelope,
    raised_envelope,
    updated_envelope,
)
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.diagnosis.report import (
    DiagnosisCandidate,
    EvidenceRef,
    ObservationRef,
)
from domain.observation import parse_envelope, validate_payload

from tests._support.diagnosis_fixtures import RUN_ID, SESSION_ID


def _candidate(**overrides) -> DiagnosisCandidate:
    values = dict(
        diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        run_id=RUN_ID,
        rule_id="DIA-PAT-MISSING",
        rule_version="1.0.0",
        code="DIAG_PAT_MISSING",
        priority=10,
        severity=DiagnosisSeverity.ERROR,
        confidence=DiagnosisConfidence.HIGH,
        title="PAT missing in window",
        summary="No PAT observed on PID 0 between packet 12000 and 18000",
        observation_refs=[
            ObservationRef(journal_seq=42, event_type="ts.psi_section_observed"),
            ObservationRef(journal_seq=43, event_type="ts.psi_section_observed"),
        ],
        affected_node_ids=["mux-0"],
        suggested_actions=["Restore PAT emission on PID 0"],
        evidence=EvidenceRef(
            artifact_id="9f2c0000-0000-4000-8000-000000000001",
            pid=0,
            packet_index=12000,
        ),
    )
    values.update(overrides)
    return DiagnosisCandidate(**values)


class TestRaisedEnvelope:
    def test_valid_envelope_passes_parse_and_registry(self):
        document = raised_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        envelope = parse_envelope(document)
        assert envelope.event_type == "diagnosis.raised"
        validate_payload("diagnosis.raised", envelope.payload)

    def test_producer_identity_and_no_journal_seq(self):
        document = raised_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        assert document["producer"]["producer_id"] == PRODUCER_ID
        # The producer view never carries a stamp (ADR-0006 decision 2):
        # the parsed envelope keeps the field unset until the journal
        # durable append fills it.
        assert document.get("journal_seq") is None

    def test_scope_run_id_attribution_and_dual_clock(self):
        document = raised_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        assert document["scope"]["session_id"] == SESSION_ID
        assert document["scope"]["run_id"] == RUN_ID  # SPEC-306 §5
        assert document["time"]["source"]["clock_domain"] == f"sim:{SESSION_ID}"
        assert document["time"]["observed"]["clock_domain"] == "wall:utc"

    def test_payload_matches_spec_306_section_7_shape(self):
        document = raised_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        payload = document["payload"]
        assert payload["diagnosis_id"] == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        assert payload["rule_id"] == "DIA-PAT-MISSING"
        assert payload["rule_version"] == "1.0.0"
        assert payload["code"] == "DIAG_PAT_MISSING"
        assert payload["severity"] == "error"
        assert payload["confidence"] == "high"
        assert payload["observation_refs"] == [
            {"journal_seq": 42, "event_type": "ts.psi_section_observed"},
            {"journal_seq": 43, "event_type": "ts.psi_section_observed"},
        ]
        assert payload["affected_node_ids"] == ["mux-0"]
        assert payload["suggested_actions"] == ["Restore PAT emission on PID 0"]
        assert payload["evidence"] == {
            "artifact_id": "9f2c0000-0000-4000-8000-000000000001",
            "pid": 0,
            "packet_index": 12000,
        }

    def test_envelope_severity_follows_candidate_severity(self):
        document = raised_envelope(
            _candidate(severity=DiagnosisSeverity.CRITICAL),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        assert document["severity"] == "critical"

    def test_correlation_addresses_node_and_pid(self):
        document = raised_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        correlation = document["correlation"]
        assert correlation["node_id"] == "mux-0"
        assert correlation["pid"] == 0

    def test_explicit_refs_override_for_per_hit_emission(self):
        candidate = _candidate()
        document = raised_envelope(
            candidate,
            session_id=SESSION_ID,
            observation_refs=candidate.observation_refs[:1],
            source_ns=9_000,
            observed_ns=9_500,
        )
        assert document["payload"]["observation_refs"] == [
            {"journal_seq": 42, "event_type": "ts.psi_section_observed"}
        ]


class TestUpdatedEnvelope:
    def test_same_identity_accumulated_refs(self):
        document = updated_envelope(
            _candidate(),
            session_id=SESSION_ID,
            source_ns=9_100,
            observed_ns=9_600,
        )
        assert document["event_type"] == "diagnosis.updated"
        assert (
            document["payload"]["diagnosis_id"]
            == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        )
        assert len(document["payload"]["observation_refs"]) == 2


class TestClearedEnvelope:
    def test_payload_carries_only_identity_and_reason(self):
        document = cleared_envelope(
            diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            rule_id="DIA-PAT-MISSING",
            session_id=SESSION_ID,
            run_id=RUN_ID,
            reason="regenerated stream shows no PAT-missing symptom",
            source_ns=9_200,
            observed_ns=9_700,
        )
        envelope = parse_envelope(document)
        assert envelope.event_type == "diagnosis.cleared"
        assert envelope.payload == {
            "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            "rule_id": "DIA-PAT-MISSING",
            "reason": "regenerated stream shows no PAT-missing symptom",
        }
        assert envelope.scope.run_id == RUN_ID

    def test_cleared_is_informational(self):
        document = cleared_envelope(
            diagnosis_id="d",
            rule_id="r",
            session_id=SESSION_ID,
            run_id=RUN_ID,
            reason="x",
            source_ns=0,
            observed_ns=1,
        )
        assert document["severity"] == "info"


class TestConstructionGuarantee:
    """A payload that cannot pass the registry cannot leave the module."""

    def test_candidate_with_empty_refs_is_refused_not_emitted(self):
        # model_construct bypasses the model-level min-length so the test
        # reaches the ENVELOPE construction guarantee: an emission with no
        # observation refs fails the registered payload schema (construction
        # guarantee — never emitted).
        broken = DiagnosisCandidate.model_construct(
            diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            run_id=RUN_ID,
            rule_id="DIA-PAT-MISSING",
            rule_version="1.0.0",
            code="DIAG_PAT_MISSING",
            priority=10,
            severity=DiagnosisSeverity.ERROR,
            confidence=DiagnosisConfidence.HIGH,
            title="t",
            summary="s",
            observation_refs=[],
            affected_node_ids=["mux-0"],
            suggested_actions=[],
            evidence=EvidenceRef(
                artifact_id="9f2c0000-0000-4000-8000-000000000001",
                pid=0,
                packet_index=0,
            ),
        )
        with pytest.raises(Exception) as excinfo:
            raised_envelope(
                broken,
                session_id=SESSION_ID,
                source_ns=0,
                observed_ns=1,
            )
        from domain.observation.errors import EnvelopeError

        assert isinstance(excinfo.value, EnvelopeError) or isinstance(
            excinfo.value.__cause__, Exception
        )
