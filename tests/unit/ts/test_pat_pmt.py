"""SPEC-103 — PAT/PMT builders/parsers — unit tests (ticket #31).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-103 section):

- REQ-TS-103-001  PAT 正确编解码                          -> test_pat_round_trip
- REQ-TS-103-002  PMT 正确编解码                          -> test_pmt_round_trip
- REQ-TS-103-003  CRC/version/section number 正确         -> test_table_metadata_and_crc
- REQ-TS-103-004  program 0 与 PAT→PMT→ES 关联正确        -> test_program_pid_mapping
- REQ-TS-103-005  loop length 越界安全                    -> test_table_loop_bounds
- REQ-TS-103-006  多 Section 不混合版本                   -> test_table_version_aggregation

Independent sources of truth: the two 16-byte wire literals below are
hand-packed bit-by-bit from SPEC-103 §3/§4 (ITU-T H.222.0 PAT/PMT syntax)
with their CRC-32/MPEG-2 fields frozen once via the SPEC-101
check-vector-verified primitive (the same discipline as
tests/unit/ts/test_section.py); every other wire expectation is produced
programmatically from the builders and re-parsed. Ruling #9 (PMT_INVALID_CRC
/ PMT_PID_MISMATCH): corruption must surface as a parse-time rejection and a
rewritten PAT program_map_PID must surface as an association diagnostic, so
both behaviours are asserted here against the #11-frozen error-code list.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Hand-packed golden literals (see module docstring; each is exactly 16 bytes,
# at the tests/README.md §5 literal threshold, so no testdata-ok exemption)
# ---------------------------------------------------------------------------

# Minimal PAT, one program: table_id=0x00, SSI=1, section_length=13
# (5 public + 4 loop + 4 CRC), tsid=0x0001, version byte 0xC1
# (reserved=11, version=0, current_next=1), section 0/0, entry
# program_number=0x0001 -> reserved 111 + PMT PID 0x1000, CRC 2A B1 04 B2.
MINIMAL_PAT = bytes(  # testdata-ok: hand-packed golden wire literal per SPEC-103 section 3 bit table; independent source pinning the PAT wire format (CRC frozen via the SPEC-101-verified primitive)
    (0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01, 0xF0, 0x00,
     0x2A, 0xB1, 0x04, 0xB2)
)
MINIMAL_PAT_CRC = 0x2AB104B2

# Minimal PMT, zero streams: table_id=0x02, SSI=1, section_length=13
# (5 public + 2 PCR_PID + 2 program_info_length + 4 CRC), program_number
# 0x0001, version byte 0xC1, section 0/0, PCR_PID 0x1000 (reserved 111),
# program_info_length=0 (reserved 1111), CRC 4E 8C A8 23.
MINIMAL_PMT = bytes(  # testdata-ok: hand-packed golden wire literal per SPEC-103 section 4 bit table; independent source pinning the PMT wire format (CRC frozen via the SPEC-101-verified primitive)
    (0x02, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00, 0xF0, 0x00, 0xF0, 0x00,
     0x4E, 0x8C, 0xA8, 0x23)
)
MINIMAL_PMT_CRC = 0x4E8CA823


class TestPatRoundTrip:
    """REQ-TS-103-001 — PAT encode/decode per H.222.0 (primary)."""

    def test_pat_round_trip(self) -> None:
        from ts.section import PSISection, parse_section
        from ts.tables.pat import (
            PAT_SECTION_POLICY,
            PATBuilder,
            PATProgram,
            PATSection,
            parse_pat,
        )

        # Golden literal -> PSISection (framing layer, SPEC-102) -> PATSection.
        psi = parse_section(MINIMAL_PAT, PAT_SECTION_POLICY)
        assert isinstance(psi, PSISection)
        assert psi.crc_value == MINIMAL_PAT_CRC

        pat = parse_pat(psi)
        assert pat.transport_stream_id == 0x0001
        assert pat.version_number == 0
        assert pat.current_next_indicator is True
        assert pat.section_number == 0
        assert pat.last_section_number == 0
        assert pat.programs == (PATProgram(program_number=1, program_map_pid=0x1000),)

        # Builder -> byte-exact echo of the hand-packed literal.
        built = PATBuilder().build(pat)
        assert isinstance(built, PSISection)
        assert built.raw_bytes == MINIMAL_PAT
        assert built.table_id == 0x00
        assert built.section_syntax_indicator is True
        assert built.private_indicator is False
        assert built.section_length == 9 + 4 * len(pat.programs)
        assert built.table_id_extension == 0x0001
        assert built.version_number == 0
        assert built.current_next_indicator is True
        assert built.section_number == 0
        assert built.last_section_number == 0
        assert built.crc_value == MINIMAL_PAT_CRC

        # Full round-trip on a richer table: NIT entry (program_number=0) and
        # two normal programs; version 31; section_length formula holds.
        rich = PATSection(
            transport_stream_id=0xABCD,
            version_number=31,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            programs=(
                PATProgram(program_number=0, program_map_pid=0x0010),
                PATProgram(program_number=0x0001, program_map_pid=0x1000),
                PATProgram(program_number=0x00FF, program_map_pid=0x1FFE),
            ),
        )
        psi_rich = PATBuilder().build(rich)
        assert psi_rich.section_length == 9 + 4 * 3
        reparsed = parse_pat(parse_section(psi_rich.raw_bytes, PAT_SECTION_POLICY))
        assert reparsed == rich

        # current_next_indicator=0 encodes as the "next table" variant.
        nxt = PATSection(
            transport_stream_id=1,
            version_number=5,
            current_next_indicator=False,
            section_number=0,
            last_section_number=0,
            programs=(PATProgram(program_number=1, program_map_pid=0x1000),),
        )
        psi_next = PATBuilder().build(nxt)
        assert parse_section(psi_next.raw_bytes, PAT_SECTION_POLICY) == psi_next
        assert parse_pat(parse_section(psi_next.raw_bytes, PAT_SECTION_POLICY)) == nxt


class TestPmtRoundTrip:
    """REQ-TS-103-002 — PMT encode/decode per H.222.0 (primary)."""

    def test_pmt_round_trip(self) -> None:
        from ts.section import PSISection, parse_section
        from ts.tables.pmt import (
            PMT_SECTION_POLICY,
            PMTBuilder,
            PMTSection,
            ElementaryStream,
            parse_pmt,
        )

        # Golden literal -> PSISection -> PMTSection.
        psi = parse_section(MINIMAL_PMT, PMT_SECTION_POLICY)
        assert isinstance(psi, PSISection)
        assert psi.crc_value == MINIMAL_PMT_CRC

        pmt = parse_pmt(psi)
        assert pmt.program_number == 0x0001
        assert pmt.version_number == 0
        assert pmt.current_next_indicator is True
        assert pmt.section_number == 0
        assert pmt.last_section_number == 0
        assert pmt.pcr_pid == 0x1000
        assert pmt.program_descriptors == b""
        assert pmt.streams == ()

        # Builder -> byte-exact echo of the hand-packed literal.
        built = PMTBuilder().build(pmt)
        assert isinstance(built, PSISection)
        assert built.raw_bytes == MINIMAL_PMT
        assert built.table_id == 0x02
        assert built.section_syntax_indicator is True
        assert built.private_indicator is False
        assert built.section_length == 13  # 5+2+2+4, no descriptors/streams
        assert built.table_id_extension == 0x0001
        assert built.crc_value == MINIMAL_PMT_CRC

        # Rich round-trip: program descriptors + two ES entries with
        # descriptors, one of them carrying the PCR (legal, §8.6).
        rich = PMTSection(
            program_number=0x0042,
            version_number=7,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            pcr_pid=0x0100,
            program_descriptors=b"\x42\x80\x01\x02",  # 4 descriptor bytes
            streams=(
                ElementaryStream(
                    stream_type=0x1B, elementary_pid=0x0100,
                    descriptors=b"\x52\x01\xAB",
                ),
                ElementaryStream(
                    stream_type=0x0F, elementary_pid=0x0101,
                    descriptors=b"",
                ),
            ),
        )
        psi_rich = PMTBuilder().build(rich)
        expected_length = 13 + len(rich.program_descriptors) + sum(
            5 + len(stream.descriptors) for stream in rich.streams
        )
        assert psi_rich.section_length == expected_length
        reparsed = parse_pmt(parse_section(psi_rich.raw_bytes, PMT_SECTION_POLICY))
        assert reparsed == rich
        # Descriptor bytes survive verbatim (§4: parser must keep them).
        assert reparsed.program_descriptors == b"\x42\x80\x01\x02"
        assert reparsed.streams[0].descriptors == b"\x52\x01\xAB"
        assert reparsed.streams[1].descriptors == b""
        assert reparsed.streams[0].stream_type == 0x1B
        assert reparsed.streams[1].stream_type == 0x0F


class TestTableMetadataAndCrc:
    """REQ-TS-103-003 — CRC / version / section-number correctness (primary)."""

    def test_table_metadata_and_crc(self) -> None:
        from ts.crc import verify_mpeg2_crc32
        from ts.errors import InvalidSectionError
        from ts.section import CrcPolicy, SectionPolicy, parse_section
        from ts.tables.pat import (
            PAT_SECTION_POLICY,
            PATBuilder,
            PATProgram,
            PATSection,
            parse_pat,
        )
        from ts.tables.pmt import (
            PMT_SECTION_POLICY,
            PMTBuilder,
            PMTSection,
            ElementaryStream,
            parse_pmt,
        )

        # version_number 0 and 31, current_next 0/1 on both tables.
        for version in (0, 31):
            for current_next in (True, False):
                pat = PATSection(
                    transport_stream_id=0x1234,
                    version_number=version,
                    current_next_indicator=current_next,
                    section_number=0,
                    last_section_number=0,
                    programs=(PATProgram(1, 0x1000),),
                )
                psi = PATBuilder().build(pat)
                back = parse_pat(parse_section(psi.raw_bytes, PAT_SECTION_POLICY))
                assert back == pat
                assert back.version_number == version
                assert back.current_next_indicator is current_next
                pmt = PMTSection(
                    program_number=1,
                    version_number=version,
                    current_next_indicator=current_next,
                    section_number=0,
                    last_section_number=0,
                    pcr_pid=0x1000,
                    program_descriptors=b"",
                    streams=(ElementaryStream(0x1B, 0x0101),),
                )
                psi_pmt = PMTBuilder().build(pmt)
                back_pmt = parse_pmt(
                    parse_section(psi_pmt.raw_bytes, PMT_SECTION_POLICY)
                )
                assert back_pmt == pmt
                assert back_pmt.version_number == version
                assert back_pmt.current_next_indicator is current_next

        # Section-number edges: 0/0 and 255/255 round-trip (§7 ranges).
        edge = PATSection(
            transport_stream_id=1,
            version_number=3,
            current_next_indicator=True,
            section_number=255,
            last_section_number=255,
            programs=(PATProgram(1, 0x1000),),
        )
        assert parse_pat(
            parse_section(PATBuilder().build(edge).raw_bytes, PAT_SECTION_POLICY)
        ) == edge
        edge_pmt = PMTSection(
            program_number=1,
            version_number=3,
            current_next_indicator=True,
            section_number=255,
            last_section_number=255,
            pcr_pid=0x1000,
            program_descriptors=b"",
            streams=(),
        )
        assert parse_pmt(
            parse_section(PMTBuilder().build(edge_pmt).raw_bytes, PMT_SECTION_POLICY)
        ) == edge_pmt

        # Builder CRC fields verify over the exact wire bytes.
        built_pat = PATBuilder().build(
            PATSection(1, 0, True, 0, 0, (PATProgram(1, 0x1000),))
        )
        built_pmt = PMTBuilder().build(
            PMTSection(1, 0, True, 0, 0, 0x1000, b"", ())
        )
        assert verify_mpeg2_crc32(built_pat.raw_bytes)
        assert verify_mpeg2_crc32(built_pmt.raw_bytes)

        # Corruption -> parse-time rejection at BOTH layers (ruling #9:
        # PMT_INVALID_CRC corruption semantics; persistent symptom).
        corrupted = bytearray(built_pmt.raw_bytes)
        corrupted[10] ^= 0xFF
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(bytes(corrupted), PMT_SECTION_POLICY)
        assert "SECTION_CRC_INVALID" in str(excinfo.value)
        lenient = parse_section(bytes(corrupted), PMT_SECTION_POLICY, strict=False)
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pmt(lenient)
        assert "SECTION_CRC_INVALID" in str(excinfo.value)

        corrupted_pat = bytearray(built_pat.raw_bytes)
        corrupted_pat[12] ^= 0x01
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_section(bytes(corrupted_pat), PAT_SECTION_POLICY)
        assert "SECTION_CRC_INVALID" in str(excinfo.value)
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pat(
                parse_section(bytes(corrupted_pat), PAT_SECTION_POLICY, strict=False)
            )
        assert "SECTION_CRC_INVALID" in str(excinfo.value)

        # CRC is mandatory: no room for the field -> SECTION_CRC_MISSING.
        from ts.section import PSISection

        crcless = PSISection(
            table_id=0x00,
            section_syntax_indicator=True,
            private_indicator=False,
            section_length=2,
            raw_bytes=b"\x00\xb0\x02\xaa\xbb",
        )
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pat(crcless)
        assert "SECTION_CRC_MISSING" in str(excinfo.value)

        # Wrong table_id -> table-specific code, at the table layer.
        neutral = SectionPolicy(max_section_length=1021, crc_policy=CrcPolicy.OPTIONAL)
        wrong_pat = bytes([0x42]) + MINIMAL_PAT[1:]
        psi_wrong = parse_section(wrong_pat, neutral)
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pat(psi_wrong)
        assert "PAT_TABLE_ID_INVALID" in str(excinfo.value)
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pmt(parse_section(MINIMAL_PAT, neutral))
        assert "PMT_TABLE_ID_INVALID" in str(excinfo.value)

        # Builder: single-section overflow is an explicit failure (§3/§4).
        with pytest.raises(InvalidSectionError) as excinfo:
            PATBuilder().build(
                PATSection(
                    transport_stream_id=1,
                    version_number=0,
                    current_next_indicator=True,
                    section_number=0,
                    last_section_number=0,
                    programs=tuple(
                        PATProgram(number, 0x1000 + number)
                        for number in range(1, 255)  # 9 + 4*254 = 1025 > 1021
                    ),
                )
            )
        assert "TABLE_SECTION_TOO_LARGE" in str(excinfo.value)
        # Boundary: exactly 1021 encodes fine (9 + 4*253).
        max_pat = PATSection(
            transport_stream_id=1,
            version_number=0,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            programs=tuple(
                PATProgram(number, 0x0100 + number) for number in range(1, 254)
            ),
        )
        assert PATBuilder().build(max_pat).section_length == 1021

        with pytest.raises(InvalidSectionError) as excinfo:
            PMTBuilder().build(
                PMTSection(
                    program_number=1,
                    version_number=0,
                    current_next_indicator=True,
                    section_number=0,
                    last_section_number=0,
                    pcr_pid=0x1000,
                    program_descriptors=bytes(range(4)),  # 13+4+5*202 > 1021
                    streams=tuple(
                        ElementaryStream(0x1B, 0x0100 + n) for n in range(202)
                    ),
                )
            )
        assert "TABLE_SECTION_TOO_LARGE" in str(excinfo.value)
        # Boundary: 13 + 3 + 5*201 = 1021 encodes fine.
        max_pmt = PMTSection(
            program_number=1,
            version_number=0,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            pcr_pid=0x1000,
            program_descriptors=b"\x01\x02\x03",
            streams=tuple(ElementaryStream(0x1B, 0x0100 + n) for n in range(201)),
        )
        assert PMTBuilder().build(max_pmt).section_length == 1021


class TestProgramPidMapping:
    """REQ-TS-103-004 — program 0 semantics + PAT->PMT->ES association (primary)."""

    def test_program_pid_mapping(self) -> None:
        from ts.crc import mpeg2_crc32
        from ts.errors import InvalidSectionError
        from ts.issues import ValidationIssue
        from ts.section import parse_section
        from ts.tables.pat import (
            PAT_SECTION_POLICY,
            PATBuilder,
            PATProgram,
            PATSection,
            parse_pat,
        )
        from ts.tables.pmt import (
            PMT_SECTION_POLICY,
            PMTBuilder,
            PMTSection,
            ElementaryStream,
            parse_pmt,
        )
        from ts.tables.table_validation import validate_pid_associations

        # program_number=0 is the network_PID entry (NIT), never a PMT.
        pat = PATSection(
            transport_stream_id=1,
            version_number=0,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            programs=(
                PATProgram(0, 0x0010),  # network_PID
                PATProgram(1, 0x1000),
            ),
        )
        back = parse_pat(parse_section(PATBuilder().build(pat).raw_bytes, PAT_SECTION_POLICY))
        assert back.programs[0] == PATProgram(0, 0x0010)
        assert back.programs[1] == PATProgram(1, 0x1000)

        # A PMT cannot be created for program 0 (§5 hard rule).
        with pytest.raises(ValueError):
            PMTSection(
                program_number=0, version_number=0,
                current_next_indicator=True, section_number=0,
                last_section_number=0, pcr_pid=0x1000,
                program_descriptors=b"", streams=(),
            )
        # ... and a wire PMT claiming program 0 is an association mismatch.
        rogue = bytearray(
            PMTBuilder().build(
                PMTSection(1, 0, True, 0, 0, 0x1000, b"", ())
            ).raw_bytes
        )
        rogue[3] = 0x00
        rogue[4] = 0x00
        rogue[-4:] = mpeg2_crc32(bytes(rogue[:-4])).to_bytes(4, "big")
        with pytest.raises(InvalidSectionError) as excinfo:
            parse_pmt(parse_section(bytes(rogue), PMT_SECTION_POLICY))
        assert "PAT_PMT_PROGRAM_MISMATCH" in str(excinfo.value)

        # Happy association matrix: no diagnostics.
        pmt1 = PMTSection(1, 0, True, 0, 0, 0x1000, b"", (
            ElementaryStream(0x1B, 0x0100),
            ElementaryStream(0x0F, 0x0101),
        ))
        pmt2 = PMTSection(2, 0, True, 0, 0, 0x1001, b"", (
            ElementaryStream(0x1B, 0x0102),
        ))
        pat_ok = PATSection(1, 0, True, 0, 0, (
            PATProgram(0, 0x0010), PATProgram(1, 0x1000), PATProgram(2, 0x1001),
        ))
        assert validate_pid_associations(0x0000, pat_ok, [(0x1000, pmt1), (0x1001, pmt2)]) == []

        # Ruling #9 PMT_PID_MISMATCH semantics: the PAT entry is rewritten
        # (CRC recomputed by the injector), the association check must
        # surface a diagnostic — no default PMT is substituted (§8.7).
        pat_faulted = PATSection(1, 0, True, 0, 0, (
            PATProgram(1, 0x0500),  # rewritten: wrong PMT PID
            PATProgram(2, 0x1001),
        ))
        issues = validate_pid_associations(0x0000, pat_faulted, [(0x1000, pmt1), (0x1001, pmt2)])
        codes = [issue.code for issue in issues]
        assert codes == ["PAT_PMT_PROGRAM_MISMATCH"]
        assert "0x0500" in issues[0].message
        assert "0x1000" in issues[0].message
        assert all(issue.severity == "error" for issue in issues)

        # A rewritten PID pointing where no PMT exists at all.
        issues = validate_pid_associations(0x0000, pat_faulted, [(0x1001, pmt2)])
        assert [issue.code for issue in issues] == ["PAT_PMT_PROGRAM_MISMATCH"]
        assert "no PMT found" in issues[0].message

        # PMT whose program_number matches no PAT entry. With only the
        # orphan PMT provided, PAT programs 1 and 2 are also unmatched
        # (§8.7 diagnostics for every association hole).
        orphan = PMTSection(9, 0, True, 0, 0, 0x1002, b"", ())
        issues = validate_pid_associations(0x0000, pat_ok, [(0x1002, orphan)])
        assert [issue.code for issue in issues] == ["PAT_PMT_PROGRAM_MISMATCH"] * 3
        assert any("no matching PAT entry" in issue.message for issue in issues)

        # PAT not on PID 0x0000 (§8.1).
        issues = validate_pid_associations(0x0001, pat_ok, [(0x1000, pmt1), (0x1001, pmt2)])
        assert [issue.code for issue in issues] == ["PAT_PID_INVALID"]

        # PAT entries may not map to the PAT PID or the Null PID (§7).
        for bad_pid in (0x0000, 0x1FFF):
            bad = PATSection(1, 0, True, 0, 0, (PATProgram(1, bad_pid),))
            issues = validate_pid_associations(0x0000, bad, [])
            assert [issue.code for issue in issues] == ["PAT_PMTPID_INVALID"]

        # Duplicate program_number entries in one PAT (§8.2 ambiguity);
        # with no PMTs provided the two entries are also unmatched, so the
        # ambiguity diagnostic arrives first alongside §8.7 holes.
        dup = PATSection(1, 0, True, 0, 0, (
            PATProgram(1, 0x1000), PATProgram(1, 0x1001),
        ))
        issues = validate_pid_associations(0x0000, dup, [])
        assert issues[0].code == "PAT_PROGRAM_NUMBER_INVALID"
        assert issues[1].code == "PAT_PMT_PROGRAM_MISMATCH"

        # ES/PCR PID policy (§8.4/§8.6), checked against a single-program
        # PAT so association findings do not mix into the expectations.
        pat_single = PATSection(1, 0, True, 0, 0, (PATProgram(1, 0x1000),))
        # PCR_PID=0x1FFF is the project's tightened rule — the wording must
        # not claim a standard violation.
        no_pcr = PMTSection(1, 0, True, 0, 0, 0x1FFF, b"", (
            ElementaryStream(0x1B, 0x0100),
        ))
        issues = validate_pid_associations(0x0000, pat_single, [(0x1000, no_pcr)])
        assert [issue.code for issue in issues] == ["PMT_PID_INVALID"]
        assert "project rule" in issues[0].message
        assert "H.222.0" in issues[0].message

        for bad_pid in (0x0000, 0x1FFF):
            bad_pcr = PMTSection(1, 0, True, 0, 0, bad_pid, b"", ())
            issues = validate_pid_associations(0x0000, pat_single, [(0x1000, bad_pcr)])
            assert [issue.code for issue in issues] == ["PMT_PID_INVALID"]
            bad_es = PMTSection(1, 0, True, 0, 0, 0x1000, b"", (
                ElementaryStream(0x1B, bad_pid),
            ))
            issues = validate_pid_associations(0x0000, pat_single, [(0x1000, bad_es)])
            assert [issue.code for issue in issues] == ["PMT_PID_INVALID"]

        # Same program's ES PIDs must not repeat (§8.5).
        dup_es = PMTSection(1, 0, True, 0, 0, 0x1000, b"", (
            ElementaryStream(0x1B, 0x0100),
            ElementaryStream(0x0F, 0x0100),  # duplicate PID
        ))
        issues = validate_pid_associations(0x0000, pat_single, [(0x1000, dup_es)])
        assert [issue.code for issue in issues] == ["PMT_PID_INVALID"]
        assert "0x0100" in issues[0].message

        # PCR riding an ES PID is legal (§8.6 second clause): pmt1 carries
        # PCR on 0x1000 while its first ES sits on the same PID.
        assert validate_pid_associations(0x0000, pat_single, [(0x1000, pmt1)]) == []
