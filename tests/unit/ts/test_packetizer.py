"""SPEC-106 — TS packetizer — unit tests (ticket #32).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-106 section):

- REQ-TS-106-001  Section pointer/PUSI 正确                     -> test_section_packetizer
- REQ-TS-106-002  PES PUSI 和顺序正确                           -> test_pes_packetizer
- REQ-TS-106-003  每个输出固定 188 bytes                        -> test_packetizer_packet_size
- REQ-TS-106-004  AF stuffing 容量正确                          -> test_packetizer_adaptation_stuffing
- REQ-TS-106-005  CCAllocator 一致使用                          -> test_packetizer_cc
- REQ-TS-106-006  Section/PES 重组 round-trip                   -> test_packetizer_round_trip

Expected values are hand-derived from SPEC-106 §5-§8 arithmetic (first
section packet capacity 183 + pointer, continuation capacity 184,
``adaptation_field_length = 183 - payload``) and asserted against raw wire
bytes and the upstream parsers (SPEC-100 ``TSPacket.from_bytes``, SPEC-102
``SectionAssembler``, SPEC-104 ``PESAssembler``) — never recomputed through
the packetizer itself. Ruling #11 freezes ``build_pcr_only_packet`` as the
only adaptation-only PCR packet constructor (AFC=10, CC reused without
advance); the PCR insertion *timing* belongs to SPEC-107 and the PCR
*value* to SPEC-105, so these tests only assert construction semantics.
Section/PES payload bytes are procedurally generated with a fixed formula
(never ``0xFF``) — deterministic literals, not environment values
(tests/README.md §6). Imports follow the upstream ts-core test style:
``ts.*`` modules are imported inside the tests that need them.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# --- deterministic input builders (fixed arithmetic, no randomness) ---

_PES_START_PREFIX = b"\x00\x00\x01"


def make_section(total: int) -> bytes:
    """A deterministic short-form PSI section of exactly ``total`` bytes.

    Hand-packed per SPEC-102 §3: table_id 0x42, byte1 = SSI=0 | private=1 |
    reserved=0b11 | declared>>8, byte2 = declared & 0xFF. Body bytes follow
    the fixed formula ``(i * 7 + 3) & 0x7E`` — even values, never ``0xFF``
    (0xFF would collide with the assembler's stuffing boundary semantics).
    """
    from ts.section import SECTION_LENGTH_WIRE_MAX

    declared = total - 3
    assert 0 <= declared <= SECTION_LENGTH_WIRE_MAX
    body = bytes((i * 7 + 3) & 0x7E for i in range(declared))
    return bytes((0x42, 0x70 | ((declared >> 8) & 0x0F), declared & 0xFF)) + body


def make_pes_bytes(total: int) -> bytes:
    """A deterministic standard-profile PES byte string of ``total`` bytes.

    9-byte PES header (SPEC-104 §3: prefix 00 00 01, stream_id 0xC0 audio,
    16-bit length, '10' marker flags byte, flags2, header_data_length=0)
    plus a formula-generated payload of ``total - 9`` bytes (never 0xFF).
    The declared length field equals ``total - 6`` (bounded profile).
    """
    assert total >= 9
    payload = bytes((i * 13 + 5) & 0x7E for i in range(total - 9))
    return (
        _PES_START_PREFIX
        + b"\xc0"
        + (total - 6).to_bytes(2, "big")
        + b"\x80\x00\x00"
        + payload
    )


def make_pes_packet(total: int) -> "object":
    """A :class:`ts.pes.PESPacket` serializing (auto) to ``make_pes_bytes(total)``."""
    from ts.pes import PESHeader, PESPacket

    payload = bytes((i * 13 + 5) & 0x7E for i in range(total - 9))
    return PESPacket(
        header=PESHeader(stream_id=0xC0, pes_packet_length=0), payload=payload
    )


def make_pcr(base: int = 258_000, extension: int = 42) -> "object":
    """A fixed SPEC-105 PCR value (literal, independent of the code under test)."""
    from ts.pcr import PCR

    return PCR(base=base, extension=extension)


def _policy(_table_id: int) -> "object":
    """Assembler policy resolver accepting any short-form table (no CRC)."""
    from ts.section import CrcPolicy, SectionPolicy

    return SectionPolicy(max_section_length=0x0FFF, crc_policy=CrcPolicy.ABSENT)


# ---------------------------------------------------------------------------
# Primary test REQ-TS-106-001
# ---------------------------------------------------------------------------


class TestSectionPacketizer:
    """REQ-TS-106-001: Section packetization 的 pointer/PUSI 语义正确."""

    def test_section_packetizer(self) -> None:
        """pointer_field=0, PUSI 只在首包, 183/184 容量边界, 多包顺序保持."""
        from ts.adaptation_field import AdaptationFieldControl
        from ts.cc import CCAllocator
        from ts.packet import TSPacket
        from ts.packetizer.section_packetizer import SectionPacketizer
        from ts.section import PSISection, parse_section

        # Single packet (S=4): PUSI=1, pointer_field=0, section data from
        # payload offset 1, remaining capacity padded by AF stuffing (§5.1).
        sec = make_section(4)
        (p,) = list(SectionPacketizer(100, CCAllocator()).packetize(sec))
        assert isinstance(p, TSPacket)
        assert p.pid == 100
        assert p.payload_unit_start_indicator is True
        assert p.continuity_counter == 0
        assert p.payload == b"\x00" + sec
        assert p.adaptation_field is not None  # payload 5 < 184 -> AF stuffing

        # S=183: pointer + 183 section bytes = 184 payload -> AFC=01
        # payload-only, no AF at all (SPEC-106 §7).
        sec183 = make_section(183)
        (p,) = list(SectionPacketizer(100, CCAllocator()).packetize(sec183))
        assert p.payload == b"\x00" + sec183
        assert p.adaptation_field is None
        assert p.adaptation_field_control == AdaptationFieldControl.PAYLOAD_ONLY

        # S=184: first packet carries pointer+183 (capacity limit §5.2), the
        # single remaining byte goes to a PUSI=0 continuation packet.
        sec184 = make_section(184)
        packets = list(SectionPacketizer(100, CCAllocator()).packetize(sec184))
        assert len(packets) == 2
        first, second = packets
        assert first.payload_unit_start_indicator is True
        assert second.payload_unit_start_indicator is False
        assert first.payload == b"\x00" + sec184[:183]
        assert second.payload == sec184[183:]
        assert second.adaptation_field is not None  # stuffing to 188

        # Multi-packet (S=900): 1 + ceil(717/184) = 5 packets; bytes keep
        # their order, the pointer byte appears only in the first payload.
        sec900 = make_section(900)
        packets = list(SectionPacketizer(100, CCAllocator()).packetize(sec900))
        assert len(packets) == 5
        assert [p.payload_unit_start_indicator for p in packets] == [
            True,
            False,
            False,
            False,
            False,
        ]
        joined = b"".join(p.payload for p in packets)
        assert joined[0] == 0  # pointer_field=0 in the first packet only
        assert joined[1:] == sec900  # section bytes unchanged, no stuffing

        # PSISection object input frames the same bytes as raw bytes input.
        section_obj = parse_section(sec900, _policy(0x42))
        assert isinstance(section_obj, PSISection)
        obj_packets = list(
            SectionPacketizer(100, CCAllocator()).packetize(section_obj)
        )
        assert [p.payload for p in obj_packets] == [p.payload for p in packets]
        assert [p.to_bytes() for p in obj_packets] == [
            p.to_bytes() for p in packets
        ]

    def test_section_input_errors(self) -> None:
        """Empty and header-inconsistent section bytes raise PACKETIZER_* codes."""
        from ts.cc import CCAllocator
        from ts.errors import PacketizationError
        from ts.packetizer.section_packetizer import SectionPacketizer

        pktz = SectionPacketizer(100, CCAllocator())
        with pytest.raises(PacketizationError, match="PACKETIZER_EMPTY_SECTION"):
            list(pktz.packetize(b""))
        # 2 bytes: no room for the 3-byte section header (§5 framing needs it).
        with pytest.raises(
            PacketizationError, match="PACKETIZER_SECTION_HEADER_INVALID"
        ):
            list(pktz.packetize(b"\x42\x70"))
        # Declared section_length=0 but 1 trailing byte: the MVP packetizer
        # carries exactly one complete section per run (SPEC-106 §5.2).
        with pytest.raises(
            PacketizationError, match="PACKETIZER_SECTION_HEADER_INVALID"
        ):
            list(pktz.packetize(b"\x42\x70\x00\x01"))

    def test_section_packetizer_rejects_bad_pid(self) -> None:
        """Out-of-range and null PIDs raise PACKETIZER_PID_INVALID (§8)."""
        from ts.cc import CCAllocator
        from ts.errors import PacketizationError
        from ts.packet import PID_NULL
        from ts.packetizer.section_packetizer import SectionPacketizer

        for bad_pid in (-1, 0x2000, PID_NULL):
            with pytest.raises(PacketizationError, match="PACKETIZER_PID_INVALID"):
                SectionPacketizer(bad_pid, CCAllocator())
        with pytest.raises(TypeError):
            SectionPacketizer(True, CCAllocator())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Primary test REQ-TS-106-002
# ---------------------------------------------------------------------------


class TestPESPacketizer:
    """REQ-TS-106-002: PES packetization 的 PUSI 和字节顺序正确."""

    def test_pes_packetizer(self) -> None:
        """PUSI 只在首包、无 pointer_field、字节连续、PCR/RAI 附着正确."""
        from ts.adaptation_field import ZERO_LENGTH_ADAPTATION_FIELD
        from ts.cc import CCAllocator
        from ts.packetizer.pes_packetizer import PESPacketizer

        def fresh() -> PESPacketizer:
            return PESPacketizer(200, CCAllocator())

        # P=10: single packet, PUSI=1, NO pointer field, PES bytes verbatim.
        pes10 = make_pes_bytes(10)
        (p,) = list(fresh().packetize(pes10))
        assert p.pid == 200
        assert p.payload_unit_start_indicator is True
        assert p.payload == pes10  # PES payload never gets a pointer byte
        assert p.adaptation_field is not None  # payload < 183 -> AF stuffing

        # P=183: single packet, zero-length adaptation field (AFC=11,
        # adaptation_field_length=0, no flags byte — SPEC-106 §7).
        pes183 = make_pes_bytes(183)
        (p,) = list(fresh().packetize(pes183))
        assert p.payload == pes183
        assert p.adaptation_field is ZERO_LENGTH_ADAPTATION_FIELD

        # P=184: single packet AFC=01 payload-only, no AF.
        pes184 = make_pes_bytes(184)
        (p,) = list(fresh().packetize(pes184))
        assert p.payload == pes184
        assert p.adaptation_field is None

        # P=185: 2 packets; the PES byte sequence stays contiguous, no
        # stuffing bytes may be inserted between PES bytes (§6).
        pes185 = make_pes_bytes(185)
        packets = list(fresh().packetize(pes185))
        assert len(packets) == 2
        assert [p.payload_unit_start_indicator for p in packets] == [True, False]
        assert b"".join(p.payload for p in packets) == pes185
        assert packets[0].payload == pes185[:184]

        # P=400: 3 packets, order preserved.
        pes400 = make_pes_bytes(400)
        packets = list(fresh().packetize(pes400))
        assert len(packets) == 3
        assert [p.payload_unit_start_indicator for p in packets] == [
            True,
            False,
            False,
        ]
        assert b"".join(p.payload for p in packets) == pes400

        # PESPacket object input frames the same bytes as serialized input.
        obj_packets = list(fresh().packetize(make_pes_packet(400)))
        assert [p.payload for p in obj_packets] == [p.payload for p in packets]
        assert [p.to_bytes() for p in obj_packets] == [
            p.to_bytes() for p in packets
        ]

    def test_pes_random_access_indicator_first_packet_only(self) -> None:
        """random_access 由调用者显式请求, 只落在 PES 首包 AF flags (§6)."""
        from ts.cc import CCAllocator
        from ts.packetizer.pes_packetizer import PESPacketizer

        pes = make_pes_bytes(200)  # 2 packets
        packets = list(
            PESPacketizer(200, CCAllocator()).packetize(pes, random_access=True)
        )
        first, second = packets
        assert first.adaptation_field is not None
        assert first.adaptation_field.random_access_indicator is True
        assert second.adaptation_field is not None  # last packet stuffing
        assert second.adaptation_field.random_access_indicator is False

    def test_pes_first_packet_pcr_attachment(self) -> None:
        """first_packet_pcr: AFC=11, PCR 进 AF, payload 从正确 offset 开始 (§6)."""
        from ts.adaptation_field import AdaptationFieldControl
        from ts.cc import CCAllocator
        from ts.packetizer.pes_packetizer import PESPacketizer

        pcr = make_pcr(base=123_456, extension=123)
        pes = make_pes_bytes(100)  # single packet, payload 100 <= 176
        (p,) = list(
            PESPacketizer(200, CCAllocator()).packetize(pes, first_packet_pcr=pcr)
        )
        assert p.adaptation_field is not None
        assert (
            p.adaptation_field_control
            == AdaptationFieldControl.ADAPTATION_AND_PAYLOAD
        )
        assert p.adaptation_field.pcr == pcr  # 6-byte encoding stays SPEC-105's
        assert p.payload == pes  # PES start bytes intact, offset untouched

        # Multi-packet PES (P=400): first packet carries the PCR (payload
        # 176), the full 184-byte continuation is AFC=01 without AF, the
        # last remainder gets stuffing; payload stays contiguous.
        pes400 = make_pes_bytes(400)
        packets = list(
            PESPacketizer(200, CCAllocator()).packetize(pes400, first_packet_pcr=pcr)
        )
        assert len(packets) == 3
        assert packets[0].adaptation_field is not None
        assert packets[0].adaptation_field.pcr == pcr
        assert packets[0].payload == pes400[:176]
        assert packets[1].adaptation_field is None  # full continuation AFC=01
        assert packets[2].adaptation_field is not None  # last packet stuffing
        assert packets[2].adaptation_field.pcr is None  # no mid-PES PCR (§2)
        assert b"".join(p.payload for p in packets) == pes400

    def test_pes_input_errors(self) -> None:
        """Empty/short/bad-prefix/length-mismatch PES bytes raise PACKETIZER_* codes."""
        from ts.cc import CCAllocator
        from ts.errors import PacketizationError
        from ts.packetizer.pes_packetizer import PESPacketizer

        pktz = PESPacketizer(200, CCAllocator())
        with pytest.raises(PacketizationError, match="PACKETIZER_EMPTY_PES"):
            list(pktz.packetize(b""))
        # 5 bytes: no room for prefix + stream_id + PES_packet_length.
        with pytest.raises(PacketizationError, match="PACKETIZER_PES_HEADER_INVALID"):
            list(pktz.packetize(b"\x00\x00\x01\xc0\x00"))
        # Wrong start-code prefix.
        with pytest.raises(PacketizationError, match="PACKETIZER_PES_HEADER_INVALID"):
            list(pktz.packetize(b"\x00\x00\x02\xc0\x00\x04\x80\x00\x00"))
        # Declared PES_packet_length=1 implies 7 total bytes, got 12.
        with pytest.raises(PacketizationError, match="PACKETIZER_PES_HEADER_INVALID"):
            list(
                pktz.packetize(b"\x00\x00\x01\xc0\x00\x01\x80\x00\x00\xAA\xBB\xCC")
            )

    def test_pes_object_input_propagates_spec104_errors(self) -> None:
        """PESPacket serialization failures keep SPEC-104's own error family."""
        from ts.cc import CCAllocator
        from ts.errors import InvalidPESPacketError
        from ts.pes import PESHeader, PESPacket
        from ts.packetizer.pes_packetizer import PESPacketizer

        pktz = PESPacketizer(200, CCAllocator())
        mismatched = PESPacket(
            header=PESHeader(stream_id=0xC0, pes_packet_length=999), payload=b"abc"
        )
        with pytest.raises(InvalidPESPacketError):
            list(pktz.packetize(mismatched))

    def test_pes_capacity_errors(self) -> None:
        """PCR/RAI 不能与 177..184/183..184 单包 PES 共存 (§6 配置应失败)."""
        from ts.cc import CCAllocator
        from ts.errors import PacketizationError
        from ts.packetizer.pes_packetizer import PESPacketizer

        pcr = make_pcr()
        pktz = PESPacketizer(200, CCAllocator())
        # PCR needs adaptation_field_length >= 7; P in 177..184 leaves less.
        for bad_len in (177, 180, 184):
            with pytest.raises(
                PacketizationError, match="PACKETIZER_PCR_DOES_NOT_FIT"
            ):
                list(pktz.packetize(make_pes_bytes(bad_len), first_packet_pcr=pcr))
        # Boundary that still fits: P=176 -> adaptation_field_length exactly 7.
        packets = list(pktz.packetize(make_pes_bytes(176), first_packet_pcr=pcr))
        assert len(packets) == 1
        # RAI needs adaptation_field_length >= 1; P in 183..184 leaves none.
        for bad_len in (183, 184):
            with pytest.raises(
                PacketizationError, match="PACKETIZER_AF_CAPACITY_EXCEEDED"
            ):
                list(pktz.packetize(make_pes_bytes(bad_len), random_access=True))
        # Boundary that still fits: P=182 -> adaptation_field_length exactly 1.
        packets = list(pktz.packetize(make_pes_bytes(182), random_access=True))
        assert len(packets) == 1

    def test_pes_packetizer_rejects_bad_pid(self) -> None:
        """Out-of-range and null PIDs raise PACKETIZER_PID_INVALID (§8)."""
        from ts.cc import CCAllocator
        from ts.errors import PacketizationError
        from ts.packet import PID_NULL
        from ts.packetizer.pes_packetizer import PESPacketizer

        for bad_pid in (-1, 0x2000, PID_NULL):
            with pytest.raises(PacketizationError, match="PACKETIZER_PID_INVALID"):
                PESPacketizer(bad_pid, CCAllocator())
        with pytest.raises(TypeError):
            PESPacketizer(True, CCAllocator())  # type: ignore[arg-type]
