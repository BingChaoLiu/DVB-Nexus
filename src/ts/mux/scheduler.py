"""SPEC-107 §3/§5 — deterministic CBR packet-slot scheduler (ticket #33).

The mux walks an exact integer slot lattice (SPEC-107 §3.1):

    slot_time(n) = initial_media_clock + floor(n * 1504 * 27_000_000 / B)

one 188-byte packet per slot, ``output_packet_count`` slots per run.  No
float ever participates (contract §2.4): the slot lattice, the per-source
release accumulator, the table/PCR repetition dues and the deadline
windows are all exact integer formulas of the sequence/period numbers, so
long runs cannot accumulate drift.

Ruling #11 semantics implemented here:

- *PacketSource* — sources yield finished packets in a stable order and
  never see the media clock; the mux stamps ``release_tick_27mhz`` (the
  per-source phase accumulator: packet ``k`` of a ``R`` bps source is due
  at ``floor((k+1) * 1504 * 27e6 / R)``), ``source_sequence`` and the
  configured ``priority``.
- *Deadline* — a packet pulled at slot ``n`` carries
  ``deadline = slot_time(n + 1)`` (the exact integer form of
  ``release_tick + one slot period``): it must be emitted in its release
  slot or the next slot, otherwise ``MUX_PACKET_DEADLINE_MISSED`` aborts
  the run with full run-independent context (packets are never silently
  dropped, SPEC-107 §5.6).
- *Tie-break* — earliest deadline, then priority (smaller wins; tables 0,
  PCR 1, ES 2 by default, per-source override via ``PIDRateConfig``),
  then source_id lexicographic, then source_sequence (SPEC-107 §3.3).
- *PCR timing* — the PCR claims the FIRST slot with
  ``slot_time >= pcr_due_tick`` (jitter bounded < one slot period).  With
  ``payload_packet_first`` a due PES first packet on the PCR PID is armed
  and framed with ``first_packet_pcr`` through SPEC-106; a
  ``PACKETIZER_PCR_DOES_NOT_FIT`` (177..184-byte single-packet PES) or a
  missing due PES start falls back to SPEC-106's
  ``build_pcr_only_packet`` in the very same slot.  The PCR *value* is
  the emission slot time (SPEC-105 owns the encoding).
- *Adaptation-only CC* — a PCR-only packet reuses the CC of the previous
  packet EMITTED on that PID without advancing it (SPEC-100 rule).  The
  mux observes the wire (it emits every packet) and seeds the SPEC-106
  builder's CCAllocator accordingly, which keeps the rule exact even when
  the source's allocator has already allocated CCs for packets that are
  still pending emission.
- *Null padding* — a slot with no due candidate emits the SPEC-107 §5.1
  Null Packet (PID 0x1FFF, AFC=payload-only, 0xFF payload, CC 0).

Normal end-of-stream exhaustion of a source is a per-source event (the
mux stops scheduling it and nulls fill its slots — SPEC-107 §7 "不应误判
为全局错误"); only a source that promised an armed PCR carrier and then
delivered nothing raises ``MUX_SOURCE_EXHAUSTED``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from ts.cc import CCAllocator
from ts.errors import InvalidMuxConfigError, MuxSchedulingError
from ts.mux.codes import (
    MUX_PACKET_DEADLINE_MISSED,
    MUX_PID_DUPLICATE_SOURCE,
    MUX_SLOT_COUNT_MISMATCH,
    MUX_SOURCE_EXHAUSTED,
)
from ts.mux.config import (
    INSERTION_POLICY_PAYLOAD_FIRST,
    MuxConfig,
)
from ts.mux.null_packet import build_null_packet
from ts.mux.sources import (
    PAT_SOURCE_ID,
    PMT_SOURCE_ID,
    PESPacketSource,
    PacketSource,
    TablePacketSource,
)
from ts.packet import TSPacket
from ts.packetizer.pes_packetizer import build_pcr_only_packet
from ts.pcr import pcr_from_27mhz_ticks

#: Bits on the wire per TS packet: 188 bytes * 8 (SPEC-107 §3.1).
SLOT_BITS = 1504

#: 27 MHz media clock ticks per second (contract §4).
TICKS_27MHZ_PER_SECOND = 27_000_000

#: 1 ms is exactly 27_000 27 MHz ticks — whole-millisecond periods convert
#: without rounding.
TICKS_PER_MS = 27_000

_KIND_RATE = "rate"
_KIND_TABLE = "table"


def ms_to_ticks27(milliseconds: int) -> int:
    """Convert whole milliseconds to 27 MHz ticks (exact, ×27_000)."""
    return milliseconds * TICKS_PER_MS


def slot_time_27mhz(
    slot_index: int, target_bitrate_bps: int, initial_media_clock_27mhz: int = 0
) -> int:
    """Exact integer slot lattice (SPEC-107 §3.1): ``floor(n*1504*27e6/B)``.

    The floor is the frozen rounding rule; slot 0 sits at the initial
    media clock.  Pure integer arithmetic — no float ever participates.
    """
    return initial_media_clock_27mhz + (
        slot_index * SLOT_BITS * TICKS_27MHZ_PER_SECOND
    ) // target_bitrate_bps


def source_release_tick_27mhz(
    sequence: int, bitrate_bps: int, initial_media_clock_27mhz: int = 0
) -> int:
    """Release tick of packet ``sequence`` of a ``bitrate_bps`` source.

    Packet ``k`` is complete once ``(k+1)`` packets' worth of source bits
    have accumulated: ``floor((k+1) * 1504 * 27e6 / R)`` — the per-source
    exact integer phase accumulator (SPEC-107 §5.1).  A source at the
    target bitrate therefore has every packet due exactly on a slot
    boundary.
    """
    return initial_media_clock_27mhz + (
        (sequence + 1) * SLOT_BITS * TICKS_27MHZ_PER_SECOND
    ) // bitrate_bps


@dataclass(frozen=True)
class ScheduledPacket:
    """One internal scheduling item (SPEC-107 §3.3).

    ``release_tick_27mhz`` is stamped by the mux from the source's phase
    accumulator; ``deadline_tick_27mhz`` is the exact integer deadline
    (the next slot's release time after the release slot) — the spec's
    ``int | None`` option never materializes because every released
    packet has a deadline by construction.
    """

    packet: TSPacket
    release_tick_27mhz: int
    deadline_tick_27mhz: int
    priority: int
    source_id: str
    source_sequence: int


@dataclass(frozen=True)
class MuxSummary:
    """Run digest (SPEC-107 §11): slot count, bitrate, PCR and null stats.

    ``pcr_positions`` lists the slot indices of every PCR-carrying packet
    (payload-riding and adaptation-only alike), in emission order.
    """

    packet_count: int
    target_bitrate_bps: int
    pcr_positions: tuple[int, ...] = ()
    null_packet_count: int = 0


@dataclass
class _SourceState:
    """Mutable per-source scheduling state (private)."""

    source_id: str
    pid: int
    priority: int
    kind: str
    bitrate_bps: int = 0
    period_ticks: int = 0
    repetition: int = 0
    next_release: int = 0
    next_sequence: int = 0
    active: bool = True
    source: PacketSource | None = None
    stream: Iterator[TSPacket] | None = None


def _schedule_key(item: ScheduledPacket) -> tuple[int, int, str, int]:
    """Deterministic tie-break (SPEC-107 §3.3, ruling #11)."""
    return (
        item.deadline_tick_27mhz,
        item.priority,
        item.source_id,
        item.source_sequence,
    )


def _remove_identity(pending: list[ScheduledPacket], item: ScheduledPacket) -> None:
    """Remove ``item`` from ``pending`` by identity (never by value)."""
    for index, candidate in enumerate(pending):
        if candidate is item:
            del pending[index]
            return
    raise AssertionError("carrier packet vanished from the pending list")


class TSMux:
    """Deterministic CBR mux over packet-slot scheduling (SPEC-107 §6)."""

    def __init__(self, config: MuxConfig, sources: list[PacketSource]) -> None:
        """Pair the configuration with the sources and refuse bad setups.

        Raises :class:`ts.errors.InvalidMuxConfigError` (``MUX_*`` config
        codes) for duplicate/unpairable PID-source identity, reserved
        source ids and PES sources whose PID disagrees with their rate
        entry; the config dataclasses already validated ranges and the
        capacity sum.  ``MUX_PID_RATE_OVERCOMMITTED`` fires for a source
        sum above the target bitrate.
        """
        if not isinstance(config, MuxConfig):
            raise TypeError(f"config must be MuxConfig, got {type(config).__name__}")
        self._config = config
        initial = config.initial_media_clock_27mhz
        all_sources = tuple(sources)

        # --- identity pairing (MUX_PID_DUPLICATE_SOURCE family) ---
        seen_ids: set[str] = set()
        table_sources: list[TablePacketSource] = []
        rate_sources: list[PacketSource] = []
        for source in all_sources:
            if isinstance(source, TablePacketSource):
                table_sources.append(source)
            else:
                if source.source_id in (PAT_SOURCE_ID, PMT_SOURCE_ID):
                    raise InvalidMuxConfigError(
                        f"{MUX_PID_DUPLICATE_SOURCE}: source_id "
                        f"{source.source_id!r} is reserved for the built-in "
                        "table sources"
                    )
                rate_sources.append(source)
            if source.source_id in seen_ids:
                raise InvalidMuxConfigError(
                    f"{MUX_PID_DUPLICATE_SOURCE}: source_id "
                    f"{source.source_id!r} appears more than once in the "
                    "source list"
                )
            seen_ids.add(source.source_id)
        rates_by_id = {rate.source_id: rate for rate in config.pid_rates}
        if len(rates_by_id) != len(config.pid_rates):
            raise InvalidMuxConfigError(
                f"{MUX_PID_DUPLICATE_SOURCE}: pid_rates entries repeat a "
                "source_id"
            )
        for source in rate_sources:
            if source.source_id not in rates_by_id:
                raise InvalidMuxConfigError(
                    f"{MUX_PID_DUPLICATE_SOURCE}: source {source.source_id!r} "
                    "has no matching PIDRateConfig entry; every non-table "
                    "source must be paired with the configuration"
                )
        rate_entries = set(rates_by_id)
        for source in rate_sources:
            rate_entries.discard(source.source_id)
        if rate_entries:
            raise InvalidMuxConfigError(
                f"{MUX_PID_DUPLICATE_SOURCE}: pid_rates entry/entries "
                f"{sorted(rate_entries)!r} have no matching source"
            )

        # --- per-source scheduling state, sorted by source_id ---
        states: list[_SourceState] = []
        for source in table_sources:
            states.append(
                _SourceState(
                    source_id=source.source_id,
                    pid=source.pid,
                    priority=0,  # built-in table priority (ruling #11)
                    kind=_KIND_TABLE,
                    period_ticks=ms_to_ticks27(
                        config.tables.pat_period_ms
                        if source.source_id == PAT_SOURCE_ID
                        else config.tables.pmt_period_ms
                    ),
                    next_release=initial,  # first repetition at media tick 0
                    source=source,
                )
            )
        for source in rate_sources:
            rate = rates_by_id[source.source_id]
            pid = rate.pid
            if isinstance(source, PESPacketSource) and source.pid != pid:
                raise InvalidMuxConfigError(
                    f"{MUX_PID_DUPLICATE_SOURCE}: PESPacketSource "
                    f"{source.source_id!r} frames PID 0x{source.pid:04x} but "
                    f"its PIDRateConfig schedules PID 0x{pid:04x}"
                )
            states.append(
                _SourceState(
                    source_id=source.source_id,
                    pid=pid,
                    priority=rate.priority,
                    kind=_KIND_RATE,
                    bitrate_bps=rate.bitrate_bps,
                    next_release=source_release_tick_27mhz(0, rate.bitrate_bps, initial),
                    source=source,
                    stream=source.iter_packets(),
                )
            )
        states.sort(key=lambda state: state.source_id)
        self._states = states

        # --- PCR schedule state ---
        self._pcr_pes_state = next(
            (
                state
                for state in states
                if state.kind == _KIND_RATE
                and isinstance(state.source, PESPacketSource)
                and state.pid == config.pcr.pcr_pid
            ),
            None,
        )
        self._pcr_repetition = 0
        self._next_pcr_due = initial + (
            self._pcr_repetition + 1
        ) * ms_to_ticks27(config.pcr.target_interval_ms)
        self._armed_state: _SourceState | None = None

        # --- run accounting ---
        self._started = False
        self._pcr_positions: list[int] = []
        self._null_count = 0
        self._last_emitted_cc: dict[int, int] = {}

    # -- public surface (SPEC-107 §6) --

    def iter_packets(self) -> Iterator[TSPacket]:
        """Yield exactly ``output_packet_count`` packets, one per slot.

        Single-shot: the sources are consumed streams, so a second call on
        the same instance is a programming error (create a fresh TSMux
        with fresh sources to repeat a run).
        """
        if self._started:
            raise RuntimeError(
                "TSMux.iter_packets() drives the sources exactly once; "
                "build a new TSMux with fresh sources to repeat a run"
            )
        self._started = True
        return self._run()

    def summary(self) -> MuxSummary:
        """Run digest; final once :meth:`iter_packets` is exhausted."""
        return MuxSummary(
            packet_count=self._config.output_packet_count,
            target_bitrate_bps=self._config.target_bitrate_bps,
            pcr_positions=tuple(self._pcr_positions),
            null_packet_count=self._null_count,
        )

    # -- scheduling core --

    def _run(self) -> Iterator[TSPacket]:
        config = self._config
        initial = config.initial_media_clock_27mhz
        bitrate = config.target_bitrate_bps
        total = config.output_packet_count
        pending: list[ScheduledPacket] = []
        emitted = 0

        while emitted < total:
            slot = emitted
            now = slot_time_27mhz(slot, bitrate, initial)
            deadline = slot_time_27mhz(slot + 1, bitrate, initial)

            pcr_due = now >= self._next_pcr_due
            pre_built_pcr: TSPacket | None = None
            self._armed_state = None
            if pcr_due:
                # Build the adaptation-only carrier BEFORE any pull so its
                # CC reuses the last packet EMITTED on the PCR PID (the
                # source allocator may already be ahead on pending
                # packets).  allocate(has_payload=False) does not advance
                # state, so discarding the packet when a PES first packet
                # rides instead costs nothing.
                pre_built_pcr = self._build_pcr_only_packet(now)
                if config.pcr.insertion_policy == INSERTION_POLICY_PAYLOAD_FIRST:
                    state = self._pcr_pes_state
                    if state is not None and state.active:
                        pes_source = state.source
                        assert isinstance(pes_source, PESPacketSource)
                        if (
                            pes_source.next_starts_pes()
                            and state.next_release <= now
                        ):
                            pes_source.arm_pcr(pcr_from_27mhz_ticks(now))
                            self._armed_state = state

            # --- pull every due packet (sources in source_id order) ---
            carrier: ScheduledPacket | None = None
            for state in self._states:
                if not state.active:
                    continue
                if state.kind == _KIND_TABLE:
                    while state.next_release <= now:
                        table_source = state.source
                        assert isinstance(table_source, TablePacketSource)
                        for pkt in table_source.packets:
                            pending.append(
                                ScheduledPacket(
                                    packet=pkt,
                                    release_tick_27mhz=state.next_release,
                                    deadline_tick_27mhz=deadline,
                                    priority=state.priority,
                                    source_id=state.source_id,
                                    source_sequence=state.next_sequence,
                                )
                            )
                            state.next_sequence += 1
                        state.repetition += 1
                        state.next_release = (
                            initial + state.repetition * state.period_ticks
                        )
                    continue
                armed_here = self._armed_state is state
                armed_captured = False
                while state.next_release <= now:
                    stream = state.stream
                    assert stream is not None
                    try:
                        pkt = next(stream)
                    except StopIteration as exc:
                        if armed_here and not armed_captured:
                            raise MuxSchedulingError(
                                f"{MUX_SOURCE_EXHAUSTED}: source "
                                f"{state.source_id!r} (pid 0x{state.pid:04x}) "
                                "reported an available PES first packet for "
                                "the armed PCR attachment but produced "
                                "nothing; target_bitrate_bps="
                                f"{bitrate}, slot {slot}"
                            ) from exc
                        state.active = False  # per-source exhaustion: fill nulls
                        break
                    pending.append(
                        ScheduledPacket(
                            packet=pkt,
                            release_tick_27mhz=state.next_release,
                            deadline_tick_27mhz=deadline,
                            priority=state.priority,
                            source_id=state.source_id,
                            source_sequence=state.next_sequence,
                        )
                    )
                    if armed_here and not armed_captured:
                        armed_captured = True
                        pes_source = state.source
                        assert isinstance(pes_source, PESPacketSource)
                        if pes_source.pcr_rode_last:
                            carrier = pending[-1]
                    state.next_sequence += 1
                    state.next_release = source_release_tick_27mhz(
                        state.next_sequence, state.bitrate_bps, initial
                    )

            # --- deadline audit: no packet is ever silently dropped ---
            for item in pending:
                if item.deadline_tick_27mhz < now:
                    raise MuxSchedulingError(
                        f"{MUX_PACKET_DEADLINE_MISSED}: slot {slot} "
                        f"(slot_time_27mhz={now}) cannot emit packet from "
                        f"source {item.source_id!r} (pid "
                        f"0x{item.packet.pid:04x}, source_sequence "
                        f"{item.source_sequence}): release_tick "
                        f"{item.release_tick_27mhz} deadline "
                        f"{item.deadline_tick_27mhz} has passed; "
                        f"target_bitrate_bps={bitrate}"
                    )

            # --- emit exactly one packet for this slot ---
            if pcr_due:
                if carrier is not None:
                    _remove_identity(pending, carrier)
                    out = carrier.packet
                else:
                    assert pre_built_pcr is not None
                    out = pre_built_pcr
                self._pcr_positions.append(slot)
                self._pcr_repetition += 1
                self._next_pcr_due = initial + (
                    self._pcr_repetition + 1
                ) * ms_to_ticks27(config.pcr.target_interval_ms)
            elif pending:
                chosen = min(pending, key=_schedule_key)
                _remove_identity(pending, chosen)
                out = chosen.packet
            else:
                out = build_null_packet()
                self._null_count += 1

            if not isinstance(out, TSPacket):
                raise MuxSchedulingError(
                    f"{MUX_SLOT_COUNT_MISMATCH}: slot {slot} produced "
                    f"{type(out).__name__} instead of exactly one 188-byte "
                    f"TS packet; output_packet_count={total}, "
                    f"target_bitrate_bps={bitrate}"
                )
            self._last_emitted_cc[out.pid] = out.continuity_counter
            yield out
            emitted += 1

        if emitted != total:
            raise MuxSchedulingError(
                f"{MUX_SLOT_COUNT_MISMATCH}: the run emitted {emitted} "
                f"packets but output_packet_count is {total}; "
                f"target_bitrate_bps={bitrate}"
            )

    def _build_pcr_only_packet(self, slot_time: int) -> TSPacket:
        """Adaptation-only PCR carrier via the SPEC-106 authority (§5.3).

        The CC reuses the most recent CC EMITTED on the PCR PID (SPEC-100
        adaptation-only rule) — observed from the wire, seeded into a
        fresh allocator so the shared source allocators that may already
        be ahead on pending packets stay untouched.
        """
        pcr_pid = self._config.pcr.pcr_pid
        seeded_cc = self._last_emitted_cc.get(pcr_pid, 0)
        return build_pcr_only_packet(
            pcr_pid,
            pcr_from_27mhz_ticks(slot_time),
            CCAllocator(initial_cc=seeded_cc),
        )
