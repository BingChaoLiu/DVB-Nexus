"""SPEC-204 §6.3 — CC_DISCONTINUITY transform (relative-offset, persistent).

Relative-offset semantics (ADR-0007 item 5; absolute-value semantics are
deprecated — they depended on upstream scheduling details and broke with
generator version changes):

- **Landing**: the first payload-bearing packet of the target PID *after*
  the activation index (adaptation-only packets are skipped per the
  SPEC-100 §5.4 reuse rule and never land);
- the landing packet's CC becomes ``(expected_next + delta) mod 16`` with
  ``delta ∈ 1..15`` non-zero (``expected_next`` = the baseline's own
  contiguous value);
- the offset **persists**: subsequent payload packets continue +1 from the
  rewritten value (a real loss does not reset the counter);
- adaptation-only packets after the breakpoint keep the SPEC-100 §5.4
  reuse rule against the faulted stream's own last CC.

Every CC rewrite is in place (header half-byte only — 等位替换 §7).
Observation: ``ts.continuity_error`` located at the shared-frame landing
index.
"""

from __future__ import annotations

from dataclasses import replace

from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform

__all__ = ["CCDiscontinuityTransform"]


class CCDiscontinuityTransform(FaultTransform):
    """Persistent relative CC offset on the target PID (delta semantics)."""

    def __init__(self, definition: FaultDefinition) -> None:
        super().__init__(definition)
        delta = definition.parameters["delta"]
        # Registry-validated 1..15; the & 0x0F keeps the mod-16 arithmetic
        # explicit (wrap semantics, e.g. (15 + 3) mod 16).
        self._delta = delta & 0x0F
        # packet_index activation lands strictly *after* the activation
        # index ("activation index 之后"); session_start is active from the
        # very first packet.
        self._landing_from: int = (
            0
            if definition.activation.kind == "session_start"
            else definition.activation.packet_index + 1
        )
        self._landed = False
        self._last_faulted_cc: int | None = None

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid != self.target.pid:
            return packet
        has_payload = packet.payload is not None
        if not self._landed:
            if not (index >= self._landing_from and has_payload):
                return packet
            self._landed = True
        if has_payload:
            new_cc = (packet.continuity_counter + self._delta) & 0x0F
            self._last_faulted_cc = new_cc
            change = (
                f"cc {packet.continuity_counter} -> {new_cc} (delta "
                f"{self._delta}; relative offset persists, SPEC-204 §6.3)"
            )
        else:
            # Adaptation-only: reuse rule against the FAULTED stream's own
            # last CC (SPEC-100 §5.4).
            new_cc = self._last_faulted_cc
            if new_cc is None:  # pragma: no cover — landed implies a payload CC
                return packet
            change = (
                f"cc {packet.continuity_counter} -> {new_cc} "
                "(adaptation-only reuse against the faulted stream's last "
                "CC, SPEC-100 §5.4)"
            )
        after = replace(packet, continuity_counter=new_cc)
        self._record(index, packet, after, change)
        return after
