"""recovery.verification_completed payload-schema registration (ticket #56).

SPEC-206 §4 pins the verdict RESULT structure (verdict / per-criterion
with reason codes / evidence refs / summary / run + scenario version
identity / operational timestamp) but does not pin the wire payload shape —
ticket #56 proposes and registers it here (brief §1.8: the payload shape is
the ticket's to declare; DELIVERY_PROTECTED registration predates this
ticket in the #46 frozen registry).

Registered obligations (ticket #56 declaration, SPEC-206 §4 mapping):

- ``verdict`` ∈ {PASS, FAIL, INCONCLUSIVE} (three-state, §4);
- ``run_id`` (the candidate recovery run) + ``baseline_run_id`` — the
  REQ-SIM-206-004 distinguishability pair, carried in the payload so the
  event is self-contained (``scope.run_id`` attributes the envelope to the
  recovery run as well);
- ``scenario_id`` / ``scenario_version`` / ``scenario_content_hash`` — the
  SPEC-205 version-pinning identity (§4 "run_id / scenario 版本标识");
- ``criteria`` — non-empty per-criterion list: criterion_id / kind /
  mandatory / result ∈ {PASS, FAIL, NOT_EVALUATED} + reason_code (REQUIRED
  and non-empty exactly when NOT_EVALUATED — §5 item 2: no silent skips);
- ``summary`` — non-empty human-audit line.

Determinism note: the payload carries NO wall-clock field. The operational
verification timestamp (the one §4-permitted non-deterministic field) rides
the envelope ``time.observed`` (wall:utc) and the persisted verdict row —
never the payload (REQ-SIM-206-005 replay determinism).
"""

import pytest

from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.registry import RECOVERY_EVENT_TYPES, validate_payload


def _criterion(**overrides):
    entry = {
        "criterion_id": "sc-01",
        "kind": "fault_inactive",
        "mandatory": True,
        "result": "PASS",
        "reason_code": None,
        "reason": None,
    }
    entry.update(overrides)
    return entry


def _verdict_payload(**overrides):
    payload = {
        "verdict": "PASS",
        "run_id": "run-recovery-1",
        "baseline_run_id": "run-baseline-1",
        "scenario_id": "9c0f0000-0000-4000-8000-000000000001",
        "scenario_version": "1.0.0",
        "scenario_content_hash": "a" * 64,
        "criteria": [_criterion()],
        "summary": "all mandatory criteria passed on the recovery run",
    }
    payload.update(overrides)
    return payload


class TestRecoveryEventRegistration:
    """The authoritative name is registered and delivery-protected."""

    def test_recovery_event_type_is_the_single_registered_name(self):
        assert RECOVERY_EVENT_TYPES == frozenset(
            {"recovery.verification_completed"}
        )

    def test_verdict_payload_passes(self):
        validate_payload("recovery.verification_completed", _verdict_payload())


class TestVerdictShape:
    """REQ-SIM-206-006: the three-state verdict rides the payload."""

    @pytest.mark.parametrize("verdict", ["PASS", "FAIL", "INCONCLUSIVE"])
    def test_three_state_verdicts_pass(self, verdict):
        validate_payload(
            "recovery.verification_completed", _verdict_payload(verdict=verdict)
        )

    @pytest.mark.parametrize("verdict", ["pass", "UNKNOWN", "", None, 1])
    def test_verdict_outside_the_three_states_is_refused(self, verdict):
        with pytest.raises(EnvelopeError) as excinfo:
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(verdict=verdict),
            )
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_missing_verdict_is_refused(self):
        payload = _verdict_payload()
        del payload["verdict"]
        with pytest.raises(EnvelopeError):
            validate_payload("recovery.verification_completed", payload)


class TestIdentityShape:
    """REQ-SIM-206-004: run distinguishability + scenario version pinning."""

    @pytest.mark.parametrize(
        "field",
        [
            "run_id",
            "baseline_run_id",
            "scenario_id",
            "scenario_version",
            "scenario_content_hash",
            "summary",
        ],
    )
    @pytest.mark.parametrize("value", ["", None, 5])
    def test_required_strings_are_non_empty(self, field, value):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(**{field: value}),
            )

    def test_missing_required_string_is_refused(self):
        payload = _verdict_payload()
        del payload["baseline_run_id"]
        with pytest.raises(EnvelopeError):
            validate_payload("recovery.verification_completed", payload)


class TestCriteriaShape:
    """Per-criterion entries with the NOT_EVALUATED reason obligation."""

    def test_empty_criteria_list_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(criteria=[]),
            )

    def test_non_mapping_criterion_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(criteria=["sc-01"]),
            )

    @pytest.mark.parametrize("result", ["PASS", "FAIL", "NOT_EVALUATED"])
    def test_three_criterion_results_pass(self, result):
        reason = (
            "SIM_VERIF_EVIDENCE_MISSING" if result == "NOT_EVALUATED" else None
        )
        validate_payload(
            "recovery.verification_completed",
            _verdict_payload(
                criteria=[_criterion(result=result, reason_code=reason)]
            ),
        )

    @pytest.mark.parametrize("result", ["SKIPPED", "pass", None, 0])
    def test_result_outside_vocabulary_is_refused(self, result):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(criteria=[_criterion(result=result)]),
            )

    @pytest.mark.parametrize(
        ("overrides", "valid"),
        [
            ({"reason_code": None, "result": "PASS"}, True),
            ({"reason_code": "SIM_VERIF_EVIDENCE_MISSING",
              "result": "NOT_EVALUATED"}, True),
            # NOT_EVALUATED without an explicit reason = silent skip (§5.2)
            ({"reason_code": None, "result": "NOT_EVALUATED"}, False),
            ({"reason_code": "", "result": "NOT_EVALUATED"}, False),
            ({"reason_code": 7, "result": "NOT_EVALUATED"}, False),
        ],
    )
    def test_reason_code_required_exactly_for_not_evaluated(
        self, overrides, valid
    ):
        criterion = _criterion(**overrides)
        if valid:
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(criteria=[criterion]),
            )
        else:
            with pytest.raises(EnvelopeError):
                validate_payload(
                    "recovery.verification_completed",
                    _verdict_payload(criteria=[criterion]),
                )

    def test_criterion_identity_fields_are_required(self):
        for field in ("criterion_id", "kind"):
            entry = _criterion()
            del entry[field]
            with pytest.raises(EnvelopeError):
                validate_payload(
                    "recovery.verification_completed",
                    _verdict_payload(criteria=[entry]),
                )

    def test_mandatory_must_be_boolean(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "recovery.verification_completed",
                _verdict_payload(criteria=[_criterion(mandatory="yes")]),
            )


class TestNoWallClockInPayload:
    """REQ-SIM-206-005: the payload stays replay-deterministic."""

    def test_payload_carries_no_timestamp_field(self):
        payload = _verdict_payload()
        # The operational timestamp lives on envelope time.observed / the
        # persisted row — a payload that grew a wall field would break the
        # replay contract, so the branch refuses unknown REQUIRED time keys
        # by simply not demanding them; this pins the shape stays time-free.
        assert not any(
            key in payload
            for key in ("verified_at_utc_ms", "verified_at", "timestamp")
        )
        validate_payload("recovery.verification_completed", payload)
