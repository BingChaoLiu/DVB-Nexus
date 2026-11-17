"""SPEC-601 §5/§6 / SPEC-303 §Phase2 — ``bbframe.*`` emission seams (#123).

The observation registry entries for ``bbframe.stage_summary`` and
``bbframe.recovery_failed`` land with #129 (ruling §10-7); until then
this module *reserves* the emission seams with the frozen payload shapes
so #128 can wire them into ``SimulationEventEmitter`` and #129 can
register the payload schemas verbatim.  The seams are emitter-injected
and pure — ``ts`` never imports ``simulation`` (ts purity, ADR-0005):
the emitter is any callable ``(event_type, payload) -> None``; identity
and clock axes belong to the event envelope (ADR-0006), so the payloads
here carry content keys only.

Payload keys (frozen, SPEC-601 §5):

``bbframe.stage_summary`` (per-stage completion):
- ``frame_count`` — total BBFRAMEs in the stage;
- ``n_ups_distribution`` — mapping user-packet count (decimal string) →
  frame count over the stage (the N_UPS 分布 face);
- ``stuffing_ratio`` — tail stuffing bytes / total data-field bytes
  (``0.0`` for an empty stage; the deterministic tail-padding rule makes
  this the visibility face of the #105 tail defect class).

``bbframe.recovery_failed`` (per-stage recovery evidence; the SPEC-307
BBHEADER_SYNC_FAULT rule's expected evidence symbol, #130):
- ``failure_count`` — frames whose CRC-8/MODE check failed (SPEC-601 §8
  ties this count to CRC-8 failures specifically; corrupt-style B2
  faults land here, shift-style faults stay CRC-valid and surface via
  the stage summary / misalignment states instead);
- ``first_failed_frame_index`` — frame index of the first CRC-8 failure
  (``None`` when the stage had none).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ts.t2mi.bbframe import BBFRAME_STATE_MALFORMED_SHORT, BBFrame

__all__ = [
    "BBFRAME_RECOVERY_FAILED_EVENT_TYPE",
    "BBFRAME_STAGE_SUMMARY_EVENT_TYPE",
    "RECOVERY_FAILED_PAYLOAD_KEYS",
    "STAGE_SUMMARY_PAYLOAD_KEYS",
    "StageSummaryEmitter",
    "collect_recovery_failed",
    "collect_stage_summary",
    "emit_recovery_failed",
    "emit_stage_summary",
]

#: The registered event types (SPEC-303 §Phase2; registry entries land #129).
BBFRAME_STAGE_SUMMARY_EVENT_TYPE = "bbframe.stage_summary"
BBFRAME_RECOVERY_FAILED_EVENT_TYPE = "bbframe.recovery_failed"

#: Frozen payload key sets (ruling §10-7: 签名与 payload 键照票卡定死).
STAGE_SUMMARY_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"frame_count", "n_ups_distribution", "stuffing_ratio"}
)
RECOVERY_FAILED_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"failure_count", "first_failed_frame_index"}
)

#: Emitter seam shape: ``(event_type, payload) -> None`` — the shape
#: ``SimulationEventEmitter.session_event``/``run_event`` present to
#: producers (src/simulation/events.py, wired by #128).
StageSummaryEmitter = Callable[[str, Mapping[str, Any]], None]


def collect_stage_summary(frames: Sequence[BBFrame]) -> dict[str, Any]:
    """Collect the ``bbframe.stage_summary`` payload from a frame stage.

    Pure and deterministic: same frame sequence → equal payload dict.
    The distribution maps each frame's ``up_count`` (decimal string) to
    its frame count; ``stuffing_ratio`` is the ratio of tail stuffing to
    total data-field bytes (``0.0`` when the stage holds no frames).
    """
    n_ups_distribution: dict[str, int] = {}
    total_data_field = 0
    total_stuffing = 0
    for frame in frames:
        key = str(frame.up_count)
        n_ups_distribution[key] = n_ups_distribution.get(key, 0) + 1
        total_data_field += len(frame.data_field)
        total_stuffing += frame.stuffing_bytes
    ratio = total_stuffing / total_data_field if total_data_field else 0.0
    return {
        "frame_count": len(frames),
        "n_ups_distribution": n_ups_distribution,
        "stuffing_ratio": ratio,
    }


def collect_recovery_failed(frames: Sequence[BBFrame]) -> dict[str, Any]:
    """Collect the ``bbframe.recovery_failed`` payload from a frame stage.

    Failure = the CRC-8/MODE check failed (``crc8_valid=False``) or the
    frame cannot even hold a BBHEADER (``malformed_short`` — same
    untrustworthy-header face).  Pure and deterministic; the first
    failure's frame index is ``None`` when the stage is clean.
    """
    failure_indexes = [
        index
        for index, frame in enumerate(frames)
        if not frame.crc8_valid
        or frame.state == BBFRAME_STATE_MALFORMED_SHORT
    ]
    return {
        "failure_count": len(failure_indexes),
        "first_failed_frame_index": failure_indexes[0] if failure_indexes else None,
    }


def emit_stage_summary(
    emitter: StageSummaryEmitter,
    payload: Mapping[str, Any],
) -> None:
    """Emit one ``bbframe.stage_summary`` event through the injected emitter.

    The event type is fixed here; the payload must carry exactly the
    :data:`STAGE_SUMMARY_PAYLOAD_KEYS` (misuse raises ``ValueError`` so a
    shape drift cannot reach the registry silently once #129 lands).
    """
    if set(payload) != STAGE_SUMMARY_PAYLOAD_KEYS:
        raise ValueError(
            f"bbframe.stage_summary payload key drift: got {sorted(payload)}, "
            f"expected exactly {sorted(STAGE_SUMMARY_PAYLOAD_KEYS)}"
        )
    emitter(BBFRAME_STAGE_SUMMARY_EVENT_TYPE, dict(payload))


def emit_recovery_failed(
    emitter: StageSummaryEmitter,
    payload: Mapping[str, Any],
) -> None:
    """Emit one ``bbframe.recovery_failed`` event through the injected emitter.

    Same shape discipline as :func:`emit_stage_summary` against
    :data:`RECOVERY_FAILED_PAYLOAD_KEYS`.
    """
    if set(payload) != RECOVERY_FAILED_PAYLOAD_KEYS:
        raise ValueError(
            f"bbframe.recovery_failed payload key drift: got {sorted(payload)}, "
            f"expected exactly {sorted(RECOVERY_FAILED_PAYLOAD_KEYS)}"
        )
    emitter(BBFRAME_RECOVERY_FAILED_EVENT_TYPE, dict(payload))
