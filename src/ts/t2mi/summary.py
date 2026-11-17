"""SPEC-600 §6 / SPEC-303 §Phase2 — ``t2mi.stage_summary`` seam (#122).

The observation registry entry for ``t2mi.stage_summary`` lands with
#129 (ruling §10-7); until then this module *reserves* the emission seam
with the frozen payload shape (per-run completion: packet count, padding
count, packet-type distribution, PLP distribution summary) so #128 can
wire it into ``SimulationEventEmitter`` and #129 can register the
payload schema verbatim.

The seam is emitter-injected and pure: ``ts`` never imports
``simulation`` (ts purity, ADR-0005) — the emitter is any callable
``(event_type, payload) -> None``; the envelope (session/run identity,
journal clocks) is stamped by the caller's emitter layer per ADR-0006,
so the payload here carries content keys only. Payload keys (frozen):

- ``packet_count`` — total T2-MI packets in the stage;
- ``padding_count`` — packets in the explicit padding/stuffing state;
- ``packet_type_distribution`` — mapping payload_kind → count
  (MVP keys: ``bbframe`` / ``padding`` / ``unknown``);
- ``plp_distribution`` — mapping PLP id (decimal string) → count over
  BBFRAME packets (the SPEC-602 PLP-distribution summary face).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ts.t2mi.packet import PAYLOAD_KIND_PADDING, T2miPacket

__all__ = [
    "STAGE_SUMMARY_PAYLOAD_KEYS",
    "T2MI_STAGE_SUMMARY_EVENT_TYPE",
    "StageSummaryEmitter",
    "collect_stage_summary",
    "emit_stage_summary",
]

#: The registered event type (SPEC-303 §Phase2; registry entry lands #129).
T2MI_STAGE_SUMMARY_EVENT_TYPE = "t2mi.stage_summary"

#: Frozen payload key set (ruling §10-7: 签名与 payload 键照票卡定死).
STAGE_SUMMARY_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"packet_count", "padding_count", "packet_type_distribution", "plp_distribution"}
)

#: Emitter seam shape: ``(event_type, payload) -> None`` — the shape
#: ``SimulationEventEmitter.session_event``/``run_event`` present to
#: producers (src/simulation/events.py, wired by #128).
StageSummaryEmitter = Callable[[str, Mapping[str, Any]], None]


def collect_stage_summary(packets: Sequence[T2miPacket]) -> dict[str, Any]:
    """Collect the ``t2mi.stage_summary`` payload from a packet stage.

    Pure and deterministic: same packet sequence → equal payload dict.
    Distribution dicts are ordered by first appearance (deterministic
    for a given packet order) and hold only content keys — identity and
    clock axes belong to the event envelope (ADR-0006).
    """
    packet_type_distribution: dict[str, int] = {}
    plp_distribution: dict[str, int] = {}
    padding_count = 0
    for packet in packets:
        kind = packet.payload_kind
        packet_type_distribution[kind] = packet_type_distribution.get(kind, 0) + 1
        if kind == PAYLOAD_KIND_PADDING:
            padding_count += 1
        plp_id = packet.plp_id
        if plp_id is not None:
            key = str(plp_id)
            plp_distribution[key] = plp_distribution.get(key, 0) + 1
    return {
        "packet_count": len(packets),
        "padding_count": padding_count,
        "packet_type_distribution": packet_type_distribution,
        "plp_distribution": plp_distribution,
    }


def emit_stage_summary(
    emitter: StageSummaryEmitter,
    payload: Mapping[str, Any],
) -> None:
    """Emit one ``t2mi.stage_summary`` event through the injected emitter.

    The event type is fixed here; the payload must carry exactly the
    :data:`STAGE_SUMMARY_PAYLOAD_KEYS` (misuse raises ``ValueError`` so a
    shape drift cannot reach the registry silently once #129 lands).
    Delivery decisions (coalescing, journal ordering) belong to the
    emitter layer, not to this module (§2bis envelope discipline).
    """
    if set(payload) != STAGE_SUMMARY_PAYLOAD_KEYS:
        raise ValueError(
            f"t2mi.stage_summary payload key drift: got {sorted(payload)}, "
            f"expected exactly {sorted(STAGE_SUMMARY_PAYLOAD_KEYS)}"
        )
    emitter(T2MI_STAGE_SUMMARY_EVENT_TYPE, dict(payload))
