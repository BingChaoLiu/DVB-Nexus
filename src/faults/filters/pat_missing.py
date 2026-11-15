"""SPEC-204 §6.1 — PAT_MISSING transform (Null 顶替 + 等位替换).

Window semantics (activation → run end): every PID-0 (PAT) packet slot is
replaced by a canonical Null packet (PID 0x1FFF, AFC 01, CC 0, 0xFF body —
the SPEC-107 §5.1 shape).  TS is a continuous packet sequence, so Null
顶替 is the only slot-preserving representation of "PAT missing": CBR and
the 188-byte invariant survive (§7), the slot count never changes.

§6.1 CC 重盖 clause: the window always runs to the run end under the MVP
activation model (ADR-0007 item 3 — "起于某 index 持续到 run 结束"), so
there is no PID-0 PAT *after* the window to re-cover; the clause has no
instance in the MVP and the PID-0 counter stays clean (single attributable
symptom: PAT absence, no secondary PID-0 continuity error).  The
``CCAllocator.reset(pid, next)`` semantics (SPEC-100 §5.4) remain the
frozen contract for a future windowed activation extension.

Parameter schema v1: ``{}`` (no extra parameters; the window is decided by
the activation).  PCR safety is a prepare/generator constraint (PCR_PID ∈
ES PID ≠ PID 0, SPEC-108 §5), so 顶替 never drops a PCR.
"""

from __future__ import annotations

from ts.packet import PID_NULL, PAYLOAD_ONLY_LENGTH, TSPacket

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform

__all__ = ["PatMissingTransform", "null_packet"]


def null_packet() -> TSPacket:
    """The canonical Null packet (SPEC-107 §5.1 shape, golden-oracle parity).

    Serializes to ``47 1F FF 10`` followed by 184 ``0xFF`` bytes.
    """
    return TSPacket(
        pid=PID_NULL,
        continuity_counter=0,
        payload=b"\xff" * PAYLOAD_ONLY_LENGTH,
    )


class PatMissingTransform(FaultTransform):
    """Replace every target-PID (PAT) slot in the window with a Null packet."""

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid != self.target.pid:
            return packet
        replacement = null_packet()
        self._record(
            index,
            packet,
            replacement,
            "PAT slot replaced by Null packet (PID 0x1FFF, 等位替换顶替; "
            "SPEC-204 §6.1)",
        )
        return replacement
