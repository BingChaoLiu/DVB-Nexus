"""Diagnosis model tests (SPEC-003 section 2.6, ticket #13 Q3-ii).

Seam: public construction/validation surface of ``domain.diagnosis``
(Diagnosis), the severity closed set, the three-tier ``DiagnosisConfidence``
enum, and the two-axes separation between rule confidence and observation
confidence. Expected literals come from SPEC-003 section 2.6 text and the
#13 ruling.
"""

import pytest
from pydantic import ValidationError

from domain.diagnosis import Diagnosis, DiagnosisConfidence, DiagnosisSeverity
from domain.observation import ConfidenceKind


def _diagnosis(**overrides) -> Diagnosis:
    fields = {
        "diagnosis_id": "diag-001",
        "run_id": "3b241101-e2bb-4255-8caf-4136c566a962",
        "rule_id": "rule-cc-discontinuity",
        "code": "CC_DISCONTINUITY_DETECTED",
        "severity": "error",
        "title": "Continuity counter discontinuity",
        "summary": "CC jumped by 2 on PID 100 between packets 128 and 129.",
        "confidence": "high",
        "observation_ids": ["obs-001", "obs-002"],
        "created_at_utc_ms": 1_700_000_000_000,
    }
    fields.update(overrides)
    return Diagnosis(**fields)


class TestEnumClosedSets:
    def test_severity_has_exactly_the_four_spec_values(self):
        assert {member.value for member in DiagnosisSeverity} == {
            "info",
            "warning",
            "error",
            "critical",
        }

    def test_confidence_is_exactly_the_three_tier_enum(self):
        # Ticket #13 Q3-ii: number -> enum, static three-tier declaration
        # low/medium/high declared by the rule definition, engine computes no
        # continuous score.
        assert {member.value for member in DiagnosisConfidence} == {
            "low",
            "medium",
            "high",
        }


class TestTwoAxesSeparation:
    def test_diagnosis_confidence_and_observation_confidence_kind_are_disjoint(self):
        # The rule-confidence axis (low/medium/high) and the observation
        # provenance axis (simulated/parsed/measured/inferred) are two
        # different axes; sharing a single value would conflate them.
        diagnosis_axis = {member.value for member in DiagnosisConfidence}
        observation_axis = {member.value for member in ConfidenceKind}
        assert diagnosis_axis.isdisjoint(observation_axis)


class TestDiagnosis:
    def test_valid_construction_required_fields_only(self):
        diag = _diagnosis()
        assert diag.severity is DiagnosisSeverity.ERROR
        assert diag.confidence is DiagnosisConfidence.HIGH
        assert diag.affected_node_ids is None
        assert diag.suggested_actions is None

    def test_valid_construction_with_optionals(self):
        diag = _diagnosis(
            affected_node_ids=["demux-0", "stb-0"],
            suggested_actions=["re-check PAT CRC", "regenerate baseline"],
        )
        assert diag.affected_node_ids == ["demux-0", "stb-0"]
        assert diag.suggested_actions == ["re-check PAT CRC", "regenerate baseline"]

    def test_round_trip(self):
        diag = _diagnosis(affected_node_ids=["demux-0"])
        assert Diagnosis.model_validate(diag.model_dump()) == diag

    def test_numeric_confidence_rejected_must_be_enum_not_score(self):
        # The pre-#13 shape (continuous score) must not validate anymore.
        with pytest.raises(ValidationError) as excinfo:
            _diagnosis(confidence=0.9)
        assert excinfo.value.errors()[0]["loc"][:1] == ("confidence",)

    def test_invalid_severity_rejected_at_severity_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _diagnosis(severity="fatal")
        assert excinfo.value.errors()[0]["loc"] == ("severity",)

    def test_empty_observation_ids_list_accepted_not_dictionary_of_semantics(self):
        diag = _diagnosis(observation_ids=[])
        assert diag.observation_ids == []

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            Diagnosis(
                diagnosis_id="diag-001",
                run_id="3b241101-e2bb-4255-8caf-4136c566a962",
                rule_id="rule-cc-discontinuity",
                code="CC_DISCONTINUITY_DETECTED",
                severity="error",
                title="Continuity counter discontinuity",
                summary="CC jumped by 2 on PID 100.",
                confidence="high",
                created_at_utc_ms=1_700_000_000_000,
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("observation_ids",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _diagnosis(probability=0.93)
        assert excinfo.value.errors()[0]["loc"] == ("probability",)

    def test_frozen_model_rejects_assignment(self):
        diag = _diagnosis()
        with pytest.raises(ValidationError):
            diag.confidence = DiagnosisConfidence.LOW
