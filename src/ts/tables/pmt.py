"""SPEC-103 — PMT (Program Map Table): model / builder / parser.

PMT semantics on top of the frozen SPEC-102 framing (§4, ITU-T H.222.0
2.4.4.8): ``table_id=0x02``, long form, CRC mandatory, reached through a PAT
``program_map_PID``. ``table_id_extension`` carries ``program_number``;
after the 5 public-header bytes come PCR_PID (3 reserved bits + 13 bits),
``program_info_length`` (4 reserved bits + 12 bits), the program-level
descriptor bytes, then the ES loop (per entry: 1-byte ``stream_type``, 2
reserved+PID bytes, 2 reserved+length bytes, descriptor bytes) and the
4-byte CRC field. The MVP builder may emit empty descriptor loops; the
parser preserves descriptor bytes verbatim without interpreting them (§4).

A PMT cannot exist for ``program_number=0`` (§5: that number is the PAT's
network_PID slot) — the :class:`PMTSection` constructor rejects it as a
programming error, and :func:`parse_pmt` rejects a wire PMT claiming it
with ``PAT_PMT_PROGRAM_MISMATCH`` (the association-mismatch family: such a
section can never match a PAT entry).

Encoding (§7, ruling #11): ``section_length`` accumulates from named parts
— 5 public-header bytes + 4 fixed bytes (PCR_PID + program_info_length) +
program descriptor bytes + Σ(5 + ES descriptor bytes) + the 4-byte CRC
field — which equals the spec formula ``13 + program_descriptors_length +
Σ(5 + es_descriptors_length)``. Reserved bits encode to the standard
constants (``0b111`` PID prefix, ``0b1111`` length prefix). A single-section
encode beyond the table maximum (``section_length > 1021``) raises
``TABLE_SECTION_TOO_LARGE`` — explicit failure, never a silent split.

Parsing (§6): ``parse_pmt`` re-derives every field from ``raw_bytes`` (the
byte authority). Gate order: table_id (``PMT_TABLE_ID_INVALID``), long-form
requirement (``SECTION_TABLE_ID_UNEXPECTED``), CRC integrity
(``SECTION_CRC_MISSING`` / ``SECTION_CRC_INVALID`` — integrity before
interpretation, the observation surface the #9 PMT_INVALID_CRC ruling
builds on), public-header room, fixed-part room
(``PMT_FIXED_HEADER_TRUNCATED``), metadata consistency
(``section_number <= last_section_number`` else ``TABLE_VERSION_MISMATCH``),
``program_number != 0`` (``PAT_PMT_PROGRAM_MISMATCH``), then
``PMT_PROGRAM_INFO_LENGTH_INVALID`` / ``PMT_ES_LOOP_TRUNCATED`` /
``PMT_ES_INFO_LENGTH_INVALID`` bounds. Every slice is preceded by a bounds
gate, so malformed lengths can never over-read (REQ-TS-103-005). Reserved
bits on PID/length fields are preserved verbatim inside
``PSISection.raw_bytes`` and not re-exposed by the §5 model (§7 "可保留原始值").

Error codes owned here (SPEC-103 §9, module-owned per contract §7 归属约定;
all raised as ``InvalidSectionError``):
``PMT_TABLE_ID_INVALID``, ``PMT_FIXED_HEADER_TRUNCATED``,
``PMT_PROGRAM_INFO_LENGTH_INVALID``, ``PMT_ES_LOOP_TRUNCATED``,
``PMT_ES_INFO_LENGTH_INVALID``, ``PMT_PID_INVALID`` (the last one is also
the ValidationIssue code :mod:`ts.tables.table_validation` reports for
PID-policy findings). ``PAT_*``, ``TABLE_*`` and
``PAT_PMT_PROGRAM_MISMATCH`` codes are imported from :mod:`ts.tables.pat`
(the table-family owner; importing keeps the graph acyclic).
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
from ts.tables.pat import (
    PAT_PMT_PROGRAM_MISMATCH,
    TABLE_SECTION_MISSING,
    TABLE_SECTION_TOO_LARGE,
    TABLE_VERSION_MISMATCH,
)

# --- SPEC-103 §9 error codes owned by this module ---

PMT_TABLE_ID_INVALID = "PMT_TABLE_ID_INVALID"
PMT_FIXED_HEADER_TRUNCATED = "PMT_FIXED_HEADER_TRUNCATED"
PMT_PROGRAM_INFO_LENGTH_INVALID = "PMT_PROGRAM_INFO_LENGTH_INVALID"
PMT_ES_LOOP_TRUNCATED = "PMT_ES_LOOP_TRUNCATED"
PMT_ES_INFO_LENGTH_INVALID = "PMT_ES_INFO_LENGTH_INVALID"
PMT_PID_INVALID = "PMT_PID_INVALID"

# --- SPEC-103 §4 constants ---

#: PMT table_id (H.222.0 2.4.4.8).
PMT_TABLE_ID = 0x02
#: Fixed bytes after the public header: PCR_PID(2) + program_info_length(2).
PMT_FIXED_PART_SIZE = 4
#: 5 fixed bytes per ES entry: stream_type + PID word + info-length word.
PMT_ES_ENTRY_PREFIX_SIZE = 5
#: Single-section table maximum (§4: ``section_length`` never exceeds 1021).
PMT_SECTION_LENGTH_MAX = 1021

#: Section profile for PMT sections (§4: long form, CRC mandatory).
PMT_SECTION_POLICY = SectionPolicy(
    max_section_length=PMT_SECTION_LENGTH_MAX,
    crc_policy=CrcPolicy.REQUIRED,
    require_long_syntax=True,
    expected_table_id=PMT_TABLE_ID,
)

_U16_MAX = 0xFFFF
_U8_MAX = 0xFF
_PID_MAX = 0x1FFF
_VERSION_MAX = 0x1F

_BYTES_LIKE = (bytes, bytearray, memoryview)


def _check_int(value: object, name: str, lo: int, hi: int) -> int:
    """Programming-error guard: strict int in range, bool excluded.

    Same contract as the per-module guard in :mod:`ts.section` /
    :mod:`ts.tables.pat` (each module owns its private helpers, mirroring
    the upstream precedent).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")
    return value


def _coerce_bytes(value: object, name: str) -> bytes:
    """Accept ``bytes``/``bytearray``/``memoryview``, reject everything else."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, _BYTES_LIKE):
        return bytes(value)
    raise TypeError(f"{name} must be bytes-like, got {type(value).__name__}")


@dataclass(frozen=True)
class ElementaryStream:
    """One PMT ES-loop entry (§5).

    ``descriptors`` accepts any bytes-like object and is stored as
    ``bytes``; the parser preserves descriptor bytes verbatim (§4) without
    interpreting them.
    """

    stream_type: int
    elementary_pid: int
    descriptors: bytes = b""

    def __post_init__(self) -> None:
        _check_int(self.stream_type, "stream_type", 0, _U8_MAX)
        _check_int(self.elementary_pid, "elementary_pid", 0, _PID_MAX)
        object.__setattr__(self, "descriptors", _coerce_bytes(self.descriptors, "descriptors"))


@dataclass(frozen=True)
class PMTSection:
    """One PMT section as a semantic object (§5).

    ``program_number`` must be non-zero (§5 "禁止对 program_number=0 创建
    PMT": program 0 is the PAT's network_PID slot). ``program_descriptors``
    and every stream's ``descriptors`` accept bytes-like objects. Wire
    sections violating ``section_number <= last_section_number`` are
    rejected by :func:`parse_pmt` with ``TABLE_VERSION_MISMATCH`` before
    this guard is ever reached.
    """

    program_number: int
    version_number: int
    current_next_indicator: bool
    section_number: int
    last_section_number: int
    pcr_pid: int
    program_descriptors: bytes
    streams: tuple[ElementaryStream, ...]

    def __post_init__(self) -> None:
        _check_int(self.program_number, "program_number", 0, _U16_MAX)
        if self.program_number == 0:
            raise ValueError(
                "program_number must be non-zero: program 0 is the PAT's "
                "network_PID (NIT) slot and no PMT may be created for it (§5)"
            )
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
        _check_int(self.pcr_pid, "pcr_pid", 0, _PID_MAX)
        object.__setattr__(
            self,
            "program_descriptors",
            _coerce_bytes(self.program_descriptors, "program_descriptors"),
        )
        streams = tuple(self.streams)
        for stream in streams:
            if not isinstance(stream, ElementaryStream):
                raise TypeError(
                    "streams entries must be ElementaryStream, got "
                    f"{type(stream).__name__}"
                )
        object.__setattr__(self, "streams", streams)


class PMTBuilder:
    """Encode a :class:`PMTSection` into one framed PSI section (§6).

    Single-section builder per the MVP (§7); descriptor loops are encoded
    exactly as carried (empty loops are the MVP default, §12), reserved
    bits encode to the standard constants, and the CRC field is computed
    over the exact wire bytes (§7: SPEC-102 framing + SPEC-101 CRC).
    """

    def build(self, table: PMTSection) -> PSISection:
        """Encode ``table`` into one CRC-complete PSI section (§7).

        Args:
            table: The :class:`PMTSection` to encode; descriptor loops are
                encoded exactly as carried (empty loops are the MVP
                default, §12) and reserved bits encode to the standard
                constants.

        Returns:
            The framed :class:`PSISection` (public header + PCR_PID /
            program_info_length + program descriptors + ES loop + CRC
            field over the exact wire bytes).

        Raises:
            TypeError: ``table`` is not a :class:`PMTSection`.
            InvalidSectionError: the encoded section_length exceeds
                ``PMT_SECTION_LENGTH_MAX`` (split the ES loop across
                sections instead of relying on an implicit split).
        """
        if not isinstance(table, PMTSection):
            raise TypeError(
                f"table must be PMTSection, got {type(table).__name__}"
            )

        es_loop = bytearray()
        for stream in table.streams:
            es_loop.append(stream.stream_type)
            # 3 reserved bits ('111') + 13-bit elementary_PID.
            es_loop += ((0b111 << 13) | stream.elementary_pid).to_bytes(2, "big")
            # 4 reserved bits ('1111') + 12-bit ES_info_length.
            es_loop += ((0b1111 << 12) | len(stream.descriptors)).to_bytes(2, "big")
            es_loop += stream.descriptors

        # §7 accumulation: 5 public-header bytes + 4 fixed bytes
        # (PCR_PID + program_info_length) + program descriptors + ES loop
        # + 4-byte CRC field == 13 + Σ(5 + es_descriptors).
        section_length = (
            LONG_PUBLIC_HEADER_SIZE
            + PMT_FIXED_PART_SIZE
            + len(table.program_descriptors)
            + len(es_loop)
            + CRC_FIELD_SIZE
        )
        if section_length > PMT_SECTION_LENGTH_MAX:
            raise InvalidSectionError(
                f"{TABLE_SECTION_TOO_LARGE}: encoded PMT section_length "
                f"{section_length} exceeds the single-section table maximum "
                f"{PMT_SECTION_LENGTH_MAX}; split the ES loop across "
                "sections instead of relying on an implicit split"
            )

        header = bytearray()
        header.append(PMT_TABLE_ID)
        header.append(0b10_11_0000 | ((section_length >> 8) & 0x0F))
        header.append(section_length & 0xFF)
        header += table.program_number.to_bytes(2, "big")
        # Reserved '11' + version_number + current_next_indicator.
        header.append(
            (0b11 << 6)
            | (table.version_number << 1)
            | (1 if table.current_next_indicator else 0)
        )
        header.append(table.section_number)
        header.append(table.last_section_number)
        # 3 reserved bits ('111') + 13-bit PCR_PID.
        header += ((0b111 << 13) | table.pcr_pid).to_bytes(2, "big")
        # 4 reserved bits ('1111') + 12-bit program_info_length.
        header += ((0b1111 << 12) | len(table.program_descriptors)).to_bytes(2, "big")
        header += table.program_descriptors
        header += es_loop

        crc = mpeg2_crc32(header)
        raw = header + crc.to_bytes(CRC_FIELD_SIZE, "big")
        return PSISection(
            table_id=PMT_TABLE_ID,
            section_syntax_indicator=True,
            private_indicator=False,
            section_length=section_length,
            raw_bytes=raw,
            table_id_extension=table.program_number,
            version_number=table.version_number,
            current_next_indicator=table.current_next_indicator,
            section_number=table.section_number,
            last_section_number=table.last_section_number,
            crc_value=crc,
        )


def parse_pmt(section: PSISection) -> PMTSection:
    """Parse one PMT section (§6).

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
    if section.table_id != PMT_TABLE_ID:
        raise InvalidSectionError(
            f"{PMT_TABLE_ID_INVALID}: PMT requires table_id "
            f"{PMT_TABLE_ID:#04x}, got {section.table_id:#04x}"
        )
    if not section.section_syntax_indicator:
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: PMT requires long syntax "
            "(section_syntax_indicator=1) but the section declares short form"
        )

    raw = section.raw_bytes

    # CRC integrity before interpretation (§4 CRC mandatory; ruling #9).
    if section.section_length < CRC_FIELD_SIZE:
        raise InvalidSectionError(
            f"{SECTION_CRC_MISSING}: PMT CRC is mandatory but "
            f"section_length {section.section_length} has no room for the "
            f"{CRC_FIELD_SIZE}-byte CRC field"
        )
    if not verify_mpeg2_crc32(raw):
        raise InvalidSectionError(
            f"{SECTION_CRC_INVALID}: CRC remainder over the PMT section is "
            "non-zero (wire CRC field "
            f"{int.from_bytes(raw[-CRC_FIELD_SIZE:], 'big'):#010x})"
        )

    if section.section_length < LONG_PUBLIC_HEADER_SIZE:
        raise InvalidSectionError(
            f"{SECTION_LONG_HEADER_TRUNCATED}: PMT long-form public header "
            f"needs {LONG_PUBLIC_HEADER_SIZE} bytes after the 3-byte "
            f"header, section_length is {section.section_length}"
        )
    if section.section_length < (
        LONG_PUBLIC_HEADER_SIZE + PMT_FIXED_PART_SIZE + CRC_FIELD_SIZE
    ):
        raise InvalidSectionError(
            f"{PMT_FIXED_HEADER_TRUNCATED}: PMT needs "
            f"{LONG_PUBLIC_HEADER_SIZE + PMT_FIXED_PART_SIZE} fixed bytes "
            f"plus the {CRC_FIELD_SIZE}-byte CRC (section_length >= "
            f"{LONG_PUBLIC_HEADER_SIZE + PMT_FIXED_PART_SIZE + CRC_FIELD_SIZE}), "
            f"got section_length {section.section_length}"
        )

    program_number = int.from_bytes(raw[3:5], "big")
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
    if program_number == 0:
        raise InvalidSectionError(
            f"{PAT_PMT_PROGRAM_MISMATCH}: wire PMT claims program_number 0, "
            "but program 0 is the PAT's network_PID (NIT) slot and no PMT "
            "can exist for it (§5)"
        )

    pcr_pid = ((raw[8] & 0x1F) << 8) | raw[9]
    program_info_length = ((raw[10] & 0x0F) << 8) | raw[11]

    body_end = SECTION_HEADER_SIZE + section.section_length
    crc_start = body_end - CRC_FIELD_SIZE
    descriptors_start = (
        SECTION_HEADER_SIZE + LONG_PUBLIC_HEADER_SIZE + PMT_FIXED_PART_SIZE
    )
    descriptors_end = descriptors_start + program_info_length
    if descriptors_end > crc_start:
        raise InvalidSectionError(
            f"{PMT_PROGRAM_INFO_LENGTH_INVALID}: program_info_length "
            f"{program_info_length} runs "
            f"{descriptors_end - crc_start} byte(s) past the CRC field "
            f"boundary (offset {crc_start})"
        )
    program_descriptors = raw[descriptors_start:descriptors_end]

    es_start = descriptors_end
    es_end = crc_start
    streams: list[ElementaryStream] = []
    position = es_start
    while position < es_end:
        remaining = es_end - position
        if remaining < PMT_ES_ENTRY_PREFIX_SIZE:
            raise InvalidSectionError(
                f"{PMT_ES_LOOP_TRUNCATED}: ES loop region ends with "
                f"{remaining} unconsumable byte(s) before offset {es_end}; "
                f"an entry needs its {PMT_ES_ENTRY_PREFIX_SIZE}-byte prefix"
            )
        stream_type = raw[position]
        elementary_pid = ((raw[position + 1] & 0x1F) << 8) | raw[position + 2]
        es_info_length = (
            (raw[position + 3] & 0x0F) << 8
        ) | raw[position + 4]
        entry_end = position + PMT_ES_ENTRY_PREFIX_SIZE + es_info_length
        if entry_end > es_end:
            raise InvalidSectionError(
                f"{PMT_ES_INFO_LENGTH_INVALID}: ES_info_length "
                f"{es_info_length} runs "
                f"{entry_end - es_end} byte(s) past the ES loop boundary "
                f"(offset {es_end})"
            )
        streams.append(
            ElementaryStream(
                stream_type=stream_type,
                elementary_pid=elementary_pid,
                descriptors=bytes(raw[position + PMT_ES_ENTRY_PREFIX_SIZE : entry_end]),
            )
        )
        position = entry_end

    return PMTSection(
        program_number=program_number,
        version_number=version_number,
        current_next_indicator=current_next,
        section_number=section_number,
        last_section_number=last_section_number,
        pcr_pid=pcr_pid,
        program_descriptors=program_descriptors,
        streams=tuple(streams),
    )


@dataclass(frozen=True)
class PMTTable:
    """Aggregated PMT version set (§6 logical aggregate).

    ``sections`` is ordered by ``section_number``; ``streams`` concatenates
    every section's ES entries in that order. ``pcr_pid`` and
    ``program_descriptors`` are program-level properties carried by the
    lowest-numbered section (H.222.0 places the program descriptors in the
    first section); they are not part of the version-set identity, so a
    cross-section disagreement is preserved verbatim rather than rejected.
    """

    program_number: int
    version_number: int
    current_next_indicator: bool
    last_section_number: int
    pcr_pid: int
    program_descriptors: bytes
    sections: tuple[PMTSection, ...]
    streams: tuple[ElementaryStream, ...]

    def __post_init__(self) -> None:
        sections = tuple(self.sections)
        for section in sections:
            if not isinstance(section, PMTSection):
                raise TypeError(
                    "sections entries must be PMTSection, got "
                    f"{type(section).__name__}"
                )
        object.__setattr__(self, "sections", sections)
        streams = tuple(self.streams)
        for stream in streams:
            if not isinstance(stream, ElementaryStream):
                raise TypeError(
                    "streams entries must be ElementaryStream, got "
                    f"{type(stream).__name__}"
                )
        object.__setattr__(self, "streams", streams)


def parse_pmt_sections(sections: Sequence[PSISection]) -> PMTTable:
    """Aggregate one PMT version set from its sections (§6/§7).

    Each member goes through the full :func:`parse_pmt` gates first. The
    same-version set is identified by ``program_number`` (the
    table_id_extension) + ``version_number`` + ``current_next_indicator`` +
    ``last_section_number`` (§7); any disagreement raises
    ``TABLE_VERSION_MISMATCH`` — sections of different versions are never
    merged into one table. ``section_number`` values must cover
    ``0..last_section_number`` exactly: absent numbers raise
    ``TABLE_SECTION_MISSING``.

    Section order in the input is irrelevant; the aggregate is ordered by
    ``section_number``, takes ``pcr_pid``/``program_descriptors`` from the
    lowest-numbered section, and concatenates the ES loops in section
    order. Duplicate ``section_number`` values and an empty input list are
    caller bookkeeping errors (ValueError), not wire problems.

    Raises:
        TypeError: a member is not a PSISection.
        ValueError: empty input or duplicate ``section_number``.
        InvalidSectionError: any per-section parse problem,
            ``TABLE_VERSION_MISMATCH`` on identity disagreement, or
            ``TABLE_SECTION_MISSING`` on incomplete coverage.
    """
    parsed: dict[int, PMTSection] = {}
    for item in sections:
        if not isinstance(item, PSISection):
            raise TypeError(
                f"sections entries must be PSISection, got {type(item).__name__}"
            )
        table = parse_pmt(item)
        if table.section_number in parsed:
            raise ValueError(
                f"duplicate section_number {table.section_number} in the "
                "input; each section of one version set must appear at "
                "most once (retransmissions are the caller's dedup)"
            )
        parsed[table.section_number] = table
    if not parsed:
        raise ValueError("at least one PSISection is required to aggregate a PMT")

    ordered = [parsed[number] for number in sorted(parsed)]
    reference = ordered[0]
    identity = (
        reference.program_number,
        reference.version_number,
        reference.current_next_indicator,
        reference.last_section_number,
    )
    for member in ordered[1:]:
        member_identity = (
            member.program_number,
            member.version_number,
            member.current_next_indicator,
            member.last_section_number,
        )
        if member_identity != identity:
            raise InvalidSectionError(
                f"{TABLE_VERSION_MISMATCH}: section_number "
                f"{member.section_number} belongs to a different version "
                f"set (program/version/current_next/last = "
                f"{member_identity}) than the reference section "
                f"{reference.section_number} ({identity}); sections of "
                "different versions are never merged (§7)"
            )

    expected = range(0, reference.last_section_number + 1)
    missing = [number for number in expected if number not in parsed]
    if missing:
        raise InvalidSectionError(
            f"{TABLE_SECTION_MISSING}: the PMT declares "
            f"last_section_number {reference.last_section_number} but "
            f"section_number(s) {missing} are absent"
        )

    streams = tuple(stream for member in ordered for stream in member.streams)
    return PMTTable(
        program_number=reference.program_number,
        version_number=reference.version_number,
        current_next_indicator=reference.current_next_indicator,
        last_section_number=reference.last_section_number,
        pcr_pid=reference.pcr_pid,
        program_descriptors=reference.program_descriptors,
        sections=tuple(ordered),
        streams=streams,
    )
