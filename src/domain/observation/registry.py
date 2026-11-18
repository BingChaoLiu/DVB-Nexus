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

# --- Phase 2 encapsulation namespaces (SPEC-303 §Phase2, ticket #129) ----------
#
# The four construction/evidence namespaces of the layered pipeline
# (ADR-0010 §3 / ADR-0011 §2). They are NOT observation faces: no
# source/confidence axes (SPEC-003 §2.4) — the ``ts.*`` branch stays the
# only observation-axes carrier. All discrete event faces (no continuous
# metric stream added); journal_seq per-session ordering, run_id
# correlation and the envelope shape are unchanged (ADR-0006 untouched).
# Delivery policy: none of them is coalescable or delivery-protected —
# the MVP COALESCABLE/DELIVERY_PROTECTED faces stay exactly as they were.

#: ``t2mi.*`` (SPEC-600 §6 / SPEC-602 §6): the per-stage transport summary
#: and the B1 candidate (缺失 ≠ 零).
T2MI_EVENT_TYPES = frozenset(
    {"t2mi.stage_summary", "t2mi.plp_mismatch"}
)

#: ``bbframe.*`` (SPEC-601 §5): the per-stage frame summary and the B2
#: recovery evidence (the SPEC-307 BBHEADER_SYNC_FAULT rule's symbol).
BBFRAME_EVENT_TYPES = frozenset(
    {"bbframe.stage_summary", "bbframe.recovery_failed"}
)

#: ``biss.*`` (SPEC-610/611 §5): the scramble confirmation and the
#: descramble-failure candidate (解扰失败 ≠ 码流损坏). Payloads carry key
#: FINGERPRINTS only — key material never enters a payload (SPEC-610 §9).
BISS_EVENT_TYPES = frozenset(
    {"biss.scramble_applied", "biss.descramble_failed"}
)

#: ``gen.*`` (SPEC-303 §Phase2): the three construction-event types.
#: Stage-level + sampled-packet-level only — the full per-packet stream
#: is closed (#112); magnitude stays O(layers) + O(sampling).
GEN_EVENT_TYPES = frozenset(
    {
        "gen.stage_started",
        "gen.stage_completed",
        "gen.packet_sampled",
    }
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
    | T2MI_EVENT_TYPES
    | BBFRAME_EVENT_TYPES
    | BISS_EVENT_TYPES
    | GEN_EVENT_TYPES
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

# --- Phase 2 payload vocabularies (ticket #129) ---------------------------------

#: The generation ``layer`` axis (CONTEXT.md 作用层; ADR-0010 §3 stage order).
#: One vocabulary for all three ``gen.*`` types (layer 字段贯穿).
GENERATION_LAYERS = frozenset({"TS", "BBFRAME", "T2MI", "BISS"})

#: The ``biss.*`` mode vocabulary — owner is ``ts.biss.cissa``
#: (BISS_MODE_1/"1", BISS_MODE_E/"E", BISS_MODE_2/"2").
BISS_MODES = frozenset({"1", "E", "2"})

#: The T2-MI packet payload-kind vocabulary (SPEC-600 §5/§8, #122 三态).
_T2MI_PAYLOAD_KINDS = frozenset({"bbframe", "padding", "unknown"})

#: PLP id cap (TS 102 773 transport prefix: 8-bit PLP id, #122 builder).
_T2MI_PLP_ID_MAX = 255

#: ``failed_indices_sample`` bound (#126: the evidence payload stays bounded).
_BISS_SAMPLE_LIMIT = 16

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIGITS_PATTERN = re.compile(r"^[0-9]+$")


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
    if event_type in GEN_EVENT_TYPES:
        _validate_generation_payload(event_type, payload)
    if event_type in T2MI_EVENT_TYPES:
        _validate_t2mi_payload(event_type, payload)
    if event_type in BBFRAME_EVENT_TYPES:
        _validate_bbframe_payload(event_type, payload)
    if event_type in BISS_EVENT_TYPES:
        _validate_biss_payload(event_type, payload)


# --- Phase 2 payload rules (SPEC-303 §Phase2, ticket #129) ----------------------
#
# Structural construction/evidence faces, NOT observation (brief §8 #129
# card): no source/confidence axes. Unlike the still-schemaless families,
# the Phase 2 payloads are STRICT: the upstream REPORT key sets are the
# contract (ruling §10-7 froze them), so missing keys AND extra keys are
# both refused — the emission seams already self-check their exact key
# sets, the registry side mirrors that discipline.
#
# ``*_KEYS`` constants name the frozen key sets so the mirrors (api/dto
# event payload DTOs, #132/134 consumers) can cite them by symbol.


_GEN_STAGE_STARTED_KEYS = frozenset({"layer"})
_GEN_STAGE_COMPLETED_KEYS = frozenset({"layer", "item_count"})
_GEN_PACKET_SAMPLED_KEYS = frozenset(
    {"layer", "packet_index", "byte_size", "sha256"}
)

_T2MI_STAGE_SUMMARY_KEYS = frozenset(
    {
        "packet_count",
        "padding_count",
        "packet_type_distribution",
        "plp_distribution",
    }
)
_T2MI_PLP_MISMATCH_KEYS = frozenset(
    {"expected_plp", "actual_plp", "business_absent_evidence"}
)
_T2MI_BUSINESS_ABSENT_KEYS = frozenset(
    {
        "plps_seen",
        "bbframe_packet_count",
        "filtered_packet_count",
        "total_packet_count",
    }
)

_BBFRAME_STAGE_SUMMARY_KEYS = frozenset(
    {"frame_count", "n_ups_distribution", "stuffing_ratio"}
)
_BBFRAME_RECOVERY_FAILED_KEYS = frozenset(
    {"failure_count", "first_failed_frame_index"}
)

#: The shared scrambler face (#126) — Mode 1 emits exactly these.
_BISS_SCRAMBLE_BASE_KEYS = frozenset(
    {
        "pid_scope",
        "packet_count",
        "key_fingerprint",
        "mutation_log_ref",
        "mode",
    }
)
#: The Mode E derivation face (#127) — additive over the base.
_BISS_SCRAMBLE_DERIVATION_KEYS = frozenset(
    {"derivation_ref", "mismatch_variants"}
)
_BISS_DESCRAMBLE_FAILED_KEYS = frozenset(
    {
        "pid_scope",
        "failed_indices_sample",
        "self_check_kind",
        "key_fingerprint_ref",
        "mode",
    }
)

#: The #141 same-source face (ticket #141): the Phase 2 payload key sets
#: in the #129 REPORT §2 display order — the SINGLE source the frontend
#: gen module (``scripts/dump-payload-keys.mjs`` → ``payloadKeys.gen.ts``)
#: renders from, replacing the hand-maintained render table keys.  The
#: import-time self-check below locks THIS face against the frozen
#: validator constants (a key added to one side without the other fails
#: at import); a NEWLY registered Phase 2 event type is pinned by the
#: unit test (test_phase2_payload_key_sets.py — the face must cover
#: exactly the four Phase 2 families).
PHASE2_PAYLOAD_KEY_SETS: dict[str, tuple[str, ...]] = {
    "t2mi.stage_summary": (
        "packet_count",
        "padding_count",
        "packet_type_distribution",
        "plp_distribution",
    ),
    "t2mi.plp_mismatch": (
        "expected_plp",
        "actual_plp",
        "business_absent_evidence",
    ),
    "bbframe.stage_summary": (
        "frame_count",
        "n_ups_distribution",
        "stuffing_ratio",
    ),
    "bbframe.recovery_failed": (
        "failure_count",
        "first_failed_frame_index",
    ),
    # the maximal mode face (base + the optional #127 derivation face) —
    # absent optional keys render nothing on a concrete envelope
    "biss.scramble_applied": (
        "pid_scope",
        "packet_count",
        "key_fingerprint",
        "mutation_log_ref",
        "mode",
        "derivation_ref",
        "mismatch_variants",
    ),
    "biss.descramble_failed": (
        "pid_scope",
        "failed_indices_sample",
        "self_check_kind",
        "key_fingerprint_ref",
        "mode",
    ),
    "gen.stage_started": ("layer",),
    "gen.stage_completed": ("layer", "item_count"),
    "gen.packet_sampled": (
        "layer",
        "packet_index",
        "byte_size",
        "sha256",
    ),
}

for _event_type, _keys, _frozen in (
    (
        event_type,
        PHASE2_PAYLOAD_KEY_SETS[event_type],
        frozen,
    )
    for event_type, frozen in (
        ("t2mi.stage_summary", _T2MI_STAGE_SUMMARY_KEYS),
        ("t2mi.plp_mismatch", _T2MI_PLP_MISMATCH_KEYS),
        ("bbframe.stage_summary", _BBFRAME_STAGE_SUMMARY_KEYS),
        ("bbframe.recovery_failed", _BBFRAME_RECOVERY_FAILED_KEYS),
        (
            "biss.scramble_applied",
            _BISS_SCRAMBLE_BASE_KEYS | _BISS_SCRAMBLE_DERIVATION_KEYS,
        ),
        ("biss.descramble_failed", _BISS_DESCRAMBLE_FAILED_KEYS),
        ("gen.stage_started", _GEN_STAGE_STARTED_KEYS),
        ("gen.stage_completed", _GEN_STAGE_COMPLETED_KEYS),
        ("gen.packet_sampled", _GEN_PACKET_SAMPLED_KEYS),
    )
):
    if set(_keys) != _frozen:
        raise ImportError(
            f"PHASE2_PAYLOAD_KEY_SETS[{_event_type!r}] drifted from the "
            f"frozen validator key set: ordered face "
            f"{sorted(_keys)} vs validator {sorted(_frozen)} (ticket #141 "
            "same-source self-check)"
        )
del _event_type, _keys, _frozen


def _validate_generation_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """``gen.*`` shapes (SPEC-303 §Phase2; #128 emission contract)."""
    if event_type == "gen.stage_started":
        keys, extra = _GEN_STAGE_STARTED_KEYS, ()
    elif event_type == "gen.stage_completed":
        keys, extra = _GEN_STAGE_COMPLETED_KEYS, (("item_count", _require_natural),)
    else:
        keys, extra = _GEN_PACKET_SAMPLED_KEYS, (
            ("packet_index", _require_natural),
            ("byte_size", _require_natural),
        )
    _require_exact_keys(event_type, payload, keys)
    _require_vocabulary(event_type, payload, "layer", GENERATION_LAYERS)
    for field, check in extra:
        check(event_type, payload, field)
    if event_type == "gen.packet_sampled":
        digest = payload.get("sha256")
        if not isinstance(digest, str) or not _SHA256_PATTERN.match(digest):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload 'sha256' for {event_type!r} must be a lowercase "
                f"64-hex digest, got {digest!r}",
            )


def _validate_t2mi_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """``t2mi.*`` shapes (SPEC-600 §6 / SPEC-602 §6; #122/#124 contract)."""
    if event_type == "t2mi.stage_summary":
        _require_exact_keys(event_type, payload, _T2MI_STAGE_SUMMARY_KEYS)
        for field in ("packet_count", "padding_count"):
            _require_natural(event_type, payload, field)
        distribution = payload.get("packet_type_distribution")
        if not isinstance(distribution, Mapping):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload 'packet_type_distribution' for {event_type!r} "
                f"must be an object, got {distribution!r}",
            )
        for kind, count in distribution.items():
            if kind not in _T2MI_PAYLOAD_KINDS:
                raise EnvelopeError(
                    EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                    f"packet_type_distribution keys for {event_type!r} must "
                    f"be one of {sorted(_T2MI_PAYLOAD_KINDS)}, got {kind!r}",
                )
            _require_count_value(event_type, kind, count)
        _require_plp_distribution(event_type, payload)
        return
    # t2mi.plp_mismatch — the B1 candidate (缺失 ≠ 零).
    _require_exact_keys(event_type, payload, _T2MI_PLP_MISMATCH_KEYS)
    _require_plp_id(event_type, payload, "expected_plp")
    actual = payload.get("actual_plp")
    if actual is not None:
        # Honest ambiguity: ≠1 observed PLP → None (never a guess).
        _require_plp_id(event_type, payload, "actual_plp")
    evidence = payload.get("business_absent_evidence")
    if not isinstance(evidence, Mapping):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'business_absent_evidence' for {event_type!r} must "
            f"be an object, got {evidence!r}",
        )
    _require_exact_keys(
        event_type, evidence, _T2MI_BUSINESS_ABSENT_KEYS, label="evidence"
    )
    plps_seen = evidence.get("plps_seen")
    if not isinstance(plps_seen, list):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"evidence 'plps_seen' for {event_type!r} must be a list of "
            f"PLP ids, got {plps_seen!r}",
        )
    for plp_id in plps_seen:
        if (
            not isinstance(plp_id, int)
            or isinstance(plp_id, bool)
            or not 0 <= plp_id <= _T2MI_PLP_ID_MAX
        ):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"evidence 'plps_seen' entries for {event_type!r} must be "
                f"integers in 0..{_T2MI_PLP_ID_MAX}, got {plp_id!r}",
            )
    for field in (
        "bbframe_packet_count",
        "filtered_packet_count",
        "total_packet_count",
    ):
        _require_natural(event_type, evidence, field)


def _validate_bbframe_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """``bbframe.*`` shapes (SPEC-601 §5; #123 contract)."""
    if event_type == "bbframe.stage_summary":
        _require_exact_keys(event_type, payload, _BBFRAME_STAGE_SUMMARY_KEYS)
        _require_natural(event_type, payload, "frame_count")
        _require_distribution(event_type, payload, "n_ups_distribution")
        ratio = payload.get("stuffing_ratio")
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not 0 <= ratio <= 1
        ):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload 'stuffing_ratio' for {event_type!r} must be a "
                f"number in 0..1 (stuffing bytes / data-field bytes), "
                f"got {ratio!r}",
            )
        return
    # bbframe.recovery_failed — the B2 recovery evidence.
    _require_exact_keys(event_type, payload, _BBFRAME_RECOVERY_FAILED_KEYS)
    _require_natural(event_type, payload, "failure_count")
    index = payload.get("first_failed_frame_index")
    if index is not None:
        _require_natural(event_type, payload, "first_failed_frame_index")


def _validate_biss_payload(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """``biss.*`` shapes (SPEC-610 §5 / SPEC-611 §5; #126/#127 contract).

    Key-fingerprint discipline: ``key_fingerprint`` /
    ``key_fingerprint_ref`` are fingerprint REFERENCES, never key
    material (SPEC-610 §9) — the shape check demands non-empty strings;
    the envelope-level secret scan is the second guard.
    """
    if event_type == "biss.scramble_applied":
        keys = set(payload)
        mode = payload.get("mode")
        if mode not in BISS_MODES:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload 'mode' for {event_type!r} must be one of "
                f"{sorted(BISS_MODES)}, got {mode!r}",
            )
        base = set(_BISS_SCRAMBLE_BASE_KEYS)
        derivation = set(_BISS_SCRAMBLE_DERIVATION_KEYS)
        if mode == "1":
            legal = (base,)
        else:
            # The derived-key faces carry EITHER the bare base keys (the
            # construction path — ``cissa_scramble`` has no mismatch to
            # declare) OR base + the derivation face (the fault transform
            # declares the redacted chain reference + variants, #127).
            # A HALF derivation face is a shape violation either way.
            legal = (base, base | derivation)
        if keys not in legal:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"payload keys for {event_type!r} (mode={mode!r}) must be "
                f"one of {[sorted(option) for option in legal]}, got "
                f"{sorted(keys)}",
            )
        _require_pid_scope(event_type, payload)
        _require_natural(event_type, payload, "packet_count")
        _require_non_empty_str(event_type, payload, "key_fingerprint")
        ref = payload.get("mutation_log_ref")
        if ref is not None:
            _require_non_empty_str(event_type, payload, "mutation_log_ref")
        if "derivation_ref" in payload:
            _require_derivation_ref(event_type, payload)
            variants = payload.get("mismatch_variants")
            if not isinstance(variants, list) or not all(
                isinstance(item, str) and item for item in variants
            ):
                raise EnvelopeError(
                    EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                    f"payload 'mismatch_variants' for {event_type!r} must "
                    "be a list of non-empty variant names, got "
                    f"{variants!r}",
                )
        return
    # biss.descramble_failed — 解扰失败 ≠ 码流损坏 (ADR-0011 §4).
    _require_exact_keys(event_type, payload, _BISS_DESCRAMBLE_FAILED_KEYS)
    _require_pid_scope(event_type, payload)
    sample = payload.get("failed_indices_sample")
    if (
        not isinstance(sample, list)
        or len(sample) > _BISS_SAMPLE_LIMIT
        or not all(
            isinstance(index, int)
            and not isinstance(index, bool)
            and index >= 0
            for index in sample
        )
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'failed_indices_sample' for {event_type!r} must be "
            f"a list of at most {_BISS_SAMPLE_LIMIT} non-negative shared-"
            f"frame indexes, got {sample!r}",
        )
    _require_non_empty_str(event_type, payload, "self_check_kind")
    _require_non_empty_str(event_type, payload, "key_fingerprint_ref")
    _require_vocabulary(event_type, payload, "mode", BISS_MODES)


def _require_exact_keys(
    event_type: str,
    payload: Mapping[str, Any],
    keys: frozenset[str],
    *,
    label: str = "payload",
) -> None:
    present = set(payload)
    if present != set(keys):
        missing = sorted(set(keys) - present)
        unexpected = sorted(present - set(keys))
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"{label} keys for {event_type!r} must be exactly "
            f"{sorted(keys)}; missing {missing}, unexpected {unexpected}",
        )


def _require_count_value(
    event_type: str, field: str, value: Any
) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"distribution {field!r} for {event_type!r} must be a "
            f"non-negative integer count, got {value!r}",
        )


def _require_distribution(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    distribution = payload.get(field)
    if not isinstance(distribution, Mapping):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload {field!r} for {event_type!r} must be an object, "
            f"got {distribution!r}",
        )
    for key, count in distribution.items():
        if not isinstance(key, str) or not _DIGITS_PATTERN.match(key):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"{field} keys for {event_type!r} must be decimal strings, "
                f"got {key!r}",
            )
        _require_count_value(event_type, key, count)


def _require_plp_distribution(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    """``plp_distribution``: decimal PLP id → count (SPEC-602 §6)."""
    distribution = payload.get("plp_distribution")
    if not isinstance(distribution, Mapping):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'plp_distribution' for {event_type!r} must be an "
            f"object, got {distribution!r}",
        )
    for key, count in distribution.items():
        if not isinstance(key, str) or not _DIGITS_PATTERN.match(key):
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"plp_distribution keys for {event_type!r} must be decimal "
                f"PLP id strings, got {key!r}",
            )
        _require_count_value(event_type, key, count)


def _require_plp_id(
    event_type: str, payload: Mapping[str, Any], field: str
) -> None:
    value = payload.get(field)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= _T2MI_PLP_ID_MAX
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload {field!r} for {event_type!r} must be an integer in "
            f"0..{_T2MI_PLP_ID_MAX} (TS 102 773 transport-prefix PLP id), "
            f"got {value!r}",
        )


def _require_pid_scope(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    scope = payload.get("pid_scope")
    if (
        not isinstance(scope, list)
        or not scope
        or not all(
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and 0 <= pid <= _DIAGNOSIS_PID_MAX
            for pid in scope
        )
    ):
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'pid_scope' for {event_type!r} must be a non-empty "
            f"list of PIDs in 0..{_DIAGNOSIS_PID_MAX} (13-bit DVB PID), "
            f"got {scope!r}",
        )


def _require_derivation_ref(
    event_type: str, payload: Mapping[str, Any]
) -> None:
    derivation = payload.get("derivation_ref")
    if not isinstance(derivation, Mapping) or not derivation:
        raise EnvelopeError(
            EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
            f"payload 'derivation_ref' for {event_type!r} must be a "
            "non-empty object of fingerprint references (SPEC-611 §5), "
            f"got {derivation!r}",
        )
    for key, value in derivation.items():
        if not isinstance(key, str) or not key:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"derivation_ref keys for {event_type!r} must be "
                f"non-empty strings, got {key!r}",
            )
        if not isinstance(value, str) or not value:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_ENVELOPE,
                f"derivation_ref {key!r} for {event_type!r} must be a "
                f"non-empty fingerprint string, got {value!r}",
            )


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
    "BISS_EVENT_TYPES",
    "BISS_MODES",
    "BBFRAME_EVENT_TYPES",
    "COALESCABLE_EVENT_TYPES",
    "CRITERION_RESULTS",
    "DELIVERY_PROTECTED_EVENT_TYPES",
    "DIAGNOSIS_CONFIDENCES",
    "DIAGNOSIS_EVENT_TYPES",
    "DIAGNOSIS_SEVERITIES",
    "FAULT_EVENT_TYPES",
    "GEN_EVENT_TYPES",
    "GENERATION_LAYERS",
    "PHASE2_PAYLOAD_KEY_SETS",
    "RECOVERY_EVENT_TYPES",
    "REGISTERED_EVENT_TYPES",
    "SCENARIO_EVENT_TYPES",
    "SIMULATION_CLOCK_EVENT_TYPES",
    "SIMULATION_RUN_EVENT_TYPES",
    "SIMULATION_SESSION_EVENT_TYPES",
    "T2MI_EVENT_TYPES",
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
