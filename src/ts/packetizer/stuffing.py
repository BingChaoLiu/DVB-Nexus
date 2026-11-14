"""SPEC-106 §7 — AF stuffing capacity arithmetic and packet emission helpers.

Shared by :class:`ts.packetizer.section_packetizer.SectionPacketizer`,
:class:`ts.packetizer.pes_packetizer.PESPacketizer` and
:func:`ts.packetizer.pes_packetizer.build_pcr_only_packet` — one place owns
the 188-byte frame arithmetic so both packetizers cannot drift apart:

- AFC=11: ``4 header + 1 length + AF body + payload = 188`` hence
  ``adaptation_field_length = 183 - payload_length`` (§7 formula). Length 0
  means no flags byte at all and is represented by the upstream
  :data:`ts.adaptation_field.ZERO_LENGTH_ADAPTATION_FIELD` marker; payload
  184 needs no AF (AFC=01).
- All AF stuffing bytes are ``0xFF`` (§7); the padding itself is written by
  the SPEC-100 encoder :func:`ts.adaptation_field.encode_adaptation_field`
  — this module never re-implements the byte-level encode (single-sourced
  per contract §9).
- AFC=10 (adaptation-only): the AF fills all 184 bytes after the header and
  the CC does not advance (§7/§8) — used only by ``build_pcr_only_packet``.

Error codes raised here (SPEC-106 §9, owned by :mod:`ts.packetizer.codes`):
``PACKETIZER_PCR_DOES_NOT_FIT`` / ``PACKETIZER_AF_CAPACITY_EXCEEDED`` /
``PACKETIZER_PACKET_SIZE_INVARIANT_FAILED``; all map onto
:class:`ts.errors.PacketizationError`.
"""

from __future__ import annotations

from ts.adaptation_field import (
    ZERO_LENGTH_ADAPTATION_FIELD,
    AdaptationField,
    af_encoded_length,
)
from ts.errors import PacketizationError
from ts.packet import (
    AF_ONLY_BODY_LENGTH,
    PAYLOAD_ONLY_LENGTH,
    TS_PACKET_SIZE,
    TSPacket,
)
from ts.pcr import PCR

from ts.packetizer.codes import (
    PACKETIZER_AF_CAPACITY_EXCEEDED,
    PACKETIZER_PACKET_SIZE_INVARIANT_FAILED,
    PACKETIZER_PCR_DOES_NOT_FIT,
)

#: Bytes after the 4-byte packet header (AF length byte + AF body + payload).
#: Derived from the canonical frame geometry in :mod:`ts.packet` (review-fix
#: F6: 183/184 single source); the historical public name is kept.
AF_REGION_SIZE = PAYLOAD_ONLY_LENGTH  # 184

#: Adaptation-field length byte value when the payload consumes the whole
#: region minus the length byte (AFC=11 zero-length AF). Derived from the
#: canonical constant in :mod:`ts.packet`; the historical public name is kept.
ZERO_AF_PAYLOAD_LENGTH = AF_ONLY_BODY_LENGTH  # 183


def adaptation_field_length_for_payload(payload_length: int) -> int:
    """The §7 formula: ``adaptation_field_length = 183 - payload_length``.

    Value 0 means the zero-length AF (no flags byte on the wire); the
    payload itself then fills 183 of the 184 post-header bytes.
    """
    return ZERO_AF_PAYLOAD_LENGTH - payload_length


def build_adaptation_field(
    payload_length: int,
    *,
    random_access: bool = False,
    pcr: PCR | None = None,
) -> AdaptationField | None:
    """Select the AF that frames ``payload_length`` payload bytes into 188.

    Returns ``None`` for a payload-only packet (payload 184, AFC=01), the
    zero-length AF marker for payload 183 (AFC=11 with
    ``adaptation_field_length=0``), and otherwise a flags-bearing field
    carrying the requested ``random_access``/``pcr`` content; the encoder
    pads the remaining body with ``0xFF`` stuffing at serialization time.

    Raises:
        PacketizationError: ``PACKETIZER_PCR_DOES_NOT_FIT`` when a
            requested PCR has no room (the flags byte plus the 6-byte PCR
            need ``adaptation_field_length >= 7``), or
            ``PACKETIZER_AF_CAPACITY_EXCEEDED`` for a flags-only request
            (needs ``>= 1``) or any other impossible frame. Payload length
            must be 1..184; other values are caller bugs and raise
            ``ValueError``.
    """
    if isinstance(payload_length, bool) or not isinstance(payload_length, int):
        raise TypeError(
            f"payload_length must be int, got {type(payload_length).__name__}"
        )
    if not 1 <= payload_length <= PAYLOAD_ONLY_LENGTH:
        raise ValueError(
            f"payload_length must be in 1..{PAYLOAD_ONLY_LENGTH}, got "
            f"{payload_length}"
        )
    if payload_length == PAYLOAD_ONLY_LENGTH:
        if pcr is not None or random_access:
            raise PacketizationError(
                f"{PACKETIZER_PCR_DOES_NOT_FIT if pcr is not None else PACKETIZER_AF_CAPACITY_EXCEEDED}: "
                "a payload-only packet (AFC=01, 184 payload bytes) has no "
                "adaptation field space for the requested AF content"
            )
        return None
    if payload_length == ZERO_AF_PAYLOAD_LENGTH:
        # adaptation_field_length == 0: no flags byte, so no field content.
        if pcr is not None or random_access:
            raise PacketizationError(
                f"{PACKETIZER_PCR_DOES_NOT_FIT if pcr is not None else PACKETIZER_AF_CAPACITY_EXCEEDED}: "
                "a zero-length adaptation field (payload 183) has no flags "
                "byte and cannot carry the requested AF content"
            )
        return ZERO_LENGTH_ADAPTATION_FIELD
    af_length = adaptation_field_length_for_payload(payload_length)
    required = 1 + (6 if pcr is not None else 0)
    if af_length < required:
        if pcr is not None:
            raise PacketizationError(
                f"{PACKETIZER_PCR_DOES_NOT_FIT}: the PCR field (flags byte "
                f"+ 6 bytes) needs adaptation_field_length >= 7, but "
                f"{payload_length} payload bytes leave only {af_length}"
            )
        raise PacketizationError(
            f"{PACKETIZER_AF_CAPACITY_EXCEEDED}: the requested adaptation "
            f"field content needs {required} body bytes, but "
            f"{payload_length} payload bytes leave only {af_length}"
        )
    af = AdaptationField(random_access_indicator=random_access, pcr=pcr)
    # Guard the invariant the SPEC-100 constructor would otherwise check
    # with its own error family: keep the failure in the PACKETIZER_* one.
    if af_encoded_length(af) > af_length:
        raise PacketizationError(  # pragma: no cover - required check above
            f"{PACKETIZER_AF_CAPACITY_EXCEEDED}: AF content "
            f"({af_encoded_length(af)} bytes) exceeds the {af_length}-byte "
            f"body left by {payload_length} payload bytes"
        )
    return af


def emit_verified_packet(
    pid: int,
    continuity_counter: int,
    payload: bytes | None,
    adaptation_field: AdaptationField | None,
    *,
    payload_unit_start_indicator: bool = False,
) -> TSPacket:
    """Construct the packet and enforce the 188-byte size invariant (§10).

    The SPEC-100 constructor already rejects frames that could never
    serialize; this guard additionally serializes the packet once and
    raises ``PACKETIZER_PACKET_SIZE_INVARIANT_FAILED`` if the byte count
    deviates — a packetizer arithmetic bug can never surface as a
    non-canonical packet (REQ-TS-106-003 is enforced at the source).
    """
    packet = TSPacket(
        pid=pid,
        continuity_counter=continuity_counter,
        payload=payload,
        adaptation_field=adaptation_field,
        payload_unit_start_indicator=payload_unit_start_indicator,
    )
    data = packet.to_bytes()
    if len(data) != TS_PACKET_SIZE:
        raise PacketizationError(
            f"{PACKETIZER_PACKET_SIZE_INVARIANT_FAILED}: packetization "
            f"produced a packet that serializes to {len(data)} bytes "
            f"instead of {TS_PACKET_SIZE}"
        )
    return packet
