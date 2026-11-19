"""The SPEC-306 evidence anchor TWO-state face (ticket #138, SPEC-306
§Phase2 补丁修订).

Four layers pin the same contract:

- the ``EvidenceRef`` value object: MVP flat triple (byte-unchanged wire)
  vs the Phase 2 ``{artifact_id, locator}`` state — exactly one state
  holds, a partial triple is refused in both states;
- the rule interpreter's ``_evidence_of``: the Phase 2 evidence family
  anchors through the application-resolved ``evidence_artifact_id`` plus
  the namespace-mapped locator (payload locator fields verbatim —
  无对应定位字段不虚填); no anchor, no candidate;
- the ``diagnosis.*`` envelope builders: the Phase 2 candidate publishes
  ``{artifact_id, locator}`` evidence and leaves the correlation pid
  neutral (never fabricated); the MVP candidate's payload stays
  byte-identical (pinned by the #54 tests);
- the registry gate: a Phase 2-shaped ``raised`` payload passes
  ``validate_payload``, locator/pid mixing and empty locators are
  refused (the schema document's ``evidence_anchor`` oneOf mirror).
"""

import pytest
from pydantic import ValidationError

from domain.diagnosis.engine import ObservationRecord
from domain.diagnosis.events import raised_envelope
from domain.diagnosis.report import DiagnosisCandidate, EvidenceRef, ObservationRef
from domain.diagnosis.rules.model import _evidence_of
from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.observation import validate_payload

from tests._support.diagnosis_fixtures import RUN_ID, SESSION_ID


def _mvp_evidence() -> EvidenceRef:
    return EvidenceRef(
        artifact_id="9f2c0000-0000-4000-8000-000000000001",
        pid=0,
        packet_index=12000,
    )


def _phase2_candidate(**evidence_overrides) -> DiagnosisCandidate:
    return DiagnosisCandidate(
        diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        run_id=RUN_ID,
        rule_id="DIA-BBHEADER-SYNC-FAULT",
        rule_version="1.0.0",
        code="DIAG_BBHEADER_SYNC_FAULT",
        priority=60,
        severity=DiagnosisSeverity.ERROR,
        confidence=DiagnosisConfidence.MEDIUM,
        title="BBFRAME header recovery failed on the received frames",
        summary="BBFRAME header recovery failed on 2 frame(s)",
        observation_refs=[
            ObservationRef(journal_seq=7, event_type="bbframe.recovery_failed")
        ],
        affected_node_ids=[],
        suggested_actions=["Inspect the BBHEADER of the first failed frame"],
        evidence=EvidenceRef(
            artifact_id="inner-2",
            locator={"first_failed_frame_index": 3, "failure_count": 2},
            **evidence_overrides,
        ),
    )


class TestEvidenceRefTwoStates:
    """Exactly one state holds; partial triples are refused."""

    def test_mvp_state_stands(self):
        evidence = _mvp_evidence()
        assert evidence.pid == 0
        assert evidence.packet_index == 12000
        assert evidence.locator is None

    def test_phase2_state_stands(self):
        evidence = EvidenceRef(
            artifact_id="inner-2",
            locator={"first_failed_frame_index": 3, "failure_count": 2},
        )
        assert evidence.pid is None and evidence.packet_index is None
        assert evidence.locator == {
            "first_failed_frame_index": 3,
            "failure_count": 2,
        }

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"pid": 0},  # partial MVP triple: pid without packet_index
            {"packet_index": 3},  # partial MVP triple: the other way round
            {"pid": 0, "packet_index": 3, "locator": {"failure_count": 1}},
            {"locator": {}},  # empty locator
            {"locator": None},  # neither state
        ],
    )
    def test_invalid_states_are_refused(self, kwargs):
        with pytest.raises(ValidationError):
            EvidenceRef(artifact_id="inner-2", **kwargs)


class TestInterpreterPhase2Mapping:
    """``_evidence_of``: the namespace-mapped locator, verbatim."""

    @staticmethod
    def _record(event_type: str, payload: dict, anchor: str | None) -> ObservationRecord:
        return ObservationRecord(
            journal_seq=7,
            event_type=event_type,
            event_id="obs-evidence-1",
            payload=dict(payload),
            node_id=None,
            evidence_artifact_id=anchor,
        )

    @pytest.mark.parametrize(
        ("event_type", "payload", "expected_locator"),
        [
            (
                "t2mi.plp_mismatch",
                {
                    "expected_plp": 0,
                    "actual_plp": 1,
                    "business_absent_evidence": {
                        "plps_seen": [1],
                        "bbframe_packet_count": 4,
                        "filtered_packet_count": 0,
                        "total_packet_count": 60,
                    },
                },
                {
                    "expected_plp": 0,
                    "actual_plp": 1,
                    "business_absent_evidence": {
                        "plps_seen": [1],
                        "bbframe_packet_count": 4,
                        "filtered_packet_count": 0,
                        "total_packet_count": 60,
                    },
                },
            ),
            (
                "bbframe.recovery_failed",
                {"failure_count": 2, "first_failed_frame_index": 3},
                {"first_failed_frame_index": 3, "failure_count": 2},
            ),
            (
                "biss.descramble_failed",
                {
                    "pid_scope": [256],
                    "failed_indices_sample": [0, 1, 2],
                    "self_check_kind": "cis_mode1",
                    "key_fingerprint_ref": "fp:abc",
                    "mode": "1",
                },
                {"failed_indices_sample": [0, 1, 2], "pid_scope": [256]},
            ),
        ],
    )
    def test_anchored_evidence_records_map_the_locator_verbatim(
        self, event_type, payload, expected_locator
    ):
        evidence = _evidence_of(self._record(event_type, payload, "inner-2"))
        assert evidence is not None
        assert evidence.artifact_id == "inner-2"
        assert evidence.locator == expected_locator
        assert evidence.pid is None and evidence.packet_index is None

    def test_unstamped_evidence_record_produces_no_anchor(self):
        evidence = _evidence_of(
            self._record(
                "bbframe.recovery_failed",
                {"failure_count": 2, "first_failed_frame_index": 3},
                None,
            )
        )
        assert evidence is None  # no anchor, no candidate (SPEC-306 §6)

    def test_mvp_payload_triple_takes_precedence_on_ts_records(self):
        payload = {"artifact_id": "art-1", "pid": 16, "packet_index": 300}
        evidence = _evidence_of(self._record("ts.psi_section_observed", payload, None))
        assert evidence is not None
        assert (evidence.pid, evidence.packet_index) == (16, 300)
        assert evidence.locator is None


class TestDiagnosisEventPhase2Evidence:
    """``diagnosis.*`` payload: the Phase 2 state and the neutral pid."""

    def test_phase2_candidate_publishes_locator_evidence(self):
        document = raised_envelope(
            _phase2_candidate(),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        payload = document["payload"]
        assert payload["evidence"] == {
            "artifact_id": "inner-2",
            "locator": {"first_failed_frame_index": 3, "failure_count": 2},
        }
        # The correlation pid stays the neutral None — never fabricated.
        assert document["correlation"]["pid"] is None
        # And the registry gate accepts the Phase 2 shape.
        validate_payload("diagnosis.raised", payload)

    def test_mvp_candidate_payload_stays_byte_identical(self):
        document = raised_envelope(
            DiagnosisCandidate(
                diagnosis_id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                run_id=RUN_ID,
                rule_id="DIA-PAT-MISSING",
                rule_version="1.0.0",
                code="DIAG_PAT_MISSING",
                priority=10,
                severity=DiagnosisSeverity.ERROR,
                confidence=DiagnosisConfidence.HIGH,
                title="PAT missing in window",
                summary="No PAT observed on PID 0",
                observation_refs=[
                    ObservationRef(journal_seq=42, event_type="ts.psi_section_observed")
                ],
                affected_node_ids=["mux-0"],
                suggested_actions=["Restore PAT emission on PID 0"],
                evidence=_mvp_evidence(),
            ),
            session_id=SESSION_ID,
            source_ns=9_000,
            observed_ns=9_500,
        )
        assert document["payload"]["evidence"] == {
            "artifact_id": "9f2c0000-0000-4000-8000-000000000001",
            "pid": 0,
            "packet_index": 12000,
        }
        assert document["correlation"]["pid"] == 0


class TestRegistryPhase2Evidence:
    """``_require_evidence``: the two states, the mixing refusals."""

    def _raised_with_evidence(self, evidence: dict) -> dict:
        return {
            "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            "rule_id": "DIA-BBHEADER-SYNC-FAULT",
            "rule_version": "1.0.0",
            "code": "DIAG_BBHEADER_SYNC_FAULT",
            "severity": "error",
            "confidence": "medium",
            "title": "BBFRAME header recovery failed",
            "summary": "BBFRAME header recovery failed on 2 frame(s)",
            "observation_refs": [
                {"journal_seq": 7, "event_type": "bbframe.recovery_failed"}
            ],
            "affected_node_ids": [],
            "suggested_actions": ["Inspect the BBHEADER"],
            "evidence": evidence,
        }

    def test_phase2_locator_state_passes(self):
        validate_payload(
            "diagnosis.raised",
            self._raised_with_evidence(
                {
                    "artifact_id": "inner-2",
                    "locator": {"first_failed_frame_index": 3, "failure_count": 2},
                }
            ),
        )

    def test_mvp_triple_state_still_passes(self):
        validate_payload(
            "diagnosis.raised",
            self._raised_with_evidence(
                {"artifact_id": "art-1", "pid": 16, "packet_index": 300}
            ),
        )

    @pytest.mark.parametrize(
        "evidence",
        [
            {"artifact_id": "inner-2", "locator": {}},  # empty locator
            {
                "artifact_id": "inner-2",
                "locator": {"failure_count": 1},
                "pid": 16,
            },  # both states
            {"artifact_id": "inner-2", "pid": 16},  # partial MVP triple
            {"artifact_id": "inner-2"},  # neither state
            {"artifact_id": "inner-2", "locator": None},  # neither state
        ],
    )
    def test_invalid_evidence_states_are_refused(self, evidence):
        from domain.observation.errors import EnvelopeError

        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", self._raised_with_evidence(evidence))
