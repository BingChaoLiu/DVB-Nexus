"""SPEC-108 — TS Generator — unit tests (ticket #34).

Traceability (docs/spec/.../ts-core/TRACEABILITY.md, SPEC-108 section):

- REQ-TS-108-001  GeneratorConfig 校验               -> test_generator_config_validation
- REQ-TS-108-002  生成 188-byte TS                   -> test_generator_packet_format
- REQ-TS-108-003  PAT/PMT/PES/PCR 可回读             -> test_generator_self_parse
- REQ-TS-108-004  CBR/packet slot 符合配置           -> test_generator_mux_integration
- REQ-TS-108-005  相同输入 SHA-256 相同              -> test_generator_determinism
- REQ-TS-108-006  Generator 与 Fault Injector 解耦   -> test_generator_clean_baseline
- REQ-TS-108-007  analysis_only 边界明确             -> test_generator_profile
- REQ-TS-108-008  TSDuck 集成报告有真实证据          -> test_tsduck_integration
                                                    (+ test_tsduck_real_run_blocked_until_ticket_35)

Every expected value is hand-derived from the frozen integer arithmetic of
the upstream tickets (never recomputed through the generator itself):

- slot lattice (SPEC-107 §3.1): ``slot_time(n) = initial + floor(n * 1504 *
  27e6 / B)``; the PCR carrier claims the first slot with
  ``slot_time >= pcr_due_tick`` and its decoded value equals that slot time
  (mux stamps ``pcr_from_27mhz_ticks(slot_time)``, ruling #11).
- table repetitions are due at ``initial + r * period_ticks`` (r >= 0), so
  the emitted repetition count over ``N`` slots is exactly
  ``floor(slot_time(N-1) / period_ticks) + 1``.
- per-source release (SPEC-107 §5.1): packet ``k`` of an ``R`` bps source is
  due at ``floor((k+1) * 1504 * 27e6 / R)``; over ``N`` slots the source can
  emit at most ``floor(N * R / B) + 1`` packets, minus the slots stolen by
  table/PCR carriers (each steals at most one emission opportunity and the
  pending packet emits within its one-slot deadline window).
- PES budget (SPEC-108 §7 step 4): ``((N*R)//B + 4) * 184`` serialized bytes
  so an ES source never dries up mid-run (a dry source would silently
  null-fill its slots and break the CBR promise).

Default test geometry — hand-proven pull-safe for the frozen SPEC-107
deadline window (a packet pulled at slot ``n`` must emit at ``n`` or
``n+1``, else the mux aborts with ``MUX_PACKET_DEADLINE_MISSED``; any slot
with >=3 pulls, or two consecutive slots with 2 pulls each, is fatal):

- ``B = 3_008_000`` -> slot = ``40_608_000_000 / 3_008_000 = 13_500`` ticks
  = exactly 0.5 ms, so ``1 ms = 2`` slots.
- PAT 101 ms / PMT 103 ms -> repetition grids 202 / 206 slots; lcm(202, 206)
  = 20_806 slots, so within any test run the two tables coincide only at
  slot 0 (2 pulls, deadline window 2 — safe; the first ES pull is slot 25).
- ES rates ``B/25 = 120_320`` and ``B/50 = 60_160`` -> exact pull slots at
  multiples of 25 / 50 (ES2 ⊂ ES1 slots, so coincidences are exactly 2
  pulls), and no multiple of 25/50 is a PAT/PMT repetition slot.
- PCR 40 ms = 80 slots -> claims at 80k; within the 600-slot runs only slot
  400 meets an ES pull, where ES1's seq 15 is a PES start (payload-first
  ride); the ES2 packet pulled there emits at slot 401 inside its window.

(The systemic constraint behind this choice — the frozen mux deadline
window makes "natural" round-rate configurations with coincident PAT/PMT
repetitions abort, e.g. the SPEC-108 §4 default periods with a 2 Mbps ES
miss at slots 200/399/599 — is reported in the ticket #34 implementation
report as a SPEC-107/#33 semantics question; the mux abort is loud, never
silent.)

The JSON mapping literals follow the SPEC-108 §4 table verbatim (ruling
#11: snake_case, hex for bytes fields).  ``ts.*`` modules are imported
inside the tests that need them (so the RED phase is per-test, not a
collection error) — test_mux.py precedent.  Unit layer discipline
(SPEC-505 §8): no I/O, no wall clock, no subprocess; sinks are in-memory
objects and hashing is ``hashlib`` (no ``hash()``).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, replace

import pytest

pytestmark = pytest.mark.unit

# --- exact integer scheduling arithmetic (SPEC-107 §3.1, hand-rolled) -------

_SLOT_BITS = 1504
_TICKS_27MHZ_PER_S = 27_000_000
_C = _SLOT_BITS * _TICKS_27MHZ_PER_S  # 40_608_000_000 ticks*bit / s
_TICKS_PER_MS = 27_000

B_DEFAULT = 3_008_000  # -> slot = 13_500 ticks = 0.5 ms exactly
_SLOT_DEFAULT = _C // B_DEFAULT  # 13_500 ticks — exact


def slot_time(n: int, bitrate: int = B_DEFAULT, initial: int = 0) -> int:
    """Hand-rolled SPEC-107 §3.1 slot formula (floor, exact integers)."""
    return initial + (n * _C) // bitrate


def first_slot_at_least(
    tick: int, bitrate: int = B_DEFAULT, initial: int = 0
) -> int:
    """Smallest slot index n with slot_time(n) >= tick (exact integers)."""
    return -(-((tick - initial) * bitrate) // _C)


def table_repetitions(last_slot_tick: int, period_ms: int) -> int:
    """Emitted repetition count: r*period <= last_slot_tick, r >= 0."""
    return last_slot_tick // (period_ms * _TICKS_PER_MS) + 1


def pcr_slots_for_run(
    output_packet_count: int,
    interval_ms: int,
    bitrate: int = B_DEFAULT,
    initial: int = 0,
) -> tuple[int, ...]:
    """Hand-derived PCR slot indices: first slot >= (k+1)*interval ticks."""
    slots: list[int] = []
    k = 0
    last = slot_time(output_packet_count - 1, bitrate, initial)
    while True:
        due = initial + (k + 1) * interval_ms * _TICKS_PER_MS
        index = first_slot_at_least(due, bitrate, initial)
        if due > last or index >= output_packet_count:
            return tuple(slots)
        slots.append(index)
        k += 1


# --- deterministic config builders (SPEC-108 §4 shapes) ----------------------


def make_es1(**overrides):
    """Video-flavoured ES on PID 256 carrying the PCR (B/25 = 120_320 bps).

    ``C/R = 337_500`` ticks = exactly 25 slots, so pull slots are the
    multiples of 25 — the hand-proven pull-safe grid (see module docstring).
    """
    from ts.generator.config import ElementaryStreamConfig

    values = dict(
        pid=256,
        stream_type=27,  # 0x1B, AVC — declaration matches config (§2)
        stream_id=0xE0,
        bitrate_bps=120_320,
        payload_profile="synthetic_test_data",
        payload_seed_offset=0,
    )
    values.update(overrides)
    return ElementaryStreamConfig(**values)


def make_es2(**overrides):
    """Audio-flavoured ES on PID 257 (B/50 = 60_160 bps, other seed offset).

    ``C/R = 675_000`` ticks = exactly 50 slots; pull slots (multiples of 50)
    are a subset of ES1's, so ES-ES coincidences are exactly 2 pulls.
    """
    from ts.generator.config import ElementaryStreamConfig

    values = dict(
        pid=257,
        stream_type=3,
        stream_id=0xC0,
        bitrate_bps=60_160,
        payload_profile="synthetic_test_data",
        payload_seed_offset=1,
    )
    values.update(overrides)
    return ElementaryStreamConfig(**values)


def make_program(**overrides):
    from ts.generator.config import ProgramConfig

    values = dict(
        transport_stream_id=1,
        program_number=1,
        pmt_pid=4096,
        pcr_pid=256,  # rides ES1 (allowed reuse, SPEC-108 §5)
        version_number=0,
        streams=(make_es1(), make_es2()),
        program_descriptors=b"",
    )
    values.update(overrides)
    return ProgramConfig(**values)


def make_config(**overrides):
    """The default test config: the hand-proven pull-safe geometry (N=600)."""
    from ts.generator.config import GeneratorConfig

    values = dict(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=1234567,
        initial_media_clock_27mhz=0,
        target_bitrate_bps=B_DEFAULT,
        output_packet_count=600,
        program=make_program(),
        pat_period_ms=101,
        pmt_period_ms=103,
        pcr_interval_ms=40,
        pcr_insertion_policy="payload_packet_first",
    )
    values.update(overrides)
    return GeneratorConfig(**values)


class MemorySink:
    """Minimal ``write(bytes)`` sink (SPEC-108 §6) recording every chunk."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.chunks.append(bytes(data))
        return len(data)


def run_generator(config):
    """generate_to into a MemorySink; return (sink, summary)."""
    from ts.generator.generator import TSGenerator

    sink = MemorySink()
    summary = TSGenerator().generate_to(config, sink)
    return sink, summary


def run_bytes(config):
    """generate_to into a MemorySink; return (list of 188-byte chunks, summary)."""
    sink, summary = run_generator(config)
    return sink.chunks, summary


def sha256_of(chunks) -> str:
    return hashlib.sha256(b"".join(chunks)).hexdigest()


def split_packets(chunks):
    """Strict-parse every 188-byte chunk into TSPacket objects."""
    from ts.packet import TSPacket

    return [TSPacket.from_bytes(chunk) for chunk in chunks]


def parse_tables_from(packets, pid: int, policy):
    """Collect PSI sections from one PID via the SPEC-102 assembler."""
    from ts.section_assembler import SectionAssembler

    assembler = SectionAssembler(pid, lambda table_id: policy)
    sections: list = []
    for packet in packets:
        sections.extend(assembler.push(packet))
    issues = assembler.flush()
    assert issues == []
    return sections


def reassemble_pes(packets, pid: int):
    """Reassemble PES packets from one PID's stream order (SPEC-104)."""
    from ts.pes_assembler import PESAssembler

    assembler = PESAssembler(pid, max_buffer_bytes=1 << 20)
    out: list = []
    for packet in packets:
        if packet.pid == pid:
            out.extend(assembler.push(packet))
    issues = assembler.flush()
    return out, issues


# --- REQ-TS-108-001: typed config validation ---------------------------------


def test_generator_config_validation():
    from ts.errors import GenerationError
    from ts.generator.codes import (
        GENERATOR_INVALID_BITRATE,
        GENERATOR_INVALID_PACKET_COUNT,
        GENERATOR_INVALID_PROGRAM_CONFIG,
        GENERATOR_NONDETERMINISTIC_SOURCE,
        GENERATOR_PID_COLLISION,
        GENERATOR_PROFILE_UNSUPPORTED,
        GENERATOR_RATE_OVERCOMMITTED,
        GENERATOR_SCHEMA_VERSION_UNSUPPORTED,
    )
    from ts.generator.generator import TSGenerator
    from ts.generator.validator import validate_config

    # A fully valid config produces no findings at all.
    assert validate_config(make_config()) == []

    # Hand-mapped §5 violations -> §10 codes (mapping documented in the
    # validator docstring; every issue is severity="error" and field-named).
    es_reserved = make_es1(pid=0x0010)  # ISO/DVB PSI reserved PID
    cases = [
        # (mutator, expected code, expected field)
        (lambda c: replace(c, schema_version=2), GENERATOR_SCHEMA_VERSION_UNSUPPORTED, "schema_version"),
        (lambda c: replace(c, schema_version=0), GENERATOR_SCHEMA_VERSION_UNSUPPORTED, "schema_version"),
        (lambda c: replace(c, profile="playback_ready"), GENERATOR_PROFILE_UNSUPPORTED, "profile"),
        (lambda c: replace(c, profile=""), GENERATOR_PROFILE_UNSUPPORTED, "profile"),
        (lambda c: replace(c, deterministic=False), GENERATOR_NONDETERMINISTIC_SOURCE, "deterministic"),
        (lambda c: replace(c, output_packet_count=0), GENERATOR_INVALID_PACKET_COUNT, "output_packet_count"),
        (lambda c: replace(c, output_packet_count=-5), GENERATOR_INVALID_PACKET_COUNT, "output_packet_count"),
        (lambda c: replace(c, target_bitrate_bps=0), GENERATOR_INVALID_BITRATE, "target_bitrate_bps"),
        (lambda c: replace(c, target_bitrate_bps=-1), GENERATOR_INVALID_BITRATE, "target_bitrate_bps"),
        # ADR-0008 §2 frozen envelope: 1..100 Mbps.
        (lambda c: replace(c, target_bitrate_bps=100_000_001), GENERATOR_INVALID_BITRATE, "target_bitrate_bps"),
        (lambda c: replace(c, initial_media_clock_27mhz=-1), GENERATOR_INVALID_PROGRAM_CONFIG, "initial_media_clock_27mhz"),
        (lambda c: replace(c, pat_period_ms=0), GENERATOR_INVALID_PROGRAM_CONFIG, "pat_period_ms"),
        (lambda c: replace(c, pmt_period_ms=-1), GENERATOR_INVALID_PROGRAM_CONFIG, "pmt_period_ms"),
        (lambda c: replace(c, pcr_interval_ms=0), GENERATOR_INVALID_PROGRAM_CONFIG, "pcr_interval_ms"),
        (lambda c: replace(c, pcr_insertion_policy="always"), GENERATOR_INVALID_PROGRAM_CONFIG, "pcr_insertion_policy"),
        # Program-level field widths (§5: TSID/program_number/stream_type/stream_id).
        (lambda c: replace(c, program=replace(c.program, program_number=0)), GENERATOR_INVALID_PROGRAM_CONFIG, "program_number"),
        (lambda c: replace(c, program=replace(c.program, transport_stream_id=0x10000)), GENERATOR_INVALID_PROGRAM_CONFIG, "transport_stream_id"),
        (lambda c: replace(c, program=replace(c.program, version_number=32)), GENERATOR_INVALID_PROGRAM_CONFIG, "version_number"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(stream_id=256), make_es2()))), GENERATOR_INVALID_PROGRAM_CONFIG, "stream_id"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(stream_id=0xBE), make_es2()))), GENERATOR_INVALID_PROGRAM_CONFIG, "stream_id"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(stream_type=256), make_es2()))), GENERATOR_INVALID_PROGRAM_CONFIG, "stream_type"),
        # payload_profile is the analysis-only boundary marker (§2).
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(payload_profile="h264_real"), make_es2()))), GENERATOR_INVALID_PROGRAM_CONFIG, "payload_profile"),
        # Descriptor space must fit the single-section PMT (§5 + SPEC-103 §7).
        # 1000 procedurally generated descriptor bytes (fixed formula, never
        # a repeated literal).
        (lambda c: replace(c, program=replace(c.program, program_descriptors=bytes((i * 7 + 5) & 0xFF for i in range(1000)))), GENERATOR_INVALID_PROGRAM_CONFIG, "program_descriptors"),
        # PID policy: reserved PIDs and pairwise collisions (§5).
        (lambda c: replace(c, program=replace(c.program, streams=(es_reserved, make_es2()))), GENERATOR_PID_COLLISION, "pid"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(pid=0x1FFF), make_es2()))), GENERATOR_PID_COLLISION, "pid"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(pid=0x0000), make_es2()))), GENERATOR_PID_COLLISION, "pid"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(pid=4096), make_es2()))), GENERATOR_PID_COLLISION, "pid"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(), make_es2(pid=256)))), GENERATOR_PID_COLLISION, "pid"),
        (lambda c: replace(c, program=replace(c.program, pmt_pid=0x0000)), GENERATOR_PID_COLLISION, "pmt_pid"),
        (lambda c: replace(c, program=replace(c.program, pmt_pid=0x1FFF)), GENERATOR_PID_COLLISION, "pmt_pid"),
        (lambda c: replace(c, program=replace(c.program, pcr_pid=4096)), GENERATOR_PID_COLLISION, "pcr_pid"),
        (lambda c: replace(c, program=replace(c.program, pcr_pid=0x1FFF)), GENERATOR_PID_COLLISION, "pcr_pid"),
        # ES bitrate per-stream width/sign (§5).
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(bitrate_bps=0), make_es2()))), GENERATOR_INVALID_BITRATE, "bitrate_bps"),
        (lambda c: replace(c, program=replace(c.program, streams=(make_es1(bitrate_bps=-1), make_es2()))), GENERATOR_INVALID_BITRATE, "bitrate_bps"),
        # Rate fit: ES sum + conservative table/PCR overhead must fit target
        # (§5): the default geometry needs 180_480 + 67_680 = 248_160 bps,
        # so a 240_000 bps target is provably infeasible.
        (lambda c: replace(c, target_bitrate_bps=240_000), GENERATOR_RATE_OVERCOMMITTED, "target_bitrate_bps"),
    ]
    for mutator, expected_code, expected_field in cases:
        config = mutator(make_config())
        issues = validate_config(config)
        errors = [issue for issue in issues if issue.severity == "error"]
        assert errors, f"expected an error issue for {expected_code}"
        assert errors[0].code == expected_code, (
            f"expected {expected_code}, got "
            f"{[i.code for i in errors]} (field {expected_field})"
        )
        assert errors[0].field == expected_field
        # generate_to refuses invalid configs instead of faking a summary
        # (§7 step 9: no pseudo-success).
        with pytest.raises(GenerationError) as excinfo:
            run_generator(config)
        assert expected_code in str(excinfo.value)

    # iter_packets refuses with the same discipline.
    with pytest.raises(GenerationError):
        list(TSGenerator().iter_packets(replace(make_config(), profile="playback_ready")))

    # Allowed edge: PCR_PID may reuse one ES PID (§5) — already the default
    # config; and the target exactly fitting ES sum + overhead is accepted.
    base = make_config()
    overhead_bps = _SLOT_BITS * (
        -(-1000 // base.pat_period_ms)
        + -(-1000 // base.pmt_period_ms)
        + -(-1000 // base.pcr_interval_ms)
    )
    es_sum = sum(stream.bitrate_bps for stream in base.program.streams)
    tight_target = es_sum + overhead_bps
    assert validate_config(make_config(target_bitrate_bps=tight_target)) == []


# --- REQ-TS-108-002: fixed 188-byte packet output -----------------------------


def test_generator_packet_format():
    from ts.generator.generator import GENERATOR_VERSION

    config = make_config(output_packet_count=50)
    sink, summary = run_generator(config)

    # Exactly output_packet_count writes, each exactly 188 bytes, each
    # starting with the sync byte (§9: file size is a multiple of 188).
    assert len(sink.chunks) == 50
    assert all(len(chunk) == 188 for chunk in sink.chunks)
    assert all(chunk[0] == 0x47 for chunk in sink.chunks)

    assert summary.packet_count == 50
    assert summary.byte_count == 50 * 188
    assert summary.target_bitrate_bps == B_DEFAULT
    assert summary.generator_version == GENERATOR_VERSION
    assert isinstance(summary.generator_version, str) and summary.generator_version

    # iter_packets() and generate_to() walk the same deterministic stream.
    from ts.generator.generator import TSGenerator

    iterated = list(TSGenerator().iter_packets(config))
    assert len(iterated) == 50
    assert [pkt.to_bytes() for pkt in iterated] == sink.chunks


# --- REQ-TS-108-003: self-parse round trip ------------------------------------


def test_generator_self_parse():
    from ts.generator.sources import (
        SyntheticPESSource,
        synthetic_pes_byte_budget,
    )
    from ts.pes import serialize_pes
    from ts.tables.pat import PAT_SECTION_POLICY, PATProgram, parse_pat
    from ts.tables.pmt import PMT_SECTION_POLICY, parse_pmt

    config = make_config(output_packet_count=600)
    chunks, summary = run_bytes(config)
    packets = split_packets(chunks)
    assert len(packets) == 600

    # PAT round trip: identity fields and the single program association.
    pat_sections = parse_tables_from(packets, 0x0000, PAT_SECTION_POLICY)
    expected_pat_reps = table_repetitions(slot_time(599), config.pat_period_ms)
    assert len(pat_sections) == expected_pat_reps
    pat = parse_pat(pat_sections[0])
    assert pat.transport_stream_id == 1
    assert pat.version_number == 0
    assert pat.current_next_indicator is True
    assert pat.programs == (PATProgram(1, 4096),)

    # PMT round trip: PCR PID association and the declared ES loop.
    pmt_sections = parse_tables_from(packets, 4096, PMT_SECTION_POLICY)
    assert len(pmt_sections) == table_repetitions(
        slot_time(599), config.pmt_period_ms
    )
    pmt = parse_pmt(pmt_sections[0])
    assert pmt.program_number == 1
    assert pmt.pcr_pid == 256
    assert [(s.stream_type, s.elementary_pid) for s in pmt.streams] == [
        (27, 256),
        (3, 257),
    ]

    # PES reassembly: PESAssembler reproduces the generator's source bytes
    # (SPEC-108 §11: "与 Generator Source 一致"), tail truncation excepted.
    es1 = config.program.streams[0]
    es2 = config.program.streams[1]
    expected_es1 = list(
        SyntheticPESSource(
            stream_config=es1,
            seed=config.seed,
            initial_media_clock_27mhz=config.initial_media_clock_27mhz,
            byte_budget=synthetic_pes_byte_budget(
                600, config.target_bitrate_bps, es1.bitrate_bps
            ),
        ).iter_pes()
    )
    expected_es2 = list(
        SyntheticPESSource(
            stream_config=es2,
            seed=config.seed,
            initial_media_clock_27mhz=config.initial_media_clock_27mhz,
            byte_budget=synthetic_pes_byte_budget(
                600, config.target_bitrate_bps, es2.bitrate_bps
            ),
        ).iter_pes()
    )
    for pid, expected_items in ((256, expected_es1), (257, expected_es2)):
        reassembled, issues = reassemble_pes(packets, pid)
        # Only the tail of the run may truncate (run ends mid-PES); everything
        # complete matches the source byte-for-byte.
        assert len(issues) <= 1
        assert all(issue.code == "PES_TRUNCATED_AT_EOF" for issue in issues)
        assert len(reassembled) >= 1
        for got, want in zip(reassembled, expected_items):
            assert serialize_pes(got) == serialize_pes(want)
        assert len(reassembled) <= len(expected_items)

    # PCR round trip: decodable, strictly increasing, and every value equals
    # the exact emission slot time (the mux stamps slot_time).
    interval_ticks = 40 * _TICKS_PER_MS
    expected_slots = pcr_slots_for_run(600, 40)
    observed_slots = []
    observed_ticks = []
    for index, packet in enumerate(packets):
        af = packet.adaptation_field
        if packet.pid == 256 and af is not None and af.pcr is not None:
            observed_slots.append(index)
            observed_ticks.append(af.pcr.ticks_27mhz)
    assert tuple(observed_slots) == expected_slots
    assert tuple(summary.pcr_packet_indices) == expected_slots
    assert observed_ticks == [slot_time(index) for index in observed_slots]
    assert len(observed_slots) >= 2
    for before, after in zip(observed_ticks, observed_ticks[1:]):
        delta = after - before
        assert interval_ticks <= delta <= interval_ticks + _SLOT_DEFAULT


# --- REQ-TS-108-004: CBR / packet-slot conformance ----------------------------


def test_generator_mux_integration():
    config = make_config(output_packet_count=600)
    chunks, summary = run_bytes(config)

    counts = summary.pid_packet_counts
    # Every emitted packet lands in exactly one PID bucket; the null PID is
    # registered as a stat (never as a business ES).
    assert sum(counts.values()) == 600
    assert counts.get(0x1FFF, 0) == summary.null_packet_count
    assert 0x1FFF not in {stream.pid for stream in config.program.streams}

    # PAT/PMT repetitions land exactly on the hand-derived repetition count
    # (MVP tables are single-packet sections).
    last_tick = slot_time(599)
    assert counts[0x0000] == table_repetitions(last_tick, config.pat_period_ms)
    assert counts[4096] == table_repetitions(last_tick, config.pmt_period_ms)

    # ES packet share matches the configured rate within the slot-stealing
    # bound (steals = table reps + PCR carriers + deadline slack); the
    # shares derive from the config rates, never hardcoded.
    es1_share = 600 * config.program.streams[0].bitrate_bps // B_DEFAULT
    es2_share = 600 * config.program.streams[1].bitrate_bps // B_DEFAULT
    pcr_count = len(summary.pcr_packet_indices)
    steals = counts[0x0000] + counts[4096] + pcr_count + 2
    assert es1_share - steals <= counts[256] <= es1_share + 1 + pcr_count
    assert es2_share - steals <= counts[257] <= es2_share + 1

    # PCR slots are exactly the first slot at or after each due tick.
    assert summary.pcr_packet_indices == pcr_slots_for_run(600, 40)

    # Null packets fill exactly the idle slots (§11: "Null Packet 统计与
    # 空闲 slot 一致").
    non_null = sum(count for pid, count in counts.items() if pid != 0x1FFF)
    assert summary.null_packet_count == 600 - non_null
    assert summary.null_packet_count > 0


# --- REQ-TS-108-005: byte-level determinism ------------------------------------


def test_generator_determinism():
    from ts.pes import serialize_pes

    chunks_a, summary_a = run_bytes(make_config())
    chunks_b, summary_b = run_bytes(make_config())

    # Same normalized config + seed + initial clock => byte-identical output.
    assert sha256_of(chunks_a) == sha256_of(chunks_b)
    assert summary_a == summary_b

    # Changing the seed only moves the synthetic payload bytes: the protocol
    # frames (PAT/PMT repetitions, PCR slots) stay byte-identical.
    chunks_c, _ = run_bytes(make_config(seed=7654321))
    assert sha256_of(chunks_c) != sha256_of(chunks_a)
    packets_a = split_packets(chunks_a)
    packets_c = split_packets(chunks_c)
    pat_a = [p.to_bytes() for p in packets_a if p.pid == 0x0000]
    pat_c = [p.to_bytes() for p in packets_c if p.pid == 0x0000]
    assert pat_a == pat_c
    pmt_a = [p.to_bytes() for p in packets_a if p.pid == 4096]
    pmt_c = [p.to_bytes() for p in packets_c if p.pid == 4096]
    assert pmt_a == pmt_c
    pes_a, _ = reassemble_pes(split_packets(chunks_a), 257)
    pes_c, _ = reassemble_pes(split_packets(chunks_c), 257)
    assert pes_a[0].payload != pes_c[0].payload

    # Changing the initial media clock moves the PCR/PTS protocol values.
    chunks_d, _ = run_bytes(make_config(initial_media_clock_27mhz=1_000_000))
    assert sha256_of(chunks_d) != sha256_of(chunks_a)

    # A fresh TSGenerator instance changes nothing (no hidden run state).
    chunks_e, _ = run_bytes(make_config())
    assert sha256_of(chunks_e) == sha256_of(chunks_a)

    # The generator never touches the wall clock for protocol fields: the
    # run is reproducible here and the implementation imports no time source
    # (structural import purity is enforced by lint-imports contract 1; the
    # byte-level proof is this repeated-run equality).


# --- REQ-TS-108-006: clean baseline, no fault branches -------------------------


def test_generator_clean_baseline():
    from ts.packet import PID_NULL

    chunks, _ = run_bytes(make_config(output_packet_count=600))
    packets = split_packets(chunks)

    # Strict parse succeeds for every packet; no transport errors, no
    # discontinuity markers anywhere in the baseline stream.
    for packet in packets:
        assert packet.transport_error_indicator is False
        af = packet.adaptation_field
        assert af is None or af.discontinuity_indicator is False

    # Table PIDs re-emit byte-identical repetition packets (the mux never
    # re-frames; upstream #33 frozen semantics).
    table_pids = (0x0000, 4096)
    for pid in table_pids:
        variants = {packet.to_bytes() for packet in packets if packet.pid == pid}
        assert len(variants) == 1, f"PID {pid:#06x} carries mutated repetitions"

    # Null packets are the canonical filler (PID 0x1FFF, CC 0, 0xFF body) —
    # compared against the SPEC-107 §5.1 builder constants, never
    # hand-assembled bytes.
    from ts.mux.null_packet import NULL_PACKET_CC, NULL_PACKET_PAYLOAD

    nulls = [packet for packet in packets if packet.pid == PID_NULL]
    assert nulls
    for packet in nulls:
        assert packet.continuity_counter == NULL_PACKET_CC
        assert packet.payload == NULL_PACKET_PAYLOAD

    # ES PIDs walk the CC rule: payload packets advance +1 (mod 16) in wire
    # order; adaptation-only PCR carriers repeat the last payload CC.
    es_pids = {256, 257}
    last_payload_cc: dict[int, int] = {}
    for packet in packets:
        pid = packet.pid
        if pid in table_pids or pid == PID_NULL:
            continue
        if packet.payload is None:
            assert pid in last_payload_cc
            assert packet.continuity_counter == last_payload_cc[pid]
            continue
        expected = last_payload_cc.get(pid)
        expected = 0 if expected is None else (expected + 1) % 16
        assert packet.continuity_counter == expected, (
            f"CC discontinuity on PID {pid:#06x}"
        )
        last_payload_cc[pid] = packet.continuity_counter
    assert set(last_payload_cc) == es_pids

    # Structural isolation (REQ-TS-108-006): a fresh import of the generator
    # package pulls in no faults package and no adapter (ADR-0007: the
    # semantic fault filter lives downstream of the Generator->sink edge;
    # TSDuck stays behind the adapters boundary).
    import importlib

    before = set(sys.modules)
    for name in [
        name
        for name in list(sys.modules)
        if name == "ts.generator" or name.startswith("ts.generator.")
    ]:
        del sys.modules[name]
    importlib.import_module("ts.generator")
    importlib.import_module("ts.generator.generator")
    fresh = set(sys.modules) - before
    offenders = [
        name
        for name in fresh
        if name == "faults"
        or name.startswith("faults.")
        or name.startswith("adapters.")
    ]
    assert offenders == []


# --- REQ-TS-108-007: analysis_only profile boundary ----------------------------


def test_generator_profile():
    from ts.errors import GenerationError
    from ts.generator.codes import GENERATOR_PROFILE_UNSUPPORTED
    from ts.generator.generator import GenerationSummary, TSGenerator
    from ts.pes import ANALYSIS_ONLY_PROFILE_METADATA
    from ts.tables.pat import PAT_SECTION_POLICY, PATProgram, parse_pat
    from ts.tables.pmt import PMT_SECTION_POLICY, parse_pmt

    config = make_config(output_packet_count=120)
    assert config.profile == "analysis_only"

    # MVP accepts only the analysis_only profile (§2).
    from ts.generator.validator import validate_config

    for bad_profile in ("playback_ready", "analysis", ""):
        bad = replace(config, profile=bad_profile)
        errors = [
            issue for issue in validate_config(bad) if issue.severity == "error"
        ]
        assert errors[0].code == GENERATOR_PROFILE_UNSUPPORTED
        with pytest.raises(GenerationError):
            sink = MemorySink()
            TSGenerator().generate_to(bad, sink)

    # The payload boundary: synthetic test data only; playback is a future
    # capability this spec does not implement (§2 + REQ-TS-104-006 metadata).
    assert make_es1().payload_profile == "synthetic_test_data"
    assert ANALYSIS_ONLY_PROFILE_METADATA.playback_ready is False
    assert ANALYSIS_ONLY_PROFILE_METADATA.payload_is_synthetic is True

    # The summary/report surface makes no playback claim (§9): the frozen
    # §6 field set exactly, and PES packets carry the analysis-only mark.
    sink, summary = run_generator(config)
    assert isinstance(summary, GenerationSummary)
    field_names = set(asdict(summary).keys())
    assert field_names == {
        "packet_count",
        "byte_count",
        "target_bitrate_bps",
        "null_packet_count",
        "pcr_packet_indices",
        "pid_packet_counts",
        "generator_version",
    }
    assert not any("playback" in name for name in field_names)

    # PMT stream_type declarations match the configuration exactly (§2) and
    # the payload stays synthetic (parsed PES payload is the deterministic
    # formula bytes, never a real codec bitstream claim).
    packets = split_packets(sink.chunks)
    pmt = parse_pmt(parse_tables_from(packets, 4096, PMT_SECTION_POLICY)[0])
    declared = {s.elementary_pid: s.stream_type for s in pmt.streams}
    assert declared == {
        stream.pid: stream.stream_type for stream in config.program.streams
    }
    pat = parse_pat(parse_tables_from(packets, 0x0000, PAT_SECTION_POLICY)[0])
    assert pat.programs == (PATProgram(1, 4096),)


# --- REQ-TS-108-008: TSDuck integration interface ------------------------------


def test_tsduck_integration():
    """Artifact + self-parse comparison seam the TSDuck adapter consumes.

    The real ``tsp -I null … tsanalyze --json`` command, its version/exit
    code and the field-by-field comparison report are ticket #35 scope
    (SPEC-108 §11/§13: TS Core never starts TSDuck).  This primary test
    executes and passes the *interface* obligations: a stable artifact with
    the packet-size invariants, a JSON-mappable config (SPEC-500 DTO seam)
    and a JSON-serializable self-parse evidence shape for the analyzer
    comparison.

    Cross-reference (REQ-TS-108-008): the real-machine ``tsanalyze --json``
    evidence lives in ``tests/integration/ts/test_cbr_end_to_end.py`` — this
    unit-layer test is the interface / self-parse evidence (repo-side note
    for the TRACEABILITY primary-name mapping; the real-run obligation was
    absorbed by the integration ticket #35 evidence, so no permanent skip
    placeholder is kept here per SPEC-506 §6).
    """
    from ts.generator.generator import GENERATOR_VERSION
    from ts.generator.json_map import (
        generator_config_from_json,
        generator_config_to_json,
    )
    from ts.tables.pat import PAT_SECTION_POLICY, parse_pat
    from ts.tables.pmt import PMT_SECTION_POLICY, parse_pmt

    config = make_config(output_packet_count=120)
    chunks, summary = run_bytes(config)
    artifact = b"".join(chunks)

    # Artifact invariants the adapter relies on (§9).
    assert len(artifact) == 120 * 188
    assert len(artifact) % 188 == 0
    assert all(chunk[0] == 0x47 for chunk in chunks)

    # Config DTO seam: the §4 JSON mapping round-trips (snake_case, hex
    # bytes) — the same shape a SPEC-500 Pydantic DTO will delegate to.
    json_text = json.dumps(generator_config_to_json(config))
    assert generator_config_from_json(json.loads(json_text)) == config

    # Summary surface is JSON-serializable evidence.
    summary_json = json.loads(json.dumps(asdict(summary)))
    assert summary_json["packet_count"] == 120
    assert summary_json["null_packet_count"] == summary.null_packet_count
    assert summary_json["generator_version"] == GENERATOR_VERSION

    # Self-parse comparison fields (§11: PAT/PMT/PES/PCR 对照面).
    packets = split_packets(chunks)
    pat = parse_pat(parse_tables_from(packets, 0x0000, PAT_SECTION_POLICY)[0])
    pmt = parse_pmt(parse_tables_from(packets, 4096, PMT_SECTION_POLICY)[0])
    pes_items, pes_issues = reassemble_pes(packets, 256)
    evidence = {
        "generator_version": summary.generator_version,
        "packet_count": summary.packet_count,
        "pat": {
            "transport_stream_id": pat.transport_stream_id,
            "programs": [
                [p.program_number, p.program_map_pid] for p in pat.programs
            ],
            "section_count": len(
                parse_tables_from(packets, 0x0000, PAT_SECTION_POLICY)
            ),
        },
        "pmt": {
            "program_number": pmt.program_number,
            "pcr_pid": pmt.pcr_pid,
            "streams": [
                [s.stream_type, s.elementary_pid] for s in pmt.streams
            ],
        },
        "pes": {
            "reassembled_count": len(pes_items),
            "tail_issue_codes": [issue.code for issue in pes_issues],
        },
        "pcr": {
            "indices": list(summary.pcr_packet_indices),
            "interval_ms": config.pcr_interval_ms,
        },
    }
    rendered = json.dumps(evidence)
    assert json.loads(rendered)["pmt"]["pcr_pid"] == 256
    assert evidence["pes"]["reassembled_count"] >= 1


# --- JSON↔DTO mapping table conformance (ruling #11 / SPEC-108 §4) ------------


def test_generator_json_mapping_table():
    from ts.generator.json_map import (
        generator_config_from_json,
        generator_config_to_json,
    )

    payload = {
        "schema_version": 1,
        "profile": "analysis_only",
        "deterministic": True,
        "seed": 42,
        "initial_media_clock_27mhz": 27000,
        "target_bitrate_bps": 3008000,
        "output_packet_count": 600,
        "program": {
            "transport_stream_id": 1,
            "program_number": 1,
            "pmt_pid": 4096,
            "pcr_pid": 256,
            "version_number": 0,
            "program_descriptors": "5051",
            "streams": [
                {
                    "pid": 256,
                    "stream_type": 27,
                    "stream_id": 224,
                    "bitrate_bps": 120320,
                    "payload_profile": "synthetic_test_data",
                    "payload_seed_offset": 0,
                },
                {
                    "pid": 257,
                    "stream_type": 3,
                    "stream_id": 192,
                    "bitrate_bps": 60160,
                    "payload_profile": "synthetic_test_data",
                    "payload_seed_offset": 7,
                },
            ],
        },
        "pat_period_ms": 101,
        "pmt_period_ms": 103,
        "pcr_interval_ms": 40,
        "pcr_insertion_policy": "adaptation_only_fallback",
    }
    config = generator_config_from_json(payload)
    assert config == make_config(
        seed=42,
        initial_media_clock_27mhz=27000,
        program=make_program(
            program_descriptors=b"\x50\x51",
            streams=(make_es1(), make_es2(payload_seed_offset=7)),
        ),
        pcr_insertion_policy="adaptation_only_fallback",
    )

    # Reverse mapping: bytes fields encode as hex, snake_case preserved.
    as_json = generator_config_to_json(config)
    assert as_json["program"]["program_descriptors"] == "5051"
    assert generator_config_from_json(json.loads(json.dumps(as_json))) == config

    # Structural strictness per the §4 table: missing / unknown / mistyped.
    from_json = generator_config_from_json

    def without(key):
        clone = json.loads(json.dumps(payload))
        clone.pop(key)
        return clone

    for key in (
        "schema_version",
        "profile",
        "deterministic",
        "seed",
        "initial_media_clock_27mhz",
        "target_bitrate_bps",
        "output_packet_count",
        "program",
        "pat_period_ms",
        "pmt_period_ms",
        "pcr_interval_ms",
        "pcr_insertion_policy",
    ):
        with pytest.raises(ValueError, match=key):
            from_json(without(key))

    clone = json.loads(json.dumps(payload))
    clone["unknown_future_field"] = 1
    with pytest.raises(ValueError, match="unknown_future_field"):
        from_json(clone)

    clone = json.loads(json.dumps(payload))
    clone["deterministic"] = 1  # bool must stay bool (strict JSON mapping)
    with pytest.raises(ValueError, match="deterministic"):
        from_json(clone)

    clone = json.loads(json.dumps(payload))
    clone["program"]["program_descriptors"] = "5"  # odd hex length
    with pytest.raises(ValueError, match="program_descriptors"):
        from_json(clone)

    clone = json.loads(json.dumps(payload))
    clone["program"]["streams"][0]["pid"] = "256"
    with pytest.raises(ValueError, match="pid"):
        from_json(clone)
