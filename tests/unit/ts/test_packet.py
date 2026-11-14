"""SPEC-100 — MPEG-2 TS Packet — unit tests (ticket #28).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-100 section):

- REQ-TS-100-001  188-byte parse/serialize round trip        -> test_packet_round_trip
- REQ-TS-100-002  header bit layout / PID / AFC / CC fields  -> test_header_fields
- REQ-TS-100-003  adaptation field + opaque extension        -> test_adaptation_field_round_trip
- REQ-TS-100-004  length/offset boundary safety              -> test_packet_malformed_boundaries
- REQ-TS-100-005  CCAllocator PID state / payload rule / wrap -> test_cc_allocator
- REQ-TS-100-006  fuzz/property stability                    -> test_packet_fuzz_safety

Expected values are hand-computed literals from the SPEC-100 §3 bit table
(ITU-T H.222.0 TS packet header), never recomputed through the
implementation under test. Ruling #11 freezes strict-rejection semantics
for trailing bytes: ``from_bytes`` accepts exactly 188 bytes and rejects
longer inputs with ``TS_PACKET_SIZE_INVALID``. Property loops use a fixed
seed so failures stay reproducible (tests/README.md §6).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# REQ-TS-100-002 — header bit layout / PID / AFC / CC fields
# ---------------------------------------------------------------------------


class TestHeaderFields:
    """REQ-TS-100-002: Header 字段位宽和 bit layout 正确 (SPEC-100 §3)."""

    def test_header_fields(self) -> None:
        """Hand-computed header literals pack/unpack to the same fields."""
        from ts.packet import TSPacket

        # Byte 1 = TEI<<7 | PUSI<<6 | priority<<5 | PID>>8 (5 bits).
        # Byte 2 = PID & 0xFF.
        # Byte 3 = TSC<<6 | AFC<<4 | CC.
        packet = TSPacket(
            pid=0x1234,
            continuity_counter=7,
            payload=bytes(184),
            payload_unit_start_indicator=True,
            transport_scrambling_control=0b10,
        )
        header = packet.to_bytes()[:4]
        # 0x47 sync | 0x40 PUSI | 0x12 pid>>8 ; 0x34 ;
        # 0x97 = TSC=10 | AFC=01 | CC=0111 (payload-only, no AF).
        assert header == bytes((0x47, 0x52, 0x34, 0x97))

        parsed = TSPacket.from_bytes(bytes((0x47, 0x52, 0x34, 0x97)) + bytes(184))
        assert parsed.pid == 0x1234
        assert parsed.continuity_counter == 7
        assert parsed.payload_unit_start_indicator is True
        assert parsed.transport_error_indicator is False
        assert parsed.transport_priority is False
        assert parsed.transport_scrambling_control == 0b10
        assert parsed.adaptation_field is None
        assert parsed.payload == bytes(184)

    def test_tei_and_priority_bits(self) -> None:
        """TEI (bit 7) and transport priority (bit 5) land in byte 1."""
        from ts.packet import TSPacket

        packet = TSPacket(
            pid=0x0002,
            continuity_counter=0,
            payload=bytes(184),
            transport_error_indicator=True,
            transport_priority=True,
        )
        # 0x80 (TEI) | 0x20 (priority) | 0x00 (pid>>8) ; byte2 = 0x02 ;
        # byte3 = TSC=00 | AFC=01 | CC=0000 = 0x10.
        assert packet.to_bytes()[:4] == bytes((0x47, 0xA0, 0x02, 0x10))
        parsed = TSPacket.from_bytes(bytes((0x47, 0xA0, 0x02, 0x10)) + bytes(184))
        assert parsed.transport_error_indicator is True
        assert parsed.transport_priority is True
        assert parsed.payload_unit_start_indicator is False
        assert parsed.pid == 0x0002

    def test_all_scrambling_and_afc_values(self) -> None:
        """TSC 00/01/10/11 and AFC 01/10/11 map onto byte 3 exactly."""
        from ts.adaptation_field import AdaptationField, ZERO_LENGTH_ADAPTATION_FIELD
        from ts.packet import TSPacket

        payload_only = TSPacket(pid=0, continuity_counter=0, payload=bytes(184))
        assert payload_only.to_bytes()[3] == 0b00_01_0000  # TSC=00 AFC=01 CC=0

        scrambled_even = TSPacket(
            pid=0,
            continuity_counter=15,
            payload=bytes(184),
            transport_scrambling_control=0b10,
        )
        assert scrambled_even.to_bytes()[3] == 0b10_01_1111

        scrambled_odd = TSPacket(
            pid=0,
            continuity_counter=15,
            payload=bytes(184),
            transport_scrambling_control=0b11,
        )
        assert scrambled_odd.to_bytes()[3] == 0b11_01_1111

        # AFC=10 (adaptation only): full-size AF (length byte + 183 body).
        adapt_only = TSPacket(pid=0, continuity_counter=1, payload=None, adaptation_field=AdaptationField())
        raw = adapt_only.to_bytes()
        assert raw[3] == 0b00_10_0001
        assert raw[4] == 183  # adaptation_field_length occupies the rest

        # AFC=11 with zero-length AF body (length byte only, 183-byte payload).
        both = TSPacket(
            pid=0,
            continuity_counter=2,
            payload=bytes(183),
            adaptation_field=ZERO_LENGTH_ADAPTATION_FIELD,
        )
        raw = both.to_bytes()
        assert raw[3] == 0b00_11_0010
        assert raw[4] == 0  # adaptation_field_length == 0, no flags byte

    def test_pid_boundaries_accepted_and_rejected(self) -> None:
        """PID 0/1/0x1FFE/0x1FFF accepted; -1 and 0x2000 rejected (§9)."""
        from ts.errors import InvalidPacketError
        from ts.packet import PID_NULL, TSPacket

        assert PID_NULL == 0x1FFF
        for pid in (0, 1, 0x1FFE, 0x1FFF):
            packet = TSPacket(pid=pid, continuity_counter=0, payload=bytes(184))
            raw = packet.to_bytes()
            assert raw[1] & 0x1F == pid >> 8
            assert raw[2] == pid & 0xFF
            assert TSPacket.from_bytes(raw).pid == pid

        for bad_pid in (-1, 0x2000, 0x10000):
            with pytest.raises(InvalidPacketError):
                TSPacket(pid=bad_pid, continuity_counter=0, payload=bytes(184))

    def test_cc_boundaries_accepted_and_rejected(self) -> None:
        """CC 0 and 15 accepted; -1 and 16 rejected (§9)."""
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket

        for cc in (0, 15):
            packet = TSPacket(pid=0, continuity_counter=cc, payload=bytes(184))
            assert packet.to_bytes()[3] & 0x0F == cc
            assert TSPacket.from_bytes(packet.to_bytes()).continuity_counter == cc

        for bad_cc in (-1, 16, 256):
            with pytest.raises(InvalidPacketError):
                TSPacket(pid=0, continuity_counter=bad_cc, payload=bytes(184))

    def test_afc_reserved_zero_is_rejected_at_parse(self) -> None:
        """AFC=00 is reserved/invalid -> stable InvalidPacketError (§8)."""
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket

        # Constructed objects can never carry AFC=00 (both AF and payload
        # absent is illegal per §4), so exercise the parse path directly.
        header = bytes((0x47, 0x00, 0x00, 0b00_00_0000))
        with pytest.raises(InvalidPacketError):
            TSPacket.from_bytes(header + bytes(184))

    def test_scrambling_reserved_01_is_preserved_and_reported(self) -> None:
        """TSC=01 round trips unchanged; validate() reports it (§5.3)."""
        from ts.packet import TSPacket

        packet = TSPacket(
            pid=0,
            continuity_counter=0,
            payload=bytes(184),
            transport_scrambling_control=0b01,
        )
        assert packet.to_bytes()[3] >> 6 == 0b01  # value preserved verbatim
        parsed = TSPacket.from_bytes(packet.to_bytes())
        assert parsed.transport_scrambling_control == 0b01  # never rewritten

        issues = parsed.validate()
        assert len(issues) == 1
        assert issues[0].code == "TS_SCRAMBLING_RESERVED"
        assert issues[0].field == "transport_scrambling_control"

        clean = TSPacket(pid=0, continuity_counter=0, payload=bytes(184))
        assert clean.validate() == []

    def test_validate_reports_semantic_issues_only(self) -> None:
        """validate() is the semantic layer: warning, no offset, typed field."""
        from ts.packet import TSPacket

        packet = TSPacket(
            pid=0,
            continuity_counter=3,
            payload=bytes(184),
            transport_scrambling_control=0b01,
        )
        issues = packet.validate()
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert not hasattr(issues[0], "offset")


# ---------------------------------------------------------------------------
# REQ-TS-100-001 — 188-byte packet parse/serialize round trip
# ---------------------------------------------------------------------------


class TestPacketRoundTrip:
    """REQ-TS-100-001: 有效 188-byte Packet 可解析并原样 round-trip (§10)."""

    @staticmethod
    def _full_round_trip(packet: "object") -> None:  # noqa: ANN001 - test helper
        from ts.packet import TS_PACKET_SIZE, TSPacket

        raw = packet.to_bytes()
        assert len(raw) == TS_PACKET_SIZE  # §9: any valid object is 188 bytes
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet  # object-level round trip
        assert parsed.to_bytes() == raw  # byte-level round trip

    def test_packet_round_trip(self) -> None:
        """Payload-only / adaptation-only / both / null-PID / TEI packets."""
        from ts.adaptation_field import AdaptationField
        from ts.packet import PID_NULL, TSPacket
        from ts.pcr import PCR

        # Payload-only (AFC=01): PAT-like header, PUSI, deterministic body.
        self._full_round_trip(
            TSPacket(
                pid=0,
                continuity_counter=0,
                payload=bytes(range(184)),
                payload_unit_start_indicator=True,
            )
        )
        # Payload-only with max PID and CC=15, TEI + priority set.
        self._full_round_trip(
            TSPacket(
                pid=PID_NULL,
                continuity_counter=15,
                payload=bytes(184),
                transport_error_indicator=True,
                transport_priority=True,
                transport_scrambling_control=0b11,
            )
        )
        # Adaptation-only (AFC=10): flags + explicit 0xFF stuffing (§5.2).
        self._full_round_trip(
            TSPacket(
                pid=0x0100,
                continuity_counter=3,
                payload=None,
                adaptation_field=AdaptationField(
                    discontinuity_indicator=True,
                    random_access_indicator=True,
                    # Frame-fill sized by SPEC-100 §5.2 length arithmetic,
                    # not golden stream data.
                    stuffing=b"\xff" * 182,  # testdata-ok: frame-fill sizing
                ),
            )
        )
        # Adaptation+payload (AFC=11) with a PCR (SPEC-105 value type).
        self._full_round_trip(
            TSPacket(
                pid=0x0100,
                continuity_counter=4,
                payload=bytes(range(170)),
                adaptation_field=AdaptationField(
                    random_access_indicator=True,
                    pcr=PCR(base=1000, extension=0),
                    stuffing=b"\xff" * 6,
                ),
            )
        )
        # AFC=11 with OPCR + splice countdown + private data combination.
        self._full_round_trip(
            TSPacket(
                pid=0x0FFF,
                continuity_counter=9,
                payload=bytes(range(150)),
                adaptation_field=AdaptationField(
                    pcr=PCR(base=0, extension=299),
                    opcr=PCR(base=7, extension=42),
                    splice_countdown=-1,
                    transport_private_data=bytes.fromhex("A1B2C3"),
                    # 183 - 150 payload - 18 field bytes = 15 stuffing.
                    stuffing=b"\xff" * 15,
                ),
            )
        )

    def test_parse_serialize_is_byte_identical(self) -> None:
        """from_bytes → to_bytes reproduces the original 188 bytes exactly."""
        from ts.adaptation_field import AdaptationField, ZERO_LENGTH_ADAPTATION_FIELD
        from ts.packet import TSPacket
        from ts.pcr import PCR

        raws = [
            TSPacket(pid=0x1FFE, continuity_counter=0, payload=bytes(184)).to_bytes(),
            TSPacket(
                pid=0x0042,
                continuity_counter=7,
                payload=b"PES\x00" + bytes(180),
            ).to_bytes(),
            # AFC=11 zero-length AF (length byte 0, no flags byte, §5.2).
            TSPacket(
                pid=0x0042,
                continuity_counter=8,
                payload=bytes(183),
                adaptation_field=ZERO_LENGTH_ADAPTATION_FIELD,
            ).to_bytes(),
            TSPacket(
                pid=0x2000 >> 1,
                continuity_counter=12,
                payload=None,
                adaptation_field=AdaptationField(
                    pcr=PCR(base=(1 << 33) - 1, extension=299),
                    # 183 - 1 flags - 6 PCR = 176 stuffing (AFC=10 fills 184).
                    # Frame-fill, not golden stream data.
                    stuffing=b"\xff" * 176,  # testdata-ok: frame-fill sizing
                ),
            ).to_bytes(),
        ]
        for raw in raws:
            assert len(raw) == 188
            assert TSPacket.from_bytes(raw).to_bytes() == raw

    def test_golden_afc11_pcr_packet(self) -> None:
        """Hand-computed 188-byte literal for an AFC=11 PCR packet (§3/§5.2).

        Built from the §3 bit table and the SPEC-105 encoding rules
        (base=1000, extension=0 -> 00 00 01 F4 7E 00), never recomputed by
        the implementation under test.
        """
        from ts.adaptation_field import AdaptationField
        from ts.packet import TSPacket
        from ts.pcr import PCR

        af_body = bytes.fromhex("50" "000001F47E00") + b"\xff" * 6
        expected = (
            bytes((0x47, 0x40, 0x00, 0x30, len(af_body)))
            + af_body
            + bytes(range(170))
        )
        assert len(expected) == 188
        packet = TSPacket(
            pid=0x0000,
            continuity_counter=0,
            payload=bytes(range(170)),
            payload_unit_start_indicator=True,
            adaptation_field=AdaptationField(
                random_access_indicator=True,
                pcr=PCR(base=1000, extension=0),
                stuffing=b"\xff" * 6,
            ),
        )
        assert packet.to_bytes() == expected
        parsed = TSPacket.from_bytes(expected)
        assert parsed.to_bytes() == expected
        assert parsed.pid == 0
        assert parsed.continuity_counter == 0
        assert parsed.payload_unit_start_indicator is True
        assert parsed.payload == bytes(range(170))
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.random_access_indicator is True
        assert parsed.adaptation_field.pcr is not None
        assert parsed.adaptation_field.pcr.base == 1000
        assert parsed.adaptation_field.pcr.extension == 0


# ---------------------------------------------------------------------------
# REQ-TS-100-003 — adaptation field parse/serialize + opaque extension
# ---------------------------------------------------------------------------


class TestAdaptationFieldRoundTrip:
    """REQ-TS-100-003: AF 字段可解析/编码, 未知 extension 无损保留 (§10)."""

    def test_adaptation_field_round_trip(self) -> None:
        """AF length 0 / 1 / 183 and the full optional-field combination."""
        from ts.adaptation_field import AdaptationField, ZERO_LENGTH_ADAPTATION_FIELD
        from ts.packet import TSPacket
        from ts.pcr import PCR

        # AF length 0 (no flags byte) inside AFC=11, §5.2 + §9.
        packet = TSPacket(
            pid=0x0100,
            continuity_counter=1,
            payload=bytes(183),
            adaptation_field=ZERO_LENGTH_ADAPTATION_FIELD,
        )
        raw = packet.to_bytes()
        assert raw[4] == 0  # adaptation_field_length, no flags byte follows
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.is_zero_length

        # AF length 1: flags byte only, every flag bit zero (§9).
        packet = TSPacket(
            pid=0x0100,
            continuity_counter=2,
            payload=bytes(182),
            adaptation_field=AdaptationField(),
        )
        raw = packet.to_bytes()
        assert raw[4] == 1
        assert raw[5] == 0x00
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet

        # AF length 183 is legal only for AFC=10 (§9); flags byte + stuffing.
        verbatim_stuffing = bytes(range(1, 183))  # non-0xFF, deterministic
        packet = TSPacket(
            pid=0x0100,
            continuity_counter=3,
            payload=None,
            adaptation_field=AdaptationField(
                discontinuity_indicator=True,
                stuffing=verbatim_stuffing,
            ),
        )
        raw = packet.to_bytes()
        assert raw[4] == 183
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.stuffing == verbatim_stuffing

        # §9 boundary combination: PCR + OPCR + splice + private + extension.
        af = AdaptationField(
            discontinuity_indicator=True,
            random_access_indicator=True,
            elementary_stream_priority_indicator=True,
            pcr=PCR(base=0x12345678 >> 1, extension=0x100),
            opcr=PCR(base=0x111111, extension=7),
            splice_countdown=-128,
            transport_private_data=bytes.fromhex("DEADBEEF"),
            extension_raw=bytes.fromhex("02ABCD"),
            stuffing=b"\x5a",
        )
        packet = TSPacket(
            pid=0x1BEE,
            continuity_counter=6,
            payload=bytes(160),
            adaptation_field=af,
        )
        raw = packet.to_bytes()
        # 1 flags + 6 PCR + 6 OPCR + 1 splice + 5 private + 3 ext + 1 stuff
        assert raw[4] == 23
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.pcr == PCR(
            base=0x12345678 >> 1, extension=0x100
        )
        assert parsed.adaptation_field.opcr == PCR(base=0x111111, extension=7)
        assert parsed.adaptation_field.splice_countdown == -128
        assert parsed.adaptation_field.transport_private_data == bytes.fromhex(
            "DEADBEEF"
        )
        assert parsed.adaptation_field.extension_raw == bytes.fromhex("02ABCD")
        # Strict parse success keeps the issue list empty (§8 info items
        # belong to the non-strict diagnostic surface only).
        assert parsed.parse_issues == ()

    def test_extension_opaque_bytes_survive_round_trip(self) -> None:
        """Unrecognized extension content is preserved bit-exact (§5.2/§7.5)."""
        from ts.adaptation_field import AdaptationField
        from ts.packet import TSPacket

        # Arbitrary private extension body (never interpreted by this
        # module); the leading byte is the extension length per H.222.0.
        extension = bytes([5]) + b"\x00\xff\x13\x37\x42"
        af = AdaptationField(
            extension_raw=extension,
            # 183 - 160 payload - 1 flags - 6 ext = 16 stuffing bytes.
            stuffing=b"\xff" * 16,
        )
        packet = TSPacket(
            pid=0x0666,
            continuity_counter=4,
            payload=bytes(160),
            adaptation_field=af,
        )
        raw = packet.to_bytes()
        assert raw[4] == 23
        # The extension bytes appear verbatim inside the packet.
        assert extension in raw
        parsed = TSPacket.from_bytes(raw)
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.extension_raw == extension
        assert parsed.to_bytes() == raw

    def test_extension_filling_whole_adaptation_field(self) -> None:
        """Extension consuming the entire 183-byte AF body (AFC=10 boundary)."""
        from ts.adaptation_field import AdaptationField
        from ts.packet import TSPacket

        extension = bytes([181]) + bytes(range(181))  # 182 bytes total
        af = AdaptationField(extension_raw=extension)
        packet = TSPacket(
            pid=0x0111,
            continuity_counter=0,
            payload=None,
            adaptation_field=af,
        )
        raw = packet.to_bytes()
        assert raw[4] == 183  # flags byte (0x01) + 182 extension bytes
        assert raw[5] == 0x01  # only the extension flag is set
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.extension_raw == extension
        assert parsed.adaptation_field.stuffing == b""

    def test_af_length_zero_marker_is_distinct_from_flags_zero(self) -> None:
        """Length-0 AF (no flags) and length-1 zero-flags AF stay distinct."""
        from ts.adaptation_field import AdaptationField, ZERO_LENGTH_ADAPTATION_FIELD
        from ts.packet import TSPacket

        zero = TSPacket(
            pid=0x0100,
            continuity_counter=1,
            payload=bytes(183),
            adaptation_field=ZERO_LENGTH_ADAPTATION_FIELD,
        )
        flags_zero = TSPacket(
            pid=0x0100,
            continuity_counter=1,
            payload=bytes(182),
            adaptation_field=AdaptationField(),
        )
        assert zero.to_bytes() != flags_zero.to_bytes()
        assert zero.to_bytes()[4] == 0
        assert flags_zero.to_bytes()[4] == 1
        assert TSPacket.from_bytes(zero.to_bytes()) == zero
        assert TSPacket.from_bytes(flags_zero.to_bytes()) == flags_zero
        assert ZERO_LENGTH_ADAPTATION_FIELD != AdaptationField()

    def test_non_0xff_stuffing_is_preserved_verbatim(self) -> None:
        """Stuffing bytes are round-tripped as-is (no silent 0xFF rewrite)."""
        from ts.adaptation_field import AdaptationField
        from ts.packet import TSPacket

        af = AdaptationField(
            random_access_indicator=True,
            stuffing=bytes(13),  # 0x00 * 13, non-conformant but preserved
        )
        packet = TSPacket(
            pid=0x0222,
            continuity_counter=5,
            payload=bytes(169),
            adaptation_field=af,
        )
        raw = packet.to_bytes()
        parsed = TSPacket.from_bytes(raw)
        assert parsed == packet
        assert parsed.adaptation_field is not None
        assert parsed.adaptation_field.stuffing == bytes(13)
        assert parsed.to_bytes() == raw


# ---------------------------------------------------------------------------
# REQ-TS-100-004 — length/offset boundary safety + #11 trailing bytes
# ---------------------------------------------------------------------------


class TestPacketMalformedBoundaries:
    """REQ-TS-100-004: 长度/偏移校验安全, 负向输入稳定报错 (§10)."""

    @staticmethod
    def _payload_only() -> bytes:
        from ts.packet import TSPacket

        return TSPacket(
            pid=0x0001, continuity_counter=0, payload=bytes(184)
        ).to_bytes()

    def test_packet_malformed_boundaries(self) -> None:
        """Wrong sizes, bad sync, AFC=00 and AF overflow all reject stably."""
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket

        payload_only = self._payload_only()

        # §7.1: length is validated before any header field is read.
        for bad_input in (
            b"",
            b"\x47",
            payload_only[:-1],
            payload_only + b"\x00",
            payload_only * 2,
        ):
            with pytest.raises(InvalidPacketError) as excinfo:
                TSPacket.from_bytes(bad_input)
            assert "TS_PACKET_SIZE_INVALID" in str(excinfo.value)

        # Ruling #11 trailing-bytes freeze: a valid 188-byte prefix with
        # trailing bytes is rejected, never silently consumed.
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(payload_only + b"\x47")
        assert "TS_PACKET_SIZE_INVALID" in str(excinfo.value)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(payload_only * 2)  # two concatenated packets
        assert "TS_PACKET_SIZE_INVALID" in str(excinfo.value)

        # Sync byte at the first position: strict raises, lenient records.
        bad_sync = b"\x00" + payload_only[1:]
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(bad_sync)
        assert "TS_SYNC_BYTE_INVALID" in str(excinfo.value)
        lenient = TSPacket.from_bytes(bad_sync, strict=False)
        assert [issue.code for issue in lenient.parse_issues] == [
            "TS_SYNC_BYTE_INVALID"
        ]
        assert lenient.parse_issues[0].offset == 0
        assert lenient.pid == 0x0001  # the rest still parsed

        # AFC=00 is reserved and unconstructible in both modes (§4/§8).
        afc00 = bytes((0x47, 0x00, 0x00, 0b00_00_0000)) + bytes(184)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(afc00)
        assert "TS_AFC_RESERVED" in str(excinfo.value)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(afc00, strict=False)
        assert "TS_AFC_RESERVED" in str(excinfo.value)

        # AF length beyond the packet boundary (§7.3).
        af_overflow = bytes((0x47, 0x40, 0x00, 0b00_11_0000, 0xFF)) + bytes(183)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(af_overflow)
        assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

        # AFC=10 requires adaptation_field_length == 183 (§5.2).
        af_short = bytes((0x47, 0x00, 0x00, 0b00_10_0000, 100)) + bytes(183)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(af_short)
        assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

        # AFC=11 must leave at least one payload byte (§5.2).
        af_eats_payload = bytes((0x47, 0x00, 0x00, 0b00_11_0000, 183)) + bytes(183)
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket.from_bytes(af_eats_payload)
        assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

    def test_truncated_optional_af_fields_rejected(self) -> None:
        """§7.4: optional fields are bounds-checked before consumption."""
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket

        def af_packet(flags: int, af_length: int, body: bytes) -> bytes:
            header = bytes((0x47, 0x00, 0x00, 0b00_11_0000, af_length))
            return header + body + bytes(188 - len(header) - len(body))

        # A syntactically valid PCR field (reserved bits 111111) for cases
        # that must reach past a complete PCR before truncating (SPEC-105
        # would otherwise reject zero-filled PCR bytes first).
        valid_pcr = bytes.fromhex("000000007E00")  # PCR(base=0, ext=0)
        cases = [
            # PCR declared but only 3 of 6 bytes present.
            (0x10, 4, bytes([0x10]) + bytes(3)),
            # OPCR declared, nothing after the flags byte.
            (0x08, 1, bytes([0x08])),
            # PCR complete, OPCR truncated.
            (0x18, 10, bytes([0x18]) + valid_pcr + bytes(3)),
            # Splice countdown declared but missing.
            (0x04, 1, bytes([0x04])),
            # transport_private_data_length declares 10, only 3 present.
            (0x02, 5, bytes([0x02, 10]) + bytes(3)),
            # adaptation_field_extension_length declares 8, only 2 present.
            (0x01, 4, bytes([0x01, 8]) + bytes(2)),
        ]
        for flags, af_length, body in cases:
            raw = af_packet(flags, af_length, body)
            assert len(raw) == 188
            with pytest.raises(InvalidPacketError) as excinfo:
                TSPacket.from_bytes(raw)
            assert "TS_AF_FIELD_TRUNCATED" in str(excinfo.value)
            # The lenient surface still refuses structurally truncated
            # fields: §4 forbids non-serializable packet objects.
            with pytest.raises(InvalidPacketError) as excinfo:
                TSPacket.from_bytes(raw, strict=False)
            assert "TS_AF_FIELD_TRUNCATED" in str(excinfo.value)

    def test_construction_rejects_unserializable_frame_shapes(self) -> None:
        """§8 构造/序列化拒绝: bad payload sizes never become objects."""
        from ts.adaptation_field import AdaptationField
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket
        from ts.pcr import PCR

        # Payload-only needs exactly 184 bytes.
        for bad_payload in (b"", bytes(1), bytes(183), bytes(185), bytes(188)):
            with pytest.raises(InvalidPacketError) as excinfo:
                TSPacket(pid=0, continuity_counter=0, payload=bad_payload)
            assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

        # Adaptation+payload needs 1..183 payload bytes.
        with pytest.raises(InvalidPacketError):
            TSPacket(
                pid=0,
                continuity_counter=0,
                payload=b"",
                adaptation_field=AdaptationField(),
            )
        with pytest.raises(InvalidPacketError):
            TSPacket(
                pid=0,
                continuity_counter=0,
                payload=bytes(184),
                adaptation_field=AdaptationField(),
            )

        # AF content that can never fit the payload room is rejected at
        # construction (§4: every object stays serializable).
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket(
                pid=0,
                continuity_counter=0,
                payload=bytes(180),
                # 1 flags + 6 PCR = 8 body bytes > 183 - 180.
                adaptation_field=AdaptationField(pcr=PCR(base=1, extension=0)),
            )
        assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

        # Adaptation-only AF content beyond 183 bytes.
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket(
                pid=0,
                continuity_counter=0,
                payload=None,
                adaptation_field=AdaptationField(
                    transport_private_data=bytes(255),
                    extension_raw=bytes([255]) + bytes(255),
                ),
            )
        assert "TS_AF_LENGTH_INVALID" in str(excinfo.value)

        # Neither payload nor AF: AFC=00 (§4).
        with pytest.raises(InvalidPacketError) as excinfo:
            TSPacket(pid=0, continuity_counter=0, payload=None)
        assert "TS_AFC_RESERVED" in str(excinfo.value)

    def test_non_strict_reports_issues_without_silent_fix(self) -> None:
        """strict=False exposes findings; nothing is repaired quietly."""
        from ts.errors import InvalidPacketError
        from ts.packet import TSPacket

        payload_only = self._payload_only()
        bad_sync = b"\x12" + payload_only[1:]
        lenient = TSPacket.from_bytes(bad_sync, strict=False)
        # The packet is explicitly marked, not silently "valid".
        assert len(lenient.parse_issues) == 1
        issue = lenient.parse_issues[0]
        assert issue.code == "TS_SYNC_BYTE_INVALID"
        assert issue.severity == "error"
        # Re-serialization uses the canonical sync byte and stays 188 bytes;
        # the deviation was reported via parse_issues, not hidden.
        assert len(lenient.to_bytes()) == 188
        assert lenient.to_bytes()[0] == 0x47
        # strict=True on the same bytes still raises.
        with pytest.raises(InvalidPacketError):
            TSPacket.from_bytes(bad_sync)

    def test_splice_and_private_field_range_guards(self) -> None:
        """Construction guards: signed splice range, 8-bit length fields."""
        from ts.adaptation_field import AdaptationField
        from ts.errors import InvalidPacketError

        with pytest.raises(InvalidPacketError):
            AdaptationField(splice_countdown=128)
        with pytest.raises(InvalidPacketError):
            AdaptationField(splice_countdown=-129)
        # Boundary values are legal.
        for boundary in (-128, -1, 0, 127):
            AdaptationField(splice_countdown=boundary)
        with pytest.raises(InvalidPacketError):
            AdaptationField(transport_private_data=bytes(256))
        # Opaque extension must carry its own leading length byte.
        with pytest.raises(InvalidPacketError):
            AdaptationField(extension_raw=bytes(10))
        with pytest.raises(InvalidPacketError):
            AdaptationField(extension_raw=bytes([7]) + bytes(9))


# ---------------------------------------------------------------------------
# REQ-TS-100-005 — CCAllocator: PID-independent state, payload rule, wrap
# ---------------------------------------------------------------------------


class TestCcAllocator:
    """REQ-TS-100-005: CCAllocator PID 独立状态/回绕/规则 (§5.4, §6)."""

    def test_cc_allocator(self) -> None:
        """§5.4 mandated sequences + §9 checklist in one spec trace."""
        from ts.cc import CCAllocator

        allocator = CCAllocator()  # default initial_cc = 0

        # §5.4 example: payload -> adaptation-only -> payload = 0, 0, 1.
        assert allocator.allocate(100, has_payload=True) == 0
        assert allocator.allocate(100, has_payload=False) == 0
        assert allocator.allocate(100, has_payload=True) == 1

        # Fresh allocator: two consecutive payload packets -> 0, 1.
        allocator = CCAllocator()
        assert allocator.allocate(100, has_payload=True) == 0
        assert allocator.allocate(100, has_payload=True) == 1

        # §5.4 example: first packet adaptation-only -> first payload = 0, 0.
        allocator = CCAllocator()
        assert allocator.allocate(100, has_payload=False) == 0
        assert allocator.allocate(100, has_payload=True) == 0

        # Adaptation-only never advances the counter.
        allocator = CCAllocator()
        assert allocator.allocate(100, has_payload=True) == 0
        for _ in range(5):
            assert allocator.allocate(100, has_payload=False) == 0
        assert allocator.allocate(100, has_payload=True) == 1

        # Different PIDs keep independent state.
        allocator = CCAllocator()
        assert allocator.allocate(2000, has_payload=True) == 0
        assert allocator.allocate(2001, has_payload=True) == 0
        assert allocator.allocate(2000, has_payload=True) == 1
        assert allocator.allocate(2001, has_payload=False) == 0
        assert allocator.allocate(2000, has_payload=False) == 1

        # Modulo-16 wrap: 16 payload allocations cycle 0..15 -> 0.
        allocator = CCAllocator()
        sequence = [
            allocator.allocate(100, has_payload=True) for _ in range(17)
        ]
        assert sequence == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 0]

        # reset(pid, next_value) clears history and sets a new generation.
        allocator = CCAllocator()
        assert allocator.allocate(100, has_payload=True) == 0
        assert allocator.allocate(100, has_payload=True) == 1
        allocator.reset(100, 7)
        # §6 pseudocode: fresh generation -> adapt-only takes the new
        # initial; the next payload also uses initial (no payload emitted
        # yet in this generation), mirroring §5.4 "0, 0" pattern.
        assert allocator.allocate(100, has_payload=False) == 7
        assert allocator.allocate(100, has_payload=True) == 7
        # reset only affects the given PID.
        assert allocator.allocate(101, has_payload=True) == 0
        allocator.reset(101, 15)
        assert allocator.allocate(101, has_payload=True) == 15  # 15 wraps next
        assert allocator.allocate(101, has_payload=True) == 0

        # clear() forgets every PID; the allocator initial applies again.
        allocator = CCAllocator(initial_cc=5)
        assert allocator.allocate(100, has_payload=True) == 5
        assert allocator.allocate(100, has_payload=True) == 6
        assert allocator.allocate(200, has_payload=True) == 5
        allocator.clear()
        assert allocator.allocate(100, has_payload=True) == 5
        assert allocator.allocate(100, has_payload=False) == 5

    def test_cc_allocator_initial_cc_configuration(self) -> None:
        """initial_cc seeds the first packet of every fresh PID."""
        from ts.cc import CCAllocator

        allocator = CCAllocator(initial_cc=13)
        assert allocator.allocate(100, has_payload=False) == 13
        assert allocator.allocate(100, has_payload=True) == 13
        assert allocator.allocate(200, has_payload=True) == 13
        assert allocator.allocate(200, has_payload=True) == 14

    def test_cc_allocator_rejects_out_of_range_inputs(self) -> None:
        """PID must be 13-bit, CC values 4-bit (§8, module error codes)."""
        from ts.cc import CCAllocator
        from ts.errors import InvalidPacketError

        allocator = CCAllocator()
        for bad_pid in (-1, 0x2000, 0x1FFFF):
            with pytest.raises(InvalidPacketError) as excinfo:
                allocator.allocate(bad_pid, has_payload=True)
            assert "TS_PID_OUT_OF_RANGE" in str(excinfo.value)
            with pytest.raises(InvalidPacketError) as excinfo:
                allocator.reset(bad_pid, 0)
            assert "TS_PID_OUT_OF_RANGE" in str(excinfo.value)

        for bad_cc in (-1, 16, 256):
            with pytest.raises(InvalidPacketError) as excinfo:
                allocator.reset(100, bad_cc)
            assert "TS_CC_OUT_OF_RANGE" in str(excinfo.value)
        with pytest.raises(InvalidPacketError) as excinfo:
            CCAllocator(initial_cc=16)
        assert "TS_CC_OUT_OF_RANGE" in str(excinfo.value)
        CCAllocator(initial_cc=15)  # boundary is legal

    def test_cc_allocator_has_payload_is_keyword_only(self) -> None:
        """The §6 signature makes has_payload keyword-only."""
        from ts.cc import CCAllocator

        allocator = CCAllocator()
        with pytest.raises(TypeError):
            allocator.allocate(100, True)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# REQ-TS-100-006 — fuzz/property stability (deterministic seeds)
# ---------------------------------------------------------------------------


class TestPacketFuzzSafety:
    """REQ-TS-100-006: fuzz/property 稳定 — Packet 或稳定 ParseError (§9)."""

    @staticmethod
    def _generate_inputs(rng: "random.Random") -> list[bytes]:
        """Deterministic 188-byte corpus: random, sync-forced, mutated."""
        from ts.adaptation_field import AdaptationField, ZERO_LENGTH_ADAPTATION_FIELD
        from ts.packet import TSPacket
        from ts.pcr import PCR

        inputs: list[bytes] = []
        # (a) Fully random bytes.
        for _ in range(100):
            inputs.append(bytes(rng.randrange(256) for _ in range(188)))
        # (b) Sync byte forced to 0x47, rest random (header paths dominate).
        for _ in range(100):
            body = bytes(rng.randrange(256) for _ in range(187))
            inputs.append(b"\x47" + body)
        # (c) Valid packets of every AFC shape, then 1-4 random mutations.
        shapes = [
            TSPacket(pid=0x0100, continuity_counter=4, payload=bytes(range(184))),
            TSPacket(
                pid=0x0100,
                continuity_counter=5,
                payload=None,
                adaptation_field=AdaptationField(
                    discontinuity_indicator=True,
                    pcr=PCR(base=12345, extension=67),
                    # 183 - 1 flags - 6 PCR = 176 stuffing.
                    stuffing=b"\xff" * 176,  # testdata-ok: frame-fill sizing
                ),
            ),
            TSPacket(
                pid=0x0100,
                continuity_counter=6,
                # 1 flags + 6 PCR + 1 splice + 3 private + 3 ext = 14 body
                # bytes -> payload must be 183 - 14 = 169 at most.
                payload=bytes(range(169)),
                adaptation_field=AdaptationField(
                    random_access_indicator=True,
                    pcr=PCR(base=1, extension=0),
                    splice_countdown=3,
                    transport_private_data=bytes.fromhex("0102"),
                    extension_raw=bytes.fromhex("020304"),
                ),
            ),
            TSPacket(
                pid=0x0100,
                continuity_counter=7,
                payload=bytes(183),
                adaptation_field=ZERO_LENGTH_ADAPTATION_FIELD,
            ),
        ]
        for shape in shapes:
            raw = bytearray(shape.to_bytes())
            for _ in range(50):
                mutated = bytearray(raw)
                for _ in range(rng.randrange(1, 5)):
                    mutated[rng.randrange(188)] = rng.randrange(256)
                inputs.append(bytes(mutated))
        return inputs

    def test_packet_fuzz_safety(self) -> None:
        """Any 188-byte input yields a Packet or a stable typed error (§9)."""
        import random

        from ts.errors import InvalidPacketError, TSCoreError
        from ts.packet import TS_PACKET_SIZE, TSPacket

        rng = random.Random(0x5F100)  # fixed seed, reproducible failures
        for data in self._generate_inputs(rng):
            assert len(data) == TS_PACKET_SIZE
            # strict surface: TSPacket or a stable parse error — never an
            # IndexError/ValueError/TypeError crash family.
            try:
                packet = TSPacket.from_bytes(data)
            except (InvalidPacketError, TSCoreError):
                continue  # stable typed rejection is allowed
            # Lossless property: a strict-parsed packet round-trips to the
            # exact input bytes (stuffing/extension preserved verbatim).
            assert packet.to_bytes() == data
            # Lenient surface: parses at least as much as strict did, or
            # rejects with the same stable typed error family (it never
            # crashes on bytes strict accepted).
            try:
                lenient = TSPacket.from_bytes(data, strict=False)
            except TSCoreError:
                pytest.fail("strict=False rejected bytes strict accepted")
            assert len(lenient.to_bytes()) == TS_PACKET_SIZE

    def test_fuzz_lenient_never_crashes(self) -> None:
        """strict=False on arbitrary bytes: Packet or typed error, no crash."""
        import random

        from ts.errors import TSCoreError
        from ts.packet import TS_PACKET_SIZE, TSPacket

        rng = random.Random(0x5F101)  # different fixed seed
        parsed_count = 0
        for _ in range(300):
            data = bytes(rng.randrange(256) for _ in range(188))
            try:
                packet = TSPacket.from_bytes(data, strict=False)
            except TSCoreError:
                continue
            parsed_count += 1
            assert len(packet.to_bytes()) == TS_PACKET_SIZE
            # Lenient parse results always re-serialize to 188 bytes.
        assert parsed_count > 0  # sanity: the corpus does parse sometimes
