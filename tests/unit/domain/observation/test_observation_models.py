"""Observation model tests (SPEC-003 section 2.4 incl. ticket #13 Q3-i pointer).

Seam: public construction/validation surface of ``domain.observation``
(Observation) plus the two closed-set vocabularies ``ObservationSource``
(six values since SPEC-003 §Phase3 — #160 adds ``state_evaluator``) and
``ConfidenceKind`` (four values). Expected literals come from SPEC-003
section 2.4 text.
"""

import pytest
from pydantic import ValidationError

from domain.observation import ConfidenceKind, Observation, ObservationSource


def _observation(**overrides) -> Observation:
    fields = {
        "observation_id": "obs-001",
        "run_id": "3b241101-e2bb-4255-8caf-4136c566a962",
        "source": "tsduck",
        "confidence": "parsed",
        "type": "continuity_error",
        "observed_at_utc_ms": 1_700_000_000_000,
    }
    fields.update(overrides)
    return Observation(**fields)


class TestEnumClosedSets:
    def test_observation_source_has_exactly_the_six_spec_sources(self):
        # SPEC-003 §Phase3 (ticket #160): five → six values, the L0
        # evaluation product source joins the closed set (always paired
        # with ``simulated`` confidence; never parsed/measured).
        assert {member.value for member in ObservationSource} == {
            "generator",
            "internal_parser",
            "tsduck",
            "hardware",
            "rule_engine",
            "state_evaluator",
        }

    def test_state_evaluator_member_value(self):
        assert ObservationSource.STATE_EVALUATOR.value == "state_evaluator"

    def test_confidence_kind_has_exactly_the_four_spec_kinds(self):
        assert {member.value for member in ConfidenceKind} == {
            "simulated",
            "parsed",
            "measured",
            "inferred",
        }


class TestObservation:
    def test_valid_construction_required_fields_only(self):
        obs = _observation()
        assert obs.source is ObservationSource.TSDUCK
        assert obs.confidence is ConfidenceKind.PARSED
        assert obs.simulation_time_ticks is None
        assert obs.pid is None
        assert obs.packet_index is None
        assert obs.value is None
        assert obs.unit is None
        assert obs.artifact_id is None
        assert obs.evidence_refs is None

    def test_valid_construction_full_payload(self):
        obs = _observation(
            simulation_time_ticks=90_000,
            pid=0,
            packet_index=128,
            value={"cc_delta": 1},
            unit="packets",
            artifact_id="aa11bb33-9c2b-4f3e-9c2b-7a1d5e0f3a44",
            evidence_refs=["art:aa11bb33", "evt:42"],
        )
        assert obs.pid == 0
        assert obs.value == {"cc_delta": 1}
        assert obs.evidence_refs == ["art:aa11bb33", "evt:42"]

    def test_round_trip(self):
        obs = _observation(pid=100, packet_index=5, value=12.5, unit="dB")
        assert Observation.model_validate(obs.model_dump()) == obs

    def test_value_accepts_arbitrary_payload_shapes(self):
        assert _observation(value=None).value is None
        assert _observation(value="sync-byte").value == "sync-byte"
        assert _observation(value=[1, 2, 3]).value == [1, 2, 3]

    def test_invalid_source_rejected_at_source_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _observation(source="spreadsheet")
        assert excinfo.value.errors()[0]["loc"] == ("source",)

    def test_invalid_confidence_rejected_at_confidence_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _observation(confidence="high")
        assert excinfo.value.errors()[0]["loc"] == ("confidence",)

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            Observation(
                observation_id="obs-001",
                run_id="3b241101-e2bb-4255-8caf-4136c566a962",
                source="tsduck",
                confidence="parsed",
                type="continuity_error",
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("observed_at_utc_ms",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _observation(measured=True)
        assert excinfo.value.errors()[0]["loc"] == ("measured",)

    def test_frozen_model_rejects_assignment(self):
        obs = _observation()
        with pytest.raises(ValidationError):
            obs.confidence = ConfidenceKind.MEASURED
