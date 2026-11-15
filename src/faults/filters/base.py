"""Fault transform base: slot-preserving rewriters + mutation records.

Every MVP fault transform is a **slot-preserving substitution** (ADR-0007
item 4 / SPEC-204 §7): ``apply(index, packet)`` maps one packet at shared
frame index ``index`` to exactly one packet at the same index — no
insertion, no removal — operating on the ``ts.packet.TSPacket`` object
model before serialization (semantic stream filter, ADR-0007 item 1).

Each actual byte change appends one :class:`MutationRecord` (SPEC-204
§8.2 evidence locator: fault identity, shared-frame packet index,
before/after packet summaries, effective parameters + schema version).
The semantic filter (:mod:`faults.filters.semantic`) aggregates the
records into the mutation log artifact.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from ts.packet import TSPacket

from faults.definition import FaultDefinition
from faults.targets import FaultTarget, parse_target_id

__all__ = [
    "FaultTransform",
    "MutationRecord",
    "psi_section_header",
    "summarize_packet",
]


@dataclass(frozen=True)
class MutationRecord:
    """One actual transformation (SPEC-204 §8.2 mutation log record)."""

    fault_id: str
    fault_type: str
    target_node_id: str
    target_pid: int
    packet_index: int
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    change: str
    parameters: Mapping[str, Any]
    parameters_schema_version: int


def summarize_packet(packet: TSPacket) -> dict[str, Any]:
    """Offline-verifiable packet slot summary (header + slot digest).

    The SHA-256 over the serialized 188 bytes lets any consumer re-derive
    the slot from either artifact (generated_ts / faulted_ts share the
    packet frame), and the header fields identify the changed wire field.
    """
    return {
        "pid": packet.pid,
        "continuity_counter": packet.continuity_counter,
        "afc": int(packet.adaptation_field_control),
        "pusi": packet.payload_unit_start_indicator,
        "slot_sha256": hashlib.sha256(packet.to_bytes()).hexdigest(),
    }


def psi_section_header(payload: "bytes | bytearray") -> "tuple[int, int] | None":
    """Decode the first PSI section header of a PUSI payload slot.

    SPEC-102 PSI framing: byte 0 of a payload_unit_start_indicator payload
    is the ``pointer_field``; the section starts at ``1 + pointer_field``
    and its 3-byte header is table_id + a 12-bit ``section_length`` (the
    reserved high nibble of the length byte is masked off). Returns
    ``(section_start, section_length)``, or ``None`` when the slot does not
    hold the full header. Shared by the PSI-header rewriter transforms
    (M3 review-fix #5: the pointer/length arithmetic lived duplicated in
    PMT_INVALID_CRC and PMT_PID_MISMATCH); byte-level transform behavior
    is unchanged — the oracle golden pair stays the authority.
    """
    start = 1 + payload[0]
    if start + 3 > len(payload):
        return None
    return start, ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]


class FaultTransform:
    """Base class for one registered fault's stream transform.

    Subclasses implement :meth:`transform` (packet → packet for one
    shared-frame index) and call :meth:`_record` for every actual change.
    Activation semantics: ``packet_index`` activation is "from that index
    through run end"; ``session_start`` is the whole run (ADR-0007 item 3).
    """

    def __init__(self, definition: FaultDefinition) -> None:
        self._definition = definition
        self.target: FaultTarget = parse_target_id(definition.target_id)
        #: Activation index on the shared frame (0 = from the stream start).
        self.activation_index: int = (
            0
            if definition.activation.kind == "session_start"
            else definition.activation.packet_index
        )
        self.records: list[MutationRecord] = []

    def apply(self, index: int, packet: TSPacket) -> TSPacket:
        """Public filter hook: never records anything for untouched slots."""
        if index < self.activation_index:
            return packet
        return self.transform(index, packet)

    def transform(self, index: int, packet: TSPacket) -> TSPacket:
        raise NotImplementedError  # pragma: no cover — abstract

    def _record(
        self,
        index: int,
        before: TSPacket,
        after: TSPacket,
        change: str,
    ) -> None:
        self.records.append(
            MutationRecord(
                fault_id=self._definition.fault_id,
                fault_type=self._definition.fault_type,
                target_node_id=self.target.node_id,
                target_pid=self.target.pid if self.target.pid is not None else -1,
                packet_index=index,
                before=summarize_packet(before),
                after=summarize_packet(after),
                change=change,
                parameters=dict(self._definition.parameters),
                parameters_schema_version=1,
            )
        )

    @property
    def applied_packet_indexes(self) -> tuple[int, ...]:
        """Shared-frame indexes where fault bytes actually entered the flow."""
        return tuple(record.packet_index for record in self.records)
