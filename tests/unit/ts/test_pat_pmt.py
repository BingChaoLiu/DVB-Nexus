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
