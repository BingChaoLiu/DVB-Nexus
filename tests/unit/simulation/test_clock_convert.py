"""SPEC-201 section 6 — virtual_time_ns ↔ PCR/PTS conversion tests (#39).

Traceability:

- REQ-SIM-201-006  conversions go ONLY through the explicit SPEC-105
  primitives (single authority; no re-implemented 27 MHz/90 kHz modular
  arithmetic), backed by the approved test vectors in
  ``docs/test-vectors/PCR-PTS.md`` -> TestConvertVectors, TestConvertWrap,
  TestConvertRoundTrip

Golden expectations come from the vector document and from exact rational
arithmetic computed by hand (1 s = 27 000 000 ticks27 = 90 000 ticks90;
1 tick90 = 100000/9 ns, 1 tick27 = 1000/27 ns); never recomputed via the
implementation under test. Exact-integer grids: ns multiples of 1000 map
exactly to ticks27; ticks multiples of 27 (resp. 9) map exactly back to
ns; the floor remainder is dropped deterministically (no accumulation).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

#: Exact integer anchors: 1 second of virtual time.
NS_PER_SECOND = 1_000_000_000
TICKS27_PER_SECOND = 27_000_000
TICKS90_PER_SECOND = 90_000


class TestConvertVectors:
    """Golden vectors from docs/test-vectors/PCR-PTS.md (and exact ratios)."""

    def test_epoch_maps_to_zero_pcr_and_pts(self) -> None:
        from ts.pcr import PCR

        from simulation.clock_convert import (
            virtual_ns_to_ticks27,
            virtual_to_pcr,
            virtual_to_pts90,
        )

        assert virtual_ns_to_ticks27(0) == 0
        assert virtual_to_pcr(0) == PCR(base=0, extension=0)
        assert virtual_to_pts90(0) == 0

    def test_one_second_maps_to_exact_tick_counts(self) -> None:
        from ts.pcr import PCR

        from simulation.clock_convert import (
            virtual_ns_to_ticks27,
            virtual_to_pcr,
            virtual_to_pts90,
        )

        assert virtual_ns_to_ticks27(NS_PER_SECOND) == TICKS27_PER_SECOND
        # 27 000 000 ticks27 = base 90 000, extension 0 (exact).
        assert virtual_to_pcr(NS_PER_SECOND) == PCR(base=90_000, extension=0)
        # 90 000 ticks90 = 1 s (exact).
        assert virtual_to_pts90(NS_PER_SECOND) == TICKS90_PER_SECOND

    def test_half_second_maps_to_exact_tick_counts(self) -> None:
        from ts.pcr import PCR

        from simulation.clock_convert import virtual_to_pcr, virtual_to_pts90

        half = NS_PER_SECOND // 2
        assert virtual_to_pcr(half) == PCR(base=45_000, extension=0)
        assert virtual_to_pts90(half) == 45_000

    def test_pcr_encoding_of_converted_value_matches_vector_bytes(self) -> None:
        """Cross-check against the PCR-PTS.md vector: base=1/ext=0 encodes
        to 00 00 00 00 FE 00 (SPEC-105's encoder is the single authority).
        300 ticks27 happen first at ns = ceil(300*1000/27) = 11112."""
        from ts.pcr import encode_pcr

        from simulation.clock_convert import virtual_to_pcr

        pcr = virtual_to_pcr(11_112)
        assert pcr.base == 1 and pcr.extension == 0
        assert encode_pcr(pcr) == bytes.fromhex("00000000" "FE00")

    def test_pts90_to_ns_floor_vector(self) -> None:
        """1 tick90 = 100000/9 ns → floor 11111 (exact rational, no float)."""
        from simulation.clock_convert import pts90_to_virtual_ns

        assert pts90_to_virtual_ns(1) == 11_111
        assert pts90_to_virtual_ns(9) == 100_000  # exact multiple
        assert pts90_to_virtual_ns(TICKS90_PER_SECOND) == NS_PER_SECOND

    def test_ticks27_to_ns_floor_vector(self) -> None:
        from simulation.clock_convert import ticks27_to_virtual_ns

        # 1 tick27 = 1000/27 ns → floor 37.
        assert ticks27_to_virtual_ns(1) == 37
        assert ticks27_to_virtual_ns(27) == 1_000  # exact multiple
        assert ticks27_to_virtual_ns(TICKS27_PER_SECOND) == NS_PER_SECOND


class TestConvertWrap:
    """Wrap semantics are DELEGATED to SPEC-105 (PCR-PTS.md section 3:
    combined PCR wrap modulus = 2^33 * 300 ticks27; PTS wraps at 2^33)."""

    def test_beyond_one_pts_wrap_modulo_is_applied_by_ts(self) -> None:
        """10^5 s = 9 * 10^9 ticks90; one PTS wrap is 2^33 ticks90, so the
        wrapped reading is 9e9 - 2^33 = 410065408 (hand-derived)."""
        from simulation.clock_convert import virtual_to_pts90

        ns = 100_000 * NS_PER_SECOND
        assert virtual_to_pts90(ns) == 9_000_000_000 - (1 << 33)
        assert virtual_to_pts90(ns) == 410_065_408

    def test_beyond_one_pcr_wrap_modulo_is_applied_by_ts(self) -> None:
        """10^5 s = 2.7 * 10^12 ticks27; one PCR wrap is 2^33 * 300 =
        2576980377600 ticks27, leaving 123019622400 ticks27 = base
        410065408, extension 0 (hand-derived)."""
        from ts.pcr import PCR

        from simulation.clock_convert import virtual_to_pcr

        ns = 100_000 * NS_PER_SECOND
        assert virtual_to_pcr(ns) == PCR(base=410_065_408, extension=0)


class TestConvertRoundTrip:
    """Round trips on the exact integer grids (no float ever involved)."""

    def test_ns_ticks27_round_trip_on_microsecond_grid(self) -> None:
        from simulation.clock_convert import (
            ticks27_to_virtual_ns,
            virtual_ns_to_ticks27,
        )

        # ns multiples of 1000 are exact in both directions.
        for us in (0, 1, 7, 1_000, 90_000, 123_456_789):
            ns = us * 1_000
            assert ticks27_to_virtual_ns(virtual_ns_to_ticks27(ns)) == ns

    def test_pcr_round_trip_below_wrap(self) -> None:
        """PCR base multiples of 9 sit on the exact ns grid (base*300
        ticks27 must be divisible by 27 for an exact ns inverse)."""
        from simulation.clock_convert import (
            pcr_to_virtual_ns,
            virtual_to_pcr,
        )

        for base in (0, 9, 90_000, 1_111_104):
            ns = base * 300 * NS_PER_SECOND // TICKS27_PER_SECOND
            pcr = virtual_to_pcr(ns)
            assert pcr.base == base
            assert pcr_to_virtual_ns(pcr) == ns

    def test_pts_round_trip_below_wrap(self) -> None:
        from simulation.clock_convert import (
            pts90_to_virtual_ns,
            virtual_to_pts90,
        )

        for pts in (0, 9, 45_000, 90_000):  # multiples of 9: exact grid
            ns = pts * NS_PER_SECOND // TICKS90_PER_SECOND
            assert virtual_to_pts90(ns) == pts
            assert pts90_to_virtual_ns(pts) == ns

    def test_floor_policy_is_documented_asymmetry_not_drift(self) -> None:
        """Floor inversion loses the sub-tick remainder deterministically —
        a pure function: same input, same output, never accumulates."""
        from simulation.clock_convert import (
            pts90_to_virtual_ns,
            virtual_to_pts90,
        )

        # 1 tick90 floors to 11111 ns; converting back floors to 0 ticks
        # — the remainder is dropped once, not smeared over time.
        assert pts90_to_virtual_ns(1) == 11_111
        assert virtual_to_pts90(11_111) == 0


class TestConvertValidation:
    def test_negative_virtual_ns_rejected(self) -> None:
        from ts.errors import InvalidTimestampError

        from simulation.clock_convert import virtual_ns_to_ticks27

        with pytest.raises(InvalidTimestampError):
            virtual_ns_to_ticks27(-1)

    def test_negative_ticks_rejected(self) -> None:
        from ts.errors import InvalidTimestampError

        from simulation.clock_convert import ticks27_to_virtual_ns

        with pytest.raises(InvalidTimestampError):
            ticks27_to_virtual_ns(-1)

    def test_non_integer_rejected(self) -> None:
        from simulation.clock_convert import virtual_ns_to_ticks27

        with pytest.raises(TypeError):
            virtual_ns_to_ticks27(1.5)  # type: ignore[arg-type]
