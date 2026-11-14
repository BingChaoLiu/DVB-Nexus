"""SPEC-106 §5 — PSI section to TS packet framing (ticket #32).

:class:`SectionPacketizer` is the one-way framing layer from a complete PSI
section (SPEC-102 verified/serialized bytes or a :class:`ts.section.PSISection`
object whose ``raw_bytes`` are the byte-level authority) to 188-byte TS
packets (SPEC-100). Framing rules (SPEC-106 §5):

- One section per run, starting on a fresh packet (MVP efficiency trade-off,
  §12): the first packet carries ``PUSI=1`` and ``pointer_field=0``, so the
  section data starts at payload offset 1; continuation packets carry
  ``PUSI=0`` and no pointer field.
- First-packet section capacity is 183 bytes (payload 184 with the pointer);
  continuation packets carry up to 184 bytes; the last packet's remainder is
  padded with Adaptation Field stuffing (§5.2 recommends AF stuffing over
  ``0xFF`` PSI payload stuffing so the SectionAssembler cannot mistake the
  padding for a next section).
- Section bytes are never truncated, reordered or interleaved with stuffing
  bytes; CC allocation is delegated to the caller's SPEC-100 ``CCAllocator``
  for every packet (contract §9 — no second counting rule here).
- Null packets are Mux-owned (§8): PID 0x1FFF is rejected at construction.

Error codes (SPEC-106 §9, via :mod:`ts.packetizer.codes`):
``PACKETIZER_PID_INVALID`` / ``PACKETIZER_EMPTY_SECTION`` /
``PACKETIZER_SECTION_HEADER_INVALID`` — all raised as
:class:`ts.errors.PacketizationError`. PSISection objects are trusted
(their constructor guarantees raw/header coherence); raw bytes input is
validated before framing.
"""

from __future__ import annotations

from typing import Iterator

from ts._bytesutil import _BYTES_LIKE, PID_MAX
from ts.cc import CCAllocator
from ts.errors import PacketizationError
from ts.packet import PID_NULL, TSPacket
from ts.section import PSISection

from ts.packetizer.codes import (
    PACKETIZER_EMPTY_SECTION,
    PACKETIZER_PID_INVALID,
    PACKETIZER_SECTION_HEADER_INVALID,
)
from ts.packetizer.stuffing import (
    PAYLOAD_ONLY_LENGTH,
    build_adaptation_field,
    emit_verified_packet,
)

_SECTION_HEADER_SIZE = 3
#: Section bytes the first packet can carry next to the pointer field (§5.2).
_FIRST_PACKET_SECTION_CAPACITY = PAYLOAD_ONLY_LENGTH - 1  # 183
#: Section bytes a continuation packet can carry (§5.2).
_CONTINUATION_CAPACITY = PAYLOAD_ONLY_LENGTH  # 184


def validate_packetizer_pid(pid: int) -> int:
    """Validate a packetizer PID argument (shared by both packetizers).

    Raises ``TypeError`` for non-integers (programming error) and
    ``PacketizationError(PACKETIZER_PID_INVALID)`` for out-of-range or null
    PIDs (§8: null packets belong to the Mux, not to a payload packetizer).
    """
    if isinstance(pid, bool) or not isinstance(pid, int):
        raise TypeError(f"pid must be int, got {type(pid).__name__}")
    if not 0 <= pid <= PID_MAX or pid == PID_NULL:
        raise PacketizationError(
            f"{PACKETIZER_PID_INVALID}: pid must be in 0..{PID_MAX} "
            f"(13-bit) and must not be the null PID 0x{PID_NULL:04X} "
            "(null packets are owned by the Mux, SPEC-106 §8), got "
            f"{pid}"
        )
    return pid


class SectionPacketizer:
    """Frame one complete PSI section into 188-byte TS packets (§4/§5)."""

    def __init__(self, pid: int, cc_allocator: CCAllocator) -> None:
        """Bind the packetizer to one PID and one SPEC-100 CC allocator.

        The allocator is the only CC state authority (contract §9): whether
        CC state carries across :meth:`packetize` runs is entirely the
        caller's allocator lifecycle — this instance itself keeps no CC
        state (SPEC-106 §3).
        """
        self._pid = validate_packetizer_pid(pid)
        if not isinstance(cc_allocator, CCAllocator):
            raise TypeError(
                f"cc_allocator must be CCAllocator, got "
                f"{type(cc_allocator).__name__}"
            )
        self._cc_allocator = cc_allocator

    @property
    def pid(self) -> int:
        """The PID every packetized packet carries."""
        return self._pid

    def packetize(self, section: PSISection | bytes) -> Iterator[TSPacket]:
        """Frame ``section`` into an iterator of 188-byte packets (§5).

        ``PSISection`` objects frame their ``raw_bytes`` (§4 immutable raw
        echo); bytes-like input must be exactly one complete section — the
        declared ``section_length`` field has to match the actual byte
        count. Validation happens eagerly at call time; the returned
        iterator then yields the fully constructed packets. Every packet's
        CC comes from ``cc_allocator.allocate(pid, has_payload=True)``
        (section packets always carry payload).
        """
        if isinstance(section, PSISection):
            data = section.raw_bytes
        elif isinstance(section, _BYTES_LIKE):
            data = self._validate_section_bytes(bytes(section))
        else:
            raise TypeError(
                f"section must be PSISection or bytes, got "
                f"{type(section).__name__}"
            )
        packets: list[TSPacket] = []
        first_take = min(len(data), _FIRST_PACKET_SECTION_CAPACITY)
        chunks = [data[:first_take]]
        rest = data[first_take:]
        while rest:
            take = min(len(rest), _CONTINUATION_CAPACITY)
            chunks.append(rest[:take])
            rest = rest[take:]
        for index, chunk in enumerate(chunks):
            # First payload = pointer_field(0) + section data; continuation
            # payloads carry section data only (§5.1).
            payload = b"\x00" + chunk if index == 0 else chunk
            af = build_adaptation_field(len(payload))
            cc = self._cc_allocator.allocate(self._pid, has_payload=True)
            packets.append(
                emit_verified_packet(
                    self._pid,
                    cc,
                    payload,
                    af,
                    payload_unit_start_indicator=index == 0,
                )
            )
        return iter(packets)

    @staticmethod
    def _validate_section_bytes(data: bytes) -> bytes:
        """Raw-bytes precondition: exactly one complete section (§5.2)."""
        if len(data) == 0:
            raise PacketizationError(
                f"{PACKETIZER_EMPTY_SECTION}: section input is empty"
            )
        if len(data) < _SECTION_HEADER_SIZE:
            raise PacketizationError(
                f"{PACKETIZER_SECTION_HEADER_INVALID}: a PSI section needs "
                f"at least {_SECTION_HEADER_SIZE} header bytes, got "
                f"{len(data)}"
            )
        declared = ((data[1] & 0x0F) << 8) | data[2]
        if len(data) != _SECTION_HEADER_SIZE + declared:
            raise PacketizationError(
                f"{PACKETIZER_SECTION_HEADER_INVALID}: declared "
                f"section_length {declared} implies "
                f"{_SECTION_HEADER_SIZE + declared} total bytes, got "
                f"{len(data)} (the MVP packetizer frames exactly one "
                "complete section per run, SPEC-106 §5.2)"
            )
        return data


__all__ = [
    "SectionPacketizer",
    "validate_packetizer_pid",
]
