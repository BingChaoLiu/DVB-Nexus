"""SPEC-301 section 4 — authoritative event type registry.

The unique legal event type list (REQ-OBS-301-006): every published
``event_type`` must be registered here, and new types require a payload
schema plus compatibility review. The list implements the #12 registry
restructure ruling (ADR-0006 decision 5):

- fault family: four events for the four fault states
  SCHEDULED->ACTIVE->APPLIED->REMOVED (ADR-0007 section 6 semantics);
- ``simulation.run_*`` family admitted (session-level ``lifecycle.changed``
  abolished — session state goes on ``session_*``, run state on ``run_*``);
- ``snapshot.updated`` withdrawn from the event stream: snapshot is a pull
  API with a ``journal_seq`` cursor (SPEC-200 section 4);
- authoritative recovery name is ``recovery.verification_completed``
  (Party B ``verification.completed`` abolished);
- ``diagnosis.raised/updated/cleared`` (SPEC-306/307) — never under the
  ``observation.*`` namespace: Diagnosis (root-cause candidates) is not
  Observation (facts), SPEC-003 section 2.6 / CONTEXT.md 观测;
- ``observation.*`` namespace is empty in MVP (zero envelope events; the
  alert lifecycle's authority is the alert record, exposed via SPEC-305
  WS notification + REST pull, SPEC-304 section 8) — reserved for future
  observation-surface threshold alerting;
- packet-level construction visualization types are RESERVED but undecided
  (ADR-0005 decision 3) — they are not registered and stay refused until
  the registry gains them (envelope layer needs no change, SPEC-301 §12).

Delivery policy (SPEC-301 §5, grafted backpressure rules, ADR-0006
decision 1): high-fanout progress/metrics events MAY coalesce; fault,
session, terminal-run and verification events must never be silently
dropped. The journal remains the source of truth; consumers catch up from
a snapshot + ``journal_seq`` cursor.
"""

import re
from typing import Any, Mapping

from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.model import ConfidenceKind, ObservationSource

# --- families (SPEC-301 section 4) ------------------------------------------

SIMULATION_SESSION_EVENT_TYPES = frozenset(
    {
        "simulation.session_created",
        "simulation.session_started",
        "simulation.session_paused",
        "simulation.session_resumed",
        "simulation.session_stopped",
    }
)

SIMULATION_RUN_EVENT_TYPES = frozenset(
    {
        "simulation.run_started",
        "simulation.run_progress",
        "simulation.run_completed",
        "simulation.run_failed",
    }
)

SIMULATION_CLOCK_EVENT_TYPES = frozenset({"simulation.clock_advanced"})

TOPOLOGY_EVENT_TYPES = frozenset({"topology.state_changed"})

TS_EVENT_TYPES = frozenset(
    {
        "ts.packet_batch_observed",
        "ts.continuity_error",
        "ts.pcr_jitter_observed",
        "ts.psi_section_observed",
        "ts.service_state_changed",
    }
)

FAULT_EVENT_TYPES = frozenset(
    {
        "fault.injected",  # SCHEDULED — prepare-time validation passed
        "fault.activated",  # ACTIVE — fault window starts
        "fault.applied",  # APPLIED — L1 only: faulted bytes confirmed in
        # the output stream; in state-level scenarios it coincides with
        # activated and may be omitted (SPEC-204 section 8)
        "fault.cleared",  # REMOVED — window end or run end
    }
)

SCENARIO_EVENT_TYPES = frozenset(
    {"scenario.step_started", "scenario.step_completed"}
)

RECOVERY_EVENT_TYPES = frozenset({"recovery.verification_completed"})

DIAGNOSIS_EVENT_TYPES = frozenset(
    {"diagnosis.raised", "diagnosis.updated", "diagnosis.cleared"}
)

#: The unique legal ``event_type`` set (SPEC-301 section 4, REQ-OBS-301-006).
REGISTERED_EVENT_TYPES = (
    SIMULATION_SESSION_EVENT_TYPES
    | SIMULATION_RUN_EVENT_TYPES
    | SIMULATION_CLOCK_EVENT_TYPES
    | TOPOLOGY_EVENT_TYPES
    | TS_EVENT_TYPES
    | FAULT_EVENT_TYPES
    | SCENARIO_EVENT_TYPES
    | RECOVERY_EVENT_TYPES
    | DIAGNOSIS_EVENT_TYPES
)

# --- withdrawn / abolished (must never be re-registered) --------------------

WITHDRAWN_EVENT_TYPES = frozenset(
    {
        "snapshot.updated",  # pulled out: snapshot is a pull API with a
        # journal_seq cursor (SPEC-200 section 4, ADR-0006 decision 5)
        "lifecycle.changed",  # abolished: session_* / run_* carry the states
        "verification.completed",  # Party B name; authoritative name is
        # recovery.verification_completed (ADR-0006 decision 5)
    }
)

#: ``observation.*`` namespace is empty in MVP (SPEC-301 section 4): any
#: type under it is refused; reserved for future observation-surface alerts.
WITHDRAWN_NAMESPACE_PREFIXES = ("observation.",)

# --- delivery policy (SPEC-301 section 5) ------------------------------------

#: High-fanout events allowed to coalesce (new value overwrites an undelivered
#: old value). MVP registers exactly ``run_progress``; metrics-style envelope
#: types do not exist yet (metrics are queried via SPEC-302/305).
COALESCABLE_EVENT_TYPES = frozenset({"simulation.run_progress"})

#: Events that must never be silently dropped under backpressure: the fault
#: family, the session family, terminal runs, and the verification verdict.
DELIVERY_PROTECTED_EVENT_TYPES = (
    FAULT_EVENT_TYPES
    | SIMULATION_SESSION_EVENT_TYPES
    | frozenset({"simulation.run_completed", "simulation.run_failed"})
    | RECOVERY_EVENT_TYPES
)

# Registry-side ``event_type`` shape (mirrors the 1.0 schema document
# pattern): lowercase dotted identifiers.
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def is_registered(event_type: str) -> bool:
    """True when ``event_type`` is in the authoritative registry."""
    return event_type in REGISTERED_EVENT_TYPES


def is_withdrawn(event_type: str) -> bool:
    """True when the type was withdrawn/abolished or sits in a reserved
    (MVP-empty) namespace — refusal is contractual, not an accident."""
    return event_type in WITHDRAWN_EVENT_TYPES or event_type.startswith(
        WITHDRAWN_NAMESPACE_PREFIXES
    )


def validate_event_type(event_type: str) -> None:
    """Refuse anything not in the authoritative registry (SPEC-301 §10).

    Raises :class:`EnvelopeError` with ``OBS_INVALID_ENVELOPE`` for
    malformed names, unregistered types, withdrawn types and the MVP-empty
    ``observation.*`` namespace.
    """
    if not isinstance(event_type, str) or not _EVENT_TYPE_PATTERN.match(
        event_type
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"event_type is not a dotted lowercase identifier: {event_type!r}",
        )
    if is_withdrawn(event_type):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"event_type {event_type!r} is withdrawn from the registry "
            "(SPEC-301 section 4)",
        )
    if not is_registered(event_type):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"event_type {event_type!r} is not registered "
            "(SPEC-301 section 4); new types need a payload schema and "
            "compatibility review",
        )


def is_coalescable(event_type: str) -> bool:
    """True when the event MAY be coalesced under backpressure (§5)."""
    return event_type in COALESCABLE_EVENT_TYPES


def is_delivery_protected(event_type: str) -> bool:
    """True when the event must never be silently dropped (§5)."""
    return event_type in DELIVERY_PROTECTED_EVENT_TYPES


# --- payload rules ------------------------------------------------------------
#
# Loose envelope, tight payload (ADR-0006 decision 4, SPEC-301 §7/§8): the
# envelope ignores unknown optional fields, but payloads are validated per
# event type against independently versioned payload schemas. MVP registers
# exactly one payload obligation: observation-flavoured ``ts.*`` events carry
# ``source`` (five-value ObservationSource) and ``confidence`` (four-value
# ConfidenceKind) per the #13 Q3-i ruling — the diagnosis three-level rule
# confidence (SPEC-307) is a different axis and is refused here.


def validate_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    """Validate a payload against the event type's registered schema.

    Raises :class:`EnvelopeError` with ``OBS_INVALID_ENVELOPE`` when the
    type is not registered or the payload violates the registered schema.
    """
    validate_event_type(event_type)
    if not isinstance(payload, Mapping):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload for {event_type!r} must be a JSON object",
        )
    if event_type in TS_EVENT_TYPES:
        _validate_observation_axes(event_type, payload)


def _validate_observation_axes(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    for field, vocabulary, label in (
        ("source", ObservationSource, "ObservationSource"),
        ("confidence", ConfidenceKind, "ConfidenceKind"),
    ):
        if field not in payload:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload for {event_type!r} must carry {field!r} "
                f"({label}, SPEC-003 section 2.4; #13 Q3-i)",
            )
        value = payload[field]
        try:
            vocabulary(value)
        except ValueError:
            legal = [item.value for item in vocabulary]
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload {field!r} for {event_type!r} must be one of "
                f"{legal}, got {value!r}",
            ) from None


__all__ = [
    "COALESCABLE_EVENT_TYPES",
    "DELIVERY_PROTECTED_EVENT_TYPES",
    "DIAGNOSIS_EVENT_TYPES",
    "FAULT_EVENT_TYPES",
    "RECOVERY_EVENT_TYPES",
    "REGISTERED_EVENT_TYPES",
    "SCENARIO_EVENT_TYPES",
    "SIMULATION_CLOCK_EVENT_TYPES",
    "SIMULATION_RUN_EVENT_TYPES",
    "SIMULATION_SESSION_EVENT_TYPES",
    "TOPOLOGY_EVENT_TYPES",
    "TS_EVENT_TYPES",
    "WITHDRAWN_EVENT_TYPES",
    "WITHDRAWN_NAMESPACE_PREFIXES",
    "is_coalescable",
    "is_delivery_protected",
    "is_registered",
    "is_withdrawn",
    "validate_event_type",
    "validate_payload",
]
