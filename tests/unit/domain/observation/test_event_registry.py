"""SPEC-301 section 4 event type registry — the authoritative type list.

Registry tests verify the #12 registry restructure item-by-item (ADR-0006
decision 5): fault four-events-for-four-states, run_* family present,
snapshot.updated withdrawn, lifecycle.changed abolished, observation.*
namespace empty in MVP, diagnosis family admitted, authoritative
recovery.verification_completed naming.
"""

import pytest

from domain.observation.errors import EnvelopeErrorCode, EnvelopeError
from domain.observation.registry import (
    DELIVERY_PROTECTED_EVENT_TYPES,
    FAULT_EVENT_TYPES,
    REGISTERED_EVENT_TYPES,
    WITHDRAWN_EVENT_TYPES,
    is_coalescable,
    is_delivery_protected,
    is_registered,
    is_withdrawn,
    validate_event_type,
    validate_payload,
)
from domain.observation.model import ConfidenceKind, ObservationSource

SIMULATION_SESSION_EVENTS = frozenset(
    {
        "simulation.session_created",
        "simulation.session_started",
        "simulation.session_paused",
        "simulation.session_resumed",
        "simulation.session_stopped",
    }
)

SIMULATION_RUN_EVENTS = frozenset(
    {
        "simulation.run_started",
        "simulation.run_progress",
        "simulation.run_completed",
        "simulation.run_failed",
    }
)

SIMULATION_CLOCK_EVENTS = frozenset({"simulation.clock_advanced"})

TOPOLOGY_EVENTS = frozenset({"topology.state_changed"})

TS_EVENTS = frozenset(
    {
        "ts.packet_batch_observed",
        "ts.continuity_error",
        "ts.pcr_jitter_observed",
        "ts.psi_section_observed",
        "ts.service_state_changed",
    }
)

FAULT_EVENTS = frozenset(
    {
        "fault.injected",
        "fault.activated",
        "fault.applied",
        "fault.cleared",
    }
)

SCENARIO_EVENTS = frozenset(
    {"scenario.step_started", "scenario.step_completed"}
)

RECOVERY_EVENTS = frozenset({"recovery.verification_completed"})

DIAGNOSIS_EVENTS = frozenset(
    {"diagnosis.raised", "diagnosis.updated", "diagnosis.cleared"}
)

EXPECTED_REGISTERED = (
    SIMULATION_SESSION_EVENTS
    | SIMULATION_RUN_EVENTS
    | SIMULATION_CLOCK_EVENTS
    | TOPOLOGY_EVENTS
    | TS_EVENTS
    | FAULT_EVENTS
    | SCENARIO_EVENTS
    | RECOVERY_EVENTS
    | DIAGNOSIS_EVENTS
)


class TestAuthoritativeRegistry:
    """SPEC-301 section 4 / ADR-0006 decision 5, #12 restructure items."""

    def test_registry_equals_spec_301_section_4_exactly(self):
        # The registry is the unique legal event type list (REQ-OBS-301-006):
        # exact set equality, no extras, no omissions.
        assert REGISTERED_EVENT_TYPES == EXPECTED_REGISTERED

    def test_fault_family_is_four_events_for_four_states(self):
        # ADR-0006 decision 5: SCHEDULED->ACTIVE->APPLIED->REMOVED maps to
        # fault.injected -> fault.activated -> fault.applied -> fault.cleared.
        assert FAULT_EVENT_TYPES == frozenset(
            {
                "fault.injected",  # SCHEDULED (prepare validated)
                "fault.activated",  # ACTIVE (window start)
                "fault.applied",  # APPLIED (L1: faulted bytes in output stream)
                "fault.cleared",  # REMOVED (window end or run end)
            }
        )

    def test_run_family_present(self):
        # ADR-0006 decision 5: run_* family admitted (Party C had only session_*).
        assert SIMULATION_RUN_EVENTS <= REGISTERED_EVENT_TYPES

    def test_withdrawn_types_are_not_registered(self):
        # snapshot.updated: pulled out of the event stream (pull API with
        # journal_seq cursor, SPEC-200 section 4); lifecycle.changed:
        # abolished (session state -> session_*, run state -> run_*).
        assert "snapshot.updated" in WITHDRAWN_EVENT_TYPES
        assert "lifecycle.changed" in WITHDRAWN_EVENT_TYPES
        assert is_withdrawn("snapshot.updated")
        assert is_withdrawn("lifecycle.changed")
        assert WITHDRAWN_EVENT_TYPES.isdisjoint(REGISTERED_EVENT_TYPES)

    def test_observation_namespace_is_empty_in_mvp(self):
        # #12 ruling 3: zero observation.* envelope events in MVP; alert
        # lifecycle authority is the alert record (SPEC-304), notified via
        # SPEC-305 WS + REST. The whole namespace is refused.
        assert is_withdrawn("observation.alert_raised")
        assert is_withdrawn("observation.alert_updated")
        assert is_withdrawn("observation.alert_cleared")
        assert not any(
            event_type.startswith("observation.")
            for event_type in REGISTERED_EVENT_TYPES
        )

    def test_diagnosis_family_registered(self):
        # ADR-0006 decision 5 renaming: diagnosis.* (SPEC-306/307), payload
        # schema per #13 — never observation.*.
        assert DIAGNOSIS_EVENTS <= REGISTERED_EVENT_TYPES

    def test_authoritative_recovery_verification_name(self):
        # Party B "verification.completed" abolished; authoritative name is
        # recovery.verification_completed.
        assert "recovery.verification_completed" in REGISTERED_EVENT_TYPES
        assert "verification.completed" not in REGISTERED_EVENT_TYPES
        assert "verification.completed" in WITHDRAWN_EVENT_TYPES


class TestTypeValidation:
    """SPEC-301 section 10 negative: unregistered and withdrawn refused."""

    @pytest.mark.parametrize(
        "event_type", sorted(EXPECTED_REGISTERED), ids=str
    )
    def test_registered_types_validate(self, event_type):
        assert is_registered(event_type)
        validate_event_type(event_type)  # must not raise

    def test_unregistered_type_refused(self):
        # Well-formed dotted lowercase, but not in the registry.
        with pytest.raises(EnvelopeError) as exc:
            validate_event_type("packet.viz.stream")
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    @pytest.mark.parametrize(
        "event_type",
        ["snapshot.updated", "lifecycle.changed", "verification.completed"],
        ids=str,
    )
    def test_withdrawn_type_refused(self, event_type):
        with pytest.raises(EnvelopeError) as exc:
            validate_event_type(event_type)
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    @pytest.mark.parametrize(
        "event_type",
        [
            "observation.alert_raised",
            "observation.anything",
            "session_created",  # not dotted
            "Simulation.Run_Started",  # uppercase
            "simulation.run_started.",  # trailing dot
            "",
        ],
        ids=str,
    )
    def test_malformed_or_reserved_namespace_refused(self, event_type):
        with pytest.raises(EnvelopeError):
            validate_event_type(event_type)


class TestDeliveryPolicy:
    """SPEC-301 section 5: coalescable vs never-silently-dropped."""

    def test_run_progress_is_the_only_coalescable_event(self):
        assert is_coalescable("simulation.run_progress")
        coalescable = {
            event_type
            for event_type in REGISTERED_EVENT_TYPES
            if is_coalescable(event_type)
        }
        assert coalescable == {"simulation.run_progress"}

    def test_delivery_protected_set(self):
        # fault.* family + session_* family + terminal runs + verification:
        # forbidden to silently drop (backpressure graft, ADR-0006 decision 1).
        expected = (
            FAULT_EVENTS
            | SIMULATION_SESSION_EVENTS
            | {"simulation.run_completed", "simulation.run_failed"}
            | RECOVERY_EVENTS
        )
        assert DELIVERY_PROTECTED_EVENT_TYPES == expected
        assert is_delivery_protected("fault.injected")
        assert is_delivery_protected("simulation.session_paused")
        assert is_delivery_protected("recovery.verification_completed")
        assert not is_delivery_protected("simulation.run_progress")
        assert not is_delivery_protected("ts.continuity_error")


class TestTsPayloadContract:
    """#13 Q3-i: observation-flavoured ts.* payloads carry source/confidence.

    Loose envelope, tight payload (ADR-0006 decision 4): the envelope stays
    untouched; the payload schema per event type enforces the two axes from
    SPEC-003 section 2.4 (ObservationSource / ConfidenceKind) — never the
    diagnosis three-level confidence axis.
    """

    @pytest.mark.parametrize("event_type", sorted(TS_EVENTS), ids=str)
    def test_ts_payload_requires_both_axes(self, event_type):
        payload = {"value": 1}
        with pytest.raises(EnvelopeError) as exc:
            validate_payload(event_type, payload)
        assert exc.value.code is EnvelopeErrorCode.OBS_INVALID_ENVELOPE

    def test_ts_payload_rejects_illegal_source_value(self):
        # Source/confidence mixing bans are producer disciplines (SPEC-003
        # section 2.4), but the vocabulary itself is closed: an unknown
        # source value is refused.
        with pytest.raises(EnvelopeError):
            validate_payload(
                "ts.continuity_error",
                {"source": "guesswork", "confidence": "parsed"},
            )

    def test_ts_payload_rejects_diagnosis_confidence_axis(self):
        # low/medium/high belong to the diagnosis rule axis (SPEC-307), not here.
        with pytest.raises(EnvelopeError):
            validate_payload(
                "ts.continuity_error",
                {"source": "internal_parser", "confidence": "high"},
            )

    def test_ts_payload_accepts_declared_vocabulary(self):
        payload = {
            "source": ObservationSource.INTERNAL_PARSER.value,
            "confidence": ConfidenceKind.PARSED.value,
        }
        validate_payload("ts.continuity_error", payload)  # must not raise

    def test_still_schemaless_registered_payload_has_no_extra_constraint(self):
        # MVP payload schemas beyond ts.*/diagnosis.*/fault.*/recovery.* are
        # registered with their owning tickets (SPEC-301 section 13); the
        # still-schemaless families only demand an object.
        validate_payload("simulation.run_progress", {"progress": 0.5})
        validate_payload("topology.state_changed", {})
        validate_payload("scenario.step_started", {})

    def test_fault_registered_payload_shape_is_enforced(self):
        # ticket #56 registered the SPEC-204 §9 fault.* payload schema —
        # the family is no longer schemaless.
        with pytest.raises(EnvelopeError):
            validate_payload("fault.injected", {})

    def test_payload_must_be_a_mapping(self):
        with pytest.raises(EnvelopeError):
            validate_payload("simulation.run_progress", "not-an-object")
