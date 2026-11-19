"""SPEC-600 §5 — T2-MI packet model unit tests (ticket #122).

Seams under test: :class:`ts.t2mi.packet.T2miPacket` construction guards,
field encoding (:func:`encode_packet`), and the derived payload-kind /
PLP faces downstream tickets (#123/#124/#125/#129) consume. Bytes are
built programmatically (tests/README §5 — no hand-assembled literals).
"""

from __future__ import annotations

import pytest

from ts.crc import mpeg2_crc32
from ts.t2mi.errors import T2miError
from ts.t2mi.packet import (
    T2MI_CRC_SIZE,
    T2MI_HEADER_SIZE,
    T2MI_INTERLEAVING_FRAME_START_FLAG,
    T2MI_TYPE_BBFRAME,
    T2MI_TYPE_PADDING,
    T2miPacket,
    encode_packet,
    make_header_reserved,
)

PADDING_BITS_CODES = "T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE"


def _payload(size: int, seed: int = 0) -> bytes:
    """Deterministic programmatic payload (no byte literals, §5 discipline)."""
    return bytes((index * 31 + seed * 7) & 0xFF for index in range(size))


def _packet(
    *,
    packet_type: int = T2MI_TYPE_BBFRAME,
    packet_counter: int = 0,
    superframe_index: int = 0,
    payload: bytes | None = None,
    payload_bits: int | None = None,
    crc32: int | None = None,
) -> T2miPacket:
    body = _payload(8) if payload is None else payload
    bits = len(body) * 8 if payload_bits is None else payload_bits
    reserved = bytes([(superframe_index & 0x0F) << 4, 0x00])
    value = 0 if crc32 is None else crc32
    return T2miPacket(
        packet_type=packet_type,
        packet_counter=packet_counter,
        reserved=reserved,
        payload_bits=bits,
        payload=body,
        crc32=value,
    )


def _encoded_prefix(packet: T2miPacket) -> bytes:
    """The 6-byte header prefix of the encoding, asserted byte-by-byte."""
    encoded = encode_packet(packet)
    return encoded[:T2MI_HEADER_SIZE]


class TestPacketEncoding:
    def test_header_size_and_crc_size_constants(self) -> None:
        # TS 102 773 §5.1: 6-byte header + payload + 32-bit CRC tail.
        assert T2MI_HEADER_SIZE == 6
        assert T2MI_CRC_SIZE == 4

    def test_encode_header_layout_byte_by_byte(self) -> None:
        packet = _packet(packet_type=0x00, packet_counter=3, superframe_index=5)
        header = _encoded_prefix(packet)
        assert header[0] == 0x00  # packet_type
        assert header[1] == 3  # packet_counter
        assert header[2] == (5 << 4)  # superframe_index high nibble, reserved low
        assert header[3] == 0x00  # reserved
        bits = int.from_bytes(header[4:6], "big")
        assert bits == len(packet.payload) * 8  # payload length in BITS

    def test_encode_crc_trailer_matches_mpeg2_crc32_over_header_and_payload(self) -> None:
        payload = _payload(24, seed=1)
        crc = mpeg2_crc32(_encoded_prefix(_packet(payload=payload)) + payload)
        packet = _packet(payload=payload, crc32=crc)
        encoded = encode_packet(packet)
        trailer = encoded[-T2MI_CRC_SIZE:]
        assert int.from_bytes(trailer, "big") == crc
        assert len(encoded) == T2MI_HEADER_SIZE + len(payload) + T2MI_CRC_SIZE

    def test_encode_reuses_stored_crc_verbatim(self) -> None:
        # Preservation discipline: a packet whose stored CRC does not match
        # its content (the crc32_valid=False face) re-encodes to the exact
        # original bytes — encode never recomputes.
        stored = 0x11223344
        packet = _packet(crc32=stored)
        encoded = encode_packet(packet)
        assert int.from_bytes(encoded[-T2MI_CRC_SIZE:], "big") == stored

    def test_encode_round_trip_is_identity(self) -> None:
        packet = _packet(packet_counter=200, superframe_index=9)
        rebuilt = T2miPacket.from_encoded(encode_packet(packet))
        assert rebuilt == packet
        assert encode_packet(rebuilt) == encode_packet(packet)


class TestDerivedFaces:
    def test_payload_kind_bbframe_for_type_zero(self) -> None:
        assert _packet(packet_type=T2MI_TYPE_BBFRAME).payload_kind == "bbframe"

    def test_payload_kind_padding_for_stuffing_byte_type(self) -> None:
        assert _packet(packet_type=T2MI_TYPE_PADDING).payload_kind == "padding"

    def test_payload_kind_unknown_for_unregistered_type(self) -> None:
        assert _packet(packet_type=0x10).payload_kind == "unknown"

    def test_superframe_index_derived_from_reserved_high_nibble(self) -> None:
        packet = _packet(superframe_index=7)
        assert packet.superframe_index == 7

    def test_padding_bits_zero_for_byte_aligned_payload(self) -> None:
        assert _packet(payload=_payload(8)).padding_bits == 0

    def test_padding_bits_counts_partial_final_byte(self) -> None:
        # payload_bits = 65 → 9 payload bytes, 7 padding bits in the last one.
        packet = _packet(payload=_payload(9), payload_bits=65)
        assert packet.padding_bits == 7

    def test_bbframe_face_exposes_payload_after_transport_prefix(self) -> None:
        # BBFRAME packet payload = frame_idx(1) + PLP_id(1) + flags(1) + BBFRAME.
        bbframe = _payload(40, seed=2)
        packet = _packet(payload=bytes([7, 3, 0x80]) + bbframe)
        assert packet.bbframe == bbframe
        assert packet.frame_index == 7
        assert packet.plp_id == 3

    def test_bbframe_face_none_for_non_bbframe_type(self) -> None:
        assert _packet(packet_type=T2MI_TYPE_PADDING).bbframe is None
        assert _packet(packet_type=T2MI_TYPE_PADDING).plp_id is None

    def test_payload_bytes_len_face(self) -> None:
        assert _packet(payload=_payload(8)).payload_bytes_len == 8

    def test_total_size_face(self) -> None:
        packet = _packet(payload=_payload(8))
        assert packet.total_size == T2MI_HEADER_SIZE + 8 + T2MI_CRC_SIZE


class TestConstructionGuards:
    """Malformed fields raise typed errors — nothing is silently truncated."""

    def test_packet_counter_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            _packet(packet_counter=256)
        assert error.value.code == "T2MI_PACKET_COUNTER_OUT_OF_RANGE"

    def test_superframe_index_out_of_range(self) -> None:
        # superframe_index is derived from the reserved field; its 4-bit
        # domain is enforced where the field is built (make_header_reserved).
        with pytest.raises(T2miError) as error:
            make_header_reserved(16)
        assert error.value.code == "T2MI_PACKET_SUPERFRAME_OUT_OF_RANGE"

    def test_payload_bits_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            _packet(payload_bits=0x10000)
        assert error.value.code == PADDING_BITS_CODES

    def test_payload_bits_below_payload_floor_rejected(self) -> None:
        # payload must hold ceil(bits/8) bytes; fewer bytes cannot carry the
        # declared bit length (the encoding face would be unrepresentable).
        with pytest.raises(T2miError):
            _packet(payload=_payload(1), payload_bits=9)

    def test_crc_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            _packet(crc32=0x1_0000_0000)
        assert error.value.code == "T2MI_PACKET_CRC_OUT_OF_RANGE"

    def test_reserved_field_must_be_two_bytes(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miPacket(
                packet_type=T2MI_TYPE_BBFRAME,
                packet_counter=0,
                reserved=bytes([0x00]),
                payload_bits=0,
                payload=b"",
                crc32=0,
            )
        assert error.value.code == "T2MI_PACKET_RESERVED_INVALID"

    def test_packet_type_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            _packet(packet_type=0x100)
        assert error.value.code == "T2MI_PACKET_TYPE_OUT_OF_RANGE"


class TestBytes2To5NamedFaces:
    """The bytes-2..5 named faces (ticket #140 — SPEC-404 §Phase2
    「6 字节包头逐字段（TS 102 773 §5.1）」: byte 2 = superframe_index
    (high nibble), byte 3 = reserved, byte 4..5 = payload_bits 16-bit BE
    — the last already exposed; the teaching view needed the named
    decodes of the first two)."""

    def test_superframe_index_rides_header_byte2_high_nibble(self) -> None:
        for value in (0, 1, 7, 15):
            packet = _packet(superframe_index=value)
            assert packet.superframe_index == value

    def test_superframe_index_leaves_reserved_verbatim(self) -> None:
        # the named face is a decode; the raw bytes stay the byte authority
        # (SPEC-103 §7 保留纪律) — low nibble / byte 3 are untouched
        reserved_pair = bytes([0x70 | 0x0A, 0xBC])  # high nibble 7 + verbatim rest
        packet = T2miPacket(
            packet_type=T2MI_TYPE_BBFRAME,
            packet_counter=0,
            reserved=reserved_pair,
            payload_bits=64,
            payload=_payload(8),
            crc32=0,
        )
        assert packet.superframe_index == 7
        assert packet.reserved == reserved_pair
        # and the encoding round-trips the verbatim pair
        encoded = encode_packet(packet)
        assert encoded[2:4] == reserved_pair

    def test_interleaving_frame_start_from_prefix_flags_bit(self) -> None:
        # BBFRAME transport prefix flags byte, bit 0x80 (TSDuck byte-aligned
        # layout), built programmatically per tests/README §5
        prefix = bytes([0x00, 0x05, T2MI_INTERLEAVING_FRAME_START_FLAG])
        started = _packet(payload=prefix + _payload(8))
        assert started.interleaving_frame_start is True
        not_started = _packet(
            payload=bytes([prefix[0], prefix[1], prefix[2] ^ T2MI_INTERLEAVING_FRAME_START_FLAG])
            + _payload(8),
        )
        assert not_started.interleaving_frame_start is False

    def test_interleaving_frame_start_none_for_non_bbframe(self) -> None:
        # the honest tri-state discipline (frame_index/plp_id pattern):
        # the prefix flags byte does not exist without the prefix
        padding = _packet(packet_type=T2MI_TYPE_PADDING, payload=_payload(8))
        assert padding.interleaving_frame_start is None
        short = _packet(payload=_payload(2))  # < 3 prefix bytes: no face
        assert short.interleaving_frame_start is None
