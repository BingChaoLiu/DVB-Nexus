"""SPEC-204 §6.4 — PMT_PID_MISMATCH transform (repoint PAT, CRC recomputed).

The PAT's ``program_map_PID`` is rewritten to ``wrong_pmt_pid`` (13-bit,
non-reserved, ≠ the actual pmt_pid — prepare-validated) and the PAT CRC is
**recomputed** with the SPEC-101 CRC-32/MPEG-2 core: the PAT itself stays
valid, the symptom is "points wrong", not "CRC bad" (symptom separation
from PMT_INVALID_CRC).  The PMT stays on its real PID (orphan PMT).  The
rewrite is in place and section-length preserving (等长重打包, §7).

Program-loop entries carry reserved bits above the 13-bit PID — they are
preserved verbatim (SPEC-103 §7 "可保留原始值"); ``program_number == 0``
entries are the network_PID pointer and are never rewritten.
"""

from __future__ import annotations

from dataclasses import replace

from ts.crc import mpeg2_crc32
from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.errors import FaultExecutionError
from faults.filters.base import FaultTransform

__all__ = ["PmtPidMismatchTransform"]

#: PSI section layout constants (SPEC-102/103 framing).
_PAT_TABLE_ID = 0x00
_HEADER_BYTES = 8  # table_id .. last_section_number before the program loop
_ENTRY_BYTES = 4


class PmtPidMismatchTransform(FaultTransform):
    """Repoint every PAT program entry to ``wrong_pmt_pid`` (CRC valid)."""

    def __init__(self, definition: FaultDefinition) -> None:
        super().__init__(definition)
        self._wrong_pid: int = definition.parameters["wrong_pmt_pid"]

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid != self.target.pid:
            return packet
        payload = packet.payload
        if payload is None or not packet.payload_unit_start_indicator:
            return packet
        start = 1 + payload[0]  # pointer_field offset (PUSI payload)
        if start + 3 > len(payload):
            return packet  # not enough header bytes: leave the slot alone
        if payload[start] != _PAT_TABLE_ID:
            return packet  # a PSI section on PID 0 that is not a PAT
        section_length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
        end = start + 3 + section_length
        if end > len(payload):
            raise FaultExecutionError(
                "SIM_FAULT_EXEC_FAILED: the PAT section starting at packet "
                f"index {index} fragments across packets "
                f"({end - len(payload)} byte(s) continue past the slot); "
                "the MVP slot-preserving rewriter cannot repack a "
                "fragmented PAT in place (SPEC-204 §11)"
            )
        section = bytearray(payload[start:end])
        crc_offset = len(section) - 4
        changes: list[str] = []
        offset = _HEADER_BYTES
        while offset + _ENTRY_BYTES <= crc_offset:
            program_number = int.from_bytes(section[offset : offset + 2], "big")
            if program_number != 0:
                old_pid = (
                    (section[offset + 2] & 0x1F) << 8
                ) | section[offset + 3]
                section[offset + 2] = (section[offset + 2] & 0xE0) | (
                    (self._wrong_pid >> 8) & 0x1F
                )
                section[offset + 3] = self._wrong_pid & 0xFF
                changes.append(
                    f"program {program_number} pmt_pid {old_pid:#06x} -> "
                    f"{self._wrong_pid:#06x}"
                )
            offset += _ENTRY_BYTES
        if not changes:
            return packet
        recomputed = mpeg2_crc32(bytes(section[:crc_offset]))
        section[crc_offset:] = recomputed.to_bytes(4, "big")
        buffer = bytearray(payload)
        buffer[start:end] = section
        after = replace(packet, payload=bytes(buffer))
        self._record(
            index,
            packet,
            after,
            "PAT program_map_PID rewritten ("
            + "; ".join(changes)
            + "); PAT CRC recomputed — PAT stays valid, symptom is "
            "'points wrong' (SPEC-204 §6.4)",
        )
        return after
