"""SPEC-104 — MPEG-2 PES Packet Core — unit tests (ticket #30).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-104 section):

- REQ-TS-104-001  PES header encode/parse correct          -> test_pes_header_round_trip
- REQ-TS-104-002  PTS/DTS 33-bit marker/prefix correct     -> test_pes_pts_dts
- REQ-TS-104-003  packet_length semantics correct          -> test_pes_packet_length
- REQ-TS-104-004  PUSI / cross-packet assembly correct     -> test_pes_assembler
- REQ-TS-104-005  malformed input / buffer cap safety      -> test_pes_malformed_and_limits
- REQ-TS-104-006  synthetic payload not playback-ready     -> test_analysis_only_profile_metadata

Expected byte literals are hand-computed from the ITU-T H.222.0 PES packet
syntax table (SPEC-104 §3), never recomputed through the implementation
under test. The 5-byte PTS/DTS field literals follow the H.222.0 marker-bit
segment layout; marker-bit violations are produced by flipping one known
bit in a known-good literal. All timestamps delegate to SPEC-105
``ts.timestamp`` (SPEC-104 §6: one algorithm, no duplication).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# REQ-TS-104-001 — PES header encode/parse (round trip + hand literals)
# ---------------------------------------------------------------------------


class TestPesHeaderRoundTrip:
    """REQ-TS-104-001: PES Header 字段解析/编码准确 (SPEC-104 §3/§4)."""

    def test_pes_header_round_trip(self) -> None:
        """Minimal standard PES (no timestamps) parses and re-serializes."""
        from ts.pes import parse_pes, serialize_pes

        # stream_id=0xC0 (audio), no flags, hdl=0, payload 3 bytes,
        # PES_packet_length = 3 (control bytes) + 0 + 3 = 6.
        data = bytes(
            (0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00, 0x00)
        ) + b"\x11\x22\x33"
        parsed = parse_pes(data)
        assert parsed.header.stream_id == 0xC0
        assert parsed.header.pes_packet_length == 6
        assert parsed.header.pts is None
        assert parsed.header.dts is None
        assert parsed.header.pes_scrambling_control == 0
        assert parsed.header.pes_priority is False
        assert parsed.header.data_alignment_indicator is False
        assert parsed.header.copyright is False
        assert parsed.header.original_or_copy is False
        assert parsed.payload == b"\x11\x22\x33"

        assert serialize_pes(parsed) == data

    def test_header_flags_preserved(self) -> None:
        """Scrambling/priority/alignment/copyright/original bits round-trip.

        Hand-computed byte 6: '10' marker (0x80) | scrambling=10 (0x20)
        | priority (0x08) | data_alignment (0x04) | copyright (0x02)
        | original_or_copy (0x01) = 0xAF.
        """
        from ts.pes import PESHeader, PESPacket, parse_pes, serialize_pes

        packet = PESPacket(
            header=PESHeader(
                stream_id=0xE0,
                pes_packet_length=4,
                pes_scrambling_control=0b10,
                pes_priority=True,
                data_alignment_indicator=True,
                copyright=True,
                original_or_copy=True,
            ),
            payload=b"\xAA",
        )
        data = serialize_pes(packet)
        # 00 00 01 E0 00 04 AF 00 00 AA
        assert data == bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x04, 0xAF, 0x00, 0x00)
        ) + b"\xAA"

        parsed = parse_pes(data)
        assert parsed.header.pes_scrambling_control == 0b10
        assert parsed.header.pes_priority is True
        assert parsed.header.data_alignment_indicator is True
        assert parsed.header.copyright is True
        assert parsed.header.original_or_copy is True
        assert serialize_pes(parsed) == data


# ---------------------------------------------------------------------------
# REQ-TS-104-002 — PTS/DTS 33-bit marker/prefix handling
# ---------------------------------------------------------------------------


class TestPesPtsDts:
    """REQ-TS-104-002: PTS/DTS 33-bit marker/prefix 正确 (SPEC-104 §6).

    5-byte field literals are hand-computed from the H.222.0 layout:

    - byte 0: prefix(4) | value[32:30](3) | marker '1'
    - byte 1: value[29:22]
    - byte 2: value[21:15](7) | marker '1'
    - byte 3: value[14:7]
    - byte 4: value[6:0](7) | marker '1'

    e.g. PTS=90000 -> 21 00 05 BF 21 (90000 = 65536 + 24448 + 16 with
    value[21:15]=2, value[14:7]=191, value[6:0]=16).
    """

    def test_pes_pts_dts(self) -> None:
        """PTS-only and PTS+DTS round-trip through hand-built literals."""
        from ts.pes import parse_pes, serialize_pes

        # PTS only: prefix 0010, PTS_DTS_flags=10, hdl=5, length=3+5+1=9.
        pts_only = bytes(
            (
                0x00, 0x00, 0x01, 0xE0, 0x00, 0x09,
                0x80, 0x80, 0x05,
                0x21, 0x00, 0x05, 0xBF, 0x21,  # PTS=90000, prefix 0010
            )
        ) + b"\x55"
        parsed = parse_pes(pts_only)
        assert parsed.header.pts == 90000
        assert parsed.header.dts is None
        assert serialize_pes(parsed) == pts_only

        # PTS+DTS: PTS prefix 0011, DTS prefix 0001, flags=11, hdl=10.
        # DTS=45000 -> 11 00 03 5F 91 (32768 + 12160 + 72).
        pair = (
            b"\x00\x00\x01\xE0\x00\x0E"  # start code, sid=0xE0, length=14
            + b"\x80\xC0\x0A"  # marker+flags 0x80, flags2 PTS+DTS 0xC0, hdl=10
            + b"\x31\x00\x05\xBF\x21"  # PTS=90000, prefix 0011
            + b"\x11\x00\x03\x5F\x91"  # DTS=45000, prefix 0001
            + b"\x55"  # payload
        )
        parsed = parse_pes(pair)
        assert parsed.header.pts == 90000
        assert parsed.header.dts == 45000
        assert serialize_pes(parsed) == pair

    def test_pts_boundary_values(self) -> None:
        """PTS values 0, 1 and 2**33-1 round-trip byte-exactly."""
        from ts.pes import PESHeader, PESPacket, parse_pes, serialize_pes

        # PTS=0 -> 21 00 01 00 01.
        zero = PESPacket(
            header=PESHeader(stream_id=0xE0, pes_packet_length=0, pts=0),
            payload=b"",
        )
        data = serialize_pes(zero)
        assert data[9:14] == bytes((0x21, 0x00, 0x01, 0x00, 0x01))
        assert parse_pes(data).header.pts == 0

        # PTS=1 -> 21 00 01 00 03 (low bit lands in value[6:0]).
        one = PESPacket(
            header=PESHeader(stream_id=0xE0, pes_packet_length=0, pts=1),
            payload=b"",
        )
        data = serialize_pes(one)
        assert data[9:14] == bytes((0x21, 0x00, 0x01, 0x00, 0x03))
        assert parse_pes(data).header.pts == 1

        # PTS=2**33-1 -> 2F FF FF FF FF (every value bit set).
        maximal = PESPacket(
            header=PESHeader(
                stream_id=0xE0, pes_packet_length=0, pts=2**33 - 1
            ),
            payload=b"",
        )
        data = serialize_pes(maximal)
        assert data[9:14] == bytes((0x2F, 0xFF, 0xFF, 0xFF, 0xFF))
        assert parse_pes(data).header.pts == 2**33 - 1

    def test_pts_out_of_range_rejected(self) -> None:
        """Negative and 2**33 values are rejected, never silently masked."""
        from ts.errors import InvalidTimestampError
        from ts.pes import PESHeader
        from ts.timestamp import PTS_VALUE_OUT_OF_RANGE

        for bad in (-1, 2**33):
            with pytest.raises(InvalidTimestampError) as excinfo:
                PESHeader(stream_id=0xE0, pes_packet_length=0, pts=bad)
            # SPEC-105 owns the 33-bit range (single algorithm, §6); the
            # error code must be the SPEC-105 range code.
            assert PTS_VALUE_OUT_OF_RANGE in str(excinfo.value)

    def test_marker_bits_enforced(self) -> None:
        """Each of the three marker bits flipped to 0 is rejected."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_TIMESTAMP_MARKER_INVALID, parse_pes

        base = bytearray(
            bytes(
                (
                    0x00, 0x00, 0x01, 0xE0, 0x00, 0x09,
                    0x80, 0x80, 0x05,
                    0x21, 0x00, 0x05, 0xBF, 0x21,
                )
            )
        ) + b"\x55"
        # Flip the marker in byte 0 (offset 9), byte 2 (offset 11) and
        # byte 4 (offset 13) of the PTS field, one at a time.
        for offset in (9, 11, 13):
            broken = bytearray(base)
            broken[offset] &= 0xFE  # clear the marker bit
            with pytest.raises(InvalidPESPacketError) as excinfo:
                parse_pes(bytes(broken))
            assert PES_TIMESTAMP_MARKER_INVALID in str(excinfo.value)

    def test_timestamp_prefix_enforced(self) -> None:
        """PTS-only flags carrying a PTS+DTS prefix field are rejected."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_TIMESTAMP_MARKER_INVALID, parse_pes

        # Flags say PTS-only (byte7=0x80) but the field uses the
        # PTS-in-pair prefix 0011 (0x31).
        broken = bytes(
            (
                0x00, 0x00, 0x01, 0xE0, 0x00, 0x09,
                0x80, 0x80, 0x05,
                0x31, 0x00, 0x05, 0xBF, 0x21,
            )
        ) + b"\x55"
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(broken)
        assert PES_TIMESTAMP_MARKER_INVALID in str(excinfo.value)

    def test_pts_dts_flags_01_rejected(self) -> None:
        """PTS_DTS_flags=01 (reserved) is rejected on the wire."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_PTS_DTS_FLAGS_INVALID, parse_pes

        data = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x09, 0x80, 0x40, 0x05)
        ) + bytes(5) + b"\x55"
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(data)
        assert PES_PTS_DTS_FLAGS_INVALID in str(excinfo.value)

    def test_dts_without_pts_rejected_at_serialize(self) -> None:
        """A DTS without a PTS has no legal flags encoding (§3)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_PTS_DTS_FLAGS_INVALID,
            PESHeader,
            PESPacket,
            serialize_pes,
        )

        packet = PESPacket(
            header=PESHeader(
                stream_id=0xE0, pes_packet_length=0, dts=45000
            ),
            payload=b"",
        )
        with pytest.raises(InvalidPESPacketError) as excinfo:
            serialize_pes(packet)
        assert PES_PTS_DTS_FLAGS_INVALID in str(excinfo.value)


# ---------------------------------------------------------------------------
# REQ-TS-104-003 — PES_packet_length semantics and boundaries
# ---------------------------------------------------------------------------


class TestPesPacketLength:
    """REQ-TS-104-003: packet_length 语义和边界正确 (SPEC-104 §3/§8)."""

    def test_pes_packet_length(self) -> None:
        """Declared-length parse and auto-computed serialize agree.

        Auto mode must count the 3 fixed control bytes + header data +
        payload (never the 6-byte prefix): a PTS-only PES with 1 payload
        byte computes 3 + 5 + 1 = 9 (SPEC-104 §8).
        """
        from ts.pes import PESHeader, PESPacket, parse_pes, serialize_pes

        # Declared length parse: the minimal literal declares 6.
        declared = bytes(
            (0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00, 0x00)
        ) + b"\x11\x22\x33"
        assert parse_pes(declared).header.pes_packet_length == 6

        # Auto compute includes optional-header bytes.
        packet = PESPacket(
            header=PESHeader(
                stream_id=0xE0, pes_packet_length=0, pts=90000
            ),
            payload=b"\x55",
        )
        data = serialize_pes(packet)
        assert (data[4] << 8) | data[5] == 9
        assert parse_pes(data).header.pes_packet_length == 9
        assert parse_pes(data).payload == b"\x55"

    def test_declared_length_mismatch_rejected(self) -> None:
        """len(data) != 6 + declared -> PES_PACKET_LENGTH_MISMATCH (both ways).

        Ruling #11 trailing-bytes semantics: no truncation, no consumption
        of a prefix; the strict parse rejects short and long inputs alike.
        """
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_PACKET_LENGTH_MISMATCH, parse_pes

        declared = bytes(
            (0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00, 0x00)
        ) + b"\x11\x22\x33"
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(declared[:-1])
        assert PES_PACKET_LENGTH_MISMATCH in str(excinfo.value)
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(declared + b"\xFF")
        assert PES_PACKET_LENGTH_MISMATCH in str(excinfo.value)

    def test_stored_length_disagreement_rejected_in_auto_mode(self) -> None:
        """Auto mode never silently rewrites a non-zero stored length."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_PACKET_LENGTH_MISMATCH,
            PESHeader,
            PESPacket,
            serialize_pes,
        )

        packet = PESPacket(
            header=PESHeader(stream_id=0xC0, pes_packet_length=99),
            payload=b"\x11\x22\x33",  # computes to 3 + 0 + 3 = 6
        )
        with pytest.raises(InvalidPESPacketError) as excinfo:
            serialize_pes(packet)
        assert PES_PACKET_LENGTH_MISMATCH in str(excinfo.value)

    def test_zero_length_video_profile(self) -> None:
        """PES_packet_length=0 parses for video stream_ids only (§3)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_LENGTH_ZERO_NOT_ALLOWED,
            parse_pes,
            serialize_pes,
        )

        video_unbounded = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x00, 0x80, 0x00, 0x00)
        ) + b"\x01\x02"
        parsed = parse_pes(video_unbounded)
        assert parsed.header.pes_packet_length == 0
        assert parsed.payload == b"\x01\x02"

        # Same shape on an audio stream_id is illegal.
        audio_unbounded = bytes(
            (0x00, 0x00, 0x01, 0xC0, 0x00, 0x00, 0x80, 0x00, 0x00)
        ) + b"\x01\x02"
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(audio_unbounded)
        assert PES_LENGTH_ZERO_NOT_ALLOWED in str(excinfo.value)

        # Serialize side: mode="zero" is an explicit generation choice.
        from ts.pes import PESHeader, PESPacket

        packet = PESPacket(
            header=PESHeader(stream_id=0xE0, pes_packet_length=0),
            payload=b"\x01\x02",
        )
        data = serialize_pes(packet, packet_length_mode="zero")
        assert (data[4] << 8) | data[5] == 0
        assert parse_pes(data).payload == b"\x01\x02"

        audio = PESPacket(
            header=PESHeader(stream_id=0xC0, pes_packet_length=6),
            payload=b"\x11\x22\x33",
        )
        with pytest.raises(InvalidPESPacketError) as excinfo:
            serialize_pes(audio, packet_length_mode="zero")
        assert PES_LENGTH_ZERO_NOT_ALLOWED in str(excinfo.value)

    def test_length_overflow_rejected_not_truncated(self) -> None:
        """Computed lengths above 65535 are rejected (§8, no auto-truncate)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_PACKET_LENGTH_OUT_OF_RANGE,
            PESHeader,
            PESPacket,
            serialize_pes,
        )

        packet = PESPacket(
            header=PESHeader(stream_id=0xE0, pes_packet_length=0),
            payload=bytes(65536),  # computes 3 + 0 + 65536 = 65539
        )
        with pytest.raises(InvalidPESPacketError) as excinfo:
            serialize_pes(packet)
        assert PES_PACKET_LENGTH_OUT_OF_RANGE in str(excinfo.value)

    def test_unknown_packet_length_mode_rejected(self) -> None:
        """Generation config must name a known packet_length_mode (§3)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_PACKET_LENGTH_MODE_INVALID,
            PESHeader,
            PESPacket,
            serialize_pes,
        )

        packet = PESPacket(
            header=PESHeader(stream_id=0xC0, pes_packet_length=0),
            payload=b"",
        )
        with pytest.raises(InvalidPESPacketError) as excinfo:
            serialize_pes(packet, packet_length_mode="truncate")
        assert PES_PACKET_LENGTH_MODE_INVALID in str(excinfo.value)


# ---------------------------------------------------------------------------
# REQ-TS-104-004 — PUSI / cross-packet assembly (PESAssembler)
# ---------------------------------------------------------------------------

#: Minimal standard PES: stream_id=0xC0, length=6, no timestamps,
#: payload 11 22 33 (12 bytes total).
_MINIMAL_PES = bytes(
    (0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00, 0x00)
) + b"\x11\x22\x33"

#: PTS-only video PES (15 bytes total, PTS=90000, payload 0x55).
_PTS_PES = bytes(
    (
        0x00, 0x00, 0x01, 0xE0, 0x00, 0x09,
        0x80, 0x80, 0x05,
        0x21, 0x00, 0x05, 0xBF, 0x21,
    )
) + b"\x55"

#: Unbounded video PES header (PES_packet_length=0, no timestamps).
_UNBOUNDED_HEADER = bytes(
    (0x00, 0x00, 0x01, 0xE0, 0x00, 0x00, 0x80, 0x00, 0x00)
)


def _ts_packet(
    payload: bytes,
    *,
    pid: int = 0x100,
    cc: int = 0,
    pusi: bool = False,
    tei: bool = False,
    discontinuity: bool = False,
):
    """Build a 188-byte TSPacket carrying ``payload`` (AF-stuffed).

    Payload-only packets need exactly 184 bytes; anything shorter is
    framed with an adaptation field whose body the packetizer pads with
    0xFF stuffing (SPEC-104 §7.5: the assembler must not consume AF
    bytes as PES payload).
    """
    from ts.adaptation_field import AdaptationField
    from ts.packet import TSPacket

    if len(payload) == 184 and not discontinuity:
        return TSPacket(
            pid=pid,
            continuity_counter=cc,
            payload=payload,
            payload_unit_start_indicator=pusi,
            transport_error_indicator=tei,
        )
    return TSPacket(
        pid=pid,
        continuity_counter=cc,
        payload=payload,
        payload_unit_start_indicator=pusi,
        transport_error_indicator=tei,
        adaptation_field=AdaptationField(discontinuity_indicator=discontinuity),
    )


class TestPesAssembler:
    """REQ-TS-104-004: PESAssembler PUSI/跨包组装正确 (SPEC-104 §7)."""

    def test_pes_assembler(self) -> None:
        """A PES wholly inside one TS payload assembles on push."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        out = asm.push(_ts_packet(_MINIMAL_PES, pusi=True))
        assert len(out) == 1
        assert out[0].header.stream_id == 0xC0
        assert out[0].header.pes_packet_length == 6
        assert out[0].payload == b"\x11\x22\x33"
        # Adaptation field bytes were never consumed as payload (§7.5).
        assert b"\xFF" not in out[0].payload
        assert asm.flush() == []

    def test_pes_spanning_packets(self) -> None:
        """A PES header split across two and three packets assembles."""
        from ts.pes_assembler import PESAssembler

        # Two-packet split of the PTS-only PES.
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(_PTS_PES[:7], pusi=True, cc=0)) == []
        out = asm.push(_ts_packet(_PTS_PES[7:], cc=1))
        assert len(out) == 1
        assert out[0].header.pts == 90000
        assert out[0].payload == b"\x55"
        assert asm.flush() == []

        # Three-packet split of the minimal PES.
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(_MINIMAL_PES[:4], pusi=True, cc=0)) == []
        assert asm.push(_ts_packet(_MINIMAL_PES[4:9], cc=1)) == []
        out = asm.push(_ts_packet(_MINIMAL_PES[9:], cc=2))
        assert len(out) == 1
        assert out[0].payload == b"\x11\x22\x33"
        assert asm.flush() == []

    def test_unbounded_pes_completes_at_next_pusi(self) -> None:
        """Zero-length video PES: PUSI is the completion boundary (§7.4).

        The completed unbounded PES and the new PES both come out of the
        push that carries the next PUSI (§7.1: zero-length profile
        completes at the new start instead of reporting truncated).
        """
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert (
            asm.push(_ts_packet(_UNBOUNDED_HEADER + b"ABCD", pusi=True)) == []
        )
        assert asm.push(_ts_packet(b"EFGH", cc=1)) == []
        out = asm.push(_ts_packet(_MINIMAL_PES, pusi=True, cc=2))
        assert [p.payload for p in out] == [b"ABCDEFGH", b"\x11\x22\x33"]
        assert out[0].header.pes_packet_length == 0
        assert out[1].header.pes_packet_length == 6
        assert asm.flush() == []

    def test_pes_completed_with_extra_payload_bytes(self) -> None:
        """Bytes after a completed bounded PES in the same payload are
        dropped with an explicit issue (§7.3 policy, never silently)."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        out = asm.push(_ts_packet(_MINIMAL_PES + b"\xAB\xCD", pusi=True))
        assert [p.payload for p in out] == [b"\x11\x22\x33"]
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_CONTINUATION_WITHOUT_START"]
        # The offset points at the completion boundary (6 + 6 = 12).
        assert issues[0].offset == 12

    def test_new_pusi_truncates_incomplete_bounded_pes(self) -> None:
        """A new PUSI while a bounded PES is incomplete reports truncated
        and still assembles the new PES (§7.1)."""
        from ts.pes_assembler import PESAssembler

        partial = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x64, 0x80, 0x00, 0x00)
        ) + b"\xAA" * 10  # declares length 100 (0x64), only 10 sent
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(partial, pusi=True)) == []
        out = asm.push(_ts_packet(_MINIMAL_PES, pusi=True, cc=1))
        assert [p.payload for p in out] == [b"\x11\x22\x33"]
        codes = [i.code for i in asm.flush()]
        assert codes == ["PES_TRUNCATED_AT_NEW_START"]

    def test_continuation_without_active_pes(self) -> None:
        """PUSI=0 bytes with no active PES are dropped with an issue (§7.2)."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(b"\x01\x02\x03")) == []
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_CONTINUATION_WITHOUT_START"]

    def test_flush_reports_truncated_at_eof(self) -> None:
        """flush() reports an incomplete PES at EOF instead of fabricating
        completion (SPEC-102 flush symmetry; bounded and unbounded)."""
        from ts.pes_assembler import PESAssembler

        partial_bounded = bytes(
            (0x00, 0x00, 0x01, 0xC0, 0x00, 0x64, 0x80, 0x00, 0x00)
        ) + b"\xAA" * 10
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(partial_bounded, pusi=True)) == []
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_TRUNCATED_AT_EOF"]
        # The assembler is reusable after flush.
        assert asm.flush() == []
        out = asm.push(_ts_packet(_MINIMAL_PES, pusi=True))
        assert [p.payload for p in out] == [b"\x11\x22\x33"]

        unbounded = _UNBOUNDED_HEADER + b"ABCD"
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(unbounded, pusi=True)) == []
        assert [i.code for i in asm.flush()] == ["PES_TRUNCATED_AT_EOF"]


# ---------------------------------------------------------------------------
# REQ-TS-104-005 — malformed input / buffer cap safety (stable errors)
# ---------------------------------------------------------------------------


class TestPesMalformedAndLimits:
    """REQ-TS-104-005: 异常输入稳定错误、无越界、无无界内存 (§3/§9)."""

    def test_pes_malformed_and_limits(self) -> None:
        """Core malformed-input codes: start code, truncation, markers."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import (
            PES_FLAGS_RESERVED,
            PES_HEADER_TRUNCATED,
            PES_START_CODE_INVALID,
            parse_pes,
        )

        # Bad start code prefixes.
        for prefix in (b"\x00\x00\x02", b"\x00\x01\x01", b"\x47\x00\x01"):
            with pytest.raises(InvalidPESPacketError) as excinfo:
                parse_pes(prefix + bytes((0xC0, 0x00, 0x06, 0x80, 0x00, 0x00)))
            assert PES_START_CODE_INVALID in str(excinfo.value)

        # Header truncation: fewer than 9 bytes cannot hold the control
        # block; short PTS header data is also truncated.
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(bytes((0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00)))
        assert PES_HEADER_TRUNCATED in str(excinfo.value)
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(
                bytes(
                    (
                        0x00, 0x00, 0x01, 0xE0, 0x00, 0x09,
                        0x80, 0x80, 0x05, 0x21, 0x00,
                    )
                )
            )
        assert PES_HEADER_TRUNCATED in str(excinfo.value)

        # The '10' marker of the optional header is mandatory.
        for marker_byte in (0x00, 0x40, 0xC0):
            with pytest.raises(InvalidPESPacketError) as excinfo:
                parse_pes(
                    bytes(
                        (0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, marker_byte, 0x00, 0x00)
                    )
                    + b"\x11\x22\x33"
                )
            assert PES_FLAGS_RESERVED in str(excinfo.value)

    def test_unsupported_optional_flags_rejected(self) -> None:
        """ESCR/ES_rate/DSM/add-copy/CRC/extension flags -> unsupported (§3).

        Their bytes must never be misread as PTS or payload.
        """
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_OPTIONAL_FIELD_UNSUPPORTED, parse_pes

        for flags2 in (0x20, 0x10, 0x08, 0x04, 0x02, 0x01, 0x3F):
            data = bytes(
                (
                    0x00, 0x00, 0x01, 0xC0, 0x00, 0x09,
                    0x80, flags2, 0x05,
                )
            ) + bytes(5) + b"\x11\x22\x33"
            with pytest.raises(InvalidPESPacketError) as excinfo:
                parse_pes(data)
            assert PES_OPTIONAL_FIELD_UNSUPPORTED in str(excinfo.value)

    def test_header_data_length_mismatch_rejected(self) -> None:
        """PES_header_data_length must exactly match the flags (no raw bytes)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_HEADER_DATA_LENGTH_INVALID, parse_pes

        # PTS-only flags (0x80) but hdl=6 (raw optional bytes).
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(
                bytes(
                    (0x00, 0x00, 0x01, 0xE0, 0x00, 0x0A, 0x80, 0x80, 0x06)
                )
                + bytes(6) + b"\x55"
            )
        assert PES_HEADER_DATA_LENGTH_INVALID in str(excinfo.value)

        # No-timestamp flags but hdl=3.
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(
                bytes((0x00, 0x00, 0x01, 0xC0, 0x00, 0x06, 0x80, 0x00, 0x03))
                + bytes(3) + b"\x11\x22\x33"
            )
        assert PES_HEADER_DATA_LENGTH_INVALID in str(excinfo.value)

    def test_special_stream_ids_rejected(self) -> None:
        """Special stream_ids never get mis-parsed as standard headers (§3)."""
        from ts.errors import InvalidPESPacketError
        from ts.pes import PES_STREAM_ID_PROFILE_UNSUPPORTED, parse_pes

        special_ids = (0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xF2, 0xF8, 0xFF)
        for stream_id in special_ids:
            data = bytes(
                (0x00, 0x00, 0x01, stream_id, 0x00, 0x06, 0x80, 0x00, 0x00)
            ) + b"\x11\x22\x33"
            with pytest.raises(InvalidPESPacketError) as excinfo:
                parse_pes(data)
            assert PES_STREAM_ID_PROFILE_UNSUPPORTED in str(excinfo.value)

        # Unknown parse profiles are rejected as profile-unsupported.
        with pytest.raises(InvalidPESPacketError) as excinfo:
            parse_pes(_MINIMAL_PES, profile="special_padding")
        assert PES_STREAM_ID_PROFILE_UNSUPPORTED in str(excinfo.value)

    def test_assembler_pid_mismatch(self) -> None:
        """A foreign-PID packet is evidenced and the active PES discarded."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        partial = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x64, 0x80, 0x00, 0x00)
        ) + b"\xAA" * 10
        assert asm.push(_ts_packet(partial, pusi=True)) == []
        assert asm.push(_ts_packet(b"\x01\x02", pid=0x200, cc=0)) == []
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_PID_MISMATCH"]
        # The active PES was discarded: a PUSI=0 continuation finds no PES.
        assert asm.push(_ts_packet(b"\x03\x04")) == []
        assert [i.code for i in asm.flush()] == ["PES_CONTINUATION_WITHOUT_START"]

    def test_assembler_tei_drops_packet_and_pes(self) -> None:
        """TEI=1: current PES discarded, payload not consumed (§7.6)."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        partial = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x64, 0x80, 0x00, 0x00)
        ) + b"\xAA" * 10
        assert asm.push(_ts_packet(partial, pusi=True)) == []
        # A TEI packet carrying a complete PES must NOT emit it.
        assert (
            asm.push(_ts_packet(_MINIMAL_PES, pusi=True, cc=1, tei=True)) == []
        )
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_TRANSPORT_ERROR"]

    def test_assembler_discontinuity_evidence(self) -> None:
        """discontinuity_indicator=1 discards the PES but keeps the stream
        going: this packet's own payload is still processed (§7.6)."""
        from ts.pes_assembler import PESAssembler

        partial = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x64, 0x80, 0x00, 0x00)
        ) + b"\xAA" * 10
        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        assert asm.push(_ts_packet(partial, pusi=True)) == []
        out = asm.push(
            _ts_packet(_MINIMAL_PES, pusi=True, cc=1, discontinuity=True)
        )
        assert [p.payload for p in out] == [b"\x11\x22\x33"]
        issues = asm.flush()
        assert [i.code for i in issues] == ["PES_DISCONTINUITY"]

    def test_assembler_buffer_cap_unbounded(self) -> None:
        """An unbounded PES over the cap is discarded with evidence (§7.4)."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=10)
        assert (
            asm.push(_ts_packet(_UNBOUNDED_HEADER + b"ABCD", pusi=True)) == []
        )
        assert [i.code for i in asm.flush()] == ["PES_BUFFER_LIMIT_EXCEEDED"]

    def test_assembler_buffer_cap_bounded(self) -> None:
        """A bounded PES accumulation also respects the cap."""
        from ts.pes_assembler import PESAssembler

        header_only = bytes(
            (0x00, 0x00, 0x01, 0xE0, 0x00, 0x64, 0x80, 0x00, 0x00)
        )  # declares length 100 -> target 106 > cap
        asm = PESAssembler(0x100, max_buffer_bytes=10)
        assert asm.push(_ts_packet(header_only + b"\xAA\xBB", pusi=True)) == []
        assert [i.code for i in asm.flush()] == ["PES_BUFFER_LIMIT_EXCEEDED"]

    def test_assembler_cap_boundary_still_assembles(self) -> None:
        """A PES completing exactly at the cap is not over the limit."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=12)
        out = asm.push(_ts_packet(_MINIMAL_PES, pusi=True))
        assert [p.payload for p in out] == [b"\x11\x22\x33"]
        assert asm.flush() == []

    def test_assembler_malformed_pes_becomes_issues(self) -> None:
        """Parse failures inside the assembler surface as issues, never
        exceptions, and never emit packets."""
        from ts.pes_assembler import PESAssembler

        asm = PESAssembler(0x100, max_buffer_bytes=1000)
        # Bad start code in the PUSI payload.
        assert asm.push(_ts_packet(b"\x00\x00\x02" + bytes(9), pusi=True)) == []
        # Special stream_id.
        special = bytes(
            (0x00, 0x00, 0x01, 0xBE, 0x00, 0x03, 0x80, 0x00, 0x00)
        ) + b"\x99"
        assert asm.push(_ts_packet(special, pusi=True, cc=1)) == []
        codes = [i.code for i in asm.flush()]
        assert codes == ["PES_START_CODE_INVALID", "PES_STREAM_ID_PROFILE_UNSUPPORTED"]

    def test_parse_fuzz_stability(self) -> None:
        """Random bytes only ever raise the typed PES error (fixed seed)."""
        import random

        from ts.errors import InvalidPESPacketError, TSCoreError
        from ts.pes import parse_pes

        rng = random.Random(104)
        for _ in range(300):
            size = rng.randrange(0, 40)
            blob = bytes(rng.randrange(256) for _ in range(size))
            try:
                parse_pes(blob)
            except TSCoreError as exc:
                assert isinstance(exc, InvalidPESPacketError)

    def test_assembler_fuzz_stability(self) -> None:
        """Random TS payloads only produce issues or packets, never crashes."""
        import random

        from ts.adaptation_field import AdaptationField
        from ts.issues import ParseIssue
        from ts.packet import TSPacket
        from ts.pes import PESPacket
        from ts.pes_assembler import PESAssembler

        rng = random.Random(1041)
        asm = PESAssembler(0x100, max_buffer_bytes=64)
        for i in range(60):
            size = rng.randrange(1, 60)
            blob = bytes(rng.randrange(256) for _ in range(size))
            pusi = rng.random() < 0.4
            tei = rng.random() < 0.1
            packet = TSPacket(
                pid=0x100,
                continuity_counter=i % 16,
                payload=blob,
                payload_unit_start_indicator=pusi,
                transport_error_indicator=tei,
                adaptation_field=AdaptationField(),
            )
            out = asm.push(packet)
            assert all(isinstance(p, PESPacket) for p in out)
        for issue in asm.flush():
            assert isinstance(issue, ParseIssue)


# ---------------------------------------------------------------------------
# REQ-TS-104-006 — analysis_only profile metadata (no playback claims)
# ---------------------------------------------------------------------------


class TestAnalysisOnlyProfileMetadata:
    """REQ-TS-104-006: synthetic payload 明确 analysis_only，不虚构
    playback-ready (SPEC-104 §8)."""

    def test_analysis_only_profile_metadata(self) -> None:
        """The analysis-only profile marks synthetic payloads and can
        never claim playback readiness."""
        from ts.pes import (
            ANALYSIS_ONLY_PROFILE,
            ANALYSIS_ONLY_PROFILE_METADATA,
            make_analysis_only_pes,
        )

        # The profile name and its frozen metadata record.
        assert ANALYSIS_ONLY_PROFILE == "analysis_only"
        assert ANALYSIS_ONLY_PROFILE_METADATA.profile == "analysis_only"
        # playback_ready is False by construction — the profile cannot
        # assert decoding capability (SPEC-104 §8, REQ-104-006).
        assert ANALYSIS_ONLY_PROFILE_METADATA.playback_ready is False
        assert ANALYSIS_ONLY_PROFILE_METADATA.payload_is_synthetic is True
        assert ANALYSIS_ONLY_PROFILE_METADATA.deterministic is True

        # Synthetic PES packets carry the mark on the object.
        packet = make_analysis_only_pes(
            stream_id=0xE0, payload=b"\x7F\x00\xAA"
        )
        assert packet.analysis_only is True

    def test_analysis_only_payload_is_deterministic(self) -> None:
        """Same builder inputs give byte-identical PES (no wall clock)."""
        from ts.pes import make_analysis_only_pes, serialize_pes

        first = make_analysis_only_pes(stream_id=0xE0, pts=90000)
        second = make_analysis_only_pes(stream_id=0xE0, pts=90000)
        assert serialize_pes(first) == serialize_pes(second)

    def test_analysis_only_mark_never_touches_wire_bytes(self) -> None:
        """parse never invents the mark; serialize ignores it (contract §2:
        the protocol bytes are the authoritative result)."""
        from ts.pes import (
            PESHeader,
            PESPacket,
            make_analysis_only_pes,
            parse_pes,
            serialize_pes,
        )

        marked = make_analysis_only_pes(stream_id=0xC0, payload=b"\x01\x02")
        data = serialize_pes(marked)
        # The mark is construction metadata only: wire bytes carry no
        # playback/analysis bit, so parsing yields analysis_only=False.
        parsed = parse_pes(data)
        assert parsed.analysis_only is False
        assert parsed.payload == b"\x01\x02"

        # An unmarked twin serializes to identical bytes.
        plain = PESPacket(
            header=PESHeader(
                stream_id=0xC0,
                pes_packet_length=marked.header.pes_packet_length,
            ),
            payload=b"\x01\x02",
        )
        assert serialize_pes(plain) == data
