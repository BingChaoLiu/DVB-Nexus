"""The analysis-bridge parser — real bytes in, deterministic facts out
(ticket #58, 裁定 A).

The pure semantic-layer half of the minimal analysis bridge: one faulted
(or clean) TS artifact's bytes plus the run's :class:`GeneratorConfig`
in, a tuple of frozen *facts* out. No I/O, no wall clock, no publisher —
the orchestration half (:mod:`application.analysis.service`) normalizes
the facts into ``ts.*`` observation events and publishes them.

Scope pin (dispatch + ticket #58): the FOUR fault-signal families of the
MVP fault lab — NOT a SPEC-308 full analyzer:

1. **PAT presence** — PSI repetition supervision: the declared
   ``pat_period_ms`` (converted to shared-frame slots through the
   declared bitrate) predicts the PAT window slots; a predicted slot
   whose packet does not start a PAT section is a :class:`PatMissingFact`
   (the pat-missing null-substitution symptom, SPEC-204 §6).
2. **PMT CRC** — every PMT section is verified; CRC-invalid instances
   are :class:`PmtSectionFact` with ``crc_valid=False`` (the persistent
   corruption symptom — one fact per instance, so the SPEC-307 count
   window sees the persistence).
3. **PAT↔PMT mapping** — every PAT section reports its parsed
   ``program_map_pids`` declaration; the service layer compares against
   the config-declared PMT PID (the repoint symptom).
4. **CC sequence** — payload-bearing packets of supervised PIDs must
   continue ``(previous + 1) mod 16``; violations are
   :class:`ContinuityErrorFact` at the landing slot (the relative-offset
   symptom: an internal parser sees ONE error, the shift then persists
   contiguously).

CC supervision scope note (analyzer convention, recorded for the report):
the supervision covers the ES PIDs and skips (a) the null-packet PID
0x1FFF — null-packet CC is undefined (ISO 13818-1) — and (b) the PSI PIDs
(PAT PID 0 + the declared PMT PID). The platform generator (SPEC-108)
emits CC=0 on every PSI retransmission burst, so cross-instance CC
continuity on the PSI PIDs is not a defined property of the platform's
own streams; the golden fault pairs target the ES PIDs exclusively
(the e2e/conformance oracles pin this).

Framing authority: PSI section reassembly goes through
:class:`ts.section_assembler.SectionAssembler` with the SPEC-103 table
policies (``PAT_SECTION_POLICY`` / ``PMT_SECTION_POLICY``). The one fact
the assembler cannot date is a CRC failure (its issues are undated), so
a supplementary per-PUSI direct slice (the shared
``faults.filters.base.psi_section_header`` framing arithmetic over
public ``ts`` primitives) dates single-packet CRC-invalid instances.
Multi-packet sections still emit through the assembler when they verify
(a documented MVP limitation: CRC-invalid multi-packet sections are not
dated by this bridge).
"""

from __future__ import annotations

from dataclasses import dataclass

from ts.crc import verify_mpeg2_crc32
from ts.generator.config import GeneratorConfig
from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pat import PAT_SECTION_POLICY, PAT_TABLE_ID, parse_pat_sections
from ts.tables.pmt import PMT_SECTION_POLICY, PMT_TABLE_ID, parse_pmt

__all__ = [
    "BatchFact",
    "ContinuityErrorFact",
    "Fact",
    "NULL_PID",
    "PAT_PID",
    "PatMissingFact",
    "PatSectionFact",
    "PmtSectionFact",
    "analyze_transport_stream",
    "slot_duration_ns",
]

#: Null-packet PID (ISO 13818-1; CC undefined on the null stream).
NULL_PID = 0x1FFF

#: The PAT's home PID (SPEC-103).
PAT_PID = 0x0000


@dataclass(frozen=True)
class PatSectionFact:
    """One observed PAT section (the mapping-declaration carrier)."""

    packet_index: int
    program_map_pids: tuple[int, ...]
    crc_valid: bool
    gap_ms: int | None  # None = first instance (anchors the schedule)


@dataclass(frozen=True)
class PmtSectionFact:
    """One observed PMT section (CRC-valid via the SPEC-103 gate)."""

    packet_index: int
    crc_valid: bool
    gap_ms: int | None


@dataclass(frozen=True)
class PatMissingFact:
    """One predicted PAT window slot carrying no PAT section."""

    packet_index: int


@dataclass(frozen=True)
class ContinuityErrorFact:
    """One CC sequence violation at its landing slot."""

    packet_index: int
    pid: int
    expected_cc: int
    actual_cc: int


@dataclass(frozen=True)
class BatchFact:
    """The analyzed stream's coverage summary (one per analysis)."""

    packet_count: int
    byte_count: int
    duration_ns: int
    null_packet_count: int
    continuity_error_count: int


Fact = PatSectionFact | PmtSectionFact | PatMissingFact | ContinuityErrorFact | BatchFact


def slot_duration_ns(config: GeneratorConfig) -> int:
    """Shared-frame slot duration in ns (CBR geometry, SPEC-108)."""
    return 188 * 8 * 1_000_000_000 // config.target_bitrate_bps


def _period_slots(config: GeneratorConfig, period_ms: int) -> int:
    """A declared PSI period in shared-frame slots (nearest slot)."""
    return max(1, round(period_ms * 1_000_000 / slot_duration_ns(config)))


def analyze_transport_stream(
    ts_bytes: bytes, config: GeneratorConfig
) -> tuple[Fact, ...]:
    """Parse one artifact's bytes into the four-family fact set."""
    if len(ts_bytes) % 188:
        raise ValueError(
            "analyze_transport_stream expects packet-aligned bytes "
            f"(188-byte multiples), got {len(ts_bytes)} bytes"
        )
    packets = [
        TSPacket.from_bytes(ts_bytes[offset : offset + 188])
        for offset in range(0, len(ts_bytes), 188)
    ]
    slot_ns = slot_duration_ns(config)
    pmt_pid = config.program.pmt_pid

    pat_facts: list[PatSectionFact] = []
    pmt_facts: list[PmtSectionFact] = []
    missing_facts: list[PatMissingFact] = []
    continuity_facts: list[ContinuityErrorFact] = []

    # --- PAT walk: assembler emission (framing authority) + slot census ----
    pat_assembler = SectionAssembler(
        PAT_PID, lambda table_id: PAT_SECTION_POLICY if table_id == PAT_TABLE_ID else None
    )
    pat_slots: set[int] = set()
    last_pat_index: int | None = None
    for index, packet in enumerate(packets):
        if _starts_pat(packet):
            pat_slots.add(index)
        for section in pat_assembler.push(packet):
            programs = parse_pat_sections([section])
            pids = tuple(entry.program_map_pid for entry in programs.programs)
            gap_ms = (
                None
                if last_pat_index is None
                else (index - last_pat_index) * slot_ns // 1_000_000
            )
            pat_facts.append(
                PatSectionFact(
                    packet_index=index,
                    program_map_pids=pids,
                    crc_valid=True,
                    gap_ms=gap_ms,
                )
            )
            last_pat_index = index
    pat_assembler.flush()

    # PAT presence supervision: predicted window slots from the FIRST
    # observed instance (0 when the stream carries no PAT at all — the
    # whole stream is then one missing window per period, starting at the
    # frame origin).
    period = _period_slots(config, config.pat_period_ms)
    origin = min(pat_slots) if pat_slots else 0
    for slot in range(origin, len(packets), period):
        if slot not in pat_slots:
            missing_facts.append(PatMissingFact(packet_index=slot))

    # --- PMT walk: assembler emission + dated CRC supervision ---------------
    pmt_assembler = SectionAssembler(
        pmt_pid,
        lambda table_id: PMT_SECTION_POLICY if table_id == PMT_TABLE_ID else None,
    )
    last_pmt_instance_index: int | None = None
    dated_crc_bad: set[int] = set()
    for index, packet in enumerate(packets):
        for section in pmt_assembler.push(packet):
            parse_pmt(section)  # SPEC-103 semantic gate (strict parse)
            pmt_facts.append(
                PmtSectionFact(
                    packet_index=index,
                    crc_valid=True,
                    gap_ms=_gap_ms(last_pmt_instance_index, index, slot_ns),
                )
            )
            last_pmt_instance_index = index
        if _is_dated_crc_failure(packet, pmt_pid):
            dated_crc_bad.add(index)
    pmt_assembler.flush()
    # A dated CRC failure whose slot the assembler never emitted = the
    # corrupt instance fact (assembler-emitted slots verified cleanly).
    for index in sorted(dated_crc_bad):
        pmt_facts.append(
            PmtSectionFact(
                packet_index=index,
                crc_valid=False,
                gap_ms=_gap_ms(last_pmt_instance_index, index, slot_ns),
            )
        )
        last_pmt_instance_index = index
    pmt_facts.sort(key=lambda fact: fact.packet_index)

    # --- CC walk: ES-PID payload continuity (scope note in the docstring) --
    last_payload_cc: dict[int, int] = {}
    for index, packet in enumerate(packets):
        if packet.pid == NULL_PID or packet.payload is None:
            continue
        if packet.pid in (PAT_PID, pmt_pid):
            continue  # PSI-PID exemption (SPEC-108 PSI-burst convention)
        previous = last_payload_cc.get(packet.pid)
        if previous is not None:
            expected = (previous + 1) & 0x0F
            if packet.continuity_counter != expected:
                continuity_facts.append(
                    ContinuityErrorFact(
                        packet_index=index,
                        pid=packet.pid,
                        expected_cc=expected,
                        actual_cc=packet.continuity_counter,
                    )
                )
        last_payload_cc[packet.pid] = packet.continuity_counter

    batch = BatchFact(
        packet_count=len(packets),
        byte_count=len(ts_bytes),
        duration_ns=len(packets) * slot_ns,
        null_packet_count=sum(1 for p in packets if p.pid == NULL_PID),
        continuity_error_count=len(continuity_facts),
    )
    return tuple(pat_facts + pmt_facts + missing_facts + continuity_facts) + (
        batch,
    )


def _starts_pat(packet: TSPacket) -> bool:
    """True when the packet STARTS a PAT section (PUSI + pointer + table)."""
    if packet.pid != PAT_PID or not packet.payload_unit_start_indicator:
        return False
    payload = packet.payload
    if payload is None or len(payload) < 2:
        return False
    start = 1 + payload[0]
    return start < len(payload) and payload[start] == PAT_TABLE_ID


def _is_dated_crc_failure(packet: TSPacket, pmt_pid: int) -> bool:
    """True when the packet carries a whole single-packet PMT section
    that FAILS the MPEG-2 CRC (multi-packet sections are the assembler's
    — see the module docstring limitation)."""
    if (
        packet.pid != pmt_pid
        or not packet.payload_unit_start_indicator
        or packet.payload is None
    ):
        return False
    payload = packet.payload
    start = 1 + payload[0]
    if start + 3 > len(payload) or payload[start] != PMT_TABLE_ID:
        return False
    section_length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
    total = 3 + section_length
    if start + total > len(payload):
        return False  # multi-packet: not dated by this bridge
    section_bytes = payload[start : start + total]
    return not verify_mpeg2_crc32(section_bytes)


def _gap_ms(previous: int | None, index: int, slot_ns: int) -> int | None:
    """Repetition gap since the previous same-family instance (ms)."""
    if previous is None:
        return None
    return (index - previous) * slot_ns // 1_000_000
