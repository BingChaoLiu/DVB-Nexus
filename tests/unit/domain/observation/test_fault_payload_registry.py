"""fault.* payload-schema registration (ticket #56, 裁定 2).

SPEC-204 §9 pins the payload obligations ("payload 携带 fault_id /
fault_type / 注入 index / before-after 摘要指针"); ticket #56 registers
the ``validate_payload`` branch (SPEC-301 §7: payload schemas land with
their owning ticket). The registry is the sole authority: a fault envelope
whose payload violates the shape is refused at the envelope layer and can
never reach the journal (SPEC-300 §7 step 2).

Registered obligations (SPEC-204 §9 literal reading):

- every ``fault.*`` payload: ``fault_id`` / ``fault_type`` (identity) and
  ``injection_index`` (the activation index on the shared packet frame —
  the atomic-boundary precision of ADR-0007 item 4);
- ``fault.injected`` carries ``expected_observations`` (non-empty — the
  prepare stage guarantees it, SPEC-204 §11 SIM_FAULT_EXPECTED_OBS_MISSING);
- ``fault.applied`` (L1 only) carries ``applied_packet_indexes`` (the
  slots where faulted bytes confirmed in the flow, SPEC-204 §8.1);
- ``mutation_log_ref`` (the before-after summary pointer to the §8.2
  mutation-log record) and ``cleared_reason`` are optional — missing /
  unknown / not-applicable stay distinguishable (SPEC-301 §3 payload
  three-state discipline).

The fault family is structural evidence, NOT observation: no
``source``/``confidence`` axes are demanded here (brief §6 — the engine
lifecycle events carry no provenance axis; mixing them in would be the
混标 violation).
"""

import pytest

from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.registry import validate_payload

FAULT_EVENT_TYPES = (
    "fault.injected",
    "fault.activated",
    "fault.applied",
    "fault.cleared",
)


def _base_payload(**overrides):
    """The minimal conforming payload shared by all four fault events."""
    payload = {
        "fault_id": "fd000000-0000-4000-8000-000000000001",
        "fault_type": "CC_DISCONTINUITY",
        "injection_index": 50,
    }
    payload.update(overrides)
    return payload


def _injected_payload(**overrides):
    payload = _base_payload(
        expected_observations=["ts.continuity_error"],
        mutation_log_ref="mutation-log:fd000000-0000-4000-8000-000000000001",
    )
    payload.update(overrides)
    return payload


def _event_payload(event_type, **overrides):
    """Event-appropriate conforming payload (injected/applied carry more)."""
    if event_type == "fault.injected":
        return _injected_payload(**overrides)
    if event_type == "fault.applied":
        payload = _base_payload(
            applied_packet_indexes=[50],
            mutation_log_ref="mutation-log:fd000000#50",
        )
        payload.update(overrides)
        return payload
    return _base_payload(**overrides)


class TestFaultFamilyShape:
    """Every fault.* event validates the shared identity/index shape."""

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    def test_minimal_shared_shape_passes(self, event_type):
        validate_payload(event_type, _event_payload(event_type))

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("fault_id", ""),
            ("fault_id", None),
            ("fault_id", 7),
            ("fault_type", ""),
            ("fault_type", None),
        ],
    )
    def test_empty_or_non_string_identity_is_refused(
        self, event_type, field, value
    ):
        with pytest.raises(EnvelopeError) as excinfo:
            validate_payload(
                event_type, _base_payload(**{field: value})
            )
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    def test_missing_fault_id_is_refused(self, event_type):
        payload = _base_payload()
        del payload["fault_id"]
        with pytest.raises(EnvelopeError):
            validate_payload(event_type, payload)

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    @pytest.mark.parametrize("index", [-1, "50", None, True, 1.5])
    def test_non_natural_injection_index_is_refused(self, event_type, index):
        with pytest.raises(EnvelopeError):
            validate_payload(
                event_type, _base_payload(injection_index=index)
            )

    def test_injection_index_zero_is_the_session_start_anchor(self):
        # session_start activation = window opens at shared-frame index 0
        # (ADR-0007 item 3) — 0 is a legal, meaningful index.
        validate_payload("fault.activated", _base_payload(injection_index=0))

    def test_non_mapping_payload_is_refused(self):
        with pytest.raises(EnvelopeError):
            validate_payload("fault.injected", ["not", "a", "mapping"])


class TestInjectedShape:
    """fault.injected = SCHEDULED: carries the prepare declaration."""

    def test_injected_with_expected_observations_passes(self):
        validate_payload("fault.injected", _injected_payload())

    def test_injected_requires_expected_observations(self):
        with pytest.raises(EnvelopeError) as excinfo:
            validate_payload("fault.injected", _base_payload())
        assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_injected_expected_observations_must_be_non_empty_strings(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "fault.injected",
                _injected_payload(expected_observations=[]),
            )
        with pytest.raises(EnvelopeError):
            validate_payload(
                "fault.injected",
                _injected_payload(expected_observations=["ok", ""]),
            )

    @pytest.mark.parametrize("event_type", ["fault.activated", "fault.cleared"])
    def test_other_family_members_do_not_demand_expected_observations(
        self, event_type
    ):
        # The obligation is injected-specific (SPEC-204 §11 prepare rule);
        # the other events stay valid without it.
        validate_payload(event_type, _base_payload())


class TestAppliedShape:
    """fault.applied = APPLIED (L1 only): the confirmed-slot index list."""

    def test_applied_with_confirmed_slots_passes(self):
        validate_payload(
            "fault.applied",
            _base_payload(
                applied_packet_indexes=[50, 63],
                mutation_log_ref="mutation-log:fd000000#50",
            ),
        )

    def test_applied_requires_confirmed_slots(self):
        with pytest.raises(EnvelopeError):
            validate_payload("fault.applied", _base_payload())

    def test_applied_empty_slot_list_is_refused(self):
        # APPLIED confirms fault bytes in the flow — an empty list would
        # assert a confirmation with no confirmation (SPEC-204 §8.1).
        with pytest.raises(EnvelopeError):
            validate_payload(
                "fault.applied", _base_payload(applied_packet_indexes=[])
            )

    def test_applied_slot_indexes_must_be_natural(self):
        with pytest.raises(EnvelopeError):
            validate_payload(
                "fault.applied",
                _base_payload(applied_packet_indexes=[50, -1]),
            )


class TestOptionalPointers:
    """mutation_log_ref / cleared_reason: optional, typed when present.

    Three states stay distinguishable (SPEC-301 §3): key absent = unknown,
    explicit ``null`` = not applicable, a string value = the pointer.
    """

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    def test_mutation_log_ref_optional_everywhere(self, event_type):
        validate_payload(event_type, _event_payload(event_type))

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    def test_mutation_log_ref_null_is_not_applicable(self, event_type):
        validate_payload(
            event_type, _event_payload(event_type, mutation_log_ref=None)
        )

    @pytest.mark.parametrize("event_type", FAULT_EVENT_TYPES)
    @pytest.mark.parametrize("value", ["", 42])
    def test_malformed_mutation_log_ref_is_refused(self, event_type, value):
        with pytest.raises(EnvelopeError):
            validate_payload(
                event_type, _event_payload(event_type, mutation_log_ref=value)
            )

    def test_cleared_reason_when_present_must_be_non_empty_string(self):
        validate_payload(
            "fault.cleared", _base_payload(cleared_reason="run_end")
        )
        with pytest.raises(EnvelopeError):
            validate_payload(
                "fault.cleared", _base_payload(cleared_reason="")
            )


class TestNoObservationAxes:
    """Structural evidence carries NO provenance axis (brief §6 混标禁令).

    A payload that *adds* source/confidence still passes (additive payload
    evolution, SPEC-301 §8) — but the branch never DEMANDS the axes: a
    minimal fault envelope without them is valid, which is what keeps the
    engine lifecycle events from being silently reshaped into observations.
    """

    def test_minimal_payload_without_axes_is_valid(self):
        payload = _base_payload()
        assert "source" not in payload
        assert "confidence" not in payload
        validate_payload("fault.activated", {**payload})
