"""SPEC-201 section 6 — virtual_time_ns ↔ PCR/PTS conversion boundary.

Single authority (SPEC-201 section 6): the 27 MHz/90 kHz modular
arithmetic, wrap semantics and the ``modular_delta`` half-period window
belong to SPEC-105 (``ts.clock`` / ``ts.pcr``, ruling #11) and are NEVER
re-implemented here. This module only:

1. scales the ``virtual_time_ns`` domain onto the media tick domains with
   exact integer arithmetic (floats never participate — contract §2.4,
   REQ-SIM-201-004), and
2. delegates to the SPEC-105 primitives for value construction, wrap
   handling and error policy (``InvalidTimestampError`` with
   ``CLOCK_NEGATIVE_TICKS`` for negative inputs).

All functions are stateless pure functions (SPEC-201 section 6). Floor is
the frozen rounding policy in both directions, mirroring
``ts.clock.RoundingMode.FLOOR``; exact-integer grids (ns multiples of
1000 → ticks27; ticks multiples of 27 / 9 → ns) round-trip losslessly.
"""

from __future__ import annotations

from ts.clock import MediaClock, pts90_to_ticks27
from ts.errors import InvalidTimestampError
from ts.pcr import (
    CLOCK_NEGATIVE_TICKS,
    PCR,
    pcr_from_27mhz_ticks,
    pcr_to_27mhz_ticks,
)

__all__ = [
    "NS_PER_SECOND",
    "PCR_RATE_27MHZ",
    "PTS_RATE_90KHZ",
    "ticks27_to_virtual_ns",
    "virtual_ns_to_ticks27",
    "virtual_to_pcr",
    "virtual_to_pts90",
    "pcr_to_virtual_ns",
    "pts90_to_virtual_ns",
]

#: Exact integer anchors for the domain scaling.
NS_PER_SECOND = 1_000_000_000
#: 27 MHz PCR combined-tick rate (ticks27 per second).
PCR_RATE_27MHZ = 27_000_000
#: 90 kHz PTS/DTS tick rate (ticks90 per second).
PTS_RATE_90KHZ = 90_000


def _require_non_negative_int(value: object, field: str) -> int:
    """Type/range gate mirroring the ts primitive conventions."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise InvalidTimestampError(
            f"{CLOCK_NEGATIVE_TICKS}: {field} must be non-negative, got {value}"
        )
    return value


def virtual_ns_to_ticks27(virtual_time_ns: int) -> int:
    """Scale virtual nanoseconds onto absolute 27 MHz ticks (floor).

    Exact integer arithmetic: ``ns * 27_000_000 // 1_000_000_000``. The
    absolute (unwrapped) tick count is returned; wrapping at the PCR
    encode boundary happens only inside the SPEC-105 primitives.
    """
    _require_non_negative_int(virtual_time_ns, "virtual_time_ns")
    return virtual_time_ns * PCR_RATE_27MHZ // NS_PER_SECOND


def ticks27_to_virtual_ns(ticks_27mhz: int) -> int:
    """Scale absolute 27 MHz ticks onto virtual nanoseconds (floor).

    Exact integer inverse: ``ticks * 1_000_000_000 // 27_000_000``.
    Lossless for tick counts divisible by 27.
    """
    _require_non_negative_int(ticks_27mhz, "ticks_27mhz")
    return ticks_27mhz * NS_PER_SECOND // PCR_RATE_27MHZ


def virtual_to_pcr(virtual_time_ns: int) -> PCR:
    """Map virtual time onto the wrapped 42-bit PCR value.

    Delegates entirely to :func:`ts.pcr.pcr_from_27mhz_ticks` — the wrap
    at ``2^33 * 300`` ticks and the negative-input error policy are
    SPEC-105's (ruling #11, PCR-PTS.md section 3).
    """
    return pcr_from_27mhz_ticks(virtual_ns_to_ticks27(virtual_time_ns))


def pcr_to_virtual_ns(pcr: PCR) -> int:
    """Map a PCR value onto virtual nanoseconds (floor, exact grid).

    Delegates the tick count to :func:`ts.pcr.pcr_to_27mhz_ticks`
    (``base * 300 + extension``).
    """
    return ticks27_to_virtual_ns(pcr_to_27mhz_ticks(pcr))


def virtual_to_pts90(virtual_time_ns: int) -> int:
    """Map virtual time onto the wrapped 33-bit 90 kHz PTS domain.

    Scales to absolute ticks27 then delegates to
    :meth:`ts.clock.MediaClock.pts90k` — the exact /300 down-conversion
    and the ``2^33`` wrap-at-encode-boundary are SPEC-105's (§5).
    """
    return MediaClock(virtual_ns_to_ticks27(virtual_time_ns)).pts90k()


def pts90_to_virtual_ns(pts_90k: int) -> int:
    """Map a 90 kHz PTS value onto virtual nanoseconds (floor, exact grid).

    Delegates the tick-domain validation and the exact *300 up-conversion
    to :func:`ts.clock.pts90_to_ticks27`.
    """
    return ticks27_to_virtual_ns(pts90_to_ticks27(pts_90k))
