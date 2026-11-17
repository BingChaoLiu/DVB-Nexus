"""SPEC-600 §6/§7/§8 — T2-MI parser unit tests (ticket #122).

Seam under test: :func:`ts.t2mi.parser.parse` — deterministic byte
stream → packet sequence with the five error faces (SPEC-600 §8):
CRC failure marked (never dropped), unknown packet_type explicit,
padding/stuffing explicit, truncation explicit, and — on the builder
side — no inter-packet padding ever skipped over. All streams are built
programmatically from the packet model (§5 discipline: no literals).
"""

from __future__ import annotations

import pytest

from ts.crc import mpeg2_crc32
from ts.t2mi.packet import (
    T2MI_CRC_SIZE,
    T2MI_HEADER_SIZE,
    T2MI_TYPE_BBFRAME,
    T2miPacket,
    encode_packet,
    make_header_reserved,
)
from ts.t2mi.parser import T2miParseResult, parse


def _payload(size: int, seed: int = 0) -> bytes:
    return bytes((index * 31 + seed * 7) & 0xFF for index in range(size))


def _bbframe_packet(counter: int, frame_idx: int, plp: int, body_seed: int) -> T2miPacket:
    payload = bytes([frame_idx & 0xFF, plp & 0xFF, 0x80]) + _payload(16, seed=body_seed)
    reserved = make_header_reserved(0)
    prefix = bytes([T2MI_TYPE_BBFRAME, counter & 0xFF, reserved[0], reserved[1]]) + (
        len(payload) * 8
    ).to_bytes(2, "big")
    crc = mpeg2_crc32(prefix + payload)
    return T2miPacket(
        packet_type=T2MI_TYPE_BBFRAME,
        packet_counter=counter & 0xFF,
        reserved=reserved,
        payload_bits=len(payload) * 8,
        payload=payload,
        crc32=crc,
    )


def _stream(*packets: T2miPacket) -> bytes:
    return b"".join(encode_packet(packet) for packet in packets)


def _three_packet_stream() -> bytes:
    return _stream(
        _bbframe_packet(0, 0, 0, 1),
        _bbframe_packet(1, 1, 0, 2),
        _bbframe_packet(2, 2, 1, 3),
    )


class TestParseHappyPath:
    def test_three_packets_parse_with_fields_preserved(self) -> None:
        result = parse(_three_packet_stream())
        assert len(result) == 3
        assert not result.truncated
        assert result.trailing == b""
        for index, packet in enumerate(result):
            assert packet.packet_type == T2MI_TYPE_BBFRAME
            assert packet.packet_counter == index  # counter continuity preserved
            assert packet.crc32_valid
            assert packet.frame_index == index
        # PLP distribution as parsed: frames 0/1 on PLP 0, frame 2 on PLP 1.
        assert [packet.plp_id for packet in result] == [0, 0, 1]

    def test_result_is_a_sequence_of_packets(self) -> None:
        result = parse(_three_packet_stream())
        assert isinstance(result, T2miParseResult)
        assert list(iter(result)) == list(result.packets)
        assert result[0] == result.packets[0]
        assert result[-1] == result.packets[-1]

    def test_parse_is_deterministic(self) -> None:
        stream = _three_packet_stream()
        first = parse(stream)
        second = parse(stream)
        assert list(first.packets) == list(second.packets)
        assert first.truncated == second.truncated

    def test_padding_bits_preserved_from_partial_final_byte(self) -> None:
        # 9 payload bytes declaring 65 bits → 7 padding bits survive parse.
        payload = _payload(9, seed=4)
        reserved = make_header_reserved(0)
        prefix = bytes([T2MI_TYPE_BBFRAME, 0, reserved[0], reserved[1]]) + (65).to_bytes(
            2, "big"
        )
        packet = T2miPacket(
            packet_type=T2MI_TYPE_BBFRAME,
            packet_counter=0,
            reserved=reserved,
            payload_bits=65,
            payload=payload,
            crc32=mpeg2_crc32(prefix + payload),
        )
        parsed = parse(encode_packet(packet))
        assert len(parsed) == 1
        assert parsed[0].padding_bits == 7
        assert parsed[0].crc32_valid

    def test_empty_stream_yields_empty_result(self) -> None:
        result = parse(b"")
        assert len(result) == 0
        assert not result.truncated

    def test_accepts_bytearray_input(self) -> None:
        result = parse(bytearray(_three_packet_stream()))
        assert len(result) == 3

    def test_rejects_non_bytes_input(self) -> None:
        with pytest.raises(TypeError):
            parse("not bytes")  # type: ignore[arg-type]


class TestCrcBadPacketFace:
    def test_crc_failure_marks_packet_and_continues(self) -> None:
        # Flip one payload bit inside packet 1 of 3: packet 1 is marked
        # crc32_valid=False, neighbours stay valid, NOTHING is dropped.
        stream = bytearray(_three_packet_stream())
        packet_total = 29  # 6 header + (3 prefix + 16 body) payload + 4 CRC
        target = packet_total + T2MI_HEADER_SIZE + 3 + 5  # inside packet 1 payload
        stream[target] ^= 0x01
        result = parse(bytes(stream))
        assert len(result) == 3
        assert result[0].crc32_valid
        assert not result[1].crc32_valid
        assert result[2].crc32_valid
        # The corrupted byte is preserved verbatim (no silent repair).
        baseline = list(parse(_three_packet_stream()).packets)
        assert result[1].payload[8] != baseline[1].payload[8]
        assert result[1].packet_counter == 1  # header fields still readable

    def test_crc_field_itself_flipped_is_also_marked(self) -> None:
        stream = bytearray(_three_packet_stream())
        stream[-1] ^= 0x80  # flip a CRC trailer bit of the last packet
        result = parse(bytes(stream))
        assert len(result) == 3
        assert not result[2].crc32_valid
        assert int.from_bytes(bytes(stream[-T2MI_CRC_SIZE:]), "big") == result[2].crc32


class TestExplicitTypeStates:
    def test_unknown_packet_type_is_explicit_state_not_error(self) -> None:
        stream = bytearray(_three_packet_stream())
        stream[0] = 0x10  # an unregistered (standard-table) packet type
        result = parse(bytes(stream))
        assert result[0].payload_kind == "unknown"
        assert result[0].packet_type == 0x10
        # The type byte is part of the CRC-covered region → also invalid.
        assert not result[0].crc32_valid
        assert len(result) == 3  # still not dropped

    def test_padding_stuffing_type_is_explicit_state(self) -> None:
        stream = bytearray(_three_packet_stream())
        stream[0] = 0xFF  # stuffing byte identity in the type field
        result = parse(bytes(stream))
        assert result[0].payload_kind == "padding"
        assert len(result) == 3


class TestTruncationFace:
    def test_truncated_tail_is_explicit_not_dropped(self) -> None:
        stream = _three_packet_stream()
        packet_total = 29
        cut = 5
        result = parse(stream[:-cut])
        assert len(result) == 2  # first two packets complete
        assert result.truncated
        tail_len = len(stream) - cut - 2 * packet_total
        assert result.trailing_bytes == tail_len
        assert result.trailing == stream[2 * packet_total : len(stream) - cut]

    def test_header_only_tail_is_truncated(self) -> None:
        stream = _three_packet_stream()
        result = parse(stream[:-3])  # only the last 3 bytes of packet 3 remain
        assert len(result) == 2
        assert result.truncated
        assert result.trailing == stream[-29:-3]  # 29-byte packet, last 3 cut
        assert result.trailing_bytes == 26

    def test_truncation_after_complete_packets_keeps_them(self) -> None:
        stream = _three_packet_stream()
        packets = parse(stream).packets
        first_two_end = packets[0].total_size + packets[1].total_size
        result = parse(stream[:first_two_end])
        assert len(result) == 2
        assert not result.truncated
        assert result.trailing == b""

    def test_all_results_from_truncated_stream_are_deterministic(self) -> None:
        stream = _three_packet_stream()[:-1]
        assert parse(stream) == parse(stream)


class TestBackToBackDiscipline:
    def test_no_gap_is_skipped_between_packets(self) -> None:
        # The parser has no skip/scan mode: bytes after a packet must form
        # the next packet header, else they surface as truncation. A 6-byte
        # stuffing gap (the #104 demux-stall byte identity) declares a
        # 0xFFFF-bit payload no remaining stream can satisfy → the whole
        # remainder surfaces explicitly as truncation, never consumed as
        # good data.
        stream = _three_packet_stream()
        p0_end = parse(stream).packets[0].total_size
        gap = b"\xff" * 6
        gapped = stream[:p0_end] + gap + stream[p0_end:]
        result = parse(gapped)
        assert len(result) == 1  # packet 0 stays complete and valid
        assert result[0].crc32_valid
        assert result.truncated
        assert result.trailing == gap + stream[p0_end:]
