"""SPEC-105 PCR / Media Clock — unit tests (tickets #27).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-105 section):

- REQ-TS-105-001  PCR 6-byte encode/decode correct      -> test_pcr_round_trip
- REQ-TS-105-002  reserved bits / ext range validation  -> test_pcr_invalid_fields
- REQ-TS-105-003  PTS/DTS encode/decode correct         -> test_pts_encoding
- REQ-TS-105-004  integer 27 MHz / 90 kHz conversion    -> test_clock_integer_conversion
- REQ-TS-105-005  wrap / modular delta correct          -> test_clock_wrap
- REQ-TS-105-006  no wall-clock coupling                -> test_media_clock_is_pure

Golden expectations come from the independent test-vector document
``docs/test-vectors/PCR-PTS.md`` (approved with #11/#14), never recomputed
from the implementation under test. Property-style loops use a fixed seed so
failures are reproducible.
"""

from __future__ import annotations

import random

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# REQ-TS-105-001 — PCR 6-byte encode/decode (golden vectors + round trips)
# ---------------------------------------------------------------------------


class TestPcrRoundTrip:
    """REQ-TS-105-001: PCR 6-byte 编码/解码正确."""

    def test_pcr_round_trip(self) -> None:
        """Golden vectors from docs/test-vectors/PCR-PTS.md + round trips."""
        from ts.pcr import PCR, decode_pcr, encode_pcr

        # Golden vector 1: base=0, extension=0.
        pcr0 = PCR(base=0, extension=0)
        assert encode_pcr(pcr0) == bytes.fromhex("00000000" "7E00")
        assert decode_pcr(bytes.fromhex("00000000" "7E00")) == pcr0

        # Golden vector 2: base=1, extension=0.
        pcr1 = PCR(base=1, extension=0)
        assert encode_pcr(pcr1) == bytes.fromhex("00000000" "FE00")
        assert decode_pcr(bytes.fromhex("00000000" "FE00")) == pcr1

        # Golden vector 3: maximum legal field values.
        pcr_max = PCR(base=(1 << 33) - 1, extension=299)
        assert encode_pcr(pcr_max) == bytes.fromhex("FFFFFFFF" "FF2B")
        assert decode_pcr(bytes.fromhex("FFFFFFFF" "FF2B")) == pcr_max

        # Round trip over a deterministic pseudo-random sample of the space.
        rng = random.Random(0x5F105)  # fixed seed, reproducible failures
        for _ in range(200):
            base = rng.randrange(0, 1 << 33)
            ext = rng.randrange(0, 300)
            pcr = PCR(base=base, extension=ext)
            assert decode_pcr(encode_pcr(pcr)) == pcr

        # Combined 27 MHz ticks round trip.
        for _ in range(200):
            ticks = rng.randrange(0, (1 << 33) * 300)
            again = PCR(
                base=ticks // 300, extension=ticks % 300
            )
            assert again.ticks_27mhz == ticks


# ---------------------------------------------------------------------------
# REQ-TS-105-002 — reserved bits / extension range validation
# ---------------------------------------------------------------------------


class TestPcrInvalidFields:
    """REQ-TS-105-002: reserved bits 和 ext range 校验."""

    def test_pcr_invalid_fields(self) -> None:
        """Illegal PCR fields are rejected, never auto-masked (SPEC-105 §7)."""
        from ts.errors import InvalidTimestampError
        from ts.pcr import (
            PCR_BASE_OUT_OF_RANGE,
            PCR_EXTENSION_OUT_OF_RANGE,
            PCR_INPUT_LENGTH_INVALID,
            PCR_RESERVED_BITS_INVALID,
            PCR,
            decode_pcr,
        )

        # Extension 300..511 is illegal as constructor input: no auto-mod 300.
        for bad_ext in (300, 511):
            with pytest.raises(InvalidTimestampError) as exc:
                PCR(base=0, extension=bad_ext)
            assert PCR_EXTENSION_OUT_OF_RANGE in str(exc.value)

        # Extension must not be negative either.
        with pytest.raises(InvalidTimestampError) as exc:
            PCR(base=0, extension=-1)
        assert PCR_EXTENSION_OUT_OF_RANGE in str(exc.value)

        # Base beyond 33 bits and negative base are out of range.
        for bad_base in (1 << 33, (1 << 33) * 2, -1):
            with pytest.raises(InvalidTimestampError) as exc:
                PCR(base=bad_base, extension=0)
            assert PCR_BASE_OUT_OF_RANGE in str(exc.value)

        # decode: input must be exactly 6 bytes.
        for bad_input in (b"", b"\x00" * 5, b"\x00" * 7):
            with pytest.raises(InvalidTimestampError) as exc:
                decode_pcr(bad_input)
            assert PCR_INPUT_LENGTH_INVALID in str(exc.value)

        # decode: reserved bits must read 111111 — each of the six positions
        # broken individually is rejected.
        good = bytes.fromhex("00000000" "7E00")  # base=0 ext=0, reserved ok
        for bit in range(6):
            broken = bytearray(good)
            broken[4] &= ~(0x02 << bit) & 0xFF  # clear reserved bit (pos 6..1)
            assert (broken[4] >> 1) & 0x3F != 0x3F
            with pytest.raises(InvalidTimestampError) as exc:
                decode_pcr(bytes(broken))
            assert PCR_RESERVED_BITS_INVALID in str(exc.value)

        # decode: extension bits above 299 are out of range. Reserved stays
        # valid, so this isolates the extension check.
        for ext_bits, raw in ((300, (300 >> 8, 300 & 0xFF)), (511, (1, 0xFF))):
            broken = bytearray(good)
            broken[4] = (broken[4] & 0xFE) | (raw[0] & 0x01)  # ext bit 8
            broken[5] = raw[1] & 0xFF  # ext bits 7..0
            assert ((broken[4] & 1) << 8) | broken[5] == ext_bits
            with pytest.raises(InvalidTimestampError) as exc:
                decode_pcr(bytes(broken))
            assert PCR_EXTENSION_OUT_OF_RANGE in str(exc.value)

        # A non-integer field is a programming error, not a protocol error.
        with pytest.raises(TypeError):
            PCR(base=1.0, extension=0)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            PCR(base=0, extension=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# REQ-TS-105-003 — PTS/DTS 33-bit encoding (prefixes, markers, ranges)
# ---------------------------------------------------------------------------

#: Standard PTS/DTS prefixes (H.222.0): PTS-only, PTS of PTS+DTS, DTS.
PTS_ONLY_PREFIX = 0b0010
PTS_DTS_PREFIX = 0b0011
DTS_PREFIX = 0b0001


class TestPtsEncoding:
    """REQ-TS-105-003: PTS/DTS 编码/解码正确."""

    def test_pts_encoding(self) -> None:
        """Golden vectors + prefix/marker/range behaviour (SPEC-105 §4)."""
        from ts.errors import InvalidTimestampError
        from ts.timestamp import (
            PTS_INPUT_LENGTH_INVALID,
            PTS_MARKER_BIT_INVALID,
            PTS_PREFIX_INVALID,
            PTS_VALUE_OUT_OF_RANGE,
            decode_pts,
            encode_pts,
        )

        # Golden vectors (docs/test-vectors/PCR-PTS.md §2), PTS-only prefix.
        assert encode_pts(0) == bytes.fromhex("2100010001")
        assert encode_pts(1) == bytes.fromhex("2100010003")
        assert encode_pts((1 << 33) - 1) == bytes.fromhex("2FFFFFFFFF")

        assert decode_pts(bytes.fromhex("2100010001")) == 0
        assert decode_pts(bytes.fromhex("2100010003")) == 1
        assert decode_pts(bytes.fromhex("2FFFFFFFFF")) == (1 << 33) - 1

        # Round trip over a deterministic sample of the 33-bit space.
        rng = random.Random(0x5F105)
        for _ in range(200):
            value = rng.randrange(0, 1 << 33)
            assert decode_pts(encode_pts(value)) == value

        # Out-of-range encode inputs are rejected, not silently masked.
        for bad in (-1, 1 << 33, (1 << 33) + 7):
            with pytest.raises(InvalidTimestampError) as exc:
                encode_pts(bad)
            assert PTS_VALUE_OUT_OF_RANGE in str(exc.value)

        # Every standard prefix encodes and decodes.
        for prefix in (PTS_ONLY_PREFIX, PTS_DTS_PREFIX, DTS_PREFIX):
            encoded = encode_pts(123456, prefix=prefix)
            assert encoded[0] >> 4 == prefix
            assert decode_pts(encoded, expected_prefix=prefix) == 123456

        # DTS must use the DTS prefix (SPEC-105 §4).
        dts_bytes = encode_pts((1 << 33) - 1, prefix=DTS_PREFIX)
        assert dts_bytes[0] == 0x1F
        assert decode_pts(dts_bytes, expected_prefix=DTS_PREFIX) == (1 << 33) - 1

        # Non-standard prefixes are refused for encoding: callers cannot pass
        # an arbitrary nibble (SPEC-105 §6).
        for bad_prefix in (0b0000, 0b0100, 0b1111, 0b1010):
            with pytest.raises(InvalidTimestampError) as exc:
                encode_pts(0, prefix=bad_prefix)
            assert PTS_PREFIX_INVALID in str(exc.value)

        # decode: wrong expected_prefix is refused.
        pts_only = bytes.fromhex("2100010001")
        with pytest.raises(InvalidTimestampError) as exc:
            decode_pts(pts_only, expected_prefix=DTS_PREFIX)
        assert PTS_PREFIX_INVALID in str(exc.value)
        with pytest.raises(InvalidTimestampError) as exc:
            decode_pts(pts_only, expected_prefix=0b1010)
        assert PTS_PREFIX_INVALID in str(exc.value)

        # decode: every marker bit position must be 1 — flip each of the
        # three marker positions (byte 0, byte 2, byte 4 LSB) and expect
        # PTS_MARKER_BIT_INVALID.
        for marker_byte in (0, 2, 4):
            broken = bytearray(pts_only)
            broken[marker_byte] &= 0xFE
            with pytest.raises(InvalidTimestampError) as exc:
                decode_pts(bytes(broken))
            assert PTS_MARKER_BIT_INVALID in str(exc.value)

        # decode: input must be exactly 5 bytes.
        for bad_input in (b"", b"\x21\x00\x01\x00", b"\x00" * 6):
            with pytest.raises(InvalidTimestampError) as exc:
                decode_pts(bad_input)
            assert PTS_INPUT_LENGTH_INVALID in str(exc.value)


# ---------------------------------------------------------------------------
# REQ-TS-105-004 — exact integer 27 MHz / 90 kHz conversion
# ---------------------------------------------------------------------------


class TestClockIntegerConversion:
    """REQ-TS-105-004: 整数 27MHz/90kHz 换算."""

    def test_clock_integer_conversion(self) -> None:
        """Combined ticks identity + /300 rounding policies, no floats."""
        from ts.errors import InvalidTimestampError
        from ts.pcr import PCR, PCR_MODULUS, pcr_from_27mhz_ticks, pcr_to_27mhz_ticks
        from ts.clock import pts90_to_ticks27, ticks27_to_pts90

        # --- PCR <-> combined 27 MHz ticks ---
        assert pcr_to_27mhz_ticks(PCR(base=1, extension=1)) == 301
        assert pcr_to_27mhz_ticks(PCR(base=0, extension=0)) == 0
        assert pcr_from_27mhz_ticks(0) == PCR(base=0, extension=0)
        assert pcr_from_27mhz_ticks(1) == PCR(base=0, extension=1)
        assert pcr_from_27mhz_ticks(299) == PCR(base=0, extension=299)
        assert pcr_from_27mhz_ticks(300) == PCR(base=1, extension=0)

        # Encode-boundary mapping: absolute ticks beyond one wrap are taken
        # modulo 2^33 * 300 by the dedicated conversion function (§7).
        assert pcr_from_27mhz_ticks(PCR_MODULUS - 1) == PCR(
            base=(1 << 33) - 1, extension=299
        )
        assert pcr_from_27mhz_ticks(PCR_MODULUS) == PCR(base=0, extension=0)
        assert pcr_from_27mhz_ticks(2 * PCR_MODULUS + 5) == PCR(
            base=0, extension=5
        )

        # Identity over a deterministic sample.
        rng = random.Random(0x5F105)
        for _ in range(200):
            ticks = rng.randrange(0, PCR_MODULUS)
            assert pcr_to_27mhz_ticks(pcr_from_27mhz_ticks(ticks)) == ticks

        # Negative ticks are illegal for the clock-domain conversions.
        for negative in (-1, -300):
            with pytest.raises(InvalidTimestampError) as exc:
                pcr_from_27mhz_ticks(negative)
            assert "CLOCK_NEGATIVE_TICKS" in str(exc.value)

        # --- 27 MHz -> 90 kHz: exact integer division with a policy ---
        # Worked examples (hand-derived from 3000 = 300 * 10):
        assert ticks27_to_pts90(3000) == 10  # default floor, exact split
        assert ticks27_to_pts90(3000, rounding="floor") == 10
        assert ticks27_to_pts90(3000, rounding="ceil") == 10
        assert ticks27_to_pts90(3000, rounding="round") == 10

        assert ticks27_to_pts90(3001) == 10  # floor default
        assert ticks27_to_pts90(3001, rounding="floor") == 10
        assert ticks27_to_pts90(3001, rounding="ceil") == 11
        assert ticks27_to_pts90(3001, rounding="round") == 10  # rem 1

        assert ticks27_to_pts90(3149, rounding="floor") == 10  # rem 149
        assert ticks27_to_pts90(3149, rounding="ceil") == 11
        assert ticks27_to_pts90(3149, rounding="round") == 10  # rem < half

        assert ticks27_to_pts90(3150, rounding="round") == 11  # tie -> up
        assert ticks27_to_pts90(3299, rounding="round") == 11  # rem 299

        # --- 90 kHz -> 27 MHz: exact integer multiplication ---
        assert pts90_to_ticks27(10) == 3000
        assert pts90_to_ticks27(0) == 0
        assert pts90_to_ticks27((1 << 33) - 1) == ((1 << 33) - 1) * 300

        # 27 MHz -> 90 kHz -> 27 MHz stays exact for exact multiples.
        for pts in (0, 1, 999, (1 << 33) - 1):
            ticks = pts90_to_ticks27(pts)
            assert ticks27_to_pts90(ticks) == pts
            assert ticks27_to_pts90(ticks, rounding="ceil") == pts
            assert ticks27_to_pts90(ticks, rounding="round") == pts

        # Results are plain ints — floats never enter protocol conversion.
        assert type(ticks27_to_pts90(3001)) is int
        assert type(pts90_to_ticks27(10)) is int
        assert type(pcr_from_27mhz_ticks(600).ticks_27mhz) is int

        # Unsupported rounding modes are rejected (SPEC-105 §9).
        for bad_mode in ("nearest", "bankers", "", 42):
            with pytest.raises(InvalidTimestampError) as exc:
                ticks27_to_pts90(3000, rounding=bad_mode)
            assert "CLOCK_ROUNDING_MODE_UNSUPPORTED" in str(exc.value)

        # Negative tick inputs are illegal.
        with pytest.raises(InvalidTimestampError) as exc:
            ticks27_to_pts90(-1)
        assert "CLOCK_NEGATIVE_TICKS" in str(exc.value)
        with pytest.raises(InvalidTimestampError) as exc:
            pts90_to_ticks27(-1)
        assert "CLOCK_NEGATIVE_TICKS" in str(exc.value)


# ---------------------------------------------------------------------------
# REQ-TS-105-005 — wrap-around and modular delta
# ---------------------------------------------------------------------------


class TestClockWrap:
    """REQ-TS-105-005: wrap/modular delta 正确."""

    def test_clock_wrap(self) -> None:
        """Wrap vectors, [0, modulus) range, #11 half-period window."""
        from ts.clock import MediaClock, modular_delta
        from ts.errors import InvalidTimestampError
        from ts.pcr import PCR, PCR_MODULUS
        from ts.timestamp import PTS_MODULUS

        # Golden wrap vector (docs/test-vectors/PCR-PTS.md §3): 2^33-1 -> 0
        # is a forward step of exactly 1.
        assert modular_delta(0, (1 << 33) - 1, 1 << 33) == 1
        # Same vector in the combined PCR domain.
        assert modular_delta(0, PCR_MODULUS - 1, PCR_MODULUS) == 1

        # Identity and in-domain values.
        assert modular_delta(7, 7, 1 << 33) == 0
        rng = random.Random(0x5F105)
        modulus = 1 << 33
        for _ in range(200):
            a = rng.randrange(0, modulus)
            b = rng.randrange(0, modulus)
            delta = modular_delta(a, b, modulus)
            assert 0 <= delta < modulus  # value domain [0, modulus)
            assert (b + delta) % modulus == a  # forward reconstruction

        # Ruling #11: the direction-decidable window is [0, modulus/2).
        # delta just below the half period is decidable ("current ahead");
        # delta at or beyond it is not (small step back vs big step forward).
        half = modulus // 2  # 2^32
        assert modular_delta(half - 1, 0, modulus) == half - 1  # decidable
        assert modular_delta(half, 0, modulus) == half  # boundary: undecidable
        assert modular_delta(half + 1, 0, modulus) == half + 1
        # One tick back wraps to modulus-1 — indistinguishable from a giant
        # forward jump; the function reports it, judgement is the caller's.
        assert modular_delta(0, 1, modulus) == modulus - 1

        # The two natural domains share the same ~13.26 h half period:
        # (2^32 * 300) 27 MHz ticks == (2^32) 90 kHz ticks in duration,
        # cross-multiplied in integers (no float division).
        pcr_half = PCR_MODULUS // 2
        pts_half = PTS_MODULUS // 2
        assert pcr_half == pts_half * 300
        assert pcr_half * 90_000 == pts_half * 27_000_000

        # MediaClock keeps absolute counts and wraps only at the boundary.
        assert MediaClock(ticks_27mhz=PCR_MODULUS - 1).pcr() == PCR(
            base=(1 << 33) - 1, extension=299
        )
        assert MediaClock(ticks_27mhz=PCR_MODULUS).pcr() == PCR(base=0, extension=0)
        assert MediaClock(ticks_27mhz=2 * PCR_MODULUS).pcr() == PCR(base=0, extension=0)
        # The absolute count is not lost when the encoded value wraps.
        assert MediaClock(ticks_27mhz=2 * PCR_MODULUS).ticks_27mhz == 2 * PCR_MODULUS

        # PTS boundary of the same clock.
        assert MediaClock(ticks_27mhz=PTS_MODULUS * 300 - 1).pts90k() == PTS_MODULUS - 1
        assert MediaClock(ticks_27mhz=PTS_MODULUS * 300).pts90k() == 0

        # Negative ticks never enter the clock.
        with pytest.raises(InvalidTimestampError) as exc:
            MediaClock(ticks_27mhz=-1)
        assert "CLOCK_NEGATIVE_TICKS" in str(exc.value)


# ---------------------------------------------------------------------------
# REQ-TS-105-006 — no wall-clock / simulation-clock coupling
# ---------------------------------------------------------------------------


class TestMediaClockIsPure:
    """REQ-TS-105-006: 无 wall-clock 耦合."""

    def test_media_clock_is_pure(self) -> None:
        """Media-clock primitives never touch the system clock.

        Static check: no wall-clock vocabulary in the SPEC-105 module
        sources. Dynamic check: repeated evaluation of clock-derived values
        is deterministic, and results depend only on the inputs.
        """
        import inspect
        import re

        import ts.clock
        import ts.pcr
        import ts.timestamp

        sources = "\n".join(
            inspect.getsource(module)
            for module in (ts.clock, ts.pcr, ts.timestamp)
        )
        banned = [
            r"datetime",
            r"\bimport\s+time\b",
            r"\bfrom\s+time\s+import\b",
            r"\bmonotonic\b",
            r"\bperf_counter\b",
            r"\btime_ns\b",
            r"\bgmtime\b",
            r"\blocaltime\b",
            r"\bnow\(\)",
            r"\butcnow\b",
        ]
        for pattern in banned:
            assert re.search(pattern, sources) is None, (
                f"wall-clock vocabulary found in SPEC-105 sources: {pattern!r}"
            )

        # Dynamic determinism: same input -> same encoded bytes, always.
        from ts.clock import MediaClock
        from ts.pcr import decode_pcr, encode_pcr

        clock = MediaClock(ticks_27mhz=123_456_789)
        first_pcr = clock.pcr()
        for _ in range(10):
            assert clock.pcr() == first_pcr
            assert clock.pts90k() == clock.pts90k()
        assert decode_pcr(encode_pcr(first_pcr)) == first_pcr


# ---------------------------------------------------------------------------
# Shared frozen types (contract §6) + public constant pins
# ---------------------------------------------------------------------------


class TestSharedFrozenTypes:
    """issues.py is the authoritative ParseIssue/ValidationIssue definition."""

    def test_parse_and_validation_issue_contract(self) -> None:
        """Contract §6 fields/defaults/frozen semantics, verbatim."""
        import dataclasses

        from ts.issues import ParseIssue, ValidationIssue

        # Field order and defaults exactly as contract §6.
        assert [
            (f.name, f.default is dataclasses.MISSING)
            for f in dataclasses.fields(ParseIssue)
        ] == [
            ("code", True),
            ("message", True),
            ("offset", False),
            ("severity", False),
        ]
        assert [
            (f.name, f.default is dataclasses.MISSING)
            for f in dataclasses.fields(ValidationIssue)
        ] == [
            ("code", True),
            ("message", True),
            ("severity", False),
            ("field", False),
        ]
        issue = ParseIssue(code="X", message="m")
        assert issue.offset is None
        assert issue.severity == "error"
        vissue = ValidationIssue(code="Y", message="m")
        assert vissue.severity == "warning"
        assert vissue.field is None

        # Frozen: assignment must fail.
        with pytest.raises(dataclasses.FrozenInstanceError):
            issue.code = "Z"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            vissue.field = "pid"  # type: ignore[misc]

    def test_standard_prefix_constants(self) -> None:
        """The exported prefix constants equal the H.222.0 nibbles."""
        from ts.timestamp import (
            PTS_PREFIX_DTS,
            PTS_PREFIX_ONLY,
            PTS_PREFIX_PTS_DTS,
            STANDARD_PREFIXES,
        )

        assert PTS_PREFIX_ONLY == 0b0010
        assert PTS_PREFIX_PTS_DTS == 0b0011
        assert PTS_PREFIX_DTS == 0b0001
        assert STANDARD_PREFIXES == frozenset({0b0001, 0b0010, 0b0011})
