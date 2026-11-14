"""SPEC-102 — PSI Section framing/assembly — unit tests (ticket #29).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-102 section):

- REQ-TS-102-001  Section Header/length 正确                  -> test_section_header_and_length
- REQ-TS-102-002  Long-form 公共字段 round-trip               -> test_long_section_round_trip
- REQ-TS-102-003  CRC policy 正确                             -> test_section_crc_policy
- REQ-TS-102-004  PUSI/pointer/跨包/多 Section 组装正确        -> test_section_assembler
- REQ-TS-102-005  discontinuity/EOF partial 显式处理          -> test_section_assembler_recovery
- REQ-TS-102-006  畸形长度安全                                -> test_section_malformed_lengths

Expected values are hand-assembled byte literals: the 3-byte headers are
packed bit-by-bit from SPEC-102 §3 (ITU-T H.222.0 PSI section syntax), and
the two CRC fields below were computed once with the SPEC-101-verified
primitive (ticket #26 proves ``mpeg2_crc32`` against the ``b"123456789"``
check vector 0x0376E6E7) and frozen as literals here — the tests never
recompute expectations through the code under test. Ruling #11 freezes:
``SECTION_HEADER_TRUNCATED`` as the unified truncated-header code, strict
``parse_section`` rejection of trailing bytes (``SECTION_TRAILING_BYTES``),
and no default policy for unknown table_ids (``SECTION_TABLE_ID_UNEXPECTED``).
Property loops use a fixed seed so failures stay reproducible
(tests/README.md §6).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Hand-assembled section fixtures (literals, see module docstring)
# ---------------------------------------------------------------------------

# Long-form PAT-like section, table_id=0x00:
#   byte0 table_id = 0x00
#   byte1 = SSI<<7 | private<<6 | reserved(0b11)<<4 | len>>8 = 0b10_11_0000
#   byte2 = section_length = 13 (5 public + 4 loop + 4 CRC)
#   ext=0x0001, version byte 0xCB = 0b11_00101_1 (reserved=11, version=5,
#   current_next=1), section_number=0, last_section_number=0,
#   4-byte loop payload, CRC f0 4d ac 64.
SECTION_A = bytes(  # testdata-ok: expected PSI wire literal, hand-packed per SPEC-102 section 3 bit table; the framing parser under test needs exact bytes as the independent source of truth (CRC cross-checked against the SPEC-101 check-vector-verified primitive)
    (0x00, 0xB0, 0x0D, 0x00, 0x01, 0xCB, 0x00, 0x00, 0x12, 0x34,
     0xE0, 0x10, 0xF0, 0x4D, 0xAC, 0x64)
)
SECTION_A_CRC = 0xF04DAC64

# Short-form section with no room for a CRC field (length=2): used to
# reach SECTION_CRC_MISSING under a REQUIRED policy (strict long-form
# wlen<5 hits SECTION_LONG_HEADER_TRUNCATED first per §6.1 order).
SECTION_E_SHORT_REQUIRED = bytes((0x80, 0b00_11_0000, 0x02, 0xAA, 0xBB))

# Short-form private section, table_id=0x42: byte1 = SSI=0 | private=1 |
# reserved=0b11 | len>>8, length=3, body 01 02 03, no CRC field.
SECTION_B = bytes((0x42, 0b01_11_0000 | 0x00, 0x03, 0x01, 0x02, 0x03))

# Long-form section WITHOUT a CRC field, table_id=0x03:
# byte1 = 0xB0 (SSI=1, private=0, reserved=11), length=9
# (5 public + 4 body), ext=0xABCD, version byte 0xC1 = 0b11_00000_1
# (reserved=11, version=0, current_next=1), sec=0x02, last=0x01.
SECTION_C = bytes(
    (0x03, 0xB0, 0x09, 0xAB, 0xCD, 0xC1, 0x02, 0x01, 0xDE, 0xAD, 0xBE, 0xEF)
)

# Long-form section with valid CRC, table_id=0x02, length=19
# (5 public + 10 loop + 4 CRC), 22 bytes total:
# ext=0xCAFE, version byte 0xD5 = 0b11_01010_1 (version=10, current_next=1),
# section_number=0, last_section_number=3, CRC 1d 8e fe 64.
SECTION_D = bytes(  # testdata-ok: expected PSI wire literal for cross-packet assembly fixture, hand-packed per SPEC-102 section 3 (see module docstring)
    (0x02, 0xB0, 0x13, 0xCA, 0xFE, 0xD5, 0x00, 0x03, 0x40, 0x41, 0x42, 0x43,
     0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x1D, 0x8E, 0xFE, 0x64)
)
SECTION_D_CRC = 0x1D8EFE64
# SECTION_D with one body byte corrupted (CRC field preserved verbatim).
SECTION_D_BAD = bytes(  # testdata-ok: SECTION_D with one body byte deliberately corrupted for SECTION_CRC_INVALID; single-bit hand edit, documented
    (0x02, 0xB0, 0x13, 0xCA, 0xFE, 0xD5, 0x00, 0x03, 0x40, 0x41, 0xBD, 0x43,
     0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x1D, 0x8E, 0xFE, 0x64)
)

# ---------------------------------------------------------------------------
# Primary test REQ-TS-102-001
# ---------------------------------------------------------------------------


class TestSectionHeaderAndLength:
    """REQ-TS-102-001: Section Header 和长度解释正确 (SPEC-102 §3/§6.1)."""

    def test_section_header_and_length(self) -> None:
        """Header bit fields, section_length and total size decode exactly."""
        from ts.section import CrcPolicy, PSISection, SectionPolicy, parse_section, section_total_size

        pat_policy = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        section = parse_section(SECTION_A, pat_policy)
        assert isinstance(section, PSISection)
        assert section.table_id == 0x00
        assert section.section_syntax_indicator is True
        assert section.private_indicator is False
        assert section.section_length == 13  # 3-byte header excluded (§3)
        assert section.raw_bytes == SECTION_A

        short_policy = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )
        short = parse_section(SECTION_B, short_policy)
        assert short.table_id == 0x42
        assert short.section_syntax_indicator is False
        assert short.private_indicator is True
        assert short.section_length == 3
        assert short.raw_bytes == SECTION_B
        # Short form has no long-form public fields (§4 defaults).
        assert short.table_id_extension is None
        assert short.version_number is None
        assert short.current_next_indicator is None
        assert short.section_number is None
        assert short.last_section_number is None
        assert short.crc_value is None

        # section_total_size = 3 + wire section_length (§5/§7).
        assert section_total_size(SECTION_A[:3], max_section_length=1021) == 16
        assert section_total_size(SECTION_B[:3], max_section_length=256) == 6
        # section_length = 0 is a legal minimal section (total = 3 only).
        assert section_total_size(bytes((0x42, 0x70, 0x00)), max_section_length=256) == 3

        # Fewer than 3 bytes: SECTION_HEADER_TRUNCATED (§6.1 step 1).
        from ts.errors import InvalidSectionError
        for bad in (b"", b"\x42", b"\x42\x70"):
            with pytest.raises(InvalidSectionError) as excinfo:
                parse_section(bad, short_policy)
            assert "SECTION_HEADER_TRUNCATED" in str(excinfo.value)
        with pytest.raises(InvalidSectionError) as excinfo:
            section_total_size(b"\x42\x70", max_section_length=256)
        assert "SECTION_HEADER_TRUNCATED" in str(excinfo.value)

        # Wire-expressible 4095 exceeds the table profile maximum (§3):
        # the 12-bit field range is not a legal-length licence.
        wire_max_header = bytes((0x42, 0b01_11_1111, 0xFF))  # length = 0xFFF
        with pytest.raises(InvalidSectionError) as excinfo:
            section_total_size(wire_max_header, max_section_length=256)
        assert "SECTION_LENGTH_EXCEEDS_POLICY" in str(excinfo.value)
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(wire_max_header + bytes(4095), short_policy)
        assert "SECTION_LENGTH_EXCEEDS_POLICY" in str(excinfo.value)

    def test_trailing_bytes_strict_reject_lenient_slice(self) -> None:
        """Ruling #11: parse_section rejects extra bytes strictly; the
        lenient surface records SECTION_TRAILING_BYTES and slices exactly
        3 + section_length (multi-section slicing belongs to the assembler)."""
        from ts.errors import InvalidSectionError
        from ts.section import CrcPolicy, SectionPolicy, parse_section

        pat_policy = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(SECTION_A + b"\x00", pat_policy)
        assert "SECTION_TRAILING_BYTES" in str(excinfo.value)
        # Two concatenated sections are also "trailing bytes" for the
        # single-section parser — the assembler slices with
        # section_total_size() instead. Policy without expected_table_id
        # so the trailing-bytes check is reached (§6.1 order).
        tid_neutral = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(SECTION_B + SECTION_B, tid_neutral)
        assert "SECTION_TRAILING_BYTES" in str(excinfo.value)

        lenient = parse_section(SECTION_A + b"\x00", pat_policy, strict=False)
        assert lenient.raw_bytes == SECTION_A
        assert lenient.section_length == 13
        assert [issue.code for issue in lenient.parse_issues] == [
            "SECTION_TRAILING_BYTES"
        ]
        assert lenient.parse_issues[0].offset == 16  # first extra byte index

    def test_length_boundaries_round_trip(self) -> None:
        """section_length 0, profile maximum and their serialization."""
        from ts.section import CrcPolicy, SectionPolicy, parse_section, serialize_section

        absent_policy = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )
        empty = parse_section(bytes((0x42, 0x70, 0x00)), absent_policy)
        assert empty.section_length == 0
        assert empty.raw_bytes == bytes((0x42, 0x70, 0x00))
        assert serialize_section(empty, absent_policy) == bytes((0x42, 0x70, 0x00))

        # Section whose length sits exactly at the profile maximum.
        at_max = bytes((0x42, 0b01_11_0000 | 0x01, 0x00)) + bytes(256)
        assert len(at_max) == 259  # 3 + 256
        at_max_section = parse_section(at_max, absent_policy)
        assert at_max_section.section_length == 256
        assert serialize_section(at_max_section, absent_policy) == at_max


# ---------------------------------------------------------------------------
# Primary test REQ-TS-102-002
# ---------------------------------------------------------------------------


class TestLongSectionRoundTrip:
    """REQ-TS-102-002: Long-form 公共字段正确解析/序列化 (SPEC-102 §3/§4)."""

    def test_long_section_round_trip(self) -> None:
        """Long-form public header fields decode and serialize byte-exact."""
        from ts.section import CrcPolicy, SectionPolicy, parse_section, serialize_section

        pat_policy = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        section = parse_section(SECTION_A, pat_policy)
        assert section.table_id_extension == 0x0001
        assert section.version_number == 5  # 0x6B: reserved=11, ver=5, cn=1
        assert section.current_next_indicator is True
        assert section.section_number == 0
        assert section.last_section_number == 0
        assert section.crc_value == SECTION_A_CRC

        # Serialize echoes the immutable raw section byte-exact (§4).
        assert serialize_section(section, pat_policy) == SECTION_A

        # Second long-form fixture with non-zero section/last numbers and a
        # larger extension: byte5 0xD5 = 0b11_01010_1 -> version 10, cn=1.
        tid2_policy = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        )
        section_d = parse_section(SECTION_D, tid2_policy)
        assert section_d.table_id_extension == 0xCAFE
        assert section_d.version_number == 10
        assert section_d.current_next_indicator is True
        assert section_d.section_number == 0
        assert section_d.last_section_number == 3
        assert section_d.crc_value == SECTION_D_CRC
        assert serialize_section(section_d, tid2_policy) == SECTION_D

        # current_next_indicator=0 and version boundary 31 decode too:
        # version byte 0xFE = 0b11_11111_0.
        ver31 = bytes(
            (0x03, 0xB0, 0x09, 0xAB, 0xCD, 0xFE, 0x00, 0x00,
             0xDE, 0xAD, 0xBE, 0xEF)
        )
        absent_long_policy = SectionPolicy(
            max_section_length=64, crc_policy=CrcPolicy.ABSENT
        )
        parsed = parse_section(ver31, absent_long_policy)
        assert parsed.version_number == 31
        assert parsed.current_next_indicator is False

    def test_long_header_truncated_explicit(self) -> None:
        """A long-form section shorter than its 5 public-header bytes is
        rejected with SECTION_LONG_HEADER_TRUNCATED (§6.1 step 5); the
        lenient surface keeps the None fields and records the issue."""
        from ts.errors import InvalidSectionError
        from ts.section import CrcPolicy, SectionPolicy, parse_section

        # length=2: only the first two public-header bytes are present.
        truncated = bytes((0x00, 0xB0, 0x02, 0x00, 0x01))
        pat_policy = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(truncated, pat_policy)
        assert "SECTION_LONG_HEADER_TRUNCATED" in str(excinfo.value)

        lenient = parse_section(truncated, pat_policy, strict=False)
        assert lenient.table_id_extension is None
        assert lenient.version_number is None
        assert lenient.current_next_indicator is None
        assert lenient.section_number is None
        assert lenient.last_section_number is None
        # Both recoverable findings accumulate (§6.1 order: long-header
        # completeness is checked before the REQUIRED-policy CRC gate).
        assert [issue.code for issue in lenient.parse_issues] == [
            "SECTION_LONG_HEADER_TRUNCATED",
            "SECTION_CRC_MISSING",
        ]
        assert lenient.parse_issues[0].offset == 3

    def test_reserved_bits_preserved_and_reported(self) -> None:
        """Reserved bits are kept verbatim and reported by validate(); strict
        parsing still accepts them (§6.1 step 7, no §8 error code exists)."""
        from ts.section import CrcPolicy, SectionPolicy, parse_section

        # Header reserved bits = 0b10 (byte1 bit5=0): section still parses.
        bad_reserved = bytes((0x42, 0b01_10_0000 | 0x00, 0x03, 0x01, 0x02, 0x03))
        short_policy = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )
        section = parse_section(bad_reserved, short_policy)
        assert section.raw_bytes == bad_reserved  # preserved verbatim

        issues = section.validate()
        assert [issue.code for issue in issues] == ["SECTION_RESERVED_BITS"]
        assert issues[0].severity == "warning"

        # Canonical section validates clean.
        clean = parse_section(SECTION_B, short_policy)
        assert clean.validate() == []

    def test_short_form_rejected_when_long_required(self) -> None:
        """require_long_syntax=True policy rejects SSI=0 sections as a
        profile mismatch (SECTION_TABLE_ID_UNEXPECTED family, §4/§6.1)."""
        from ts.errors import InvalidSectionError
        from ts.section import CrcPolicy, SectionPolicy, parse_section

        long_required = SectionPolicy(
            max_section_length=256,
            crc_policy=CrcPolicy.ABSENT,
            require_long_syntax=True,
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(SECTION_B, long_required)
        assert "SECTION_TABLE_ID_UNEXPECTED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Primary test REQ-TS-102-003
# ---------------------------------------------------------------------------


class TestSectionCrcPolicy:
    """REQ-TS-102-003: CRC policy 与 SPEC-101 集成正确 (SPEC-102 §7)."""

    def test_section_crc_policy(self) -> None:
        """REQUIRED/ABSENT/OPTIONAL behave distinctly and integrate the
        SPEC-101 CRC-32/MPEG-2 (remainder over the whole section = 0)."""
        from ts.section import CrcPolicy, SectionPolicy, parse_section

        required = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        good = parse_section(SECTION_A, required)
        assert good.crc_value == SECTION_A_CRC

        # CRC field absent but required: distinguishable from invalid (§7).
        # Short form (no long-header precedence) with length=2 leaves no
        # room for the 4-byte CRC field.
        crc_required_short = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        )
        with pytest.raises(Exception) as excinfo:
            parse_section(SECTION_E_SHORT_REQUIRED, crc_required_short)
        assert "SECTION_CRC_MISSING" in str(excinfo.value)
        lenient_missing = parse_section(
            SECTION_E_SHORT_REQUIRED, crc_required_short, strict=False
        )
        assert lenient_missing.crc_value is None
        assert [issue.code for issue in lenient_missing.parse_issues] == [
            "SECTION_CRC_MISSING"
        ]

        # CRC field present but wrong: SECTION_CRC_INVALID (§7/§8).
        tid2_required = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        )
        with pytest.raises(Exception) as excinfo:
            parse_section(SECTION_D_BAD, tid2_required)
        assert "SECTION_CRC_INVALID" in str(excinfo.value)
        lenient_bad = parse_section(SECTION_D_BAD, tid2_required, strict=False)
        assert lenient_bad.crc_value == SECTION_D_CRC  # wire value preserved
        assert [issue.code for issue in lenient_bad.parse_issues] == [
            "SECTION_CRC_INVALID"
        ]

        # ABSENT policy: no CRC interpretation at all — a section carrying
        # 4 bytes that would verify as CRC still parses with crc_value None.
        absent = SectionPolicy(
            max_section_length=64, crc_policy=CrcPolicy.ABSENT
        )
        as_absent = parse_section(SECTION_A, absent)
        assert as_absent.crc_value is None

        # OPTIONAL policy: detect a valid CRC field, tolerate its absence
        # (§6.1 step 6: OPTIONAL is decided explicitly, never an error).
        optional = SectionPolicy(
            max_section_length=1021, crc_policy=CrcPolicy.OPTIONAL
        )
        assert parse_section(SECTION_A, optional).crc_value == SECTION_A_CRC
        no_crc = parse_section(SECTION_C, optional)
        assert no_crc.crc_value is None
        # An OPTIONAL section whose tail fails verification is treated as
        # having no CRC field (deterministic detection rule, §4 docstring).
        bad_tail = parse_section(SECTION_D_BAD, optional)
        assert bad_tail.crc_value is None

    def test_serialize_crc_gates(self) -> None:
        """serialize_section re-verifies CRC per policy and never rewrites
        the field (no implicit fixes)."""
        from ts.errors import InvalidSectionError
        from ts.section import (
            CrcPolicy,
            PSISection,
            SectionPolicy,
            parse_section,
            serialize_section,
        )

        required = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        good = parse_section(SECTION_A, required)
        assert serialize_section(good, required) == SECTION_A

        tid2_required = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        )
        # A CRC-invalid raw section cannot be re-serialized under REQUIRED.
        # Build it through the lenient parse surface (strict would refuse).
        lenient_bad = parse_section(SECTION_D_BAD, tid2_required, strict=False)
        with pytest.raises(InvalidSectionError) as excinfo:
            serialize_section(lenient_bad, tid2_required)
        assert "SECTION_CRC_INVALID" in str(excinfo.value)

        # REQUIRED with no room for a CRC field: SECTION_CRC_MISSING.
        no_room = PSISection(
            table_id=0x80,
            section_syntax_indicator=False,
            private_indicator=False,
            section_length=2,
            raw_bytes=SECTION_E_SHORT_REQUIRED,
        )
        crc_required_short = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            serialize_section(no_room, crc_required_short)
        assert "SECTION_CRC_MISSING" in str(excinfo.value)

        # ABSENT policy echoes raw bytes verbatim.
        absent = SectionPolicy(max_section_length=64, crc_policy=CrcPolicy.ABSENT)
        short_section = parse_section(SECTION_B, absent)
        assert serialize_section(short_section, absent) == SECTION_B

    def test_crc_value_construction_guards(self) -> None:
        """A crc_value that contradicts raw_bytes cannot be constructed."""
        from ts.section import PSISection

        # crc_value set but the wire length has no room for a CRC field.
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x00,
                section_syntax_indicator=True,
                private_indicator=False,
                section_length=2,
                raw_bytes=bytes((0x00, 0xB0, 0x02, 0x00, 0x01)),
                crc_value=0x11223344,
            )
        # crc_value disagreeing with the wire CRC field.
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x02,
                section_syntax_indicator=True,
                private_indicator=False,
                section_length=19,
                raw_bytes=SECTION_D,
                crc_value=0xDEADBEEF,
            )


# ---------------------------------------------------------------------------
# Assembler fixtures (SPEC-102 §6.2; upstream-frozen TSPacket/AdaptationField)
# ---------------------------------------------------------------------------

# Cross-packet fixture layout (SPEC-102 §12 deliverable, packet index map):
#
#   SECTION_D is a 22-byte long-form section (3 header + 5 public + 10 loop
#   + 4 CRC). In the cross-packet tests it is split at body byte 12:
#
#     packet index N   (PUSI=1): payload = pointer_field(0x00) + SECTION_D[0:12]
#                      -> pointer announces the section start; the packet
#                         carries the 3-byte header, the 5 public-header bytes
#                         and the first 4 loop bytes; 10 of 22 bytes remain.
#     packet index N+1 (PUSI=0): payload = SECTION_D[12:22]
#                      -> continuation completes the section; the boundary
#                         case SECTION_D[12:] fits one payload exactly.
#
#   The pointer-completion variant (packet index N+1 as PUSI=1) carries
#   pointer_field 0x0A: the 10-byte prefix finishes SECTION_D, then
#   SECTION_A starts at payload offset 11 in the same packet.

# Table profiles for the assembler resolver: PAT-like tid 0x00 (long-form,
# REQUIRED CRC) and tid 0x02 (long-form, REQUIRED CRC). Unknown table_ids
# resolve to None -> SECTION_TABLE_ID_UNEXPECTED + discard (ruling #11).
def _assembler_policies():
    from ts.section import CrcPolicy, SectionPolicy

    return {
        0x00: SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
        ),
        0x02: SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.REQUIRED
        ),
    }


def _resolver(policies):
    table = dict(policies)
    return lambda table_id: table.get(table_id)


def _packet(
    payload: bytes,
    *,
    pusi: bool = False,
    cc: int = 0,
    pid: int = 0x100,
    discontinuity: bool = False,
):
    """Build a 188-byte TSPacket carrying ``payload`` (AF stuffing pads
    the frame when the payload is shorter than 184 bytes)."""
    from ts.adaptation_field import AdaptationField
    from ts.packet import TSPacket

    if len(payload) == 184 and not discontinuity:
        return TSPacket(
            pid=pid,
            continuity_counter=cc,
            payload=payload,
            payload_unit_start_indicator=pusi,
        )
    return TSPacket(
        pid=pid,
        continuity_counter=cc,
        payload=payload,
        payload_unit_start_indicator=pusi,
        adaptation_field=AdaptationField(discontinuity_indicator=discontinuity),
    )


class TestSectionAssembler:
    """REQ-TS-102-004: PUSI/pointer_field/跨包/多 Section 组装正确
    (SPEC-102 §6.2)."""

    def test_section_assembler(self) -> None:
        """Single-packet, cross-packet, pointer-completion and multi-section
        assembly all emit complete sections in wire order."""
        from ts.section import PSISection
        from ts.section_assembler import SectionAssembler

        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))

        # One section exactly inside one packet (PUSI=1, pointer_field=0).
        emitted = assembler.push(_packet(b"\x00" + SECTION_A, pusi=True, cc=0))
        assert len(emitted) == 1
        assert isinstance(emitted[0], PSISection)
        assert emitted[0].table_id == 0x00
        assert emitted[0].raw_bytes == SECTION_A
        assert assembler.flush() == []

        # Cross-packet: the section boundary is mid-payload; the partial
        # tail keeps until the PUSI=0 continuation completes it.
        first = assembler.push(_packet(b"\x00" + SECTION_D[:12], pusi=True, cc=1))
        assert first == []
        second = assembler.push(_packet(SECTION_D[12:], pusi=False, cc=2))
        assert len(second) == 1
        assert second[0].table_id == 0x02
        assert second[0].raw_bytes == SECTION_D

        # Section boundary exactly at the payload's last byte: the next
        # packet starts clean (pointer byte only, no section data).
        boundary = assembler.push(
            _packet(b"\x00" + SECTION_A[:15], pusi=True, cc=3)
        )
        assert boundary == []
        tail = assembler.push(_packet(b"\x00" + SECTION_A[15:], pusi=True, cc=4))
        assert len(tail) == 1
        assert tail[0].raw_bytes == SECTION_A

        # Two complete sections in one packet, in wire order.
        both = assembler.push(
            _packet(b"\x00" + SECTION_A + SECTION_D, pusi=True, cc=5)
        )
        assert [section.raw_bytes for section in both] == [SECTION_A, SECTION_D]

        # pointer_field>0 completes the previous partial section first,
        # then a following section in the same payload parses (§6.2).
        assembler.push(_packet(b"\x00" + SECTION_D[:12], pusi=True, cc=6))
        completed = assembler.push(
            _packet(bytes((0x0A,)) + SECTION_D[12:] + SECTION_A, pusi=True, cc=7)
        )
        assert [section.raw_bytes for section in completed] == [
            SECTION_D,
            SECTION_A,
        ]

        # 0xFF stuffing after the last section is never parsed as a
        # table_id (§6.2).
        stuffed = assembler.push(
            _packet(b"\x00" + SECTION_A + b"\xFF" * 20, pusi=True, cc=8)  # testdata-ok: 20 stuffing bytes are filler after the section end, not expected-value material
        )
        assert [section.raw_bytes for section in stuffed] == [SECTION_A]
        assert assembler.flush() == []

        # A payload-less packet (AFC=10) contributes no data and does not
        # disturb the active partial section.
        assembler.push(_packet(b"\x00" + SECTION_A[:5], pusi=True, cc=9))
        from ts.adaptation_field import AdaptationField
        from ts.packet import TSPacket

        idle = TSPacket(
            pid=0x100, continuity_counter=10, payload=None,
            adaptation_field=AdaptationField(),
        )
        assert assembler.push(idle) == []
        resumed = assembler.push(_packet(SECTION_A[5:], pusi=False, cc=11))
        assert [section.raw_bytes for section in resumed] == [SECTION_A]

    def test_assembler_ignores_foreign_pid(self) -> None:
        """Packets of other PIDs are not this assembler's data (§5)."""
        from ts.section_assembler import SectionAssembler

        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))
        assert (
            assembler.push(_packet(b"\x00" + SECTION_A, pusi=True, pid=0x200))
            == []
        )
        assert assembler.flush() == []

    def test_unknown_table_id_discarded_no_default_policy(self) -> None:
        """Ruling #11: an unconfigured table_id yields
        SECTION_TABLE_ID_UNEXPECTED and the section is discarded — never
        parsed under a default policy. Subsequent sections still emit."""
        from ts.section_assembler import SectionAssembler

        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))
        # tid 0x42 (unknown, 6-byte section) followed by a known section.
        emitted = assembler.push(
            _packet(b"\x00" + SECTION_B + SECTION_A, pusi=True, cc=0)
        )
        assert [section.raw_bytes for section in emitted] == [SECTION_A]
        issues = assembler.flush()
        assert [issue.code for issue in issues] == ["SECTION_TABLE_ID_UNEXPECTED"]

        # The same discard works across packet boundaries: the partial
        # unknown section spans packets and is dropped at completion.
        assembler.push(_packet(b"\x00" + SECTION_B[:3], pusi=True, cc=1))
        emitted = assembler.push(
            _packet(SECTION_B[3:] + SECTION_A, pusi=False, cc=2)
        )
        assert [section.raw_bytes for section in emitted] == [SECTION_A]
        issues = assembler.flush()
        assert [issue.code for issue in issues] == ["SECTION_TABLE_ID_UNEXPECTED"]


# ---------------------------------------------------------------------------
# Primary test REQ-TS-102-005
# ---------------------------------------------------------------------------


class TestSectionAssemblerRecovery:
    """REQ-TS-102-005: 不完整和 discontinuity 的恢复行为可预测且有事件
    (SPEC-102 §6.2, §8 assembly-side codes)."""

    def test_section_assembler_recovery(self) -> None:
        """Every incomplete/malformed path yields an explicit ParseIssue and
        a cleared state that the next PUSI=1 packet recovers from."""
        from ts.section_assembler import (
            SECTION_CONTINUATION_WITHOUT_START,
            SECTION_DISCARDED_ON_DISCONTINUITY,
            SECTION_POINTER_FIELD_INVALID,
            SECTION_TRUNCATED_AT_EOF,
            SectionAssembler,
        )

        def _fresh() -> SectionAssembler:
            return SectionAssembler(0x100, _resolver(_assembler_policies()))

        # PUSI=0 with no active partial: payload dropped with an explicit
        # event, no arbitrary section start (§6.2); a later PUSI=1 recovers.
        assembler = _fresh()
        assert assembler.push(_packet(b"\xde\xad\xbe\xef", cc=0)) == []
        assert [issue.code for issue in assembler.flush()] == [
            SECTION_CONTINUATION_WITHOUT_START
        ]
        emitted = assembler.push(_packet(b"\x00" + SECTION_A, pusi=True, cc=1))
        assert [section.raw_bytes for section in emitted] == [SECTION_A]

        # pointer_field beyond the payload: explicit event, framing state
        # cleared — the pending partial is NOT resumed afterwards.
        assembler = _fresh()
        assembler.push(_packet(b"\x00" + SECTION_D[:12], pusi=True, cc=0))
        bad_pointer = assembler.push(
            _packet(bytes((0xF0,)) + b"\x11" * 4, pusi=True, cc=1)
        )
        assert bad_pointer == []
        assert [issue.code for issue in assembler.flush()] == [
            SECTION_POINTER_FIELD_INVALID
        ]
        # State was cleared: a PUSI=0 payload cannot resume the old partial.
        assert assembler.push(_packet(SECTION_D[12:], cc=2)) == []
        assert [issue.code for issue in assembler.flush()] == [
            SECTION_CONTINUATION_WITHOUT_START
        ]
        emitted = assembler.push(_packet(b"\x00" + SECTION_D, pusi=True, cc=3))
        assert [section.raw_bytes for section in emitted] == [SECTION_D]

        # discontinuity_indicator=1 drops the partial (event) and the
        # following PUSI=0 payload is not stitched onto it (§6.2).
        assembler = _fresh()
        assembler.push(_packet(b"\x00" + SECTION_D[:12], pusi=True, cc=0))
        assert (
            assembler.push(_packet(SECTION_D[12:], discontinuity=True, cc=4))
            == []
        )
        issues = assembler.flush()
        assert [issue.code for issue in issues] == [
            SECTION_DISCARDED_ON_DISCONTINUITY,
            SECTION_CONTINUATION_WITHOUT_START,
        ]
        emitted = assembler.push(_packet(b"\x00" + SECTION_D, pusi=True, cc=5))
        assert [section.raw_bytes for section in emitted] == [SECTION_D]

        # Caller reset (CC-gap notification): drops the partial with the
        # reason quoted; an idle reset records nothing.
        assembler = _fresh()
        assembler.push(_packet(b"\x00" + SECTION_D[:12], pusi=True, cc=0))
        assembler.reset("continuity counter gap reported by CC checker")
        issues = assembler.flush()
        assert [issue.code for issue in issues] == [
            SECTION_DISCARDED_ON_DISCONTINUITY
        ]
        assert "continuity counter gap" in issues[0].message
        assembler.reset("idle reset is a no-op")
        assert assembler.flush() == []

        # EOF partial: flush reports SECTION_TRUNCATED_AT_EOF and never
        # pads the section (§6.2); a second flush is empty; the cleared
        # state refuses a PUSI=0 resume.
        assembler = _fresh()
        assembler.push(_packet(b"\x00" + SECTION_D[:7], pusi=True, cc=0))
        issues = assembler.flush()
        assert [issue.code for issue in issues] == [SECTION_TRUNCATED_AT_EOF]
        assert assembler.flush() == []
        assert assembler.push(_packet(SECTION_D[7:], cc=1)) == []
        assert [issue.code for issue in assembler.flush()] == [
            SECTION_CONTINUATION_WITHOUT_START
        ]

        # section_length beyond the table profile mid-assembly: explicit
        # event, state cleared, next PUSI=1 recovers (predictable, bounded).
        assembler = _fresh()
        # Header 00 b4 01 declares section_length 1025 > 1021 (policy max).
        assert assembler.push(
            _packet(
                b"\x00" + bytes((0x00, 0xB4, 0x01)) + b"\x00" * 8,
                pusi=True,
                cc=0,
            )
        ) == []
        assert [issue.code for issue in assembler.flush()] == [
            "SECTION_LENGTH_EXCEEDS_POLICY"
        ]
        emitted = assembler.push(_packet(b"\x00" + SECTION_A, pusi=True, cc=1))
        assert [section.raw_bytes for section in emitted] == [SECTION_A]

    def test_length_fault_drops_rest_of_packet(self) -> None:
        """After an untrustworthy length the rest of the payload is not
        re-interpreted as further sections (no resync guessing)."""
        from ts.section_assembler import SectionAssembler

        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))
        # Length fault (1025 > 1021) followed by a complete known section:
        # the known section must NOT be emitted from the same payload.
        payload = b"\x00" + bytes((0x00, 0xB4, 0x01)) + b"\x00" * 8 + SECTION_A
        assert assembler.push(_packet(payload, pusi=True, cc=0)) == []
        issues = assembler.flush()
        assert [issue.code for issue in issues] == [
            "SECTION_LENGTH_EXCEEDS_POLICY"
        ]

    def test_declared_zero_section_completes_at_payload_boundary(self) -> None:
        """A declared section_length=0 section (3-byte total) whose header
        ends exactly at the payload boundary completes in place — flush()
        yields the same parse verdict as the trailing-bytes control and
        never the self-contradictory SECTION_TRUNCATED_AT_EOF "3 of 3
        bytes" (#35 difference report §4 corner)."""
        from ts.section_assembler import (
            SECTION_TRUNCATED_AT_EOF,
            SectionAssembler,
        )

        # 3-byte section under the 0x00 policy: table_id, flags byte with
        # section_syntax=1, section_length=0 — total == 3 == header size.
        SEC3 = bytes((0x00, 0x80, 0x00))

        # Variant A (corner): the section ends EXACTLY at the payload end
        # and the stream ends right there.
        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))
        assert assembler.push(_packet(b"\x00" + SEC3, pusi=True, cc=0)) == []
        corner_codes = [issue.code for issue in assembler.flush()]
        assert SECTION_TRUNCATED_AT_EOF not in corner_codes

        # Variant B (control): same section with trailing bytes completes
        # inside the same push; flush() carries only the parse verdict.
        control = SectionAssembler(0x100, _resolver(_assembler_policies()))
        # testdata-ok: 8 stuffing bytes are filler after the section end, not expected-value material
        assert control.push(
            _packet(b"\x00" + SEC3 + b"\xFF" * 8, pusi=True, cc=0)
        ) == []
        control_codes = [issue.code for issue in control.flush()]
        assert SECTION_TRUNCATED_AT_EOF not in control_codes

        # Corner and control must now agree on the verdict (the 3-byte
        # long-form section is too short for the 5 public header bytes).
        assert corner_codes == control_codes == ["SECTION_LONG_HEADER_TRUNCATED"]

        # The framing state cleared: a PUSI=0 payload is not stitched on.
        assert assembler.push(_packet(b"\xde\xad\xbe\xef", cc=1)) == []
        assert [issue.code for issue in assembler.flush()] == [
            "SECTION_CONTINUATION_WITHOUT_START"
        ]

    def test_declared_zero_unknown_table_id_completes_in_place(self) -> None:
        """The skip-mode path (unknown table_id) completes a declared
        section_length=0 section in place too: flush() keeps only the
        SECTION_TABLE_ID_UNEXPECTED event, no stale truncation event."""
        from ts.section_assembler import (
            SECTION_TRUNCATED_AT_EOF,
            SectionAssembler,
        )

        assembler = SectionAssembler(0x100, _resolver(_assembler_policies()))
        # table_id 0x71 has no configured policy; declared length 0.
        assert assembler.push(
            _packet(b"\x00" + bytes((0x71, 0x80, 0x00)), pusi=True, cc=0)
        ) == []
        codes = [issue.code for issue in assembler.flush()]
        assert codes == ["SECTION_TABLE_ID_UNEXPECTED"]
        assert SECTION_TRUNCATED_AT_EOF not in codes


# ---------------------------------------------------------------------------
# Primary test REQ-TS-102-006
# ---------------------------------------------------------------------------


class TestSectionMalformedLengths:
    """REQ-TS-102-006: 非法长度和畸形 payload 具有边界安全性 (SPEC-102 §9)."""

    def test_section_malformed_lengths(self) -> None:
        """section_length 0 / profile max / beyond profile / beyond wire
        range; body truncation; malformed lengths stay bounded (no OOB, no
        loop) in parser and assembler alike."""
        from ts.errors import InvalidSectionError
        from ts.section import (
            CrcPolicy,
            SectionPolicy,
            parse_section,
            section_total_size,
        )
        from ts.section_assembler import SectionAssembler as Assembler

        required = SectionPolicy(
            max_section_length=1021,
            crc_policy=CrcPolicy.REQUIRED,
            require_long_syntax=True,
            expected_table_id=0x00,
        )
        absent = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )

        # section_length = 0 is the minimal legal section (total = 3).
        tiny = parse_section(bytes((0x42, 0x70, 0x00)), absent)
        assert tiny.section_length == 0

        # Body truncated: bytes below 3 + section_length never fabricate an
        # object (both modes raise; no zero-padding, §6.1 step 3).
        for data in (SECTION_A[:-1], SECTION_A[:9], SECTION_A[:4]):
            with pytest.raises(InvalidSectionError) as excinfo:
                parse_section(data, required)
            assert "SECTION_BODY_TRUNCATED" in str(excinfo.value)
            with pytest.raises(InvalidSectionError):
                parse_section(data, required, strict=False)

        # Beyond profile and beyond wire range: the 12-bit field is not a
        # licence (SECTION_LENGTH_EXCEEDS_POLICY, §3/§7).
        beyond_policy = bytes((0x00, 0xB4, 0x01)) + bytes(1025)  # len 1025
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(beyond_policy, required)
        assert "SECTION_LENGTH_EXCEEDS_POLICY" in str(excinfo.value)
        wire_max = bytes((0x42, 0b01_11_1111, 0xFF))  # 0xFFF = 4095
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(wire_max + bytes(4095), absent)
        assert "SECTION_LENGTH_EXCEEDS_POLICY" in str(excinfo.value)
        with pytest.raises(InvalidSectionError) as excinfo:
            section_total_size(wire_max, max_section_length=4094)
        assert "SECTION_LENGTH_EXCEEDS_POLICY" in str(excinfo.value)

        # Assembler with a huge declared length (4095) on an unknown table:
        # the section is skipped by wire length, bounded at 3 + 4095 bytes —
        # it cannot be completed from a single 184-byte payload, so it stays
        # a bounded partial, emits nothing, over-reads nothing and loops
        # nowhere; flush reports it as truncated instead of faking it.
        assembler = Assembler(0x100, _resolver(_assembler_policies()))
        huge_unknown = bytes((0x55, 0b00_11_1111, 0xFF))[:3]  # tid 0x55, 4095
        emitted = assembler.push(
            _packet(b"\x00" + huge_unknown + SECTION_B, pusi=True, cc=0)
        )
        assert emitted == []  # partial unknown section, buffer bounded
        emitted = assembler.push(_packet(bytes(184), cc=1))
        assert emitted == []  # 4098 bytes needed, still bounded partial
        issues = assembler.flush()
        # The unknown-table event fired when its header was identified; the
        # bounded partial is then reported as truncated (never faked).
        assert [issue.code for issue in issues] == [
            "SECTION_TABLE_ID_UNEXPECTED",
            "SECTION_TRUNCATED_AT_EOF",
        ]

    def test_malformed_fuzz_never_crashes(self) -> None:
        """Random malformed payloads (fixed seed) produce typed errors or
        issues only — never IndexError/Recursion/other exceptions (§9)."""
        import random

        from ts.errors import InvalidSectionError, TSCoreError
        from ts.section import (
            CrcPolicy,
            SectionPolicy,
            parse_section,
            section_total_size,
        )
        from ts.section_assembler import SectionAssembler

        rng = random.Random(0xD9B102)  # fixed seed: reproducible failures
        policies = _assembler_policies()
        policies[0x42] = SectionPolicy(
            max_section_length=64, crc_policy=CrcPolicy.ABSENT
        )
        policies[0x55] = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.OPTIONAL
        )
        resolver = _resolver(policies)
        assembler = SectionAssembler(0x100, resolver)
        cc = 0
        for _ in range(400):
            blob = bytes(
                rng.randrange(256) for _ in range(rng.randrange(0, 48))
            )
            # Parser: typed InvalidSectionError or success — nothing else.
            policy = resolver(blob[0]) if blob else None
            if policy is not None:
                try:
                    parse_section(blob, policy)
                except InvalidSectionError:
                    pass
                try:
                    parse_section(blob, policy, strict=False)
                except InvalidSectionError:
                    pass
            if len(blob) >= 3:
                try:
                    section_total_size(
                        blob[:3],
                        max_section_length=rng.choice((0, 64, 1021, 4095)),
                    )
                except InvalidSectionError:
                    pass
            # Assembler: never raises on wire data at all. (An empty
            # payload cannot fill a TS packet frame, so skip it here; the
            # empty-input parser path is covered by the header guard.)
            if not blob:
                continue
            pusi = rng.random() < 0.5
            cc = (cc + 1) % 16
            assembler.push(_packet(blob, pusi=pusi, cc=cc))
        assembler.flush()

        # Malformed section bytes through the parser stay typed: any raise
        # is a TSCoreError, never a bare IndexError/struct error.
        for _ in range(200):
            blob = bytes(
                rng.randrange(256) for _ in range(rng.randrange(3, 24))
            )
            policy = resolver(blob[0])
            if policy is None:
                continue
            try:
                parse_section(blob, policy)
            except TSCoreError:
                pass

    def test_type_and_range_guards(self) -> None:
        """Non-bytes inputs, wrong policy types and out-of-range field
        values are programming errors with typed exceptions."""
        from ts.errors import InvalidSectionError
        from ts.section import (
            CrcPolicy,
            PSISection,
            SectionPolicy,
            parse_section,
            section_total_size,
        )
        from ts.section_assembler import SectionAssembler as Assembler

        absent = SectionPolicy(
            max_section_length=256, crc_policy=CrcPolicy.ABSENT
        )
        # A bytes-like input too short for a header is wire data: typed
        # SECTION_HEADER_TRUNCATED, not a TypeError.
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(b"\x42", absent)
        assert "SECTION_HEADER_TRUNCATED" in str(excinfo.value)
        for bad in (123, None, 3.5, "bytes"):
            with pytest.raises(TypeError):
                parse_section(bad, absent)  # type: ignore[arg-type]
            with pytest.raises(TypeError):
                section_total_size(bad, max_section_length=256)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            parse_section(SECTION_B, policy="nope")  # type: ignore[arg-type]

        # Policy range/type guards (programming errors).
        with pytest.raises(ValueError):
            SectionPolicy(
                max_section_length=4096, crc_policy=CrcPolicy.ABSENT
            )
        with pytest.raises(ValueError):
            SectionPolicy(max_section_length=-1, crc_policy=CrcPolicy.ABSENT)
        with pytest.raises(TypeError):
            SectionPolicy(max_section_length=64, crc_policy="absent")  # type: ignore[arg-type]

        # PSISection construction guards: ranges and field/raw coherence.
        with pytest.raises(ValueError):
            PSISection(
                table_id=256,
                section_syntax_indicator=False,
                private_indicator=False,
                section_length=0,
                raw_bytes=b"\x00\x30\x00",
            )
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x42,
                section_syntax_indicator=False,
                private_indicator=True,
                section_length=4096,
                raw_bytes=b"\x42\x70\x03\x01\x02\x03",
            )
        # Long-form fields on a short-form section are contradictory (§3).
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x42,
                section_syntax_indicator=False,
                private_indicator=True,
                section_length=3,
                raw_bytes=SECTION_B,
                version_number=3,
            )
        # Field/raw mismatch and short raw_bytes (§4 invariant).
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x99,
                section_syntax_indicator=False,
                private_indicator=True,
                section_length=3,
                raw_bytes=SECTION_B,
            )
        with pytest.raises(ValueError):
            PSISection(
                table_id=0x42,
                section_syntax_indicator=False,
                private_indicator=True,
                section_length=3,
                raw_bytes=SECTION_B[:-1],
            )

        # Assembler construction guards.
        with pytest.raises(ValueError):
            Assembler(0x2000, _resolver(_assembler_policies()))
        with pytest.raises(TypeError):
            Assembler("0x100", _resolver(_assembler_policies()))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            Assembler(0x100, "not-callable")  # type: ignore[arg-type]
        assembler = Assembler(0x100, _resolver(_assembler_policies()))
        with pytest.raises(TypeError):
            assembler.push(b"not-a-packet")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            assembler.reset(123)  # type: ignore[arg-type]
