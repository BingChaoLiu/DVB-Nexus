"""SPEC-204 §6.2 — PMT_INVALID_CRC transform (CRC-only corruption).

Only the 4 CRC bytes of the selected PMT section instances change (section
length unchanged — 等位替换原位改 4 字节, §7).  Parameters (schema v1,
defaults per #9/ADR-0007 item 5):

- ``mode``: ``"once"`` = the first PMT instance from the activation index;
  ``"persistent"`` = every instance from the activation on (default — a
  one-shot CRC error is washed out by the next correct table, the symptom
  is unstable);
- ``corruption``: ``"invert"`` = XOR every CRC byte with 0xFF (default);
  ``"zero"`` = clear the CRC bytes.

Section framing follows the SPEC-102 PSI wire layout (pointer_field on
PUSI packets, ``section_length`` in the 3-byte header, CRC as the last 4
section bytes).  A section that fragments across packets has its CRC tail
carried by the following packets of the same PID — the transform tracks
the pending CRC byte positions in the PID's payload stream so persistent
corruption stays byte-exact for fragmented PMTs too.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.filters.base import FaultTransform, psi_section_header

__all__ = ["PmtInvalidCrcTransform"]

_CORRUPTIONS = {"invert", "zero"}


class PmtInvalidCrcTransform(FaultTransform):
    """Corrupt the CRC field of PMT section instances (mode/corruption)."""

    def __init__(self, definition: FaultDefinition) -> None:
        super().__init__(definition)
        parameters: Mapping[str, Any] = definition.parameters
        self._mode: str = parameters.get("mode", "persistent")
        self._corruption: str = parameters.get("corruption", "invert")
        assert self._corruption in _CORRUPTIONS  # registry-validated
        self._instances_done = 0
        # Payload-byte skips until each pending CRC byte, relative to the
        # start of the target PID's next payload chunk (fragmented sections).
        self._pending_crc_bytes: list[int] = []

    def _corrupt_byte(self, byte: int) -> int:
        if self._corruption == "invert":
            return byte ^ 0xFF
        return 0x00

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid != self.target.pid:
            return packet
        payload = packet.payload
        if payload is None:
            # Adaptation-only slot: no payload stream, pending bytes wait on.
            return packet
        buffer = bytearray(payload)
        mutated_positions: list[int] = []

        # 1. consume CRC-tail bytes scheduled by earlier fragmented sections.
        still_pending: list[int] = []
        for skip in self._pending_crc_bytes:
            if skip < len(buffer):
                buffer[skip] = self._corrupt_byte(buffer[skip])
                mutated_positions.append(skip)
            else:
                still_pending.append(skip - len(buffer))
        self._pending_crc_bytes = still_pending

        # 2. a PUSI packet starts a new PMT instance (pointer_field framed).
        if packet.payload_unit_start_indicator and (
            self._mode == "persistent" or self._instances_done == 0
        ):
            header = psi_section_header(buffer)
            if header is not None:
                start, section_length = header
                crc_offset = start + 3 + section_length - 4
                for offset in range(crc_offset, crc_offset + 4):
                    if offset < len(buffer):
                        buffer[offset] = self._corrupt_byte(buffer[offset])
                        mutated_positions.append(offset)
                    else:
                        self._pending_crc_bytes.append(offset - len(buffer))
                self._instances_done += 1

        if not mutated_positions:
            return packet
        after = replace(packet, payload=bytes(buffer))
        self._record(
            index,
            packet,
            after,
            f"PMT section CRC corrupted ({self._corruption}, mode="
            f"{self._mode}; {len(mutated_positions)} CRC byte(s) in this "
            "slot; section length unchanged, SPEC-204 §6.2)",
        )
        return after
