"""SPEC-102 — PSI Section framing: parse / serialize / size (ticket #29).

Generic MPEG-2 PSI Section model (SPEC-102 §3/§4, ITU-T H.222.0): the
3-byte section header, long-form public header fields, a configurable CRC
policy integrating the SPEC-101 CRC-32/MPEG-2, and strict/lenient dual-mode
parsing. Table-specific semantics (PAT/PMT loops) belong to SPEC-103; this
module only owns framing.

Design invariants (contract §2/§7, SPEC-102 §4/§6):

- ``section_length`` counts the bytes AFTER the 3-byte header; the total
  wire size is ``3 + section_length`` (§3). The 12-bit wire range
  (0..4095) is never treated as a legal-length licence: every parse gates
  the value against ``SectionPolicy.max_section_length`` (§3/§6.1).
- ``raw_bytes`` keeps the complete section verbatim (CRC field included
  when present). Derived fields never disagree with ``raw_bytes`` — the
  frozen-dataclass constructor re-parses the header and rejects any
  field/raw mismatch. Serialization is the §4 "immutable raw section
  echo" mode: byte-exact output after policy/CRC gates, never a rewrite
  (no implicit fixes).
- CRC policy is decided by the table profile, never inferred from the
  SSI bit alone (§3: DVB TOT-style short tables may still carry CRC).
  CRC presence/validity errors are distinguishable (§7):
  ``SECTION_CRC_MISSING`` (field has no room) vs ``SECTION_CRC_INVALID``
  (remainder != 0, verified with :func:`ts.crc.verify_mpeg2_crc32`).
- Dual parse modes (contract §7: "解析不可信数据的公共 API 应允许调用方
  选择 strict 模式或取得 ParseIssue；默认 strict"): ``parse_section(...,
  strict=True)`` (default) raises :class:`ts.errors.InvalidSectionError`
  carrying a SPEC-102 §8 error code on every problem; ``strict=False``
  records recoverable findings on ``PSISection.parse_issues`` (never
  silently swallowed) and still raises for unrepresentable framing
  (truncated header/body, policy-violating length) — mirroring the #28
  TSPacket precedent. A strict success always yields
  ``parse_issues == ()``.
- Reserved bits are preserved verbatim; ``PSISection.validate()`` reports
  non-canonical values as ``SECTION_RESERVED_BITS`` warnings (§6.1 step 7
  "可记录 ValidationIssue"). No §8 error code exists for them, so strict
  parsing does not reject on reserved bits.

Ruling #11 freeze (error codes): the unified truncated-header code is
``SECTION_HEADER_TRUNCATED``; strict ``parse_section`` rejects extra bytes
with ``SECTION_TRAILING_BYTES`` (multi-section slicing is the assembler's
job via :func:`section_total_size`); an unknown ``table_id`` yields
``SECTION_TABLE_ID_UNEXPECTED`` with no fallback to a default policy.

Error codes owned here (SPEC-102 §8 table + ruling #11, module-owned per
contract §7 归属约定; all map to ``InvalidSectionError``):
``SECTION_HEADER_TRUNCATED``, ``SECTION_LENGTH_EXCEEDS_POLICY``,
``SECTION_BODY_TRUNCATED``, ``SECTION_TRAILING_BYTES``,
``SECTION_LONG_HEADER_TRUNCATED``, ``SECTION_CRC_MISSING``,
``SECTION_CRC_INVALID``, ``SECTION_TABLE_ID_UNEXPECTED``. The assembly-side
codes (``SECTION_POINTER_FIELD_INVALID``, ``SECTION_CONTINUATION_WITHOUT_START``,
``SECTION_DISCARDED_ON_DISCONTINUITY``, ``SECTION_TRUNCATED_AT_EOF``) live in
:mod:`ts.section_assembler`. ``SECTION_RESERVED_BITS`` is a ValidationIssue
code only (never raised).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ts.crc import verify_mpeg2_crc32
from ts.errors import InvalidSectionError
from ts.issues import ParseIssue, ValidationIssue

# --- SPEC-102 §8 error codes owned by this module (framing side) ---

SECTION_HEADER_TRUNCATED = "SECTION_HEADER_TRUNCATED"
SECTION_LENGTH_EXCEEDS_POLICY = "SECTION_LENGTH_EXCEEDS_POLICY"
SECTION_BODY_TRUNCATED = "SECTION_BODY_TRUNCATED"
SECTION_TRAILING_BYTES = "SECTION_TRAILING_BYTES"
SECTION_LONG_HEADER_TRUNCATED = "SECTION_LONG_HEADER_TRUNCATED"
SECTION_CRC_MISSING = "SECTION_CRC_MISSING"
SECTION_CRC_INVALID = "SECTION_CRC_INVALID"
SECTION_TABLE_ID_UNEXPECTED = "SECTION_TABLE_ID_UNEXPECTED"

#: ValidationIssue-only code (§6.1 step 7; never an error code).
SECTION_RESERVED_BITS = "SECTION_RESERVED_BITS"

# --- SPEC-102 §3 constants ---

#: 3-byte section header preceding the section body.
SECTION_HEADER_SIZE = 3
#: 5 long-form public-header bytes (extension .. last_section_number).
LONG_PUBLIC_HEADER_SIZE = 5
#: CRC field width (32-bit big-endian, §7).
CRC_FIELD_SIZE = 4
#: 12-bit wire range of the section_length field (§7).
SECTION_LENGTH_WIRE_MAX = 0x0FFF

_TABLE_ID_MAX = 0xFF
_EXT_MAX = 0xFFFF
_VERSION_MAX = 0x1F
_U8_MAX = 0xFF
_CRC_MAX = 0xFFFFFFFF

_BYTES_LIKE = (bytes, bytearray, memoryview)


def _coerce_bytes(data: bytes, *, param: str) -> bytes:
    """Accept ``bytes``/``bytearray``/``memoryview``, reject everything else."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, _BYTES_LIKE):
        return bytes(data)
    raise TypeError(
        f"{param} must be a bytes-like object (bytes, bytearray, memoryview), "
        f"got {type(data).__name__}"
    )


def _check_int(value: object, name: str, lo: int, hi: int) -> int:
    """Programming-error guard: strict int in range, bool excluded.

    Out-of-range field values on a constructed object are programming
    errors (ValueError) — wire-side problems carry §8 codes instead.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be int, got {type(value).__name__}"
        )
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")
    return value


def _check_optional_int(value: object, name: str, lo: int, hi: int) -> None:
    """Same guard for ``int | None`` fields."""
    if value is not None:
        _check_int(value, name, lo, hi)


def _check_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be bool, got {type(value).__name__}")


def _check_optional_bool(value: object, name: str) -> None:
    if value is not None:
        _check_bool(value, name)


class CrcPolicy(str, Enum):
    """CRC presence policy of a table profile (SPEC-102 §4).

    ``REQUIRED`` — the section must carry a CRC-32 field (PAT/PMT).
    ``ABSENT`` — no CRC field is interpreted.
    ``OPTIONAL`` — presence is detected; absence is never an error.
    """

    REQUIRED = "required"
    ABSENT = "absent"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class SectionPolicy:
    """Table profile governing parsing/serialization (SPEC-102 §4).

    ``max_section_length`` limits the 12-bit wire value for this table
    (PAT/PMT use their standard table maxima — SPEC-103 passes 1021 — so
    the generic wire maximum is never a blanket licence, §3).
    ``require_long_syntax``/``expected_table_id`` are profile expectations;
    a mismatch is a policy rejection (SECTION_TABLE_ID_UNEXPECTED family).

    Range violations are programming errors (ValueError/TypeError) —
    a policy that could never be satisfied is a bug, not wire data.
    """

    max_section_length: int
    crc_policy: CrcPolicy
    require_long_syntax: bool | None = None
    expected_table_id: int | None = None

    def __post_init__(self) -> None:
        _check_int(self.max_section_length, "max_section_length", 0, SECTION_LENGTH_WIRE_MAX)
        if not isinstance(self.crc_policy, CrcPolicy):
            raise TypeError(
                f"crc_policy must be CrcPolicy, got {type(self.crc_policy).__name__}"
            )
        _check_optional_bool(self.require_long_syntax, "require_long_syntax")
        _check_optional_int(self.expected_table_id, "expected_table_id", 0, _TABLE_ID_MAX)


@dataclass(frozen=True)
class PSISection:
    """One parsed (or constructed) PSI section, fields as SPEC-102 §4.

    ``raw_bytes`` is the byte-level authority: it holds the complete
    section (CRC field included when present) and the constructor verifies
    every header-derived field against it, so parsed and hand-built
    objects share one consistency invariant. ``section_length`` counts the
    bytes after the 3-byte header (``len(raw_bytes) - 3``).

    ``parse_issues`` is the non-strict parse surface (contract §7):
    findings recorded while parsing leniently
    (``parse_section(..., strict=False)``) instead of being swallowed.
    A strict-mode parse success always yields ``parse_issues == ()``.
    (Field addition per the approved #28 TSPacket precedent; the §4 field
    set itself is unchanged.)

    Long-form fields stay ``None`` for short-form sections and for a
    long-form section whose public header was incomplete (lenient parse
    recorded ``SECTION_LONG_HEADER_TRUNCATED``).
    """

    table_id: int
    section_syntax_indicator: bool
    private_indicator: bool
    section_length: int
    raw_bytes: bytes
    table_id_extension: int | None = None
    version_number: int | None = None
    current_next_indicator: bool | None = None
    section_number: int | None = None
    last_section_number: int | None = None
    crc_value: int | None = None
    parse_issues: tuple[ParseIssue, ...] = field(default=())

    def __post_init__(self) -> None:
        """Reject field-range and field/raw inconsistencies at construction.

        §4: "解析后的派生字段不得与原始 bytes 不一致" — the header fields are
        re-parsed from ``raw_bytes`` and must match exactly, and the CRC
        value must agree with the wire CRC field when both exist. These are
        programming-error guards (TypeError/ValueError); wire-side problems
        carry §8 codes at parse time instead. Reserved bits are NOT checked
        here (preserved verbatim; ``validate()`` reports them).
        """
        _check_int(self.table_id, "table_id", 0, _TABLE_ID_MAX)
        _check_bool(self.section_syntax_indicator, "section_syntax_indicator")
        _check_bool(self.private_indicator, "private_indicator")
        _check_int(
            self.section_length, "section_length", 0, SECTION_LENGTH_WIRE_MAX
        )
        raw = _coerce_bytes(self.raw_bytes, param="raw_bytes")
        object.__setattr__(self, "raw_bytes", raw)
        _check_optional_int(self.table_id_extension, "table_id_extension", 0, _EXT_MAX)
        _check_optional_int(self.version_number, "version_number", 0, _VERSION_MAX)
        _check_optional_bool(
            self.current_next_indicator, "current_next_indicator"
        )
        _check_optional_int(self.section_number, "section_number", 0, _U8_MAX)
        _check_optional_int(
            self.last_section_number, "last_section_number", 0, _U8_MAX
        )
        _check_optional_int(self.crc_value, "crc_value", 0, _CRC_MAX)
        for issue in self.parse_issues:
            if not isinstance(issue, ParseIssue):
                raise TypeError(
                    f"parse_issues entries must be ParseIssue, got "
                    f"{type(issue).__name__}"
                )

        # Short form cannot carry long-form public fields (§3).
        if not self.section_syntax_indicator:
            for name in (
                "table_id_extension",
                "version_number",
                "current_next_indicator",
                "section_number",
                "last_section_number",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{name} is a long-form public field and must be None "
                        "when section_syntax_indicator is False"
                    )

        # Header fields must re-parse identically from raw_bytes (§4).
        if len(raw) < SECTION_HEADER_SIZE:
            raise ValueError(
                f"raw_bytes must be at least {SECTION_HEADER_SIZE} bytes, "
                f"got {len(raw)}"
            )
        if raw[0] != self.table_id:
            raise ValueError(
                f"table_id {self.table_id:#04x} disagrees with raw_bytes "
                f"header byte {raw[0]:#04x}"
            )
        wire_ssi = bool(raw[1] & 0x80)
        wire_private = bool(raw[1] & 0x40)
        wire_length = ((raw[1] & 0x0F) << 8) | raw[2]
        if wire_ssi != self.section_syntax_indicator:
            raise ValueError(
                "section_syntax_indicator disagrees with raw_bytes header"
            )
        if wire_private != self.private_indicator:
            raise ValueError(
                "private_indicator disagrees with raw_bytes header"
            )
        if wire_length != self.section_length:
            raise ValueError(
                f"section_length {self.section_length} disagrees with "
                f"raw_bytes header value {wire_length}"
            )
        if len(raw) != SECTION_HEADER_SIZE + self.section_length:
            raise ValueError(
                f"raw_bytes length {len(raw)} must equal "
                f"3 + section_length = "
                f"{SECTION_HEADER_SIZE + self.section_length}"
            )

        # CRC value must agree with the wire CRC field (when there is one).
        if self.crc_value is not None:
            if self.section_length < CRC_FIELD_SIZE:
                raise ValueError(
                    f"crc_value is set but section_length "
                    f"{self.section_length} has no room for the "
                    f"{CRC_FIELD_SIZE}-byte CRC field"
                )
            wire_crc = int.from_bytes(
                raw[-CRC_FIELD_SIZE:], "big"
            )
            if wire_crc != self.crc_value:
                raise ValueError(
                    f"crc_value {self.crc_value:#010x} disagrees with the "
                    f"raw_bytes CRC field {wire_crc:#010x}"
                )

    def validate(self) -> list[ValidationIssue]:
        """Reserved-bit usage findings (contract §6 issue shape, §6.1 step 7).

        Structural rules run at parse/construction time; the semantic layer
        only reports non-canonical reserved bits, which are preserved
        verbatim rather than rewritten.
        """
        issues: list[ValidationIssue] = []
        raw = self.raw_bytes
        if (raw[1] >> 4) & 0b11 != 0b11:
            issues.append(
                ValidationIssue(
                    code=SECTION_RESERVED_BITS,
                    message="section header reserved bits (byte 1 bits 5-4) "
                    f"are {(raw[1] >> 4) & 0b11:02b}, expected 11; the "
                    "original bits are preserved",
                    severity="warning",
                    field="raw_bytes",
                )
            )
        if self.section_syntax_indicator and self.section_length >= LONG_PUBLIC_HEADER_SIZE:
            version_byte = raw[5]
            if (version_byte >> 6) & 0b11 != 0b11:
                issues.append(
                    ValidationIssue(
                        code=SECTION_RESERVED_BITS,
                        message="long-form version byte reserved bits (bits "
                        f"7-6) are {(version_byte >> 6) & 0b11:02b}, "
                        "expected 11; the original bits are preserved",
                        severity="warning",
                        field="version_number",
                    )
                )
        return issues


def _policy_gate(section_header: bytes, policy: SectionPolicy) -> None:
    """Profile expectations: table_id and long-syntax requirement (§5).

    Both mismatches are profile rejections; the §8 table names the
    table_id case, and the long-syntax requirement rides the same
    policy-mismatch family (documented mapping, no invented code).
    """
    table_id = section_header[0]
    if policy.expected_table_id is not None and table_id != policy.expected_table_id:
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: table_id {table_id:#04x} does "
            f"not match policy expected_table_id "
            f"{policy.expected_table_id:#04x}"
        )
    ssi = bool(section_header[1] & 0x80)
    if policy.require_long_syntax is True and not ssi:
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: policy requires long syntax "
            "(section_syntax_indicator=1) but the section header declares "
            "short form"
        )


def section_total_size(first_three_bytes: bytes, *, max_section_length: int) -> int:
    """Total section size ``3 + section_length`` from a header (SPEC-102 §5).

    The assembler's slicing primitive: feeds the first three wire bytes and
    the table-profile maximum, returns the complete section length.

    Raises:
        TypeError: ``first_three_bytes`` is not bytes-like.
        InvalidSectionError: fewer than 3 bytes
            (``SECTION_HEADER_TRUNCATED``) or the wire ``section_length``
            exceeds ``max_section_length``
            (``SECTION_LENGTH_EXCEEDS_POLICY``).
    """
    header = _coerce_bytes(first_three_bytes, param="first_three_bytes")
    if len(header) < SECTION_HEADER_SIZE:
        raise InvalidSectionError(
            f"{SECTION_HEADER_TRUNCATED}: need {SECTION_HEADER_SIZE} header "
            f"bytes to read the section length, got {len(header)}"
        )
    wire_length = ((header[1] & 0x0F) << 8) | header[2]
    if wire_length > max_section_length:
        raise InvalidSectionError(
            f"{SECTION_LENGTH_EXCEEDS_POLICY}: section_length {wire_length} "
            f"exceeds the policy maximum {max_section_length}"
        )
    return SECTION_HEADER_SIZE + wire_length


def parse_section(
    data: bytes, policy: SectionPolicy, *, strict: bool = True
) -> PSISection:
    """Parse exactly one complete section (SPEC-102 §5/§6.1).

    ``data`` must be exactly one section: extra bytes beyond
    ``3 + section_length`` are rejected with ``SECTION_TRAILING_BYTES``
    (ruling #11; multi-section buffers are sliced by the assembler with
    :func:`section_total_size`). Failure order follows §6.1: header
    truncated, policy gates (table_id / long syntax), length vs policy,
    body truncated, trailing bytes, long-form public header, CRC.

    Args:
        data: bytes-like input holding exactly one section.
        policy: the table profile (:class:`SectionPolicy`).
        strict: ``True`` (default) raises :class:`InvalidSectionError`
            carrying a §8 code on every problem. ``False`` records
            recoverable findings (trailing bytes, policy mismatch,
            incomplete long header, CRC missing/invalid) on
            ``PSISection.parse_issues`` and returns the section; framing
            that cannot yield a coherent object (short header, body
            truncated, length beyond policy) still raises — no object is
            fabricated from truncated wire data.

    Returns:
        The parsed :class:`PSISection` (``parse_issues == ()`` when strict).

    Raises:
        TypeError: ``data`` is not bytes-like.
        InvalidSectionError: any §6.1 problem (all modes for unrepresentable
            framing; strict-only for recoverable findings).
    """
    if not isinstance(policy, SectionPolicy):
        raise TypeError(
            f"policy must be SectionPolicy, got {type(policy).__name__}"
        )
    data = _coerce_bytes(data, param="data")

    issues: list[ParseIssue] = []

    def _recoverable(code: str, message: str, offset: int | None) -> None:
        if strict:
            raise InvalidSectionError(f"{code}: {message}")
        issues.append(ParseIssue(code=code, message=message, offset=offset))

    # §6.1 step 1: at least the 3-byte header.
    if len(data) < SECTION_HEADER_SIZE:
        raise InvalidSectionError(
            f"{SECTION_HEADER_TRUNCATED}: need {SECTION_HEADER_SIZE} header "
            f"bytes, got {len(data)}"
        )
    table_id = data[0]
    ssi = bool(data[1] & 0x80)
    private = bool(data[1] & 0x40)
    wire_length = ((data[1] & 0x0F) << 8) | data[2]

    # Profile expectations before any length trust is extended.
    if (
        policy.expected_table_id is not None
        and table_id != policy.expected_table_id
    ):
        _recoverable(
            SECTION_TABLE_ID_UNEXPECTED,
            f"table_id {table_id:#04x} does not match policy "
            f"expected_table_id {policy.expected_table_id:#04x}",
            0,
        )
    if policy.require_long_syntax is True and not ssi:
        _recoverable(
            SECTION_TABLE_ID_UNEXPECTED,
            "policy requires long syntax (section_syntax_indicator=1) but "
            "the section header declares short form",
            0,
        )

    # §6.1 step 2: the wire value is gated against the table profile.
    if wire_length > policy.max_section_length:
        raise InvalidSectionError(
            f"{SECTION_LENGTH_EXCEEDS_POLICY}: section_length "
            f"{wire_length} exceeds the policy maximum "
            f"{policy.max_section_length}"
        )

    # §6.1 step 3/4: exact framing — complete body, no extra bytes.
    total = SECTION_HEADER_SIZE + wire_length
    if len(data) < total:
        raise InvalidSectionError(
            f"{SECTION_BODY_TRUNCATED}: section needs {total} bytes "
            f"(3 + section_length {wire_length}), got {len(data)}"
        )
    if len(data) > total:
        _recoverable(
            SECTION_TRAILING_BYTES,
            f"input has {len(data)} bytes but the section is exactly "
            f"{total} (3 + section_length {wire_length}); "
            f"{len(data) - total} extra byte(s) rejected",
            total,
        )
    raw = data[:total]

    # §6.1 step 5: long-form public header completeness (fields stay None
    # when leniently recovering an incomplete one).
    table_id_extension: int | None = None
    version_number: int | None = None
    current_next: bool | None = None
    section_number: int | None = None
    last_section_number: int | None = None
    if ssi:
        if wire_length < LONG_PUBLIC_HEADER_SIZE:
            _recoverable(
                SECTION_LONG_HEADER_TRUNCATED,
                f"long-form section needs {LONG_PUBLIC_HEADER_SIZE} "
                f"public-header bytes after the 3-byte header, "
                f"section_length is {wire_length}",
                SECTION_HEADER_SIZE,
            )
        else:
            table_id_extension = (raw[3] << 8) | raw[4]
            version_number = (raw[5] >> 1) & 0b11111
            current_next = bool(raw[5] & 0x01)
            section_number = raw[6]
            last_section_number = raw[7]

    # §6.1 step 6: CRC policy (§7) — presence and validity are distinct.
    crc_value: int | None = None
    if policy.crc_policy is CrcPolicy.REQUIRED:
        if wire_length < CRC_FIELD_SIZE:
            _recoverable(
                SECTION_CRC_MISSING,
                f"crc_policy is REQUIRED but section_length "
                f"{wire_length} has no room for the "
                f"{CRC_FIELD_SIZE}-byte CRC field",
                None,
            )
        else:
            crc_value = int.from_bytes(raw[-CRC_FIELD_SIZE:], "big")
            if not verify_mpeg2_crc32(raw):
                _recoverable(
                    SECTION_CRC_INVALID,
                    f"CRC remainder over the {total}-byte section is "
                    "non-zero (wire CRC field "
                    f"{crc_value:#010x})",
                    total - CRC_FIELD_SIZE,
                )
    elif policy.crc_policy is CrcPolicy.OPTIONAL:
        # Detection rule (deterministic, §6.1 step 6 "OPTIONAL 依据表
        # profile 明确处理"): if a CRC-sized tail verifies to remainder 0
        # the section carries its CRC; otherwise it is treated as absent —
        # never an error.
        if wire_length >= CRC_FIELD_SIZE and verify_mpeg2_crc32(raw):
            crc_value = int.from_bytes(raw[-CRC_FIELD_SIZE:], "big")

    return PSISection(
        table_id=table_id,
        section_syntax_indicator=ssi,
        private_indicator=private,
        section_length=wire_length,
        raw_bytes=raw,
        table_id_extension=table_id_extension,
        version_number=version_number,
        current_next_indicator=current_next,
        section_number=section_number,
        last_section_number=last_section_number,
        crc_value=crc_value,
        parse_issues=tuple(issues),
    )


def serialize_section(section: PSISection, policy: SectionPolicy) -> bytes:
    """Serialize a section — the §4 "immutable raw section echo" mode.

    ``PSISection`` construction already guarantees field/raw coherence and
    ``raw_bytes`` keeps the complete section (CRC field included when the
    section has one), so serialization re-checks the policy gates and CRC
    validity, then echoes ``raw_bytes`` byte-exact. No field is rewritten
    and no CRC is recomputed (no implicit fixes).

    Args:
        section: the section to serialize.
        policy: the table profile to serialize under.

    Returns:
        The section bytes (identical to ``section.raw_bytes``).

    Raises:
        TypeError: ``section`` is not a PSISection.
        InvalidSectionError: policy mismatch
            (``SECTION_TABLE_ID_UNEXPECTED``), length beyond the profile
            (``SECTION_LENGTH_EXCEEDS_POLICY``), or a REQUIRED-policy CRC
            that is missing (``SECTION_CRC_MISSING``) or invalid
            (``SECTION_CRC_INVALID``).
    """
    if not isinstance(section, PSISection):
        raise TypeError(
            f"section must be PSISection, got {type(section).__name__}"
        )
    if not isinstance(policy, SectionPolicy):
        raise TypeError(
            f"policy must be SectionPolicy, got {type(policy).__name__}"
        )

    if (
        policy.expected_table_id is not None
        and section.table_id != policy.expected_table_id
    ):
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: table_id "
            f"{section.table_id:#04x} does not match policy "
            f"expected_table_id {policy.expected_table_id:#04x}"
        )
    if policy.require_long_syntax is True and not section.section_syntax_indicator:
        raise InvalidSectionError(
            f"{SECTION_TABLE_ID_UNEXPECTED}: policy requires long syntax "
            "(section_syntax_indicator=1) but the section is short form"
        )
    if section.section_length > policy.max_section_length:
        raise InvalidSectionError(
            f"{SECTION_LENGTH_EXCEEDS_POLICY}: section_length "
            f"{section.section_length} exceeds the policy maximum "
            f"{policy.max_section_length}"
        )

    if policy.crc_policy is CrcPolicy.REQUIRED:
        if section.section_length < CRC_FIELD_SIZE:
            raise InvalidSectionError(
                f"{SECTION_CRC_MISSING}: crc_policy is REQUIRED but "
                f"section_length {section.section_length} has no room for "
                f"the {CRC_FIELD_SIZE}-byte CRC field"
            )
        if not verify_mpeg2_crc32(section.raw_bytes):
            raise InvalidSectionError(
                f"{SECTION_CRC_INVALID}: CRC remainder over the section is "
                "non-zero (wire CRC field "
                f"{section.crc_value:#010x})"
            )
    elif policy.crc_policy is CrcPolicy.OPTIONAL:
        # Same detection rule as parsing: an object asserting a CRC value
        # must have it verified; an object without one serializes as-is.
        if (
            section.crc_value is not None
            and not verify_mpeg2_crc32(section.raw_bytes)
        ):
            raise InvalidSectionError(
                f"{SECTION_CRC_INVALID}: section carries crc_value "
                f"{section.crc_value:#010x} but the remainder over "
                "raw_bytes is non-zero"
            )

    return section.raw_bytes
