"""SPEC-103 — PAT (Program Association Table): model / builder / parser.

PAT semantics on top of the frozen SPEC-102 framing (§3, ITU-T H.222.0
2.4.4.2): ``table_id=0x00``, long form, CRC mandatory, fixed on PID
``0x0000``. ``table_id_extension`` carries ``transport_stream_id``; each
4-byte program-loop entry is ``program_number`` (16 bits) followed by 3
reserved bits + a 13-bit ``program_map_PID``. The ``program_number=0`` entry
is the network_PID pointer (NIT PID) — it is NOT a PMT entry, and
:attr:`PATProgram.program_map_pid` carries the network_PID for it.

Data model (§5 verbatim): frozen dataclasses whose ``__post_init__`` treats
out-of-range field values as programming errors (TypeError/ValueError,
``ts.section.PSISection`` precedent); wire-side problems carry §9 error
codes instead and are raised as :class:`ts.errors.InvalidSectionError` in
the ``"CODE: message"`` convention of :mod:`ts.section`.

Encoding (§7, ruling #11): ``section_length`` is accumulated from named
constant parts — 5 public-header bytes + 4 bytes per program entry + the
4-byte CRC field — which equals the spec formula ``9 + 4 *
program_entry_count``; no unexplained magic constants. Reserved bits encode
to the standard constant values (``0b10`` SSI/private prefix, ``0b11``
version-byte prefix, ``0b111`` PID prefix). A single-section encode beyond
the table maximum (``section_length > 1021``) raises ``TABLE_SECTION_TOO_LARGE``
— explicit failure, never a silent split (§3/§7).

Parsing (§6): ``parse_pat`` accepts a :class:`ts.section.PSISection` and
re-derives every field from ``raw_bytes`` (the byte authority, contract §2
principle 1) — convenience fields are never trusted. Gate order: table_id
(``PAT_TABLE_ID_INVALID``), long-form requirement
(``SECTION_TABLE_ID_UNEXPECTED``, the same mapping :mod:`ts.section` uses
for ``require_long_syntax``), CRC integrity over ``raw_bytes``
(``SECTION_CRC_MISSING`` / ``SECTION_CRC_INVALID`` — the table layer
enforces the CRC-mandatory profile a generic PSISection cannot assume; a
corrupted section is rejected before any structure interpretation, the
observation surface the #9 PMT_INVALID_CRC ruling builds on), public-header
room (``SECTION_LONG_HEADER_TRUNCATED``), metadata consistency
(``section_number <= last_section_number`` else ``TABLE_VERSION_MISMATCH``),
then loop arithmetic (``PAT_PROGRAM_ENTRY_TRUNCATED``). Entry reserved bits
are preserved verbatim inside ``PSISection.raw_bytes``; the §5 model has no
field for them, so non-canonical values are not re-exposed (§7 "可保留原始值").

Multi-section aggregation (§6/§7): ``parse_pat_sections`` identifies the
same-version set by transport_stream_id + version_number +
current_next_indicator + last_section_number (§7); mixing sets raises
``TABLE_VERSION_MISMATCH``, declared-but-absent section numbers raise
``TABLE_SECTION_MISSING``, and the aggregate keeps every section's identity
fields so callers can audit completeness.

Error codes owned here (SPEC-103 §9, module-owned per contract §7 归属约定;
all raised as ``InvalidSectionError``):
``PAT_TABLE_ID_INVALID``, ``PAT_PROGRAM_ENTRY_TRUNCATED``,
``PAT_PID_INVALID``, ``PAT_PMTPID_INVALID``, ``PAT_PROGRAM_NUMBER_INVALID``,
``PAT_PMT_PROGRAM_MISMATCH``, ``TABLE_VERSION_MISMATCH``,
``TABLE_SECTION_MISSING``, ``TABLE_SECTION_TOO_LARGE``. The ``TABLE_*``
codes are the table-family share between PAT and PMT, and the association
codes are shared with :mod:`ts.tables.table_validation` (which reports
``PAT_*``/``PMT_*`` findings as ValidationIssue diagnostics); both module
sets are owned here to keep the import graph acyclic (``pmt`` /
``table_validation`` import from this module). ``PMT_PID_INVALID`` is owned
by :mod:`ts.tables.pmt`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ts.crc import mpeg2_crc32, verify_mpeg2_crc32
from ts.errors import InvalidSectionError
from ts.section import (
    CRC_FIELD_SIZE,
    LONG_PUBLIC_HEADER_SIZE,
    SECTION_CRC_INVALID,
    SECTION_CRC_MISSING,
    SECTION_HEADER_SIZE,
    SECTION_LONG_HEADER_TRUNCATED,
    SECTION_TABLE_ID_UNEXPECTED,
    CrcPolicy,
    PSISection,
    SectionPolicy,
)

# --- SPEC-103 §9 error codes owned by this module ---

PAT_TABLE_ID_INVALID = "PAT_TABLE_ID_INVALID"
PAT_PROGRAM_ENTRY_TRUNCATED = "PAT_PROGRAM_ENTRY_TRUNCATED"
PAT_PID_INVALID = "PAT_PID_INVALID"
PAT_PMTPID_INVALID = "PAT_PMTPID_INVALID"
PAT_PROGRAM_NUMBER_INVALID = "PAT_PROGRAM_NUMBER_INVALID"
PAT_PMT_PROGRAM_MISMATCH = "PAT_PMT_PROGRAM_MISMATCH"
TABLE_VERSION_MISMATCH = "TABLE_VERSION_MISMATCH"
TABLE_SECTION_MISSING = "TABLE_SECTION_MISSING"
TABLE_SECTION_TOO_LARGE = "TABLE_SECTION_TOO_LARGE"

# --- SPEC-103 §3 constants ---

#: PAT table_id (H.222.0 2.4.4.2).
PAT_TABLE_ID = 0x00
#: PID the PAT is fixed on (§3/§8.1).
PAT_PID = 0x0000
#: 4 bytes per program-loop entry (16-bit number + reserved/PID word).
PAT_PROGRAM_ENTRY_SIZE = 4
#: Single-section table maximum (§3: ``section_length`` never exceeds 1021).
PAT_SECTION_LENGTH_MAX = 1021

#: Section profile for PAT sections (§3: long form, CRC mandatory).
PAT_SECTION_POLICY = SectionPolicy(
    max_section_length=PAT_SECTION_LENGTH_MAX,
    crc_policy=CrcPolicy.REQUIRED,
    require_long_syntax=True,
    expected_table_id=PAT_TABLE_ID,
)

_U16_MAX = 0xFFFF
_U8_MAX = 0xFF
_PID_MAX = 0x1FFF
_VERSION_MAX = 0x1F


def _check_int(value: object, name: str, lo: int, hi: int) -> int:
    """Programming-error guard: strict int in range, bool excluded."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")
    return value


@dataclass(frozen=True)
class PATProgram:
    """One PAT program-loop entry (§5).

    ``program_number=0`` marks the network_PID entry: ``program_map_pid``
    then carries the NIT PID and the entry is not a PMT pointer (§3; the
    API keeps the field name ``program_map_pid`` per the §5 model, so this
    special meaning is documented here).
    """

    program_number: int
    program_map_pid: int

    def __post_init__(self) -> None:
        _check_int(self.program_number, "program_number", 0, _U16_MAX)
        _check_int(self.program_map_pid, "program_map_pid", 0, _PID_MAX)


@dataclass(frozen=True)
class PATSection:
    """One PAT section as a semantic object (§5).

    ``programs`` accepts any sequence of :class:`PATProgram` and is stored
    as a tuple. ``section_number`` must not exceed ``last_section_number``
    (§7) on a constructed object — a wire section violating it is rejected
    by :func:`parse_pat` with ``TABLE_VERSION_MISMATCH`` before this guard
    is ever reached.
    """

    transport_stream_id: int
    version_number: int
    current_next_indicator: bool
    section_number: int
    last_section_number: int
    programs: tuple[PATProgram, ...]

    def __post_init__(self) -> None:
        _check_int(self.transport_stream_id, "transport_stream_id", 0, _U16_MAX)
        _check_int(self.version_number, "version_number", 0, _VERSION_MAX)
        if not isinstance(self.current_next_indicator, bool):
            raise TypeError(
                "current_next_indicator must be bool, got "
                f"{type(self.current_next_indicator).__name__}"
            )
        _check_int(self.section_number, "section_number", 0, _U8_MAX)
        _check_int(self.last_section_number, "last_section_number", 0, _U8_MAX)
        if self.section_number > self.last_section_number:
            raise ValueError(
                f"section_number {self.section_number} must not exceed "
                f"last_section_number {self.last_section_number} (§7)"
            )
        programs = tuple(self.programs)
        for program in programs:
            if not isinstance(program, PATProgram):
                raise TypeError(
                    "programs entries must be PATProgram, got "
                    f"{type(program).__name__}"
                )
        object.__setattr__(self, "programs", programs)


class PATBuilder:
    """Encode a :class:`PATSection` into one framed PSI section (§6).

    Single-section builder per the MVP (§7): the section is emitted with
    the identity fields the table object carries; declaring
    ``last_section_number > section_number`` encodes faithfully and the
    multi-section completeness becomes :func:`parse_pat_sections`' audit
    concern. Reserved bits encode to the standard constants; the CRC field
    is computed over the exact wire bytes (§7: SPEC-102 framing + SPEC-101
    CRC).
    """

    def build(self, table: PATSection) -> PSISection:
        if not isinstance(table, PATSection):
            raise TypeError(
                f"table must be PATSection, got {type(table).__name__}"
            )

        loop = bytearray()
        for program in table.programs:
            loop += program.program_number.to_bytes(2, "big")
            # 3 reserved bits ('111') + 13-bit program_map_PID.
            loop += ((0b111 << 13) | program.program_map_pid).to_bytes(2, "big")

        # §7 accumulation: 5 public-header bytes + loop + 4-byte CRC field
        # == 9 + 4 * program_entry_count.
        section_length = (
            LONG_PUBLIC_HEADER_SIZE + len(loop) + CRC_FIELD_SIZE
        )
        if section_length > PAT_SECTION_LENGTH_MAX:
            raise InvalidSectionError(
                f"{TABLE_SECTION_TOO_LARGE}: encoded PAT section_length "
                f"{section_length} exceeds the single-section table maximum "
                f"{PAT_SECTION_LENGTH_MAX}; split the program loop across "
                "sections instead of relying on an implicit split"
            )

        header = bytearray()
        header.append(PAT_TABLE_ID)
        header.append(0b10_11_0000 | ((section_length >> 8) & 0x0F))
        header.append(section_length & 0xFF)
        header += table.transport_stream_id.to_bytes(2, "big")
        # Reserved '11' + version_number + current_next_indicator.
        header.append(
            (0b11 << 6)
            | (table.version_number << 1)
            | (1 if table.current_next_indicator else 0)
        )
        header.append(table.section_number)
        header.append(table.last_section_number)
        header += loop

        crc = mpeg2_crc32(header)
        raw = header + crc.to_bytes(CRC_FIELD_SIZE, "big")
        return PSISection(
            table_id=PAT_TABLE_ID,
            section_syntax_indicator=True,
            private_indicator=False,
            section_length=section_length,
            raw_bytes=raw,
            table_id_extension=table.transport_stream_id,
            version_number=table.version_number,
            current_next_indicator=table.current_next_indicator,
            section_number=table.section_number,
            last_section_number=table.last_section_number,
            crc_value=crc,
        )


def parse_pat(section: PSISection) -> PATSection:
    """Parse one PAT section (§6).

    Every field is re-derived from ``section.raw_bytes``; the CRC gate runs
    before any table interpretation, so a corrupted section reports the CRC
    problem rather than a bogus structural one (ruling #9 corruption
    semantics). See the module docstring for the full gate order.

    Raises:
        TypeError: ``section`` is not a PSISection.
        InvalidSectionError: on any §9-listed or reused section-layer
            problem (codes prefix the message, ``"CODE: ..."``).
    """
    if not isinstance(section, PSISection):
        raise TypeError(
            f"section must be PSISection, got {type(section).__name__}"
        )
    if section.table_id != PAT_TABLE_ID:
        raise InvalidSectionError(
            f"{PAT_TABLE_ID_INVALID}: PAT requires table_id "
            f"{PAT_TABLE_ID:#04x}, got {section.table_id:#04x}"
        )
    if not section.section_syntax_indicator:
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: PAT requires long syntax "
            "(section_syntax_indicator=1) but the section declares short form"
        )

    raw = section.raw_bytes

    # CRC integrity before interpretation (§3 CRC mandatory; ruling #9).
    if section.section_length < CRC_FIELD_SIZE:
        raise InvalidSectionError(
            f"{SECTION_CRC_MISSING}: PAT CRC is mandatory but "
            f"section_length {section.section_length} has no room for the "
            f"{CRC_FIELD_SIZE}-byte CRC field"
        )
    if not verify_mpeg2_crc32(raw):
        raise InvalidSectionError(
            f"{SECTION_CRC_INVALID}: CRC remainder over the PAT section is "
            "non-zero (wire CRC field "
            f"{int.from_bytes(raw[-CRC_FIELD_SIZE:], 'big'):#010x})"
        )

    if section.section_length < LONG_PUBLIC_HEADER_SIZE:
        raise InvalidSectionError(
            f"{SECTION_LONG_HEADER_TRUNCATED}: PAT long-form public header "
            f"needs {LONG_PUBLIC_HEADER_SIZE} bytes after the 3-byte "
            f"header, section_length is {section.section_length}"
        )

    transport_stream_id = int.from_bytes(raw[3:5], "big")
    version_number = (raw[5] >> 1) & 0x1F
    current_next = bool(raw[5] & 0x01)
    section_number = raw[6]
    last_section_number = raw[7]
    if section_number > last_section_number:
        # §7 identity rule; rides the same-version-set family (the section
        # metadata contradicts the table span it declares).
        raise InvalidSectionError(
            f"{TABLE_VERSION_MISMATCH}: section_number {section_number} "
            f"exceeds last_section_number {last_section_number}"
        )

    loop_start = SECTION_HEADER_SIZE + LONG_PUBLIC_HEADER_SIZE
    loop_end = SECTION_HEADER_SIZE + section.section_length - CRC_FIELD_SIZE
    region = loop_end - loop_start
    if region < 0 or region % PAT_PROGRAM_ENTRY_SIZE != 0:
        raise InvalidSectionError(
            f"{PAT_PROGRAM_ENTRY_TRUNCATED}: PAT program loop region is "
            f"{region} byte(s) after the public header and the "
            f"{CRC_FIELD_SIZE}-byte CRC; entries are "
            f"{PAT_PROGRAM_ENTRY_SIZE} bytes each, so the region must be a "
            "non-negative multiple of that size"
        )

    programs: list[PATProgram] = []
    for offset in range(loop_start, loop_end, PAT_PROGRAM_ENTRY_SIZE):
        program_number = int.from_bytes(raw[offset : offset + 2], "big")
        program_map_pid = (
            (raw[offset + 2] & 0x1F) << 8
        ) | raw[offset + 3]
        programs.append(PATProgram(program_number, program_map_pid))

    return PATSection(
        transport_stream_id=transport_stream_id,
        version_number=version_number,
        current_next_indicator=current_next,
        section_number=section_number,
        last_section_number=last_section_number,
        programs=tuple(programs),
    )


@dataclass(frozen=True)
class PATTable:
    """Aggregated PAT version set (§6 logical aggregate).

    ``sections`` is ordered by ``section_number``; ``programs`` concatenates
    every section's entries in that order. The identity fields
    (``transport_stream_id`` / ``version_number`` /
    ``current_next_indicator`` / ``last_section_number``) are retained on
    both the aggregate and every member section so callers can audit
    completeness and detect version mixing (§6).
    """

    transport_stream_id: int
    version_number: int
    current_next_indicator: bool
    last_section_number: int
    sections: tuple[PATSection, ...]
    programs: tuple[PATProgram, ...]

    def __post_init__(self) -> None:
        sections = tuple(self.sections)
        for section in sections:
            if not isinstance(section, PATSection):
                raise TypeError(
                    "sections entries must be PATSection, got "
                    f"{type(section).__name__}"
                )
        object.__setattr__(self, "sections", sections)
        programs = tuple(self.programs)
        for program in programs:
            if not isinstance(program, PATProgram):
                raise TypeError(
                    "programs entries must be PATProgram, got "
                    f"{type(program).__name__}"
                )
        object.__setattr__(self, "programs", programs)


def parse_pat_sections(sections: Sequence[PSISection]) -> PATTable:
    """Aggregate one PAT version set from its sections (§6/§7).

    Each member goes through the full :func:`parse_pat` gates first. The
    same-version set is identified by ``transport_stream_id`` +
    ``version_number`` + ``current_next_indicator`` +
    ``last_section_number`` (§7); any disagreement raises
    ``TABLE_VERSION_MISMATCH`` — sections of different versions are never
    merged into one table. ``section_number`` values must cover
    ``0..last_section_number`` exactly: absent numbers raise
    ``TABLE_SECTION_MISSING``.

    Section order in the input is irrelevant; the aggregate is ordered by
    ``section_number``. Duplicate ``section_number`` values and an empty
    input list are caller bookkeeping errors (ValueError), not wire
    problems.

    Raises:
        TypeError: a member is not a PSISection.
        ValueError: empty input or duplicate ``section_number``.
        InvalidSectionError: any per-section parse problem,
            ``TABLE_VERSION_MISMATCH`` on identity disagreement, or
            ``TABLE_SECTION_MISSING`` on incomplete coverage.
    """
    parsed: dict[int, PATSection] = {}
    for item in sections:
        if not isinstance(item, PSISection):
            raise TypeError(
                f"sections entries must be PSISection, got {type(item).__name__}"
            )
        table = parse_pat(item)
        if table.section_number in parsed:
            raise ValueError(
                f"duplicate section_number {table.section_number} in the "
                "input; each section of one version set must appear at "
                "most once (retransmissions are the caller's dedup)"
            )
        parsed[table.section_number] = table
    if not parsed:
        raise ValueError("at least one PSISection is required to aggregate a PAT")

    ordered = [parsed[number] for number in sorted(parsed)]
    reference = ordered[0]
    identity = (
        reference.transport_stream_id,
        reference.version_number,
        reference.current_next_indicator,
        reference.last_section_number,
    )
    for member in ordered[1:]:
        member_identity = (
            member.transport_stream_id,
            member.version_number,
            member.current_next_indicator,
            member.last_section_number,
        )
        if member_identity != identity:
            raise InvalidSectionError(
                f"{TABLE_VERSION_MISMATCH}: section_number "
                f"{member.section_number} belongs to a different version "
                f"set (tsid/version/current_next/last = {member_identity}) "
                f"than the reference section {reference.section_number} "
                f"({identity}); sections of different versions are never "
                "merged (§7)"
            )

    expected = range(0, reference.last_section_number + 1)
    missing = [number for number in expected if number not in parsed]
    if missing:
        raise InvalidSectionError(
            f"{TABLE_SECTION_MISSING}: the PAT declares "
            f"last_section_number {reference.last_section_number} but "
            f"section_number(s) {missing} are absent"
        )

    programs = tuple(program for member in ordered for program in member.programs)
    return PATTable(
        transport_stream_id=reference.transport_stream_id,
        version_number=reference.version_number,
        current_next_indicator=reference.current_next_indicator,
        last_section_number=reference.last_section_number,
        sections=tuple(ordered),
        programs=programs,
    )
