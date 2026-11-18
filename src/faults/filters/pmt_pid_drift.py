"""SPEC-204 §Phase2 item 4 — PMT_PID_DRIFT transform (declaration drift).

The per-program, mid-stream evolution of PMT_PID_MISMATCH (ticket #139,
SC-09 — the C2 TS-layer equivalent, honestly scoped: the CA 全貌 belongs to
SPEC-612).  From the activation index the **declaration face** drifts while
the data keeps flowing on the real PIDs:

- **PAT face** (``new_pid_map``): every mapped program's ``program_map_PID``
  is rewritten to its drifted pmt_pid (13-bit, non-reserved, ≠-checked by
  the registry validator — prepare-trusted here); the PAT CRC is
  **recomputed** so the declaration stays valid.  ``program_number == 0``
  entries (the network_PID pointer) are never rewritten; loop-entry
  reserved bits above the 13-bit PID are preserved verbatim (SPEC-103 §7).
- **PMT version face** (``pmt_version_bump``): the PMT's
  ``version_number`` bumps +1 (mod 32) — reserved bits and
  ``current_next_indicator`` preserved — with the CRC recomputed.  The
  drift is a legal declaration update: the wire stays parseable, the
  symptom is "declared vs received drift" (PSI version comparison + the
  newly declared PID carries no data — 声明 PID 无数据漂移), never a CRC
  break.

Both faces are in place and section-length preserving (等位重打包, §7);
each actual change appends one :class:`MutationRecord` (SPEC-204 §8.2 —
the change label names the face).  A section claiming more bytes than its
slot holds fragments across packets: the MVP slot-preserving rewriter
cannot repack it in place, so it fails loudly as ``SIM_FAULT_EXEC_FAILED``
(same discipline as PMT_PID_MISMATCH, SPEC-204 §11).

The registry (#121/#131) validates the parameter face before any transform
is built — digit-string program keys are coerced there; this module mirrors
that coercion for its own map lookups so a Python-side direct construction
sees one behavior.
"""

from __future__ import annotations

from dataclasses import replace

from ts.crc import mpeg2_crc32
from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.errors import FaultExecutionError
from faults.factory import register_transform
from faults.filters.base import FaultTransform, psi_section_header
from faults.registry import (
    FAULT_TYPE_PMT_PID_DRIFT,
    PARAMETERS_SCHEMA_VERSION,
)

__all__ = ["PmtPidDriftTransform"]

#: PSI section layout constants (SPEC-102/103 framing).
_PAT_TABLE_ID = 0x00
_PMT_TABLE_ID = 0x02
_PAT_PID = 0x0000
_HEADER_BYTES = 8  # table_id .. last_section_number before the program loop
_ENTRY_BYTES = 4

#: Long-form public header byte 5: reserved '11' + version<<1 +
#: current_next_indicator — the byte the version face rewrites.  The
#: reserved bits and current_next ride verbatim (SPEC-103 §7 保留纪律).
_VERSION_LOWEST_BIT = 0b0000_0001
_VERSION_PRESERVED_BITS = 0b1100_0001
_VERSION_BYTE_OFFSET = 5


class PmtPidDriftTransform(FaultTransform):
    """Drift the PSI declaration faces from the activation index onward.

    Slot-preserving at the shared frame: the PAT instances carry the
    drifted ``program_map_PID`` per ``new_pid_map`` and the PMT instances
    on the target pid carry the bumped version — everything else passes
    untouched, and the data never moves (the declared PID's no-data face
    is the symptom the DIA-PMT-PID-DRIFT rule reads via the analysis
    bridge's PSI version comparison).
    """

    LAYER = "TS"

    def __init__(self, definition: FaultDefinition) -> None:
        super().__init__(definition)
        raw_map = definition.parameters["new_pid_map"]
        # Mirror the registry validator's wire-face coercion (digit-string
        # JSON keys → int program numbers) so both construction paths see
        # one behavior.
        self._pid_map: dict[int, int] = {
            int(key) if isinstance(key, str) else key: value
            for key, value in raw_map.items()
        }
        self._version_bump: bool = definition.parameters["pmt_version_bump"]

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.pid == _PAT_PID:
            return self._drift_pat(index, packet)
        if self._version_bump and packet.pid == self.target.pid:
            return self._bump_pmt_version(index, packet)
        return packet

    # --- the declaration face: PAT program_map_PID drift -------------------------

    def _drift_pat(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.payload is None or not packet.payload_unit_start_indicator:
            return packet
        header = psi_section_header(packet.payload)
        if header is None:
            return packet  # not enough header bytes: leave the slot alone
        start, section_length = header
        if packet.payload[start] != _PAT_TABLE_ID:
            return packet  # a PSI section on PID 0 that is not a PAT
        end = start + 3 + section_length
        if end > len(packet.payload):
            raise FaultExecutionError(
                "SIM_FAULT_EXEC_FAILED: the PAT section starting at packet "
                f"index {index} fragments across packets "
                f"({end - len(packet.payload)} byte(s) continue past the "
                "slot); the MVP slot-preserving rewriter cannot repack a "
                "fragmented PAT in place (SPEC-204 §11)"
            )
        section = bytearray(packet.payload[start:end])
        crc_offset = len(section) - 4
        changes: list[str] = []
        offset = _HEADER_BYTES
        while offset + _ENTRY_BYTES <= crc_offset:
            program_number = int.from_bytes(section[offset : offset + 2], "big")
            drifted_pid = self._pid_map.get(program_number)
            if drifted_pid is not None:
                old_pid = (
                    (section[offset + 2] & 0x1F) << 8
                ) | section[offset + 3]
                section[offset + 2] = (section[offset + 2] & 0xE0) | (
                    (drifted_pid >> 8) & 0x1F
                )
                section[offset + 3] = drifted_pid & 0xFF
                changes.append(
                    f"program {program_number} pmt_pid {old_pid:#06x} -> "
                    f"{drifted_pid:#06x}"
                )
            offset += _ENTRY_BYTES
        if not changes:
            return packet
        recomputed = mpeg2_crc32(bytes(section[:crc_offset]))
        section[crc_offset:] = recomputed.to_bytes(4, "big")
        buffer = bytearray(packet.payload)
        buffer[start:end] = section
        after = replace(packet, payload=bytes(buffer))
        self._record(
            index,
            packet,
            after,
            "PAT program_map_PID drifted ("
            + "; ".join(changes)
            + "); PAT CRC recomputed — the declared PID carries no data, "
            "the drift is semantic (SPEC-204 §Phase2 item 4)",
        )
        return after

    # --- the version face: PMT version bump ---------------------------------------

    def _bump_pmt_version(self, index: int, packet: TSPacket) -> TSPacket:
        if packet.payload is None or not packet.payload_unit_start_indicator:
            return packet
        header = psi_section_header(packet.payload)
        if header is None:
            return packet  # not enough header bytes: leave the slot alone
        start, section_length = header
        if packet.payload[start] != _PMT_TABLE_ID:
            return packet  # a PSI section on the target pid that is not a PMT
        end = start + 3 + section_length
        if end > len(packet.payload):
            raise FaultExecutionError(
                "SIM_FAULT_EXEC_FAILED: the PMT section starting at packet "
                f"index {index} fragments across packets "
                f"({end - len(packet.payload)} byte(s) continue past the "
                "slot); the MVP slot-preserving rewriter cannot repack a "
                "fragmented PMT in place (SPEC-204 §11)"
            )
        section = bytearray(packet.payload[start:end])
        crc_offset = len(section) - 4
        # the version byte rides the long-form public header (section byte
        # 5: reserved '11' + version<<1 + current_next, SPEC-103 §4)
        version_byte = section[_VERSION_BYTE_OFFSET]
        old_version = (version_byte >> 1) & 0x1F
        new_version = (old_version + 1) & 0x1F
        section[_VERSION_BYTE_OFFSET] = (
            version_byte & _VERSION_PRESERVED_BITS
        ) | (new_version << 1)
        recomputed = mpeg2_crc32(bytes(section[:crc_offset]))
        section[crc_offset:] = recomputed.to_bytes(4, "big")
        buffer = bytearray(packet.payload)
        buffer[start:end] = section
        after = replace(packet, payload=bytes(buffer))
        self._record(
            index,
            packet,
            after,
            f"PMT version bumped {old_version} -> {new_version} (reserved "
            "bits + current_next preserved); PMT CRC recomputed — a legal "
            "declaration update the demux filter has not followed "
            "(SPEC-204 §Phase2 item 4)",
        )
        return after


# --- self-registration (ruling §10-4 — factory.py is never edited again) ---------

register_transform(FAULT_TYPE_PMT_PID_DRIFT, PmtPidDriftTransform)
