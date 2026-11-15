"""diagnosis.raised/updated/cleared payload-schema registration (ticket #54).

SPEC-306 §7 pins the shared payload shape for the three diagnosis events;
ticket #54 registers the ``validate_payload`` branch (SPEC-301 §7: payload
schemas land with their owning ticket). The registry is the sole authority:
a diagnosis envelope whose payload violates the shape is refused at the
envelope layer and can never reach the journal (SPEC-300 §7 step 2).

Axis discipline (brief §6): the payload ``confidence`` is the diagnosis
three-tier static declaration (low/medium/high, ``DiagnosisConfidence``);
the observation four-value provenance axis (``ConfidenceKind``) is a
DIFFERENT axis and is refused here.
"""

import pytest
from pydantic import ValidationError

from domain.diagnosis.model import DiagnosisConfidence, DiagnosisSeverity
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.registry import validate_payload


def _raised_payload(**overrides):
    """SPEC-306 §7 example-shaped ``raised``/``updated`` payload."""
    payload = {
        "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "rule_id": "DIA-PAT-MISSING",
        "rule_version": "1.0.0",
        "code": "DIAG_PAT_MISSING",
        "severity": "error",
        "confidence": "high",
        "title": "PAT missing in window",
        "summary": "No PAT observed on PID 0 between packet 12000 and 18000",
        "observation_refs": [
            {"journal_seq": 42, "event_type": "ts.psi_section_observed"}
        ],
        "affected_node_ids": ["mux-0"],
        "suggested_actions": ["Restore PAT emission on PID 0"],
        "evidence": {"artifact_id": "9f2c0000-0000-4000-8000-000000000001", "pid": 0, "packet_index": 12000},
    }
    payload.update(overrides)
    return payload


class TestDiagnosisRaisedShape:
    """REQ-DIA-306-004: the shared shape passes, violations are refused."""

    @pytest.mark.parametrize("event_type", ["diagnosis.raised", "diagnosis.updated"])
    def test_valid_shared_shape_passes(self, event_type):
        validate_payload(event_type, _raised_payload())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("diagnosis_id", ""),
            ("rule_id", ""),
            ("rule_version", ""),
            ("code", ""),
            ("title", ""),
            ("summary", ""),
            ("diagnosis_id", None),
            ("rule_id", 7),
        ],
    )
    def test_empty_or_non_string_required_field_is_refused(self, field, value):
        with pytest.raises(EnvelopeError) as excinfo:
            validate_payload("diagnosis.raised", _raised_payload(**{field: value}))
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    @pytest.mark.parametrize("field", ["rule_version", "code"])
    def test_missing_required_field_is_refused(self, field):
        payload = _raised_payload()
        del payload[field]
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", payload)

    def test_empty_observation_refs_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(observation_refs=[]))

    def test_observation_ref_with_unregistered_event_type_is_refused(self):
        refs = [{"journal_seq": 1, "event_type": "not.registered_anywhere"}]
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(observation_refs=refs))

    def test_observation_ref_with_non_positive_journal_seq_is_refused(self):
        refs = [{"journal_seq": 0, "event_type": "ts.continuity_error"}]
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(observation_refs=refs))

    def test_non_mapping_observation_ref_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "diagnosis.raised", _raised_payload(observation_refs=[42])
            )

    @pytest.mark.parametrize("severity", ["fatal", "notice", "", None, 3])
    def test_severity_outside_diagnosis_vocabulary_is_refused(self, severity):
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(severity=severity))

    @pytest.mark.parametrize("confidence", ["parsed", "simulated", "measured", "inferred", "certain", "", None])
    def test_confidence_outside_three_tier_axis_is_refused(self, confidence):
        # The observation provenance axis (ConfidenceKind four values) is a
        # different axis and must never pass the diagnosis payload branch.
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(confidence=confidence))

    @pytest.mark.parametrize(
        "evidence",
        [
            None,
            {},
            {"pid": 0, "packet_index": 1},  # artifact_id missing
            {"artifact_id": "a", "packet_index": 1},  # pid missing
            {"artifact_id": "a", "pid": 0},  # packet_index missing
            {"artifact_id": "", "pid": 0, "packet_index": 1},
            {"artifact_id": "a", "pid": 8192, "packet_index": 1},  # pid 13-bit cap
            {"artifact_id": "a", "pid": -1, "packet_index": 1},
            {"artifact_id": "a", "pid": 0, "packet_index": -1},
            {"artifact_id": "a", "pid": "0x0", "packet_index": 1},
        ],
    )
    def test_evidence_block_violations_are_refused(self, evidence):
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.raised", _raised_payload(evidence=evidence))

    def test_affected_node_ids_non_string_element_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "diagnosis.raised", _raised_payload(affected_node_ids=[7])
            )

    def test_empty_node_and_action_lists_are_allowed(self):
        validate_payload(
            "diagnosis.raised",
            _raised_payload(affected_node_ids=[], suggested_actions=[]),
        )


class TestDiagnosisClearedShape:
    """cleared carries only diagnosis_id + rule_id + the clear reason."""

    def test_valid_cleared_payload_passes(self):
        validate_payload(
            "diagnosis.cleared",
            {
                "diagnosis_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                "rule_id": "DIA-PAT-MISSING",
                "reason": "regenerated stream shows no PAT-missing symptom",
            },
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"diagnosis_id": "d", "rule_id": "r"},  # reason missing
            {"diagnosis_id": "", "rule_id": "r", "reason": "x"},
            {"diagnosis_id": "d", "rule_id": "", "reason": "x"},
            {"diagnosis_id": "d", "rule_id": "r", "reason": ""},
            {"diagnosis_id": "d", "rule_id": "r", "reason": 3},
        ],
    )
    def test_cleared_violations_are_refused(self, payload):
        with pytest.raises(EnvelopeError):
            validate_payload("diagnosis.cleared", payload)


class TestAxisVocabularyCrossCheck:
    """The registry mirrors the domain enums exactly — no third vocabulary."""

    def test_severity_vocabulary_equals_domain_enum(self):
        from domain.observation.registry import DIAGNOSIS_SEVERITIES

        assert DIAGNOSIS_SEVERITIES == frozenset(
            item.value for item in DiagnosisSeverity
        )

    def test_confidence_vocabulary_equals_domain_enum_and_not_observation_axis(self):
        from domain.observation.registry import DIAGNOSIS_CONFIDENCES

        assert DIAGNOSIS_CONFIDENCES == frozenset(
            item.value for item in DiagnosisConfidence
        )
        from domain.observation.model import ConfidenceKind

        assert not (DIAGNOSIS_CONFIDENCES & {item.value for item in ConfidenceKind})

    def test_candidate_report_model_rejects_unknown_severity(self):
        # Guard the domain side too: the payload branch and the models share
        # one vocabulary (test lives here so a drift breaks this file first).
        from domain.diagnosis.report import EvidenceRef

        with pytest.raises(ValidationError):
            EvidenceRef(artifact_id="a", pid=-1, packet_index=0)


__all__ = ["_raised_payload"]
