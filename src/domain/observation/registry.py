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
# event type against independently versioned payload schemas. Two payload
# obligations are registered:
#
# - observation-flavoured ``ts.*`` events carry ``source`` (five-value
#   ObservationSource) and ``confidence`` (four-value ConfidenceKind) per
#   the #13 Q3-i ruling — the diagnosis three-level rule confidence is a
#   different axis and is refused there;
# - the ``diagnosis.*`` family carries the SPEC-306 §7 shared shape
#   (ticket #54): raised/updated carry the full candidate shape including
#   the evidence anchor, cleared carries only diagnosis_id + rule_id +
#   the clear reason. The vocabularies below mirror the
#   ``domain.diagnosis.model`` enums; they are restated here (instead of
#   imported) because the dependency edge points diagnosis → observation,
#   not the reverse — the ticket #54 tests cross-check the two stay
#   identical.

#: ``diagnosis.*`` payload severity vocabulary (SPEC-003 §2.6 four tiers).
DIAGNOSIS_SEVERITIES = frozenset({"info", "warning", "error", "critical"})

#: ``diagnosis.*`` payload confidence vocabulary — the diagnosis THREE-tier
#: static declaration (SPEC-307 §3), never the observation provenance axis.
DIAGNOSIS_CONFIDENCES = frozenset({"low", "medium", "high"})

#: Correlation pid cap (13-bit DVB PID space, SPEC-301 §3 correlation.pid).
_DIAGNOSIS_PID_MAX = 8191


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
    if event_type in DIAGNOSIS_EVENT_TYPES:
        _validate_diagnosis_payload(event_type, payload)
    if event_type in FAULT_EVENT_TYPES:
        _validate_fault_payload(event_type, payload)
    if event_type in RECOVERY_EVENT_TYPES:
        _validate_recovery_payload(event_type, payload)


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


_CLEARED_REQUIRED_STR_FIELDS = ("diagnosis_id", "rule_id", "reason")
_RAISED_REQUIRED_STR_FIELDS = (
    "diagnosis_id",
    "rule_id",
    "rule_version",
    "code",
    "title",
    "summary",
)


# --- fault.* payload rules (SPEC-204 §9, ticket #56) ----------------------------
#
# Structural evidence, NOT observation (brief §6 / SPEC-206 §6 指针句): the
# engine lifecycle events carry no source/confidence axes and the branch
# never demands them. Registered obligations (SPEC-204 §9): identity
# (fault_id/fault_type) + the injection index (atomic-boundary precision,
# ADR-0007 item 4); injected carries the prepare declaration
# (expected_observations, SPEC-204 §11), applied (L1 only) carries the
# confirmed-slot index list (SPEC-204 §8.1). mutation_log_ref (the
# before-after summary pointer into the §8.2 mutation log) and
# cleared_reason are optional — missing/unknown/not-applicable stay
# distinguishable (SPEC-301 §3 payload three-state discipline).

VERIFICATION_VERDICTS = frozenset({"PASS", "FAIL", "INCONCLUSIVE"})

CRITERION_RESULTS = frozenset({"PASS", "FAIL", "NOT_EVALUATED"})


def _validate_fault_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """SPEC-204 §9 shared shape (ticket #56)."""
    for field in ("fault_id", "fault_type"):
        _require_non_empty_str(event_type, payload, field)
    _require_natural(event_type, payload, "injection_index")
    if event_type == "fault.injected":
        _require_non_empty_string_list(
            event_type, payload, "expected_observations"
        )
    if event_type == "fault.applied":
        applied = payload.get("applied_packet_indexes")
        if not isinstance(applied, list) or not applied:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload 'applied_packet_indexes' for {event_type!r} must"
                " be a non-empty list of shared-frame slot indexes"
                " (SPEC-204 §8.1: APPLIED confirms fault bytes in the flow)",
            )
        for index in applied:
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
            ):
                raise EnvelopeError(
                    EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                    f"applied_packet_indexes entries for {event_type!r} "
                    f"must be non-negative integers, got {index!r}",
                )
    for optional in ("mutation_log_ref", "cleared_reason"):
        if optional in payload and payload[optional] is not None:
            _require_non_empty_str(event_type, payload, optional)


def _validate_recovery_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """SPEC-206 §4 verdict shape (ticket #56 declaration)."""
    for field in (
        "run_id",
        "baseline_run_id",
        "scenario_id",
        "scenario_version",
        "scenario_content_hash",
        "summary",
    ):
        _require_non_empty_str(event_type, payload, field)
    verdict = payload.get("verdict")
    if verdict not in VERIFICATION_VERDICTS:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'verdict' for {event_type!r} must be one of "
            f"{sorted(VERIFICATION_VERDICTS)}, got {verdict!r}",
        )
    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'criteria' for {event_type!r} must be a non-empty "
            "list of per-criterion results (SPEC-206 §4)",
        )
    for entry in criteria:
        if not isinstance(entry, Mapping):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"criteria entries for {event_type!r} must be objects, "
                f"got {entry!r}",
            )
        for field in ("criterion_id", "kind"):
            _require_non_empty_str(event_type, entry, field)
        if not isinstance(entry.get("mandatory"), bool):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"criteria 'mandatory' for {event_type!r} must be a "
                f"boolean, got {entry.get('mandatory')!r}",
            )
        result = entry.get("result")
        if result not in CRITERION_RESULTS:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"criteria 'result' for {event_type!r} must be one of "
                f"{sorted(CRITERION_RESULTS)}, got {result!r}",
            )
        reason_code = entry.get("reason_code")
        if result == "NOT_EVALUATED":
            # SPEC-206 §5 item 2: no silent skips — the reason is mandatory.
            _require_non_empty_str(event_type, entry, "reason_code")
        elif reason_code is not None and (
            not isinstance(reason_code, str) or not reason_code
        ):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"criteria 'reason_code' for {event_type!r} must be a "
                f"non-empty string or null when present, got {reason_code!r}",
            )


def _validate_diagnosis_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """SPEC-306 §7 shared shape (ticket #54).

    ``raised``/``updated`` carry the full candidate shape; ``cleared``
    carries only ``diagnosis_id`` + ``rule_id`` + the clear reason. The
    registered obligations are validated; unknown additional keys stay
    tolerated (additive payload evolution, SPEC-301 §8 — same posture as
    the ``ts.*`` axes branch).
    """
    if event_type == "diagnosis.cleared":
        for field in _CLEARED_REQUIRED_STR_FIELDS:
            _require_non_empty_str(event_type, payload, field)
        return
    for field in _RAISED_REQUIRED_STR_FIELDS:
        _require_non_empty_str(event_type, payload, field)
    _require_vocabulary(event_type, payload, "severity", DIAGNOSIS_SEVERITIES)
    _require_vocabulary(event_type, payload, "confidence", DIAGNOSIS_CONFIDENCES)
    _require_observation_refs(event_type, payload)
    _require_string_list(event_type, payload, "affected_node_ids")
    _require_string_list(event_type, payload, "suggested_actions")
    _require_evidence(event_type, payload)


def _require_non_empty_str(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload field {field!r} for {event_type!r} must be a "
            f"non-empty string, got {value!r}",
        )


def _require_natural(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    value = payload.get(field)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload field {field!r} for {event_type!r} must be a "
            f"non-negative integer (shared-frame index), got {value!r}",
        )


def _require_non_empty_string_list(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    values = payload.get(field)
    if not isinstance(values, list) or not values:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload {field!r} for {event_type!r} must be a non-empty "
            f"list of non-empty strings, got {values!r}",
        )
    _require_string_list(event_type, payload, field)


def _require_vocabulary(
    event_type: str,
    payload: Mapping[str, Any],
    field: str,
    vocabulary: frozenset[str],
) -> None:
    value = payload.get(field)
    if value not in vocabulary:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload {field!r} for {event_type!r} must be one of "
            f"{sorted(vocabulary)}, got {value!r}",
        )


def _require_observation_refs(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    refs = payload.get("observation_refs")
    if not isinstance(refs, list) or not refs:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'observation_refs' for {event_type!r} must be a "
            "non-empty list of {journal_seq, event_type} objects "
            "(SPEC-306 §7; REQ-DIA-306-003)",
        )
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"observation_refs entries for {event_type!r} must be "
                f"objects, got {ref!r}",
            )
        journal_seq = ref.get("journal_seq")
        if (
            not isinstance(journal_seq, int)
            or isinstance(journal_seq, bool)
            or journal_seq < 1
        ):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"observation_refs journal_seq for {event_type!r} must be "
                "a positive integer (per-session stamp order), got "
                f"{journal_seq!r}",
            )
        ref_type = ref.get("event_type")
        try:
            validate_event_type(ref_type)
        except EnvelopeError:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"observation_refs event_type {ref_type!r} for "
                f"{event_type!r} is not a registered event type",
            ) from None


def _require_string_list(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    values = payload.get(field)
    if not isinstance(values, list) or not all(
        isinstance(item, str) and item for item in values
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload {field!r} for {event_type!r} must be a list of "
            f"non-empty strings, got {values!r}",
        )


def _require_evidence(event_type: str, payload: Mapping[str, Any]) -> None:
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'evidence' for {event_type!r} must be an object "
            "{artifact_id, pid, packet_index} (SPEC-306 §6/§7)",
        )
    _require_non_empty_str(event_type, evidence, "artifact_id")
    pid = evidence.get("pid")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not 0 <= pid <= _DIAGNOSIS_PID_MAX
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"evidence pid for {event_type!r} must be an integer in "
            f"0..{_DIAGNOSIS_PID_MAX} (13-bit DVB PID), got {pid!r}",
        )
    packet_index = evidence.get("packet_index")
    if (
        not isinstance(packet_index, int)
        or isinstance(packet_index, bool)
        or packet_index < 0
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"evidence packet_index for {event_type!r} must be a "
            "non-negative integer (ADR-0007 item 4 shared frame), got "
            f"{packet_index!r}",
        )


__all__ = [
    "COALESCABLE_EVENT_TYPES",
    "CRITERION_RESULTS",
    "DELIVERY_PROTECTED_EVENT_TYPES",
    "DIAGNOSIS_CONFIDENCES",
    "DIAGNOSIS_EVENT_TYPES",
    "DIAGNOSIS_SEVERITIES",
    "FAULT_EVENT_TYPES",
    "RECOVERY_EVENT_TYPES",
    "REGISTERED_EVENT_TYPES",
    "SCENARIO_EVENT_TYPES",
    "SIMULATION_CLOCK_EVENT_TYPES",
    "SIMULATION_RUN_EVENT_TYPES",
    "SIMULATION_SESSION_EVENT_TYPES",
    "TOPOLOGY_EVENT_TYPES",
    "TS_EVENT_TYPES",
    "VERIFICATION_VERDICTS",
    "WITHDRAWN_EVENT_TYPES",
    "WITHDRAWN_NAMESPACE_PREFIXES",
    "is_coalescable",
    "is_delivery_protected",
    "is_registered",
    "is_withdrawn",
    "validate_event_type",
    "validate_payload",
]
