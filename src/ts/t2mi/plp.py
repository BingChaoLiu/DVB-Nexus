"""SPEC-602 — PLP filter / assign / plps_seen (ticket #124).

The PLP semantic layer of the T2-MI chain (#110: no standalone node —
filter semantics live in the ``t2mi_demux`` config, assignment semantics
in the ``t2mi_encapsulator`` config; this module is the in-process face
both consume).  Three public faces (SPEC-602 §6 interface contract):

- :func:`filter` — ``plp.filter(packets, config) -> Sequence[T2miPacket]``:
  deterministic linear selection (O(n), §9).  ``mode="expected"`` keeps
  only BBFRAME packets whose transport-prefix PLP matches; ``mode="all"``
  is the verbatim pass-through (padding/unknown included — selection is
  never a silent drop; the degradation faces stay visible on the parse
  result the caller already holds).  When the expected PLP matches zero
  BBFRAME packets the result is the **explicit empty sequence** plus the
  ``t2mi.plp_mismatch`` candidate payload (诚实「缺失 ≠ 零」纪律, §8) —
  never a silent empty.
- :func:`assign` — ``plp.assign(sources, assignment) -> tagged stream``:
  encapsulator-side PLP annotation, composed over the #122
  :func:`ts.t2mi.builder.build` ``plp_ids`` seam; the frame order is the
  sources mapping insertion order and every frame is stamped with its
  source's assigned PLP.
- :func:`plps_seen` — ``plp.plps_seen(packets) -> PlpSeenDTO shape``:
  the distinct BBFRAME PLP ids actually present, first-appearance order
  (diagnostic and teaching evidence).

Data shapes (SPEC-602 §5, aligned with ``domain.topology.node_types``
wire DTOs #121 — plain frozen dataclasses here because ``ts`` imports no
other project package, ts purity contract):

- ``PlpAssignmentDTO`` = ``{entries: [{plp_id, source_tag}]}`` →
  :class:`PlpAssignment` / :class:`PlpAssignmentEntry`;
- ``PlpFilterConfigDTO`` = ``{mode: "expected"|"all", expected_plp}`` →
  :class:`PlpFilterConfig`;
- ``PlpSeenDTO`` = ``{plps_seen: [int]}`` → the :func:`plps_seen` dict.

Prepare-before-refuse error face (§8, all raised as
:class:`ts.t2mi.errors.T2miError` at construction / call time):

- assignment-table conflicts (same source_tag twice, same plp_id twice)
  → ``T2MI_PLP_ASSIGNMENT_CONFLICT`` (同 source 双 PLP prepare 前拒绝);
- PLP id outside the 8-bit value domain → ``T2MI_PLP_ID_OUT_OF_RANGE``
  (schema rejection);
- empty assignment table → ``T2MI_PLP_ASSIGNMENT_EMPTY`` (wire schema
  ``min_length=1`` parity, node_types #121);
- invalid ``source_tag`` → ``T2MI_PLP_SOURCE_TAG_INVALID``;
- a source without an assigned PLP → ``T2MI_PLP_ASSIGNMENT_UNASSIGNED_SOURCE``
  (every frame must be stamped — no implicit PLP 0);
- a filter config that violates the mode/PLP rules →
  ``T2MI_PLP_FILTER_CONFIG_INVALID``.

``t2mi.plp_mismatch`` emission seam (ruling §10-7): the registry entry
lands with #129, so this module only *reserves* the seam — the frozen
payload key set (``expected_plp / actual_plp / business_absent_evidence``,
SPEC-602 §5) and the same emitter-injected, pure shape as the #122
``t2mi.stage_summary`` seam (:func:`collect_plp_mismatch` + 
:func:`emit_plp_mismatch`; ``ts`` never imports ``simulation``).  #128
binds the ``SimulationEventEmitter`` at the composition root; #129
registers the payload schema verbatim.

Error codes owned here (module-owned per contract §7 归属约定): the
``T2MI_PLP_*`` family above; all raised as :class:`T2miError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.errors import T2miError
from ts.t2mi.packet import PAYLOAD_KIND_BBFRAME, T2miPacket

__all__ = [
    "PLP_MISMATCH_EVIDENCE_KEYS",
    "PLP_MISMATCH_PAYLOAD_KEYS",
    "PlpAssignment",
    "PlpAssignmentEntry",
    "PlpFilterConfig",
    "T2MI_PLP_MISMATCH_EVENT_TYPE",
    "PlpMismatchEmitter",
    "assign",
    "collect_plp_mismatch",
    "emit_plp_mismatch",
    "filter",
    "plps_seen",
]

# --- error codes owned by this module (SPEC-602 §8) ---

T2MI_PLP_ID_OUT_OF_RANGE = "T2MI_PLP_ID_OUT_OF_RANGE"
T2MI_PLP_SOURCE_TAG_INVALID = "T2MI_PLP_SOURCE_TAG_INVALID"
T2MI_PLP_ASSIGNMENT_CONFLICT = "T2MI_PLP_ASSIGNMENT_CONFLICT"
T2MI_PLP_ASSIGNMENT_EMPTY = "T2MI_PLP_ASSIGNMENT_EMPTY"
T2MI_PLP_ASSIGNMENT_UNASSIGNED_SOURCE = "T2MI_PLP_ASSIGNMENT_UNASSIGNED_SOURCE"
T2MI_PLP_FILTER_CONFIG_INVALID = "T2MI_PLP_FILTER_CONFIG_INVALID"

# --- the reserved t2mi.plp_mismatch emission seam (ruling §10-7) ---

#: The registered event type (SPEC-303 §Phase2; registry entry lands #129).
T2MI_PLP_MISMATCH_EVENT_TYPE = "t2mi.plp_mismatch"

#: Frozen payload key set (SPEC-602 §5; ruling §10-7 签名与 payload 键定死).
PLP_MISMATCH_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"expected_plp", "actual_plp", "business_absent_evidence"}
)

#: Frozen ``business_absent_evidence`` content keys — the locator seed the
#: runtime (#128) binds artifact/run identity onto at the envelope layer
#: (ADR-0006: identity and clocks travel in the envelope, content here).
PLP_MISMATCH_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {"plps_seen", "bbframe_packet_count", "filtered_packet_count", "total_packet_count"}
)

#: Emitter seam shape: ``(event_type, payload) -> None`` — mirrors the #122
#: ``StageSummaryEmitter`` (the shape ``SimulationEventEmitter`` presents
#: to producers; wired by #128).
PlpMismatchEmitter = Callable[[str, Mapping[str, Any]], None]

_PLP_ID_MAX = 0xFF

_MODE_EXPECTED = "expected"
_MODE_ALL = "all"


def _require_plp_id(value: object, code: str) -> int:
    """8-bit PLP_ID value domain; bool rejected as a distinct type."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise T2miError(
            f"{code}: PLP id must be an int in 0..{_PLP_ID_MAX}, got {value!r}"
        )
    if not 0 <= value <= _PLP_ID_MAX:
        raise T2miError(
            f"{code}: PLP id {value} outside the 8-bit PLP_ID value domain "
            f"0..{_PLP_ID_MAX} (SPEC-602 §8 prepare 前拒绝)"
        )
    return value


# --- SPEC-602 §5 data shapes (frozen, wire-key aligned) -------------------------


@dataclass(frozen=True)
class PlpAssignmentEntry:
    """One PLP assignment entry (SPEC-602 §5): business tag → PLP ID."""

    plp_id: int
    source_tag: str

    def __post_init__(self) -> None:
        _require_plp_id(self.plp_id, T2MI_PLP_ID_OUT_OF_RANGE)
        if not isinstance(self.source_tag, str) or not self.source_tag.strip():
            raise T2miError(
                f"{T2MI_PLP_SOURCE_TAG_INVALID}: source_tag must be a "
                f"non-empty string, got {self.source_tag!r}"
            )


@dataclass(frozen=True)
class PlpAssignment:
    """The encapsulator-side assignment table (SPEC-602 §5).

    Conflicts are refused at construction (SPEC-602 §8): one business
    source may map to at most one PLP, and one PLP carries at most one
    source (the duplicate-``plp_id`` face of the same table conflict).
    """

    entries: tuple[PlpAssignmentEntry, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        object.__setattr__(self, "entries", entries)
        if not entries:
            raise T2miError(
                f"{T2MI_PLP_ASSIGNMENT_EMPTY}: the assignment table needs at "
                "least one entry (wire schema min_length=1)"
            )
        tags = [entry.source_tag for entry in entries]
        if len(tags) != len(set(tags)):
            raise T2miError(
                f"{T2MI_PLP_ASSIGNMENT_CONFLICT}: duplicate source_tag "
                f"entries {sorted({t for t in tags if tags.count(t) > 1})!r} — "
                "one business source may map to at most one PLP (SPEC-602 §8)"
            )
        plp_ids = [entry.plp_id for entry in entries]
        if len(plp_ids) != len(set(plp_ids)):
            raise T2miError(
                f"{T2MI_PLP_ASSIGNMENT_CONFLICT}: duplicate plp_id entries "
                f"{sorted({p for p in plp_ids if plp_ids.count(p) > 1})!r} — "
                "one PLP carries at most one source (SPEC-602 §8)"
            )

    def plp_for(self, source_tag: str) -> int:
        """The assigned PLP for ``source_tag``; unassigned tags refuse loudly."""
        for entry in self.entries:
            if entry.source_tag == source_tag:
                return entry.plp_id
        raise T2miError(
            f"{T2MI_PLP_ASSIGNMENT_UNASSIGNED_SOURCE}: source_tag "
            f"{source_tag!r} has no assigned PLP — every frame must be "
            "stamped, there is no implicit PLP (SPEC-602 §8)"
        )


@dataclass(frozen=True)
class PlpFilterConfig:
    """The demux-side PLP filter (SPEC-602 §5).

    ``mode="expected"`` requires ``expected_plp`` (the demux config rule
    #121's wire validator enforces too); ``mode="all"`` is the verbatim
    pass-through.
    """

    mode: str
    expected_plp: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in (_MODE_EXPECTED, _MODE_ALL):
            raise T2miError(
                f"{T2MI_PLP_FILTER_CONFIG_INVALID}: mode must be "
                f"'expected' or 'all', got {self.mode!r} (SPEC-602 §5)"
            )
        if self.mode == _MODE_EXPECTED:
            if self.expected_plp is None:
                raise T2miError(
                    f"{T2MI_PLP_FILTER_CONFIG_INVALID}: mode 'expected' "
                    "requires expected_plp (SPEC-602 §5)"
                )
            _require_plp_id(self.expected_plp, T2MI_PLP_ID_OUT_OF_RANGE)


# --- SPEC-602 §6 public faces ----------------------------------------------------


def assign(
    sources: Mapping[str, Sequence[bytes]],
    assignment: PlpAssignment,
    config: T2miBuildConfig | None = None,
) -> tuple[T2miPacket, ...]:
    """Stamp each source's frames with its assigned PLP (SPEC-602 §6).

    ``sources`` maps ``source_tag`` → that business's BBFRAME sequence
    (``BBHEADER + data field``, the #122 builder input).  The frames are
    concatenated in mapping insertion order (deterministic for a given
    mapping) and encapsulated through :func:`ts.t2mi.builder.build` with
    the per-frame ``plp_ids`` seam — the transport prefix of every packet
    therefore carries the assignment-table PLP of its source.

    An assignment entry with no frames this run is tolerated (the table
    is config, the mapping is payload); a source without an assignment
    refuses before any packet is produced (prepare 前拒绝).
    """
    frames: list[bytes] = []
    per_frame_plp: list[int] = []
    for source_tag, source_frames in sources.items():
        plp_id = assignment.plp_for(source_tag)
        for frame in source_frames:
            frames.append(frame)
            per_frame_plp.append(plp_id)
    return build(frames, config if config is not None else T2miBuildConfig(), plp_ids=per_frame_plp)


def filter(
    packets: Sequence[T2miPacket],
    config: PlpFilterConfig,
    *,
    emitter: PlpMismatchEmitter | None = None,
) -> tuple[T2miPacket, ...]:
    """Select packets per the demux-side filter config (SPEC-602 §6).

    Deterministic linear pass (§7/§9): same stream + same config → same
    result sequence.

    - ``mode="all"``: everything through verbatim (padding/unknown
      included — nothing is silently dropped at the selection face).
    - ``mode="expected"``: only BBFRAME packets whose transport-prefix
      PLP equals ``expected_plp``, stream order preserved.  When that
      matches **zero** packets the result is the explicit empty tuple
      plus the ``t2mi.plp_mismatch`` candidate — an injected ``emitter``
      receives it (see :func:`collect_plp_mismatch` / 
      :func:`emit_plp_mismatch`); without an emitter the caller can still
      collect the candidate payload itself (缺失 ≠ 零, the candidate is
      never fabricated silently away).

    ``emitter`` is the reserved §10-7 seam: any callable
    ``(event_type, payload) -> None``; #128 binds the simulation emitter
    at the composition root.
    """
    if config.mode == _MODE_ALL:
        return tuple(packets)
    expected = config.expected_plp
    assert expected is not None  # construction-time validated
    selected = tuple(
        packet
        for packet in packets
        if packet.payload_kind == PAYLOAD_KIND_BBFRAME and packet.plp_id == expected
    )
    if not selected:
        payload = collect_plp_mismatch(packets, config)
        assert payload is not None
        if emitter is not None:
            emit_plp_mismatch(emitter, payload)
    return selected


def plps_seen(packets: Sequence[T2miPacket]) -> dict[str, Any]:
    """The stream's actual PLP set (SPEC-602 §6, ``PlpSeenDTO`` shape).

    Distinct BBFRAME transport-prefix PLP ids in first-appearance order —
    the diagnostic and teaching evidence face (padding/unknown packets
    carry no PLP and never appear here).  Same stream → same list.
    """
    seen: list[int] = []
    for packet in packets:
        if packet.payload_kind != PAYLOAD_KIND_BBFRAME:
            continue
        plp_id = packet.plp_id
        assert plp_id is not None
        if plp_id not in seen:
            seen.append(plp_id)
    return {"plps_seen": seen}


# --- the reserved t2mi.plp_mismatch candidate seam (§10-7) -----------------------


def collect_plp_mismatch(
    packets: Sequence[T2miPacket],
    config: PlpFilterConfig,
) -> dict[str, Any] | None:
    """Build the ``t2mi.plp_mismatch`` candidate payload, or ``None``.

    Non-``None`` exactly when ``config`` is expected-mode and the expected
    PLP matched zero BBFRAME packets (the B1 absence face: 缺失 ≠ 零).
    ``actual_plp`` is honest about ambiguity: the single observed PLP
    when the stream carries exactly one, ``None`` otherwise (zero or
    several) — the full observation travels in
    ``business_absent_evidence`` either way.  Pure and deterministic.
    """
    if config.mode != _MODE_EXPECTED:
        return None
    expected = config.expected_plp
    assert expected is not None
    seen = plps_seen(packets)["plps_seen"]
    if expected in seen:
        return None
    evidence = {
        "plps_seen": list(seen),
        "bbframe_packet_count": sum(
            1 for packet in packets if packet.payload_kind == PAYLOAD_KIND_BBFRAME
        ),
        "filtered_packet_count": 0,
        "total_packet_count": len(packets),
    }
    actual_plp: int | None = seen[0] if len(seen) == 1 else None
    return {
        "expected_plp": expected,
        "actual_plp": actual_plp,
        "business_absent_evidence": evidence,
    }


def emit_plp_mismatch(
    emitter: PlpMismatchEmitter,
    payload: Mapping[str, Any],
) -> None:
    """Emit one ``t2mi.plp_mismatch`` candidate through the injected emitter.

    The event type is fixed here; the payload must carry exactly the
    :data:`PLP_MISMATCH_PAYLOAD_KEYS` (misuse raises ``ValueError`` so a
    shape drift cannot reach the registry silently once #129 lands).
    Delivery decisions (coalescing, journal ordering) belong to the
    emitter layer (§2bis envelope discipline).
    """
    if set(payload) != PLP_MISMATCH_PAYLOAD_KEYS:
        raise ValueError(
            f"t2mi.plp_mismatch payload key drift: got {sorted(payload)}, "
            f"expected exactly {sorted(PLP_MISMATCH_PAYLOAD_KEYS)}"
        )
    emitter(T2MI_PLP_MISMATCH_EVENT_TYPE, dict(payload))
