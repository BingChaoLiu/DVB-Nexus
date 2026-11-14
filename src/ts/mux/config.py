"""SPEC-107 §4 — frozen mux configuration model (ticket #33).

Frozen dataclasses exactly as the spec text prescribes; validation happens
eagerly in ``__post_init__`` so a bad configuration is refused before any
scheduling work starts (contract §2.5 无隐式修复).  Configuration errors
raise :class:`ts.errors.InvalidMuxConfigError` carrying one of the
module-owned ``MUX_*`` codes from :mod:`ts.mux.codes` (contract §7 mapping
table).

The one field that delegates validation to a neighbour is
``MuxConfig.initial_media_clock_27mhz``: it is a 27 MHz tick count, so the
non-negativity rule belongs to SPEC-105 and is enforced by constructing a
:class:`ts.clock.MediaClock` (``CLOCK_NEGATIVE_TICKS`` /
:class:`ts.errors.InvalidTimestampError` on negative input).
"""

from __future__ import annotations

from dataclasses import dataclass

from ts._bytesutil import PID_MAX, _require_int
from ts.clock import MediaClock
from ts.errors import InvalidMuxConfigError
from ts.mux.codes import (
    MUX_INVALID_BITRATE,
    MUX_INVALID_PACKET_COUNT,
    MUX_PID_DUPLICATE_SOURCE,
    MUX_PID_RATE_OVERCOMMITTED,
    MUX_PCR_INTERVAL_INVALID,
    MUX_TABLE_PERIOD_INVALID,
)

#: The null PID — never a legal ES/PCR PID (project rule, SPEC-103 §8.6).
_PID_NULL = 0x1FFF

#: PCR rides the PES first packet when one is due in the window;
#: otherwise (or with the other policy always) SPEC-106's
#: ``build_pcr_only_packet`` provides the adaptation-only carrier.
INSERTION_POLICY_PAYLOAD_FIRST = "payload_packet_first"
INSERTION_POLICY_ADAPTATION_ONLY = "adaptation_only_fallback"

#: The frozen insertion-policy value set (ruling #11).
INSERTION_POLICIES = (
    INSERTION_POLICY_PAYLOAD_FIRST,
    INSERTION_POLICY_ADAPTATION_ONLY,
)


def _require_mux_pid(pid: int, code: str, what: str) -> int:
    """13-bit PID in range and never the null PID (project rule)."""
    _require_int(pid, what)
    if not 0 <= pid <= PID_MAX or pid == _PID_NULL:
        raise InvalidMuxConfigError(
            f"{code}: {what} must be a 13-bit PID other than the null PID "
            f"0x1FFF, got {pid}"
        )
    return pid


@dataclass(frozen=True)
class PIDRateConfig:
    """Rate schedule and tie-break priority for one packet source (§4).

    ``bitrate_bps`` drives the exact integer phase accumulator (packet
    ``k`` of the source is due at ``floor((k+1) * 1504 * 27e6 / bitrate)``);
    ``priority`` feeds the deterministic tie-break — smaller values win
    (ruling #11: built-in table/PCR sources use 0/1, plain ES defaults to
    2) and may be overridden per source.
    """

    pid: int
    bitrate_bps: int
    source_id: str
    priority: int = 2

    def __post_init__(self) -> None:
        _require_mux_pid(
            self.pid, MUX_PID_DUPLICATE_SOURCE, "PIDRateConfig.pid"
        )
        _require_int(self.bitrate_bps, "PIDRateConfig.bitrate_bps")
        if self.bitrate_bps <= 0:
            raise InvalidMuxConfigError(
                f"{MUX_INVALID_BITRATE}: PIDRateConfig.bitrate_bps must be "
                f"positive, got {self.bitrate_bps}"
            )
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError(
                "PIDRateConfig.source_id must be a non-empty str, got "
                f"{self.source_id!r}"
            )
        _require_int(self.priority, "PIDRateConfig.priority")


@dataclass(frozen=True)
class TableRepetitionConfig:
    """PAT/PMT repetition periods in whole milliseconds (§4/§5.2).

    The periods are simulation configuration, not claimed universal
    standard constants; the MVP profile default (100 ms / 100 ms) is the
    Generator's concern.  1 ms is exactly 27_000 27 MHz ticks, so the
    tick conversion needs no rounding.
    """

    pat_period_ms: int
    pmt_period_ms: int

    def __post_init__(self) -> None:
        for name in ("pat_period_ms", "pmt_period_ms"):
            value = _require_int(getattr(self, name), f"{name}")
            if value <= 0:
                raise InvalidMuxConfigError(
                    f"{MUX_TABLE_PERIOD_INVALID}: {name} must be positive, "
                    f"got {value}"
                )


@dataclass(frozen=True)
class PCRScheduleConfig:
    """PCR target period and insertion policy (§4/§5.3).

    ``target_interval_ms`` is Generator/Mux configuration, not a standard
    constant; the MVP suggestion is 40 ms with measurement margin.  The
    insertion policy is one of the two values frozen by ruling #11.
    """

    pcr_pid: int
    target_interval_ms: int
    insertion_policy: str

    def __post_init__(self) -> None:
        _require_mux_pid(
            self.pcr_pid, MUX_PCR_INTERVAL_INVALID, "PCRScheduleConfig.pcr_pid"
        )
        _require_int(self.target_interval_ms, "PCRScheduleConfig.target_interval_ms")
        if self.target_interval_ms <= 0:
            raise InvalidMuxConfigError(
                f"{MUX_PCR_INTERVAL_INVALID}: target_interval_ms must be "
                f"positive, got {self.target_interval_ms}"
            )
        if self.insertion_policy not in INSERTION_POLICIES:
            raise InvalidMuxConfigError(
                f"{MUX_PCR_INTERVAL_INVALID}: insertion_policy must be one "
                f"of {list(INSERTION_POLICIES)}, got {self.insertion_policy!r}"
            )


@dataclass(frozen=True)
class MuxConfig:
    """Complete mux configuration (SPEC-107 §4).

    ``pid_rates`` pairs 1:1 with the non-table packet sources by
    ``source_id`` (validated again, against the actual source list, when
    the :class:`ts.mux.scheduler.TSMux` is constructed).
    """

    target_bitrate_bps: int
    output_packet_count: int
    pid_rates: tuple[PIDRateConfig, ...]
    tables: TableRepetitionConfig
    pcr: PCRScheduleConfig
    initial_media_clock_27mhz: int = 0

    def __post_init__(self) -> None:
        _require_int(self.target_bitrate_bps, "target_bitrate_bps")
        if self.target_bitrate_bps <= 0:
            raise InvalidMuxConfigError(
                f"{MUX_INVALID_BITRATE}: target_bitrate_bps must be "
                f"positive, got {self.target_bitrate_bps}"
            )
        _require_int(self.output_packet_count, "output_packet_count")
        if self.output_packet_count <= 0:
            raise InvalidMuxConfigError(
                f"{MUX_INVALID_PACKET_COUNT}: output_packet_count must be "
                f"positive, got {self.output_packet_count}"
            )
        if not isinstance(self.tables, TableRepetitionConfig):
            raise TypeError(
                "tables must be TableRepetitionConfig, got "
                f"{type(self.tables).__name__}"
            )
        if not isinstance(self.pcr, PCRScheduleConfig):
            raise TypeError(
                f"pcr must be PCRScheduleConfig, got {type(self.pcr).__name__}"
            )
        rates = tuple(self.pid_rates)
        for rate in rates:
            if not isinstance(rate, PIDRateConfig):
                raise TypeError(
                    "pid_rates entries must be PIDRateConfig, got "
                    f"{type(rate).__name__}"
                )
        object.__setattr__(self, "pid_rates", rates)
        seen_pids: set[int] = set()
        seen_ids: set[str] = set()
        total_bps = 0
        for rate in rates:
            if rate.pid in seen_pids or rate.source_id in seen_ids:
                raise InvalidMuxConfigError(
                    f"{MUX_PID_DUPLICATE_SOURCE}: pid_rates must be unique "
                    f"per PID and per source_id; duplicate entry pid="
                    f"{rate.pid} source_id={rate.source_id!r}"
                )
            seen_pids.add(rate.pid)
            seen_ids.add(rate.source_id)
            total_bps += rate.bitrate_bps
        if total_bps > self.target_bitrate_bps:
            raise InvalidMuxConfigError(
                f"{MUX_PID_RATE_OVERCOMMITTED}: the configured ES bitrates "
                f"sum to {total_bps} bps, exceeding the target transport "
                f"bitrate {self.target_bitrate_bps} bps (table/PCR "
                "overhead is accounted separately per SPEC-107 §4)"
            )
        # Non-negative 27 MHz tick base is SPEC-105 territory; delegate.
        MediaClock(self.initial_media_clock_27mhz)
