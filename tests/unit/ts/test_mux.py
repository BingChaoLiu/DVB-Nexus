"""SPEC-107 — TS mux — unit tests (ticket #33).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-107 section):

- REQ-TS-107-001  packet slot 数和 188 bytes 正确    -> test_mux_packet_count
- REQ-TS-107-002  CBR slot 使用精确整数时间          -> test_mux_no_float_drift
- REQ-TS-107-003  PAT/PMT 周期正确                  -> test_mux_table_repetition
- REQ-TS-107-004  PCR 插入不破坏 Payload            -> test_mux_pcr_insertion
- REQ-TS-107-005  Null Packet 补齐                  -> test_mux_null_padding
- REQ-TS-107-006  超载/过期显式报错                  -> test_mux_overcommit
- REQ-TS-107-007  调度顺序确定性                     -> test_mux_determinism

Every expected value below is hand-derived from the SPEC-107 §3/§5 integer
arithmetic (never recomputed through the mux itself):

- ``slot_time(n) = initial + floor(n * 1504 * 27e6 / B)`` — exact integer
  slot lattice (contract §2.4 float ban); a packet pulled at slot ``n`` has
  ``deadline = slot_time(n + 1)`` (ruling #11: emit in the release slot or
  the next slot, else MUX_PACKET_DEADLINE_MISSED).
- source release: packet ``k`` of a ``R`` bps source is complete once
  ``(k+1)`` packets' worth of source bits have accumulated, i.e. due at
  ``initial + floor((k+1) * 1504 * 27e6 / R)``; it is pulled at the first
  slot with ``slot_time >= release``.  With ``R == B`` every packet is due
  exactly on a slot boundary — the strongest possible drift tripwire.
- table repetitions are due at ``initial + r * period_ticks`` (first PAT
  and PMT at media tick ``initial``; two packets, two deadline slots —
  PAT wins slot 0 by the source_id tie-break, PMT takes slot 1).
- PCR repetitions are due at ``initial + (k+1) * interval_ticks`` (first
  PCR one full interval in, so a slot-0 PCR claim can never collide with
  the slot-0/1 table pair); the PCR carrier claims the first slot with
  ``slot_time >= pcr_due_tick`` (ruling #11, jitter < one slot period).
- adaptation-only PCR packets reuse the CC of the previous packet EMITTED
  on that PID without advancing (SPEC-100 rule; the mux observes the wire,
  the SPEC-106 builder stays the only construction authority).

Default test geometry: ``B = 3_000_000`` gives an exact 13_536-tick slot;
``1 ms = 27_000`` ticks exactly.  Section/PES input bytes are procedurally
generated with fixed formulas (never 0xFF) — deterministic literals, not
environment values (tests/README.md §6).  Imports follow the upstream
ts-core test style: ``ts.*`` modules are imported inside the tests that
need them (so the RED phase is per-test, not a collection error).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# --- exact integer scheduling arithmetic (SPEC-107 §3.1) -------------------

_SLOT_BITS = 1504
_TICKS_27MHZ_PER_S = 27_000_000
_C = _SLOT_BITS * _TICKS_27MHZ_PER_S  # 40_608_000_000 ticks*bit / s
_TICKS_PER_MS = 27_000

B_DEFAULT = 3_000_000
_SLOT_DEFAULT = _C // B_DEFAULT  # 13_536 ticks — exact


def slot_time(n: int, bitrate: int = B_DEFAULT, initial: int = 0) -> int:
    """Hand-rolled SPEC-107 §3.1 slot formula (floor, exact integers)."""
    return initial + (n * _C) // bitrate


def first_slot_at_least(
    tick: int, bitrate: int = B_DEFAULT, initial: int = 0
) -> int:
    """Smallest slot index n with slot_time(n) >= tick (exact integers).

    floor(n*C/B) >= tick-initial  <=>  n*C >= (tick-initial)*B, hence
    n = ceil((tick-initial)*B / C) computed with integer arithmetic only.
    """
    return -(-((tick - initial) * bitrate) // _C)


def release_tick(seq: int, rate: int, initial: int = 0) -> int:
    """Packet ``seq`` of a ``rate``-bps source is complete (due) here."""
    return initial + ((seq + 1) * _C) // rate


def pcr_due_tick(rep: int, interval_ms: int, initial: int = 0) -> int:
    """Repetition ``rep`` (0-based) of the PCR schedule is due here."""
    return initial + (rep + 1) * interval_ms * _TICKS_PER_MS


# --- deterministic input builders -------------------------------------------


def make_pes_bytes(total: int) -> bytes:
    """A deterministic bounded-profile PES byte string of ``total`` bytes.

    9-byte PES header (SPEC-104 §3: prefix 00 00 01, stream_id 0xC0 audio,
    16-bit declared length, '10' marker flags byte, flags2, header_data_
    length=0) plus a formula payload of ``total - 9`` bytes (never 0xFF).
    """
    assert total >= 9
    header = (
        b"\x00\x00\x01\xc0"
        + (total - 6).to_bytes(2, "big")
        + bytes((0x80, 0x00, 0x00))
    )
    return header + bytes((i * 7 + 3) & 0x7E for i in range(total - 9))


class ListSource:
    """Minimal PacketSource test double over pre-built packets."""

    def __init__(self, source_id: str, packets: list) -> None:
        from ts.packet import TSPacket

        for pkt in packets:
            if not isinstance(pkt, TSPacket):
                raise TypeError("ListSource needs TSPacket entries")
        self._source_id = source_id
        self._packets = list(packets)

    @property
    def source_id(self) -> str:
        return self._source_id

    def iter_packets(self):
        yield from self._packets


def make_es_packets(pid: int, count: int) -> list:
    """``count`` payload-only ES packets with a fixed byte formula."""
    from ts.packet import TSPacket

    return [
        TSPacket(
            pid=pid,
            continuity_counter=k % 16,
            payload=bytes(((k + i) * 3 + 1) & 0x7E for i in range(184)),
        )
        for k in range(count)
    ]


def make_pat_packets(pmt_pid: int) -> tuple:
    """One real SPEC-103 PAT section packetized through SPEC-106."""
    from ts.cc import CCAllocator
    from ts.packetizer.section_packetizer import SectionPacketizer
    from ts.tables.pat import PATBuilder, PATProgram, PATSection

    section = PATBuilder().build(
        PATSection(
            transport_stream_id=1,
            version_number=0,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            programs=(PATProgram(program_number=1, program_map_pid=pmt_pid),),
        )
    )
    return tuple(SectionPacketizer(0x0000, CCAllocator()).packetize(section))


def make_pmt_packets(pmt_pid: int, es_pid: int, pcr_pid: int) -> tuple:
    """One real SPEC-103 PMT section packetized through SPEC-106."""
    from ts.cc import CCAllocator
    from ts.packetizer.section_packetizer import SectionPacketizer
    from ts.tables.pmt import PMTBuilder, PMTSection, ElementaryStream

    section = PMTBuilder().build(
        PMTSection(
            program_number=1,
            version_number=0,
            current_next_indicator=True,
            section_number=0,
            last_section_number=0,
            pcr_pid=pcr_pid,
            program_descriptors=b"",
            streams=(ElementaryStream(stream_type=0x1B, elementary_pid=es_pid),),
        )
    )
    return tuple(SectionPacketizer(pmt_pid, CCAllocator()).packetize(section))


def make_config(**overrides):
    """MuxConfig with sane defaults; PCR/tables pushed beyond short runs."""
    from ts.mux.config import (
        MuxConfig,
        PCRScheduleConfig,
        TableRepetitionConfig,
    )

    params = dict(
        target_bitrate_bps=B_DEFAULT,
        output_packet_count=64,
        pid_rates=(),
        tables=TableRepetitionConfig(pat_period_ms=100_000, pmt_period_ms=100_000),
        pcr=PCRScheduleConfig(
            pcr_pid=0x100,
            target_interval_ms=10_000,
            insertion_policy="payload_packet_first",
        ),
        initial_media_clock_27mhz=0,
    )
    params.update(overrides)
    return MuxConfig(**params)


def collect_pes_runs(packets: list, pid: int) -> list:
    """Concatenate the payload of each PUSI-delimited run on ``pid``."""
    runs: list = []
    current: list | None = None
    for pkt in packets:
        if pkt.pid != pid:
            continue
        if pkt.payload_unit_start_indicator:
            if current:
                runs.append(b"".join(current))
            current = []
        if current is not None and pkt.payload is not None:
            current.append(pkt.payload)
    if current:
        runs.append(b"".join(current))
    return runs


# --- REQ-TS-107-001 ----------------------------------------------------------


def test_mux_packet_count():
    """REQ-TS-107-001: exact slot count, every packet 188 bytes."""
    from ts.packet import TS_PACKET_SIZE, PID_NULL, TSPacket

    # Empty business: packet_count slots, all null, every packet 188 bytes.
    from ts.mux.scheduler import TSMux

    mux = TSMux(make_config(output_packet_count=57), sources=[])
    packets = list(mux.iter_packets())
    assert len(packets) == 57
    assert all(len(pkt.to_bytes()) == TS_PACKET_SIZE for pkt in packets)
    assert all(pkt.pid == PID_NULL for pkt in packets)
    # total byte count equals packet_count * 188 exactly
    assert sum(len(pkt.to_bytes()) for pkt in packets) == 57 * TS_PACKET_SIZE
    # strict parse round-trip on every emitted packet
    for pkt in packets:
        assert TSPacket.from_bytes(pkt.to_bytes()) == pkt
    summary = mux.summary()
    assert summary.packet_count == 57
    assert summary.target_bitrate_bps == B_DEFAULT

    # With one rate-scheduled source the slot count is still exact.
    config = make_config(
        output_packet_count=64,
        pid_rates=(make_pid_rate(pid=0x101, bitrate_bps=512_000, source_id="es-a"),),
    )
    mux2 = TSMux(config, [ListSource("es-a", make_es_packets(0x101, 10))])
    packets2 = list(mux2.iter_packets())
    assert len(packets2) == 64
    assert all(len(pkt.to_bytes()) == TS_PACKET_SIZE for pkt in packets2)
    es_slots = [i for i, pkt in enumerate(packets2) if pkt.pid == 0x101]
    assert es_slots == [6, 12, 18, 24, 30, 36, 42, 47, 53, 59]
    assert mux2.summary().null_packet_count == 54


def make_pid_rate(pid: int, bitrate_bps: int, source_id: str, priority: int = 2):
    from ts.mux.config import PIDRateConfig

    return PIDRateConfig(
        pid=pid, bitrate_bps=bitrate_bps, source_id=source_id, priority=priority
    )


def make_table_sources(pmt_pid: int = 0x20, es_pid: int = 0x101):
    """The built-in PAT/PMT sources (SPEC-106 packetized, one packet each)."""
    from ts.mux.sources import PMT_SOURCE_ID, PAT_SOURCE_ID, TablePacketSource

    return [
        TablePacketSource(PAT_SOURCE_ID, make_pat_packets(pmt_pid)),
        TablePacketSource(PMT_SOURCE_ID, make_pmt_packets(pmt_pid, es_pid, es_pid)),
    ]


# --- REQ-TS-107-002 ----------------------------------------------------------


def test_mux_no_float_drift():
    """REQ-TS-107-002: exact integer scheduling, zero accumulated drift."""
    from ts.mux.scheduler import (
        TSMux,
        slot_time_27mhz,
        source_release_tick_27mhz,
    )

    # (1) Direct formula check for bitrates that do not divide the slot
    #     constant: the mux must use floor(n*C/B), never float sums.
    for bitrate in (7_000_000, 3_141_592):
        for initial in (0, 12_345):
            for n in range(0, 1001):
                assert slot_time_27mhz(n, bitrate, initial) == slot_time(
                    n, bitrate, initial
                )
    assert source_release_tick_27mhz(9, 512_000) == 793_125

    # (2) R == B == 7_000_000: releases land exactly on slot boundaries
    #     (C/B = 5801.142857... — non-dividing).  Any float accumulation
    #     would flip a boundary comparison.  Hand-derived wiring: PAT at
    #     slot 0, PMT at slot 1, ES#0 pulled at slot 1 loses the tie-break
    #     to PMT and emits at 2, and from there every ES packet emits at
    #     its due slot exactly: seq k -> slot k+2, no nulls, no misses.
    config = make_config(
        target_bitrate_bps=7_000_000,
        output_packet_count=500,
        pid_rates=(make_pid_rate(pid=0x101, bitrate_bps=7_000_000, source_id="es-a"),),
    )
    mux = TSMux(
        config,
        make_table_sources() + [ListSource("es-a", make_es_packets(0x101, 500))],
    )
    packets = list(mux.iter_packets())
    assert packets[0].pid == 0x0000  # PAT
    assert packets[1].pid == 0x0020  # PMT
    es_slots = [i for i, pkt in enumerate(packets) if pkt.pid == 0x101]
    assert es_slots == list(range(2, 500))
    assert mux.summary().null_packet_count == 0

    # (3) Long run with a rate whose spacing is fractional in slots
    #     (512 kbps in a 3 Mbps TS): every emission slot must equal the
    #     exact integer formula over ~683 packets / 2 seconds of media
    #     time — a float accumulator would drift off the formula.
    config3 = make_config(
        output_packet_count=4000,
        pid_rates=(make_pid_rate(pid=0x101, bitrate_bps=512_000, source_id="es-a"),),
    )
    mux3 = TSMux(
        config3,
        make_table_sources() + [ListSource("es-a", make_es_packets(0x101, 700))],
    )
    packets3 = list(mux3.iter_packets())
    es_slots3 = [i for i, pkt in enumerate(packets3) if pkt.pid == 0x101]
    expected = [
        first_slot_at_least(release_tick(k, 512_000)) for k in range(682)
    ]
    assert es_slots3 == expected
    assert mux3.summary().null_packet_count == 4000 - 682 - 2


# --- REQ-TS-107-003 ----------------------------------------------------------


def test_mux_table_repetition():
    """REQ-TS-107-003: PAT/PMT emission controlled by the configured periods."""
    from ts.mux.scheduler import TSMux

    # B=3 Mbps, run of 300 slots (4_047_264 ticks).  PAT 100 ms -> dues at
    # ticks 0 and 2_700_000 -> slots 0 and 200.  PMT 70 ms -> dues 0,
    # 1_890_000, 3_780_000 -> slots 1 (loses the slot-0 tie-break to PAT),
    # 140, 280.  PCR 40 ms on a source-less PID -> pcr-only at slots 80,
    # 160, 240.  All eight positions are pairwise distinct by construction.
    config = make_config(
        output_packet_count=300,
        tables=make_tables(pat_period_ms=100, pmt_period_ms=70),
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=40),
    )
    mux = TSMux(config, make_table_sources())
    packets = list(mux.iter_packets())
    pat_slots = [i for i, p in enumerate(packets) if p.pid == 0x0000]
    pmt_slots = [i for i, p in enumerate(packets) if p.pid == 0x0020]
    assert pat_slots == [0, 200]
    assert pmt_slots == [1, 140, 280]
    # table packets are PUSI-bearing single-packet section runs
    assert packets[0].payload_unit_start_indicator
    assert packets[1].payload_unit_start_indicator
    assert mux.summary().pcr_positions == (80, 160, 240)
    assert mux.summary().null_packet_count == 300 - 2 - 3 - 3

    # repetition count scales with the run length: PAT 40 ms / PMT 40 ms
    # over 260 slots (3_519_360 ticks, no PCR in range): PAT reps due at
    # ticks 0, 1_080_000, 2_160_000, 3_240_000 -> slots 0, 80, 160, 240;
    # PMT loses every same-tick tie-break to PAT and lands one slot later
    # (still inside its deadline: release slot + one slot period).
    config2 = make_config(
        output_packet_count=260,
        tables=make_tables(pat_period_ms=40, pmt_period_ms=40),
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=10_000),
    )
    mux2 = TSMux(config2, make_table_sources())
    packets2 = list(mux2.iter_packets())
    assert [i for i, p in enumerate(packets2) if p.pid == 0x0000] == [
        0,
        80,
        160,
        240,
    ]
    assert [i for i, p in enumerate(packets2) if p.pid == 0x0020] == [
        1,
        81,
        161,
        241,
    ]
    assert mux2.summary().null_packet_count == 260 - 8


def make_tables(pat_period_ms: int, pmt_period_ms: int):
    from ts.mux.config import TableRepetitionConfig

    return TableRepetitionConfig(
        pat_period_ms=pat_period_ms, pmt_period_ms=pmt_period_ms
    )


def make_pcr_config(pcr_pid: int, target_interval_ms: int, insertion_policy: str = "payload_packet_first"):
    from ts.mux.config import PCRScheduleConfig

    return PCRScheduleConfig(
        pcr_pid=pcr_pid,
        target_interval_ms=target_interval_ms,
        insertion_policy=insertion_policy,
    )


# --- REQ-TS-107-004 ----------------------------------------------------------


def test_mux_pcr_insertion():
    """REQ-TS-107-004: PCR timing, payload-first riding, fallbacks, CC rule."""
    from ts.pcr import pcr_to_27mhz_ticks
    from ts.mux.scheduler import TSMux, slot_time_27mhz
    from ts.mux.sources import PESPacketSource

    pes360 = make_pes_bytes(360)  # frames to 2 packets either way (176+184)

    # Scenario A — payload_packet_first: the ES source runs at 338_400 bps
    # (C/R = 120_000 ticks exactly) with 2-packet PES runs, so PES starts
    # are due at ticks (2j+1)*120_000.  PCR interval 40 ms = 1_080_000
    # ticks: rep dues land on PES #4 and PES #13 starts (payload rides,
    # slots 80/240) and between two PES starts (fallback, slot 160).
    config = make_config(
        output_packet_count=300,
        tables=make_tables(pat_period_ms=100, pmt_period_ms=100),
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=40),
        pid_rates=(
            make_pid_rate(pid=0x100, bitrate_bps=338_400, source_id="pes-src"),
        ),
    )
    mux = TSMux(
        config,
        [PESPacketSource("pes-src", 0x100, [pes360] * 40)],
    )
    packets = list(mux.iter_packets())
    summary = mux.summary()
    assert summary.pcr_positions == (80, 160, 240)
    # PCR position = first slot with slot_time >= pcr_due (jitter < 1 slot)
    for pos, rep in zip((80, 160, 240), (0, 1, 2)):
        due = pcr_due_tick(rep, 40)
        assert 0 <= slot_time_27mhz(pos, B_DEFAULT) - due < _SLOT_DEFAULT
    # slot 80: PCR rides the PES #4 first packet (PUSI, AF PCR = slot time)
    p80 = packets[80]
    assert p80.pid == 0x100 and p80.payload_unit_start_indicator
    assert p80.adaptation_field is not None and p80.adaptation_field.pcr is not None
    assert pcr_to_27mhz_ticks(p80.adaptation_field.pcr) == slot_time_27mhz(
        80, B_DEFAULT
    )
    assert p80.continuity_counter == 8  # PES #0..#3 consumed CC 0..7
    # slot 160: no due PES start (seq 17 is mid-PES) -> adaptation-only
    p160 = packets[160]
    assert p160.pid == 0x100 and p160.payload is None
    assert p160.adaptation_field is not None and p160.adaptation_field.pcr is not None
    assert pcr_to_27mhz_ticks(p160.adaptation_field.pcr) == slot_time_27mhz(
        160, B_DEFAULT
    )
    # adaptation-only CC reuses the previous packet EMITTED on the PID
    # without advancing: seq 16 (emitted at slot 151) is the 17th payload
    # packet, so its CC wrapped to 0 (mod 16) and the PCR-only packet
    # reuses exactly that
    assert p160.continuity_counter == 0
    # slot 240: PES #13 start due exactly at the PCR due tick -> rides
    p240 = packets[240]
    assert p240.payload_unit_start_indicator
    assert pcr_to_27mhz_ticks(p240.adaptation_field.pcr) == slot_time_27mhz(
        240, B_DEFAULT
    )
    # PCR attachment did not damage the payload: PES #4 = slots 80 + 89
    assert packets[80].payload is not None and packets[89].payload is not None
    assert packets[80].payload + packets[89].payload == pes360
    # and every complete PES run reassembles byte-identically; the last
    # run (PES #16) is truncated by the run end — seq 33 is never due
    # within 300 slots, so only its 184-byte first chunk was emitted
    runs = collect_pes_runs(packets, 0x100)
    assert len(runs) == 17
    assert all(run == pes360 for run in runs[:-1])
    assert runs[-1] == pes360[:184]

    # Scenario B — adaptation_only_fallback: every PCR is adaptation-only,
    # even where a PES start is due; PES packets never carry PCR.
    config_b = make_config(
        output_packet_count=300,
        tables=make_tables(pat_period_ms=100, pmt_period_ms=100),
        pcr=make_pcr_config(
            pcr_pid=0x100, target_interval_ms=40,
            insertion_policy="adaptation_only_fallback",
        ),
        pid_rates=(
            make_pid_rate(pid=0x100, bitrate_bps=338_400, source_id="pes-src"),
        ),
    )
    mux_b = TSMux(config_b, [PESPacketSource("pes-src", 0x100, [pes360] * 40)])
    packets_b = list(mux_b.iter_packets())
    assert mux_b.summary().pcr_positions == (80, 160, 240)
    for pos, cc in ((80, 7), (160, 0), (240, 9)):
        # seq7 -> CC 7; seq16 -> 17th payload -> wraps to 0; seq25 -> 26th -> 9
        pkt = packets_b[pos]
        assert pkt.pid == 0x100 and pkt.payload is None
        assert pkt.adaptation_field is not None
        assert pcr_to_27mhz_ticks(pkt.adaptation_field.pcr) == slot_time_27mhz(
            pos, B_DEFAULT
        )
        assert pkt.continuity_counter == cc  # previous emitted payload CC
    for pkt in packets_b:
        if pkt.pid == 0x100 and pkt.payload is not None:
            assert pkt.adaptation_field is None or pkt.adaptation_field.pcr is None
    runs_b = collect_pes_runs(packets_b, 0x100)
    assert len(runs_b) == 17
    assert all(run == pes360 for run in runs_b[:-1])
    assert runs_b[-1] == pes360[:184]  # truncated by the run end (no PCR arm)

    # Scenario C — PCR_DOES_NOT_FIT fallback: 180-byte PES packets fit one
    # payload-only packet but leave no room for the 7-byte PCR field, so
    # the armed attachment fails (PACKETIZER_PCR_DOES_NOT_FIT) and the mux
    # falls back to build_pcr_only_packet at the PCR slot; the PES packet
    # is reframed WITHOUT PCR and emitted one slot later (still inside its
    # deadline).  ES rate 1.5 Mbps (C/R = 27_072 = exactly 2 slots).
    pes180 = make_pes_bytes(180)
    config_c = make_config(
        output_packet_count=30,
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=3),
        pid_rates=(
            make_pid_rate(pid=0x100, bitrate_bps=1_500_000, source_id="pes-src"),
        ),
    )
    mux_c = TSMux(
        config_c,
        make_table_sources() + [PESPacketSource("pes-src", 0x100, [pes180] * 20)],
    )
    packets_c = list(mux_c.iter_packets())
    assert mux_c.summary().pcr_positions == (6, 12, 18, 24)
    for pos, cc in ((6, 1), (12, 4), (18, 7), (24, 10)):
        pkt = packets_c[pos]
        assert pkt.pid == 0x100 and pkt.payload is None
        assert pcr_to_27mhz_ticks(pkt.adaptation_field.pcr) == slot_time_27mhz(
            pos, B_DEFAULT
        )
        assert pkt.continuity_counter == cc
    for pos in (7, 13, 19, 25):  # the displaced PES packets
        pkt = packets_c[pos]
        assert pkt.pid == 0x100 and pkt.payload == pes180
        assert pkt.adaptation_field is None or pkt.adaptation_field.pcr is None
    assert mux_c.summary().null_packet_count == 10


# --- REQ-TS-107-005 ----------------------------------------------------------


def test_mux_null_padding():
    """REQ-TS-107-005: empty slots are filled with spec-exact Null Packets."""
    from ts.packet import TSPacket
    from ts.mux.scheduler import TSMux

    config = make_config(output_packet_count=11)
    mux = TSMux(config, [])
    packets = list(mux.iter_packets())
    assert len(packets) == 11
    expected_null = b"\x47\x1f\xff\x10" + b"\xff" * 184  # testdata-ok: SPEC-107 §5.1 mandates the exact null-packet wire shape (sync/header nibbles + 0xFF filler); the constant is the spec's canonical value, not assembled fixture data
    for pkt in packets:
        assert pkt.pid == 0x1FFF
        assert pkt.continuity_counter == 0
        assert pkt.payload == b"\xff" * 184  # testdata-ok: SPEC-107 §5.1 null payload filler is fixed 0xFF by the spec text itself
        assert pkt.adaptation_field is None
        assert pkt.to_bytes() == expected_null
        assert TSPacket.from_bytes(pkt.to_bytes()) == pkt
    summary = mux.summary()
    assert summary.null_packet_count == 11
    assert summary.pcr_positions == ()

    # sparse source: 100 kbps in a 3 Mbps TS -> one ES packet at slot 30
    # (C/R = 406_080 ticks = exactly 30 slots), tables at 0/1, rest null.
    config2 = make_config(
        output_packet_count=40,
        pid_rates=(make_pid_rate(pid=0x101, bitrate_bps=100_000, source_id="es-a"),),
    )
    mux2 = TSMux(
        config2,
        make_table_sources() + [ListSource("es-a", make_es_packets(0x101, 3))],
    )
    packets2 = list(mux2.iter_packets())
    non_null = [(i, pkt) for i, pkt in enumerate(packets2) if pkt.pid != 0x1FFF]
    assert [i for i, _ in non_null] == [0, 1, 30]
    assert non_null[0][1].pid == 0x0000 and non_null[1][1].pid == 0x0020
    assert non_null[2][1].pid == 0x101
    assert mux2.summary().null_packet_count == 37


# --- REQ-TS-107-006 ----------------------------------------------------------


def test_mux_overcommit():
    """REQ-TS-107-006: config rejection and explicit runtime deadline miss."""
    import pytest as _pytest
    from ts.errors import InvalidMuxConfigError, MuxSchedulingError
    from ts.mux.codes import (
        MUX_INVALID_BITRATE,
        MUX_INVALID_PACKET_COUNT,
        MUX_PID_DUPLICATE_SOURCE,
        MUX_PID_RATE_OVERCOMMITTED,
        MUX_PACKET_DEADLINE_MISSED,
        MUX_PCR_INTERVAL_INVALID,
        MUX_TABLE_PERIOD_INVALID,
    )
    from ts.mux.scheduler import TSMux
    from ts.mux.sources import PESPacketSource

    # --- config rejections (InvalidMuxConfigError, contract §7 mapping) ---
    with _pytest.raises(InvalidMuxConfigError, match=MUX_INVALID_BITRATE):
        make_config(target_bitrate_bps=0)
    with _pytest.raises(InvalidMuxConfigError, match=MUX_INVALID_BITRATE):
        make_config(target_bitrate_bps=-1)
    with _pytest.raises(InvalidMuxConfigError, match=MUX_INVALID_PACKET_COUNT):
        make_config(output_packet_count=0)
    with _pytest.raises(InvalidMuxConfigError, match=MUX_PID_DUPLICATE_SOURCE):
        make_config(
            pid_rates=(
                make_pid_rate(pid=0x101, bitrate_bps=100_000, source_id="a"),
                make_pid_rate(pid=0x101, bitrate_bps=100_000, source_id="b"),
            )
        )
    with _pytest.raises(InvalidMuxConfigError, match=MUX_PID_DUPLICATE_SOURCE):
        make_config(
            pid_rates=(
                make_pid_rate(pid=0x101, bitrate_bps=100_000, source_id="a"),
                make_pid_rate(pid=0x102, bitrate_bps=100_000, source_id="a"),
            )
        )
    # a source with no PIDRateConfig entry cannot be scheduled
    with _pytest.raises(InvalidMuxConfigError, match=MUX_PID_DUPLICATE_SOURCE):
        TSMux(make_config(), [ListSource("es-unpaired", [])])
    with _pytest.raises(InvalidMuxConfigError, match=MUX_TABLE_PERIOD_INVALID):
        make_config(tables=make_tables(pat_period_ms=0, pmt_period_ms=100))
    with _pytest.raises(InvalidMuxConfigError, match=MUX_PCR_INTERVAL_INVALID):
        make_config(pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=0))
    with _pytest.raises(InvalidMuxConfigError, match=MUX_PID_RATE_OVERCOMMITTED):
        make_config(
            pid_rates=(
                make_pid_rate(pid=0x101, bitrate_bps=2_000_000, source_id="a"),
                make_pid_rate(pid=0x102, bitrate_bps=2_000_000, source_id="b"),
            )
        )

    # --- runtime deadline miss: three aligned 1 Mbps sources in a 3 Mbps
    #     TS (sum == capacity, config-legal).  Packets are due at slots
    #     3, 6, 9, ...; each group needs three slots but the deadline
    #     window is two, so src-c (last in the source_id tie-break)
    #     misses at slot 5 and the mux aborts with full context.
    config = make_config(
        output_packet_count=30,
        pid_rates=(
            make_pid_rate(pid=0x101, bitrate_bps=1_000_000, source_id="src-a"),
            make_pid_rate(pid=0x102, bitrate_bps=1_000_000, source_id="src-b"),
            make_pid_rate(pid=0x103, bitrate_bps=1_000_000, source_id="src-c"),
        ),
    )
    mux = TSMux(
        config,
        [
            ListSource("src-a", make_es_packets(0x101, 20)),
            ListSource("src-b", make_es_packets(0x102, 20)),
            ListSource("src-c", make_es_packets(0x103, 20)),
        ],
    )
    with _pytest.raises(MuxSchedulingError) as excinfo:
        list(mux.iter_packets())
    message = str(excinfo.value)
    assert MUX_PACKET_DEADLINE_MISSED in message
    assert "src-c" in message
    assert "slot 5" in message
    assert "3000000" in message  # target bitrate context

    # --- boundary: two sources at exactly half capacity each pack the CBR
    #     perfectly (alternating slots) with zero nulls and zero misses.
    config2 = make_config(
        output_packet_count=20,
        pid_rates=(
            make_pid_rate(pid=0x101, bitrate_bps=1_500_000, source_id="cap-a"),
            make_pid_rate(pid=0x102, bitrate_bps=1_500_000, source_id="cap-b"),
        ),
    )
    mux2 = TSMux(
        config2,
        make_table_sources()
        + [
            ListSource("cap-a", make_es_packets(0x101, 12)),
            ListSource("cap-b", make_es_packets(0x102, 12)),
        ],
    )
    packets2 = list(mux2.iter_packets())
    assert [p.pid for p in packets2] == (
        [0x0000, 0x0020] + [0x101, 0x102] * 9
    )
    assert mux2.summary().null_packet_count == 0

    # --- a PESPacketSource on the PCR PID that has no data never aborts
    #     the run: the payload-first lookup simply falls back (per-source
    #     exhaustion is not a global error, SPEC-107 §7).
    config3 = make_config(
        output_packet_count=10,
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=1),
        pid_rates=(make_pid_rate(pid=0x100, bitrate_bps=1_000_000, source_id="pes-src"),),
    )
    mux3 = TSMux(config3, [PESPacketSource("pes-src", 0x100, [])])
    packets3 = list(mux3.iter_packets())  # must not raise
    assert mux3.summary().pcr_positions == (2, 4, 6, 8)
    assert all(packets3[pos].payload is None for pos in (2, 4, 6, 8))


# --- REQ-TS-107-007 ----------------------------------------------------------


def test_mux_determinism():
    """REQ-TS-107-007: identical inputs -> byte-identical scheduling."""
    from ts.mux.scheduler import TSMux

    config = make_config(
        output_packet_count=120,
        tables=make_tables(pat_period_ms=100, pmt_period_ms=100),
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=40),
        pid_rates=(
            make_pid_rate(pid=0x100, bitrate_bps=700_000, source_id="es-a"),
            make_pid_rate(pid=0x140, bitrate_bps=400_000, source_id="es-b", priority=1),
        ),
    )

    def run(source_order):
        sources = make_table_sources(pmt_pid=0x20, es_pid=0x100) + [
            ListSource("es-a", make_es_packets(0x100, 30)),
            ListSource("es-b", make_es_packets(0x140, 20)),
        ]
        sources = [sources[i] for i in source_order]
        mux = TSMux(config, sources)
        return list(mux.iter_packets()), mux.summary(), mux

    packets1, summary1, mux_run1 = run([0, 1, 2, 3])
    packets2, summary2, _ = run([0, 1, 2, 3])
    packets3, summary3, _ = run([3, 2, 1, 0])  # permuted source list order
    bytes1 = [p.to_bytes() for p in packets1]
    bytes2 = [p.to_bytes() for p in packets2]
    bytes3 = [p.to_bytes() for p in packets3]
    assert bytes1 == bytes2 == bytes3
    assert summary1 == summary2 == summary3
    # PCR on a generic (pre-framed) source PID always falls back to
    # adaptation-only packets — deterministic positions
    assert summary1.pcr_positions == (80,)
    assert packets1[80].payload is None and packets1[80].pid == 0x100

    # the iter_packets surface is single-shot: a second call on the same
    # instance is a programming error, not a silent re-run
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        list(mux_run1.iter_packets())


# --- helper coverage: per-source exhaustion, guard invariants, offset ---


def test_mux_source_exhausted():
    """Normal source exhaustion fills nulls; a lying armed source errors."""
    import pytest as _pytest
    from ts.errors import MuxSchedulingError
    from ts.mux.codes import MUX_SOURCE_EXHAUSTED
    from ts.mux.scheduler import TSMux
    from ts.mux.sources import PESPacketSource

    # A generic source that runs dry mid-run is per-source exhaustion:
    # the mux stops scheduling it and nulls fill the rest (no error).
    config = make_config(
        output_packet_count=20,
        pid_rates=(make_pid_rate(pid=0x101, bitrate_bps=500_000, source_id="es-a"),),
    )
    mux = TSMux(
        config,
        make_table_sources() + [ListSource("es-a", make_es_packets(0x101, 3))],
    )
    packets = list(mux.iter_packets())  # must not raise
    es_slots = [i for i, p in enumerate(packets) if p.pid == 0x101]
    assert es_slots == [6, 12, 18]
    assert mux.summary().null_packet_count == 20 - 2 - 3

    # A PCR-carrying PES source that PROMISES a PES start (armed pull) but
    # delivers StopIteration breaches the per-source contract: the mux
    # reports MUX_SOURCE_EXHAUSTED naming the source, never leaking a raw
    # StopIteration.
    class _LyingPESSource(PESPacketSource):
        def next_starts_pes(self) -> bool:
            return True

    config2 = make_config(
        output_packet_count=10,
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=3),
        pid_rates=(make_pid_rate(pid=0x100, bitrate_bps=512_000, source_id="pes-src"),),
    )
    mux2 = TSMux(config2, [_LyingPESSource("pes-src", 0x100, [])])
    with _pytest.raises(MuxSchedulingError) as excinfo:
        list(mux2.iter_packets())
    assert MUX_SOURCE_EXHAUSTED in str(excinfo.value)
    assert "pes-src" in str(excinfo.value)


def test_mux_slot_count_mismatch():
    """MUX_SLOT_COUNT_MISMATCH: the one-packet-per-slot invariant is loud."""
    import pytest as _pytest
    from ts.errors import MuxSchedulingError
    from ts.mux.codes import MUX_SLOT_COUNT_MISMATCH
    from ts.mux.scheduler import TSMux

    config = make_config(output_packet_count=5)

    def _broken_null():
        return None

    import ts.mux.scheduler as scheduler_module

    original = scheduler_module.build_null_packet
    scheduler_module.build_null_packet = _broken_null
    try:
        mux = TSMux(config, [])
        with _pytest.raises(MuxSchedulingError) as excinfo:
            list(mux.iter_packets())
        assert MUX_SLOT_COUNT_MISMATCH in str(excinfo.value)
    finally:
        scheduler_module.build_null_packet = original


def test_mux_initial_media_clock_offset():
    """initial_media_clock_27mhz shifts the whole slot lattice coherently."""
    from ts.pcr import pcr_to_27mhz_ticks
    from ts.mux.scheduler import TSMux, slot_time_27mhz

    initial = 1_350_000  # 50 ms
    config = make_config(
        output_packet_count=200,
        tables=make_tables(pat_period_ms=100, pmt_period_ms=100),
        pcr=make_pcr_config(pcr_pid=0x100, target_interval_ms=40),
        initial_media_clock_27mhz=initial,
    )
    mux = TSMux(config, make_table_sources())
    packets = list(mux.iter_packets())
    # the WHOLE lattice shifts with the initial media clock: slot 0 already
    # sits at tick 1_350_000, so the first PAT/PMT repetitions (due at the
    # initial tick) land on slots 0/1 and the first PCR (due one interval
    # later, initial + 1_080_000 = 2_430_000) lands on slot 80.
    assert [i for i, p in enumerate(packets) if p.pid == 0x0000] == [0]
    assert [i for i, p in enumerate(packets) if p.pid == 0x0020] == [1]
    # PCR dues at initial + 1_080_000 = 2_430_000 (slot 80) and
    # initial + 2_160_000 = 3_510_000 (slot 160)
    assert mux.summary().pcr_positions == (80, 160)
    pcr_pkt = packets[80]
    assert pcr_pkt.pid == 0x100 and pcr_pkt.payload is None
    # the PCR VALUE carries the offset: slot_time(80) = 1_350_000 + 80*13536
    assert pcr_to_27mhz_ticks(pcr_pkt.adaptation_field.pcr) == slot_time_27mhz(
        80, B_DEFAULT, initial
    )
    assert pcr_to_27mhz_ticks(pcr_pkt.adaptation_field.pcr) == 1_350_000 + 1_082_880
    assert mux.summary().null_packet_count == 200 - 2 - 2
