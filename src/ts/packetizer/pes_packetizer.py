"""SPEC-106 §6 — PES byte sequence to TS packet framing (ticket #32).

:class:`PESPacketizer` frames one complete PES packet (SPEC-104 serialized
bytes or a :class:`ts.pes.PESPacket` object) into 188-byte TS packets
(SPEC-100). Framing rules (SPEC-106 §6):

- The PES's first TS packet carries ``PUSI=1``; continuation packets carry
  ``PUSI=0``; no PSI pointer field is ever inserted into PES payloads.
- The PES byte sequence stays contiguous: stuffing lives exclusively in
  adaptation fields, never between PES bytes, and the last packet's
  remainder is padded to 188 with AF stuffing (§6/§7).
- ``random_access`` and ``first_packet_pcr`` are caller decisions (§6: the
  packetizer never guesses access-unit boundaries). The PCR — if requested
  — rides the FIRST packet's AF (AFC=11); mid-PES PCR attachment is out of
  MVP scope (§2, ruling #11).
- Single-packet PES framing failure (§6: 若 AF 空间不足，配置应失败而不是
  覆盖 PES bytes): a PES that fits one packet (≤ 184 bytes) keeps its full
  payload; a requested PCR needs ``adaptation_field_length >= 7`` (PES
  ≤ 176) and a random-access flag needs ``>= 1`` (PES ≤ 182) — otherwise
  the run fails with ``PACKETIZER_PCR_DOES_NOT_FIT`` /
  ``PACKETIZER_AF_CAPACITY_EXCEEDED`` instead of shrinking or overwriting
  PES bytes. Multi-packet PES (≥ 185 bytes) frames the first packet at
  ``183 - required_af`` payload bytes and continues with 184-byte payloads;
  continuation packets are intrinsic to a multi-packet PES, so no policy
  decision is involved there.
- CC allocation is delegated to the caller's SPEC-100 ``CCAllocator`` for
  every packet (contract §9); null packets are Mux-owned (§8).

``build_pcr_only_packet`` is the single construction authority for
adaptation-only PCR packets (ruling #11 tri-party clause: PCR value =
SPEC-105, insertion timing = SPEC-107, construction = SPEC-106): AFC=10,
the AF occupies the full 184 post-header bytes (length byte 183 + flags +
6-byte PCR + 176 x 0xFF stuffing), and the CC reuses the PID's most recent
counter without advancing (SPEC-100 CCAllocator adaptation-only semantics).

Error codes (SPEC-106 §9, via :mod:`ts.packetizer.codes`):
``PACKETIZER_PID_INVALID`` / ``PACKETIZER_EMPTY_PES`` /
``PACKETIZER_PES_HEADER_INVALID`` / ``PACKETIZER_AF_CAPACITY_EXCEEDED`` /
``PACKETIZER_PCR_DOES_NOT_FIT`` — raised as
:class:`ts.errors.PacketizationError`. ``PESPacket`` serialization failures
keep SPEC-104's own ``InvalidPESPacketError`` family (each module owns its
codes); raw bytes input is header-validated before framing.
"""

from __future__ import annotations

from typing import Iterator

from ts._bytesutil import _BYTES_LIKE
from ts.adaptation_field import AdaptationField
from ts.cc import CCAllocator
from ts.errors import PacketizationError
from ts.packet import TSPacket
from ts.pcr import PCR
from ts.pes import PESPacket, serialize_pes

from ts.packetizer.codes import (
    PACKETIZER_AF_CAPACITY_EXCEEDED,
    PACKETIZER_EMPTY_PES,
    PACKETIZER_PCR_DOES_NOT_FIT,
    PACKETIZER_PES_HEADER_INVALID,
)
from ts.packetizer.section_packetizer import validate_packetizer_pid
from ts.packetizer.stuffing import (
    PAYLOAD_ONLY_LENGTH,
    ZERO_AF_PAYLOAD_LENGTH,
    build_adaptation_field,
    emit_verified_packet,
)

__all__ = [
    "PESPacketizer",
    "build_pcr_only_packet",
]

#: packet_start_code_prefix (ITU-T H.222.0; every PES stream_id carries it).
_START_CODE_PREFIX = b"\x00\x00\x01"
#: Bytes that must exist before the length field can be read at all.
_MIN_PES_HEADER_BYTES = 6


def build_pcr_only_packet(pid: int, pcr: PCR, cc_allocator: CCAllocator) -> TSPacket:
    """Construct the one adaptation-only PCR packet for ``pid`` (ruling #11).

    The unique construction authority invoked by SPEC-107 when the PCR
    schedule needs a packet without PES payload: AFC=10, the AF fills all
    184 post-header bytes (``adaptation_field_length=183``; flags + 6-byte
    PCR from SPEC-105's encoding + ``0xFF`` stuffing), and the CC reuses
    the PID's most recent counter WITHOUT advancing — the SPEC-100
    ``CCAllocator`` adaptation-only rule, invoked with ``has_payload=False``
    so no second counting rule appears here (contract §9). The Mux calls
    this builder; it never assembles or modifies an AF itself.

    The PCR ``value`` and the insertion *timing* are the caller's (SPEC-105
    / SPEC-107 respectively); this function only performs the construction.
    """
    valid_pid = validate_packetizer_pid(pid)
    if not isinstance(pcr, PCR):
        raise TypeError(f"pcr must be ts.pcr.PCR, got {type(pcr).__name__}")
    if not isinstance(cc_allocator, CCAllocator):
        raise TypeError(
            f"cc_allocator must be CCAllocator, got {type(cc_allocator).__name__}"
        )
    # Adaptation-only: reuse the PID's current CC, never advance it (§8).
    cc = cc_allocator.allocate(valid_pid, has_payload=False)
    af = AdaptationField(pcr=pcr)
    return emit_verified_packet(valid_pid, cc, None, af)


class PESPacketizer:
    """Frame one complete PES packet into 188-byte TS packets (§4/§6)."""

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

    def packetize(
        self,
        pes: PESPacket | bytes,
        *,
        random_access: bool = False,
        first_packet_pcr: PCR | None = None,
    ) -> Iterator[TSPacket]:
        """Frame ``pes`` into an iterator of 188-byte packets (§6).

        ``PESPacket`` objects are serialized with :func:`ts.pes.serialize_pes`
        (auto length mode) — SPEC-104 validation failures propagate with
        their own ``PES_*`` error family. Bytes-like input must be exactly
        one complete PES packet (start-code prefix; a non-zero declared
        ``PES_packet_length`` has to match the byte count; the unbounded
        video profile, declared length 0, is framed as-is).

        ``first_packet_pcr`` rides the first packet's adaptation field
        (AFC=11); ``random_access`` sets the first packet's
        ``random_access_indicator`` — both are explicit caller requests,
        never inferred from the payload (§6). Validation happens eagerly at
        call time; the returned iterator then yields the fully constructed
        packets, each verified to serialize to exactly 188 bytes.
        """
        if isinstance(pes, PESPacket):
            # SPEC-104 owns PES semantics and error codes: serialize there,
            # let InvalidPESPacketError propagate unchanged.
            data = serialize_pes(pes)
        elif isinstance(pes, _BYTES_LIKE):
            data = self._validate_pes_bytes(bytes(pes))
        else:
            raise TypeError(
                f"pes must be PESPacket or bytes, got {type(pes).__name__}"
            )
        total = len(data)
        # Required AF body on the FIRST packet: flags byte + 6-byte PCR, or
        # just the flags byte for a random-access request (§6/§7).
        required_af = 0
        if first_packet_pcr is not None:
            required_af = 7
        elif random_access:
            required_af = 1
        first_capacity = PAYLOAD_ONLY_LENGTH
        if required_af > 0:
            first_capacity = ZERO_AF_PAYLOAD_LENGTH - required_af  # 176 / 182
            if total > first_capacity and total <= PAYLOAD_ONLY_LENGTH:
                # A single-packet PES cannot carry the requested AF content
                # next to its full payload: fail explicitly instead of
                # shrinking/overwriting PES bytes (§6, ruling #11 — the
                # packetizer makes no scheduling policy decisions).
                if first_packet_pcr is not None:
                    raise PacketizationError(
                        f"{PACKETIZER_PCR_DOES_NOT_FIT}: a {total}-byte PES "
                        "fits one packet but leaves adaptation_field_length "
                        f"{ZERO_AF_PAYLOAD_LENGTH - total} < 7 for the PCR "
                        "field (flags + 6 bytes); the PCR would not fit "
                        "next to the PES bytes (SPEC-106 §6)"
                    )
                raise PacketizationError(
                    f"{PACKETIZER_AF_CAPACITY_EXCEEDED}: a {total}-byte PES "
                    "fits one packet but leaves no adaptation field space "
                    "for the random_access_indicator flags byte "
                    "(SPEC-106 §6)"
                )
        first_take = min(total, first_capacity)
        chunks = [data[:first_take]]
        rest = data[first_take:]
        while rest:
            take = min(len(rest), PAYLOAD_ONLY_LENGTH)
            chunks.append(rest[:take])
            rest = rest[take:]
        packets: list[TSPacket] = []
        for index, chunk in enumerate(chunks):
            af = build_adaptation_field(
                len(chunk),
                random_access=index == 0 and random_access,
                pcr=first_packet_pcr if index == 0 else None,
            )
            cc = self._cc_allocator.allocate(self._pid, has_payload=True)
            packets.append(
                emit_verified_packet(
                    self._pid,
                    cc,
                    chunk,
                    af,
                    payload_unit_start_indicator=index == 0,
                )
            )
        return iter(packets)

    @staticmethod
    def _validate_pes_bytes(data: bytes) -> bytes:
        """Raw-bytes precondition: one structurally readable PES packet.

        The packetizer frames bytes; it never re-derives PES semantics
        (SPEC-104 owns them). It only rejects inputs it cannot frame
        honestly: no room for the common header, a wrong start-code prefix,
        or a non-zero declared ``PES_packet_length`` disagreeing with the
        byte count (the declared==0 unbounded video profile is framed as
        delivered).
        """
        if len(data) == 0:
            raise PacketizationError(
                f"{PACKETIZER_EMPTY_PES}: PES input is empty"
            )
        if len(data) < _MIN_PES_HEADER_BYTES:
            raise PacketizationError(
                f"{PACKETIZER_PES_HEADER_INVALID}: PES input needs at least "
                f"{_MIN_PES_HEADER_BYTES} bytes (prefix + stream_id + "
                f"PES_packet_length), got {len(data)}"
            )
        if data[:3] != _START_CODE_PREFIX:
            raise PacketizationError(
                f"{PACKETIZER_PES_HEADER_INVALID}: PES packets start with "
                f"the packet_start_code_prefix 00 00 01, got "
                f"{data[:3].hex(' ')}"
            )
        declared = (data[4] << 8) | data[5]
        if declared != 0 and len(data) != _MIN_PES_HEADER_BYTES + declared:
            raise PacketizationError(
                f"{PACKETIZER_PES_HEADER_INVALID}: declared "
                f"PES_packet_length {declared} implies "
                f"{_MIN_PES_HEADER_BYTES + declared} total bytes, got "
                f"{len(data)} (the packetizer frames exactly one complete "
                "PES packet; the unbounded video profile declares 0)"
            )
        return data
