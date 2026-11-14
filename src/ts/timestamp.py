"""SPEC-105 — PTS/DTS 33-bit timestamp encoding (5-byte PES field form).

Layout (ITU-T H.222.0 PES header, 5 bytes = 33 value bits + 4-bit prefix
+ three '1' marker bits):

- byte 0: 4-bit prefix | value bits 32..30 | marker ``1``
- byte 1: value bits 29..22
- byte 2: value bits 21..15 | marker ``1``
- byte 3: value bits 14..7
- byte 4: value bits 6..0 | marker ``1``

Standard prefixes (SPEC-105 §6: callers may not pass an arbitrary nibble):

- ``0b0010`` — PTS only
- ``0b0011`` — PTS in a PTS+DTS pair
- ``0b0001`` — DTS (DTS always uses the DTS prefix, SPEC-105 §4)

Error codes owned here (SPEC-105 §9): ``PTS_INPUT_LENGTH_INVALID``,
``PTS_MARKER_BIT_INVALID``, ``PTS_PREFIX_INVALID``,
``PTS_VALUE_OUT_OF_RANGE``. They map to
:class:`ts.errors.InvalidTimestampError` (contract §7).

PTS/DTS vs PCR time relationships are upper-layer Analyzer/Diagnosis
concerns (SPEC-105 §4); this module only encodes and converts values.
"""

from __future__ import annotations

from ts.errors import InvalidTimestampError

# --- SPEC-105 §9 error codes owned by this module (module-owned constants
# per contract §7 归属约定; errors.py carries no business codes). ---

PTS_INPUT_LENGTH_INVALID = "PTS_INPUT_LENGTH_INVALID"
PTS_MARKER_BIT_INVALID = "PTS_MARKER_BIT_INVALID"
PTS_PREFIX_INVALID = "PTS_PREFIX_INVALID"
PTS_VALUE_OUT_OF_RANGE = "PTS_VALUE_OUT_OF_RANGE"

#: PTS/DTS wrap modulus: 2^33 (33-bit, 90 kHz ticks).
PTS_MODULUS: int = 1 << 33

#: Highest legal 33-bit PTS/DTS value.
PTS_MAX: int = (1 << 33) - 1

#: Prefix '0010': PTS encoded alone.
PTS_PREFIX_ONLY: int = 0b0010

#: Prefix '0011': PTS encoded together with a DTS.
PTS_PREFIX_PTS_DTS: int = 0b0011

#: Prefix '0001': DTS.
PTS_PREFIX_DTS: int = 0b0001

#: The only prefixes the standard defines for PTS/DTS fields.
STANDARD_PREFIXES: frozenset[int] = frozenset(
    {PTS_PREFIX_ONLY, PTS_PREFIX_PTS_DTS, PTS_PREFIX_DTS}
)


def encode_pts(value_90khz: int, *, prefix: int = PTS_PREFIX_ONLY) -> bytes:
    """Encode a 33-bit 90 kHz PTS/DTS value into its 5-byte field.

    ``value_90khz`` must be an integer in ``0..2**33-1`` (rejecting ``-1``
    and ``2**33`` outright — no silent masking, SPEC-105 §7). ``prefix``
    must be one of the three standard prefixes.
    """
    if not isinstance(value_90khz, int) or isinstance(value_90khz, bool):
        raise TypeError(
            f"value_90khz must be int, got {type(value_90khz).__name__}"
        )
    if not 0 <= value_90khz <= PTS_MAX:
        raise InvalidTimestampError(
            f"{PTS_VALUE_OUT_OF_RANGE}: PTS/DTS must be in 0..{PTS_MAX}, "
            f"got {value_90khz}"
        )
    if prefix not in STANDARD_PREFIXES:
        raise InvalidTimestampError(
            f"{PTS_PREFIX_INVALID}: prefix must be one of the standard "
            f"PTS/DTS prefixes {sorted(STANDARD_PREFIXES)}, got "
            f"{prefix:#06b}"
        )
    return bytes(
        (
            (prefix << 4) | ((value_90khz >> 30) << 1) | 1,
            (value_90khz >> 22) & 0xFF,
            ((value_90khz >> 15) & 0x7F) << 1 | 1,
            (value_90khz >> 7) & 0xFF,
            (value_90khz & 0x7F) << 1 | 1,
        )
    )


def decode_pts(data: bytes, *, expected_prefix: int | None = None) -> int:
    """Decode a 5-byte PTS/DTS field back to its 33-bit 90 kHz value.

    All three marker bits must be ``1`` and the prefix must match
    ``expected_prefix`` when given (``expected_prefix`` itself must be a
    standard prefix). Violations raise :class:`ts.errors.InvalidTimestampError`.
    """
    if len(data) != 5:
        raise InvalidTimestampError(
            f"{PTS_INPUT_LENGTH_INVALID}: decode_pts expects exactly 5 "
            f"bytes, got {len(data)}"
        )
    if expected_prefix is not None:
        if expected_prefix not in STANDARD_PREFIXES:
            raise InvalidTimestampError(
                f"{PTS_PREFIX_INVALID}: expected_prefix must be a standard "
                f"PTS/DTS prefix, got {expected_prefix:#06b}"
            )
        if data[0] >> 4 != expected_prefix:
            raise InvalidTimestampError(
                f"{PTS_PREFIX_INVALID}: expected prefix "
                f"{expected_prefix:#06b}, got {data[0] >> 4:#06b}"
            )
    if not (data[0] & 1 and data[2] & 1 and data[4] & 1):
        raise InvalidTimestampError(
            f"{PTS_MARKER_BIT_INVALID}: PTS/DTS marker bits must all be 1 "
            f"(0x{data[0]:02X} 0x{data[2]:02X} 0x{data[4]:02X})"
        )
    return (
        ((data[0] >> 1) & 0b111) << 30
        | data[1] << 22
        | (data[2] >> 1) << 15
        | data[3] << 7
        | data[4] >> 1
    )
