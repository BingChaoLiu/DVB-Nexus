"""SPEC-107 §6 — packet source model and the built-in source kinds.

``PacketSource`` is the frozen internal Protocol (ruling #11): a stable
order of finished SPEC-100 packets identified by a ``source_id``.  Sources
never see the media clock — release ticks are stamped by the mux from the
``PIDRateConfig`` phase accumulator, ``source_sequence`` is the production
ordinal and ``priority`` comes from the configuration.

Two built-in concrete kinds live here (SPEC-108 §5 wires them up: the
Generator packetizes PAT/PMT through SPEC-106 and hands the packets to the
mux, and feeds PES through the PCR-aware source):

- :class:`TablePacketSource` — one packetized PSI table run (source_id
  ``"pat"`` or ``"pmt"``) that the mux re-emits at the configured
  repetition period; priority 0 is built in.
- :class:`PESPacketSource` — a PES byte stream framed lazily per PES
  through the SPEC-106 ``PESPacketizer`` so the mux can attach PCR to a
  PES first packet (``first_packet_pcr``) when the payload-first policy
  finds one due in the PCR window.  A ``PACKETIZER_PCR_DOES_NOT_FIT``
  (single-packet PES of 177..184 bytes) is absorbed here by reframing the
  PES without PCR — the SPEC-107-established fallback path; the mux then
  emits the SPEC-106 ``build_pcr_only_packet`` carrier instead.

Any other object satisfying the Protocol (e.g. a pre-framed packet list)
is scheduled as a plain rate source; its packets are finished frames the
mux treats read-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol

from ts.cc import CCAllocator
from ts.errors import InvalidMuxConfigError, PacketizationError
from ts.mux.codes import MUX_PID_DUPLICATE_SOURCE
from ts.packet import TSPacket
from ts.packetizer.codes import PACKETIZER_PCR_DOES_NOT_FIT
from ts.packetizer.pes_packetizer import PESPacketizer
from ts.pcr import PCR
from ts.pes import PESPacket

#: Reserved source ids for the built-in table sources (SPEC-107 §6: tables
#: are mux-built-in with priority 0; the mux maps these ids to the
#: ``TableRepetitionConfig`` periods).
PAT_SOURCE_ID = "pat"
PMT_SOURCE_ID = "pmt"

_TABLE_SOURCE_IDS = (PAT_SOURCE_ID, PMT_SOURCE_ID)


class PacketSource(Protocol):
    """Frozen source protocol (ruling #11): stable packet order, no clock."""

    @property
    def source_id(self) -> str:
        """Stable source identifier the mux schedules by (``"pat"``,
        ``"pmt"``, ``"es:<n>"`` or caller-chosen for plain rate sources)."""

    def iter_packets(self) -> Iterator[TSPacket]:
        """Yield the finished SPEC-100 packets in their stable order.

        The mux treats the yielded packets as read-only frames and stamps
        release ticks itself (sources never see the media clock).
        """


class TablePacketSource:
    """A packetized PSI table run the mux repeats at the configured period.

    ``source_id`` must be ``"pat"`` or ``"pmt"`` — the mux uses the id to
    pick the matching ``TableRepetitionConfig`` period and assigns the
    built-in table priority 0.  ``packets`` is one complete packetization
    run of the section (SPEC-106 output; MVP minimal tables are a single
    packet).  Every repetition re-emits the SAME finished packets — the
    mux never re-frames or modifies them (contract §9).

    Repetition semantics (PI-1 ruling, #35 closing comment, option (a)):
    a table repetition is a **duplicate retransmission** — the same group
    of already-finished packets is re-emitted verbatim, so the
    continuity_counter does NOT increment across repetitions.  This is the
    ISO/IEC 13818-1 duplicate-packet mechanism: a receiver that sees two
    packets with the same CC on one PID discards the second per the
    standard, and PSI reassembly is unaffected (verified in both
    directions by the #35 TSDuck cross-validation: ``duplicated=2+2`` /
    ``4+4`` agrees with the duplicate-aware walkthrough).  Alternatives
    were explicitly not adopted: (b) incrementing CC on repetition would
    change the frozen SPEC-107 packet-repetition semantics through a spec
    change, and (c) per-repetition CC carry-over conflicts with contract
    §9 (the mux never modifies finished packets).
    """

    def __init__(self, source_id: str, packets: Iterable[TSPacket]) -> None:
        if source_id not in _TABLE_SOURCE_IDS:
            raise InvalidMuxConfigError(
                f"{MUX_PID_DUPLICATE_SOURCE}: table source_id must be one "
                f"of {list(_TABLE_SOURCE_IDS)}, got {source_id!r}"
            )
        run = tuple(packets)
        if not run:
            raise ValueError(
                "TablePacketSource needs at least one packetized packet"
            )
        for pkt in run:
            if not isinstance(pkt, TSPacket):
                raise TypeError(
                    f"table packets must be TSPacket, got {type(pkt).__name__}"
                )
        pids = {pkt.pid for pkt in run}
        if len(pids) != 1:
            raise ValueError(
                "a table run shares one PID; got "
                + ", ".join(f"0x{pid:04x}" for pid in sorted(pids))
            )
        self._source_id = source_id
        self._packets = run

    @property
    def source_id(self) -> str:
        """The reserved table id (``"pat"`` or ``"pmt"``) the mux maps to
        its matching ``TableRepetitionConfig`` period."""
        return self._source_id

    @property
    def packets(self) -> tuple[TSPacket, ...]:
        """The one packetization run repeated at the configured period."""
        return self._packets

    @property
    def pid(self) -> int:
        """The table PID (every packet in the run carries it)."""
        return self._packets[0].pid

    def iter_packets(self) -> Iterator[TSPacket]:
        """Protocol conformance: yield the run once (mux repeats it)."""
        yield from self._packets


class PESPacketSource:
    """PCR-aware ES source: PES items framed lazily, one PES at a time.

    The source owns the ``PESPacketizer`` (and through it the PID's
    ``CCAllocator``) so a PES is only framed when the mux actually pulls
    its first packet — that is what makes payload-first PCR attachment
    possible: the mux arms a PCR value BEFORE the pull and the next PES
    is framed with ``first_packet_pcr`` set (ruling #11: timing = mux,
    construction = SPEC-106).

    Scheduling contract with the mux (internal, duck-typed through this
    concrete class):

    - ``next_starts_pes()`` — the next packet this source will produce
      begins a new PES (accurate, backed by a one-item lookahead so an
      exhausted stream is reported honestly).
    - ``arm_pcr(pcr)`` — attach this PCR value to the next PES start.
    - ``pcr_rode_last`` — whether the most recent PES framing actually
      carried the armed PCR (``False`` after a PCR-does-not-fit fallback).
    """

    def __init__(
        self,
        source_id: str,
        pid: int,
        pes_items: Iterable["PESPacket | bytes"],
    ) -> None:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty str")
        self._source_id = source_id
        self._pid = pid  # validated by the PESPacketizer below
        self._cc_allocator = CCAllocator()
        self._packetizer = PESPacketizer(pid, self._cc_allocator)
        self._pes_iter = iter(pes_items)
        self._peeked: "PESPacket | bytes | None" = None
        self._pes_exhausted = False
        self._run: list[TSPacket] | None = None
        self._run_index = 0
        self._armed_pcr: PCR | None = None
        self._pcr_rode_last = False

    @property
    def source_id(self) -> str:
        """The caller-chosen non-empty id (``ES_SOURCE_ID_PREFIX``-prefixed
        per SPEC-108 §5) the mux reports in scheduling/summary accounting."""
        return self._source_id

    @property
    def pid(self) -> int:
        """The single output PID this source frames every PES onto
        (validated by the owned :class:`PESPacketizer`)."""
        return self._pid

    @property
    def cc_allocator(self) -> CCAllocator:
        """This source's CC state authority (contract §9)."""
        return self._cc_allocator

    def iter_packets(self) -> Iterator[TSPacket]:
        """Protocol surface: lazily frame PES after PES, in stable order."""
        while True:
            if self._run is None and not self._fill_run():
                return
            if self._run_index >= len(self._run):
                self._run = None
                continue
            pkt = self._run[self._run_index]
            self._run_index += 1
            yield pkt

    def next_starts_pes(self) -> bool:
        """Whether the NEXT packet produced starts a new PES (accurate).

        A run whose packets were all pulled already (``_run_index`` at the
        end) counts as no current run — the next pull frames the peeked
        PES.
        """
        self._peek_pes()
        run_active = self._run is not None and self._run_index < len(self._run)
        return not run_active and self._peeked is not None

    def arm_pcr(self, pcr: PCR) -> None:
        """Attach ``pcr`` to the next PES first packet (mux decision)."""
        if not isinstance(pcr, PCR):
            raise TypeError(f"pcr must be ts.pcr.PCR, got {type(pcr).__name__}")
        self._armed_pcr = pcr

    @property
    def pcr_rode_last(self) -> bool:
        """Did the most recent PES framing carry the armed PCR?"""
        return self._pcr_rode_last

    # --- internals ---

    def _peek_pes(self) -> None:
        """Pull the next PES into the lookahead slot (honest exhaustion)."""
        if self._peeked is None and not self._pes_exhausted:
            try:
                self._peeked = next(self._pes_iter)
            except StopIteration:
                self._pes_exhausted = True

    def _fill_run(self) -> bool:
        """Frame the next PES into ``self._run``; False when exhausted."""
        self._peek_pes()
        pes = self._peeked
        if pes is None:
            return False
        self._peeked = None
        pcr = self._armed_pcr
        self._armed_pcr = None
        self._pcr_rode_last = False
        if pcr is not None:
            try:
                self._run = list(
                    self._packetizer.packetize(pes, first_packet_pcr=pcr)
                )
                self._pcr_rode_last = True
                self._run_index = 0
                return True
            except PacketizationError as exc:
                if PACKETIZER_PCR_DOES_NOT_FIT not in str(exc):
                    raise
                # SPEC-107-established path: a 177..184-byte single-packet
                # PES leaves no room for the PCR field; reframe WITHOUT
                # PCR — the mux emits the build_pcr_only_packet carrier.
                self._run = list(self._packetizer.packetize(pes))
                self._run_index = 0
                return True
        self._run = list(self._packetizer.packetize(pes))
        self._run_index = 0
        return True
