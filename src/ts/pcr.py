"""SPEC-105 — PCR 42-bit value model and 6-byte H.222.0 encoding.

PCR value ownership (ruling #11, TS-CORE-INTEGRATION-CONTRACT §9): the PCR
**value** (this module) is the single authoritative PCR data type; the 6-byte
encoding algorithm exists only here and is never duplicated by SPEC-100 /
SPEC-106 / SPEC-107. PCR insertion timing is SPEC-107's concern and the
adaptation-field construction is SPEC-106's; neither may re-encode PCR bytes.

Bit layout (ITU-T H.222.0, 6 bytes / 48 bits = 33 + 6 reserved + 9):

- bytes 0..3: ``base >> 1`` as a 32-bit big-endian integer (base bits 32..1)
- byte 4 bit 7: base bit 0; bits 6..1: reserved (must be ``111111``);
  bit 0: extension bit 8
- byte 5: extension bits 7..0

Combined tick count: ``base * 300 + extension`` 27 MHz ticks; wrap modulus
``(1 << 33) * 300``. All arithmetic is pure integer — floats never touch
protocol encoding (contract §2.4).

Error codes owned here (SPEC-105 §9): ``PCR_INPUT_LENGTH_INVALID``,
``PCR_RESERVED_BITS_INVALID``, ``PCR_EXTENSION_OUT_OF_RANGE``,
``PCR_BASE_OUT_OF_RANGE``. They map to
:class:`ts.errors.InvalidTimestampError` (contract §7).
"""

from __future__ import annotations

from dataclasses import dataclass

from ts.errors import InvalidTimestampError

# --- SPEC-105 §9 error codes owned by this module (module-owned constants
# per contract §7 归属约定; errors.py carries no business codes). ---

PCR_INPUT_LENGTH_INVALID = "PCR_INPUT_LENGTH_INVALID"
PCR_RESERVED_BITS_INVALID = "PCR_RESERVED_BITS_INVALID"
PCR_EXTENSION_OUT_OF_RANGE = "PCR_EXTENSION_OUT_OF_RANGE"
PCR_BASE_OUT_OF_RANGE = "PCR_BASE_OUT_OF_RANGE"

# CLOCK_NEGATIVE_TICKS is a SPEC-105 §9 clock-family code; it lives here
# (not in clock.py) because ts.clock imports ts.pcr and a reverse import
# would create a cycle. ts.clock re-uses this constant for its own
# negative-tick guards.
CLOCK_NEGATIVE_TICKS = "CLOCK_NEGATIVE_TICKS"

#: Wrap modulus of the combined 27 MHz counter: 2^33 * 300.
PCR_MODULUS: int = (1 << 33) * 300

#: Highest legal 33-bit program_clock_reference_base value.
PCR_BASE_MAX: int = (1 << 33) - 1

#: Highest legal 9-bit program_clock_reference_extension value (0..299).
PCR_EXTENSION_MAX: int = 299

#: Reserved 6 bits between base and extension must read ``111111``.
_PCR_RESERVED_PATTERN: int = 0b111111


@dataclass(frozen=True)
class PCR:
    """One 42-significant-bit Program Clock Reference value.

    ``base`` counts at 90 kHz (33 bits, ``0..2**33-1``); ``extension``
    counts 27 MHz sub-ticks within one 90 kHz period (``0..299``). Inputs
    are validated, never silently masked or taken modulo: extension 300..
    511 and out-of-range bases raise :class:`ts.errors.InvalidTimestampError`
    (SPEC-105 §7 "不能自动对 300 取模").
    """

    base: int
    extension: int

    @property
    def ticks_27mhz(self) -> int:
        """Combined 27 MHz tick count: ``base * 300 + extension``."""
        return self.base * 300 + self.extension

    def __post_init__(self) -> None:
        """Reject out-of-range fields; never mask or auto-modulo inputs.

        Negative or > 2**33-1 bases raise ``PCR_BASE_OUT_OF_RANGE``;
        extensions outside 0..299 raise ``PCR_EXTENSION_OUT_OF_RANGE``
        (SPEC-105 §7/§9). Non-integer fields are programming errors and
        raise ``TypeError``.
        """
        if not isinstance(self.base, int) or isinstance(self.base, bool):
            raise TypeError(
                f"PCR.base must be int, got {type(self.base).__name__}"
            )
        if not isinstance(self.extension, int) or isinstance(
            self.extension, bool
        ):
            raise TypeError(
                f"PCR.extension must be int, got {type(self.extension).__name__}"
            )
        if not 0 <= self.base <= PCR_BASE_MAX:
            raise InvalidTimestampError(
                f"{PCR_BASE_OUT_OF_RANGE}: base must be in 0..{PCR_BASE_MAX}, "
                f"got {self.base}"
            )
        if not 0 <= self.extension <= PCR_EXTENSION_MAX:
            raise InvalidTimestampError(
                f"{PCR_EXTENSION_OUT_OF_RANGE}: extension must be in "
                f"0..{PCR_EXTENSION_MAX}, got {self.extension} (300..511 is "
                "illegal; never auto-modulo to 300)"
            )


def encode_pcr(pcr: PCR) -> bytes:
    """Encode a :class:`PCR` into its 6-byte H.222.0 field.

    The reserved 6 bits are always written as ``111111`` (SPEC-105 §7).
    """
    base = pcr.base
    extension = pcr.extension
    head = (base >> 1).to_bytes(4, "big")
    byte4 = ((base & 1) << 7) | (_PCR_RESERVED_PATTERN << 1) | (extension >> 8)
    return head + bytes((byte4, extension & 0xFF))


def decode_pcr(data: bytes) -> PCR:
    """Decode a 6-byte PCR field into a :class:`PCR` value."""
    if len(data) != 6:
        raise InvalidTimestampError(
            f"{PCR_INPUT_LENGTH_INVALID}: decode_pcr expects exactly 6 "
            f"bytes, got {len(data)}"
        )
    base = (
        (data[0] << 25)
        | (data[1] << 17)
        | (data[2] << 9)
        | (data[3] << 1)
        | (data[4] >> 7)
    )
    reserved = (data[4] >> 1) & 0x3F
    if reserved != _PCR_RESERVED_PATTERN:
        raise InvalidTimestampError(
            f"{PCR_RESERVED_BITS_INVALID}: reserved bits must be 111111, "
            f"got 0b{reserved:06b}"
        )
    extension = ((data[4] & 1) << 8) | data[5]
    return PCR(base=base, extension=extension)


def pcr_to_27mhz_ticks(pcr: PCR) -> int:
    """Convert a :class:`PCR` to its combined 27 MHz tick count.

    Exact integer identity ``base * 300 + extension`` (contract §4).
    """
    return pcr.base * 300 + pcr.extension


def pcr_from_27mhz_ticks(ticks: int) -> PCR:
    """Map absolute 27 MHz ticks onto a :class:`PCR` value.

    This is the dedicated conversion for absolute media tick counts: the
    input may exceed one wrap period and is taken modulo ``PCR_MODULUS``
    (``2**33 * 300``) at the encode boundary (SPEC-105 §7). Negative ticks
    raise ``CLOCK_NEGATIVE_TICKS`` — Python's ``%`` would otherwise
    silently wrap them onto huge positive values (contract §2.5 no
    implicit fixes).
    """
    if not isinstance(ticks, int) or isinstance(ticks, bool):
        raise TypeError(f"ticks must be int, got {type(ticks).__name__}")
    if ticks < 0:
        raise InvalidTimestampError(
            f"{CLOCK_NEGATIVE_TICKS}: 27 MHz ticks must be non-negative, "
            f"got {ticks}"
        )
    mapped = ticks % PCR_MODULUS
    return PCR(base=mapped // 300, extension=mapped % 300)
