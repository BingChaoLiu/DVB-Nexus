"""SPEC-105 — Media Clock, 27 MHz / 90 kHz conversion and modular delta.

Time-domain separation (SPEC-105 §2): this module models ONLY the MPEG
media clock. Wall clock (Application/Observation) and the Simulation Clock
(SPEC-201) are different modules; nothing here reads the system time
(``test_media_clock_is_pure`` enforces this).

- 27 MHz ticks are the PCR-combined unit; 90 kHz ticks are the PTS/DTS
  unit. ``1`` 90 kHz tick = ``300`` 27 MHz ticks exactly.
- :class:`MediaClock` keeps an absolute non-negative 27 MHz tick count and
  takes the modulus only at the encode boundary (``pcr()`` / ``pts90k()``),
  so wrap counts are not lost during a run (SPEC-105 §5).
- :func:`modular_delta` is the pure forward-difference primitive. Its
  direction-decidable window is frozen to ``[0, modulus/2)`` by ruling #11:
  deltas below the half period prove "current is ahead"; deltas at or
  beyond it leave "small step back" vs "big step forward" indistinguishable
  from two modulus values alone — the function never errors, the
  comparison strategy belongs to the diagnosis/analysis layer.

Error codes owned here (SPEC-105 §9): ``CLOCK_ROUNDING_MODE_UNSUPPORTED``
(excepted: ``CLOCK_NEGATIVE_TICKS`` is defined in :mod:`ts.pcr` because
``ts.clock`` imports ``ts.pcr`` and the reverse import would be a cycle).
Both map to :class:`ts.errors.InvalidTimestampError` (contract §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ts.errors import InvalidTimestampError
from ts.pcr import CLOCK_NEGATIVE_TICKS, PCR, pcr_from_27mhz_ticks
from ts.timestamp import PTS_MODULUS

# --- SPEC-105 §9 error codes owned by this module (module-owned constants
# per contract §7 归属约定; errors.py carries no business codes). ---

CLOCK_ROUNDING_MODE_UNSUPPORTED = "CLOCK_ROUNDING_MODE_UNSUPPORTED"

#: 27 MHz sub-ticks in one 90 kHz period (exact, contract §4).
TICKS_PER_90K: int = 300


class RoundingMode(str, Enum):
    """Rounding policy for the exact 300:1 down-conversion (SPEC-105 §7).

    ``FLOOR`` is the default (round down / toward zero for non-negative
    inputs); ``CEIL`` rounds up; ``ROUND`` is nearest with ties going up
    (half-up, deterministic for the non-negative tick domain).
    """

    FLOOR = "floor"
    CEIL = "ceil"
    ROUND = "round"


@dataclass(frozen=True)
class MediaClock:
    """Absolute MPEG media time in 27 MHz ticks (non-negative integer).

    The count is absolute (not pre-wrapped): values beyond a single wrap
    period are legal and are taken modulo ``PCR_MODULUS`` / ``PTS_MODULUS``
    only at the encode boundary (SPEC-105 §5). Negative ticks raise
    ``CLOCK_NEGATIVE_TICKS``.
    """

    ticks_27mhz: int

    def __post_init__(self) -> None:
        if not isinstance(self.ticks_27mhz, int) or isinstance(
            self.ticks_27mhz, bool
        ):
            raise TypeError(
                f"ticks_27mhz must be int, got {type(self.ticks_27mhz).__name__}"
            )
        if self.ticks_27mhz < 0:
            raise InvalidTimestampError(
                f"{CLOCK_NEGATIVE_TICKS}: MediaClock accepts non-negative "
                f"ticks only, got {self.ticks_27mhz}"
            )

    def pcr(self) -> PCR:
        """Current 27 MHz count mapped onto a 6-byte-encodable PCR value."""
        return pcr_from_27mhz_ticks(self.ticks_27mhz)

    def pts90k(self) -> int:
        """Current time as a 33-bit 90 kHz PTS value (wrapped at 2^33)."""
        return (self.ticks_27mhz // TICKS_PER_90K) % PTS_MODULUS


def _normalize_rounding(rounding: "str | RoundingMode") -> RoundingMode:
    """Accept a RoundingMode or its exact string name; reject anything else."""
    if isinstance(rounding, RoundingMode):
        return rounding
    if isinstance(rounding, str):
        try:
            return RoundingMode(rounding)
        except ValueError:
            pass
    raise InvalidTimestampError(
        f"{CLOCK_ROUNDING_MODE_UNSUPPORTED}: rounding mode must be one of "
        f"{[mode.value for mode in RoundingMode]}, got {rounding!r}"
    )


def ticks27_to_pts90(
    ticks: int, *, rounding: "str | RoundingMode" = RoundingMode.FLOOR
) -> int:
    """Convert 27 MHz ticks to 90 kHz ticks by exact integer /300 division.

    ``rounding`` selects the policy for non-exact quotients: ``"floor"``
    (default), ``"ceil"``, or ``"round"`` (nearest, ties up). Floats never
    participate (contract §2.4).
    """
    if not isinstance(ticks, int) or isinstance(ticks, bool):
        raise TypeError(f"ticks must be int, got {type(ticks).__name__}")
    if ticks < 0:
        raise InvalidTimestampError(
            f"{CLOCK_NEGATIVE_TICKS}: 27 MHz ticks must be non-negative, "
            f"got {ticks}"
        )
    mode = _normalize_rounding(rounding)
    if mode is RoundingMode.FLOOR:
        return ticks // TICKS_PER_90K
    if mode is RoundingMode.CEIL:
        return -(-ticks // TICKS_PER_90K)
    # ROUND: nearest, ties up — shift by half a 90 kHz period before floor.
    return (ticks + TICKS_PER_90K // 2) // TICKS_PER_90K


def pts90_to_ticks27(pts: int) -> int:
    """Convert 90 kHz ticks to 27 MHz ticks by exact integer *300.

    Inverse of :func:`ticks27_to_pts90` for exact quotients; modulus-free
    so it also serves absolute tick arithmetic.
    """
    if not isinstance(pts, int) or isinstance(pts, bool):
        raise TypeError(f"pts must be int, got {type(pts).__name__}")
    if pts < 0:
        raise InvalidTimestampError(
            f"{CLOCK_NEGATIVE_TICKS}: 90 kHz ticks must be non-negative, "
            f"got {pts}"
        )
    return pts * TICKS_PER_90K


def modular_delta(current: int, previous: int, modulus: int) -> int:
    """Forward difference of two values in the same modulus domain.

    Returns ``(current - previous) % modulus`` — a value in
    ``[0, modulus)`` (SPEC-105 §6). Direction-decidable window (ruling #11,
    frozen): a result below ``modulus / 2`` proves "current is ahead of
    previous"; a result at or beyond ``modulus / 2`` is direction-
    indeterminate ("small step back" vs "large step forward") and the
    caller must treat it as such — this function itself never raises for
    such values. Both PCR (27 MHz) and PTS/DTS (90 kHz) domains share the
    same ~13.26 h half period for their natural moduli.

    A non-positive ``modulus`` is a programming error and raises
    ``ValueError`` (it is not a timestamp-domain failure).
    """
    if not isinstance(modulus, int) or isinstance(modulus, bool):
        raise TypeError(f"modulus must be int, got {type(modulus).__name__}")
    if modulus <= 0:
        raise ValueError(f"modulus must be positive, got {modulus}")
    return (current - previous) % modulus
