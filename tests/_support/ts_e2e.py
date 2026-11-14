"""End-to-end TS integration support — ticket #35 (TASK-TS-INT).

Shared helpers for the ``tests/integration/ts/`` fixtures. Three seams,
mirroring the ticket's acceptance chain (contract §12):

1. ``integration_config`` / ``generate_chunks`` — the generation seam:
   ``TSGenerator.generate_to`` over the #34-proven pull-safe geometry
   (B = 3,008,000 -> slot = 13,500 ticks = exactly 0.5 ms; PAT 101 ms /
   PMT 103 ms / PCR 40 ms / two ES at B/25 and B/50). The geometry and its
   hand-expanded expectations are documented in
   ``tests/integration/ts/test_cbr_end_to_end.py``.
2. ``self_parse_evidence`` — the independent self-parser chain of contract
   §12 ("TS 输出经独立自研 parser"): strict ``TSPacket.from_bytes`` ->
   ``SectionAssembler`` + ``parse_pat``/``parse_pmt`` -> ``PESAssembler`` ->
   ``packet.adaptation_field.pcr`` -> per-PID continuity walk. The walk is
   duplicate-aware (same CC + identical payload = duplicate, not
   discontinuity) so it is a fair cross-parser against TSDuck's
   ``pids[].packets.duplicated`` semantics; the null PID (0x1FFF) is
   skipped — ISO/IEC 13818-1 leaves the CC of null packets undefined.
3. ``run_tsanalyze`` — the TSDuck seam: list-argv subprocess
   ``tsanalyze --json <file>`` (tsanalyze.exe resolved as the sibling of
   the probed ``tsp.exe``). Ticket #3 discipline lives here: exit 0 is
   never treated as validity; the caller gates on the JSON content
   (``content_gates``: ``ts.bytes > 0`` and ``ts.services.total >= 1``).
   stderr is decoded with ``errors="replace"`` for display only — GBK
   localization is never parsed semantically (SPEC-308, tests/README §6).

Nothing in this module hand-splices TS bytes: every byte in play comes from
the generator (tests/README §5 source 1/2 discipline) or from tsanalyze's
stdout. This file is the permitted programmatic-constructor zone
(``tests/_support/``).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from tests._support.tsduck_probe import TSDuckProbe

# --- seam 1: generation ------------------------------------------------------


def integration_config(**overrides):
    """The #34-proven pull-safe GeneratorConfig (600 packets, two ES).

    Hand-proven pull-safe geometry (ticket #34): PAT/PMT repetitions coincide
    only at slot 0; ES pull slots (multiples of 25/50) never coincide with a
    table repetition; the only ES/PCR coincidence inside a 600-slot run is
    slot 400 where the ES1 pull is a PES start (payload_packet_first ride).
    """
    from ts.generator.config import ElementaryStreamConfig, GeneratorConfig, ProgramConfig

    bitrate = 3_008_000
    values = dict(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=1234567,
        initial_media_clock_27mhz=0,
        target_bitrate_bps=bitrate,
        output_packet_count=600,
        program=ProgramConfig(
            transport_stream_id=1,
            program_number=1,
            pmt_pid=4096,
            pcr_pid=256,
            version_number=0,
            streams=(
                ElementaryStreamConfig(
                    pid=256,
                    stream_type=27,  # 0x1B AVC — declaration matches config
                    stream_id=0xE0,
                    bitrate_bps=bitrate // 25,  # 120,320 -> pull every 25 slots
                    payload_profile="synthetic_test_data",
                    payload_seed_offset=0,
                ),
                ElementaryStreamConfig(
                    pid=257,
                    stream_type=3,  # MPEG-1 audio
                    stream_id=0xC0,
                    bitrate_bps=bitrate // 50,  # 60,160 -> pull every 50 slots
                    payload_profile="synthetic_test_data",
                    payload_seed_offset=1,
                ),
            ),
            program_descriptors=b"",
        ),
        pat_period_ms=101,
        pmt_period_ms=103,
        pcr_interval_ms=40,
        pcr_insertion_policy="payload_packet_first",
    )
    values.update(overrides)
    return GeneratorConfig(**values)


def generate_chunks(config) -> tuple[list[bytes], object]:
    """Run ``TSGenerator().generate_to`` into memory; (188-byte chunks, summary)."""
    from ts.generator.generator import TSGenerator

    class _MemorySink:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.chunks.append(bytes(data))
            return len(data)

    sink = _MemorySink()
    summary = TSGenerator().generate_to(config, sink)
    return sink.chunks, summary


# --- seam 2: independent self-parse evidence ----------------------------------

_PES_PREFIX = b"\x00\x00\x01"


@dataclass(frozen=True)
class PidPesEvidence:
    """One ES PID's reassembly evidence (starts / completes / tail issues)."""

    starts: int
    complete: tuple = ()
    tail_issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PidCCWalk:
    """One PID's continuity walk result (duplicate-aware semantics)."""

    packet_count: int
    duplicates: int
    discontinuities: int
    cc_sequence: tuple[int, ...] = ()


@dataclass(frozen=True)
class SelfParseEvidence:
    """Everything the independent self-parser can re-derive from the bytes."""

    pat_sections: tuple = ()
    pmt_sections: tuple = ()
    pes_by_pid: dict = field(default_factory=dict)
    pcr_carriers: tuple = ()  # (slot_index, ticks_27mhz) in emission order
    cc_by_pid: dict = field(default_factory=dict)

    @property
    def pat_section_count(self) -> int:
        return len(self.pat_sections)

    @property
    def pmt_section_count(self) -> int:
        return len(self.pmt_sections)


def _walk_cc(packets) -> PidCCWalk:
    """Duplicate-aware continuity walk (SPEC-100 §5 semantics + duplicates).

    Payload packet: expected CC = previous CC + 1 (mod 16). Adaptation-only
    packet (AFC=10): expected CC = previous CC (reuse, no advance). A payload
    packet repeating the previous CC with byte-identical payload is a
    duplicate (ISO/IEC 13818-1 duplicate-packet mechanism) — counted, not a
    discontinuity. Null PID is never walked (CC undefined on null packets).
    """
    duplicates = 0
    discontinuities = 0
    prev_cc: int | None = None
    prev_payload: bytes | None = None
    sequence: list[int] = []
    for packet in packets:
        cc = packet.continuity_counter
        sequence.append(cc)
        has_payload = packet.payload is not None
        if prev_cc is None:
            prev_cc, prev_payload = cc, packet.payload
            continue
        if not has_payload:
            if cc != prev_cc:
                discontinuities += 1
        elif cc == prev_cc:
            if packet.payload == prev_payload:
                duplicates += 1
            else:
                discontinuities += 1
        else:
            if cc != (prev_cc + 1) % 16:
                discontinuities += 1
        prev_cc, prev_payload = cc, packet.payload
    return PidCCWalk(
        packet_count=len(sequence),
        duplicates=duplicates,
        discontinuities=discontinuities,
        cc_sequence=tuple(sequence),
    )


def self_parse_evidence(chunks) -> SelfParseEvidence:
    """Full-chain independent readback of a generated TS (contract §12).

    Strict packet parse, then PAT/PMT section reassembly, per-ES PES
    reassembly, PCR carrier extraction and per-PID CC walks. Raises on any
    strict parse failure; assembler flush issues are returned as evidence
    (the truncated tail PES of the default geometry is expected evidence).
    """
    from ts.packet import TSPacket
    from ts.pes_assembler import PESAssembler
    from ts.section_assembler import SectionAssembler
    from ts.tables.pat import PAT_SECTION_POLICY, parse_pat
    from ts.tables.pmt import PMT_SECTION_POLICY, parse_pmt

    packets = [TSPacket.from_bytes(chunk) for chunk in chunks]

    def assemble_sections(pid: int, policy) -> tuple:
        assembler = SectionAssembler(pid, lambda table_id: policy)
        sections: list = []
        for packet in packets:
            sections.extend(assembler.push(packet))
        issues = assembler.flush()
        if issues:
            raise AssertionError(f"unexpected section issues on PID {pid}: {issues}")
        return tuple(sections)

    pat_sections = assemble_sections(0x0000, PAT_SECTION_POLICY)
    pmt_sections = assemble_sections(4096, PMT_SECTION_POLICY)
    parsed_pat = tuple(parse_pat(section) for section in pat_sections)
    parsed_pmt = tuple(parse_pmt(section) for section in pmt_sections)

    es_pids = sorted(
        {
            stream.elementary_pid
            for section in parsed_pmt
            for stream in section.streams
        }
    )
    pes_by_pid: dict[int, PidPesEvidence] = {}
    for pid in es_pids:
        assembler = PESAssembler(pid, max_buffer_bytes=1 << 20)
        complete: list = []
        starts = 0
        for packet in packets:
            if packet.pid != pid:
                continue
            if packet.payload_unit_start_indicator and (
                packet.payload is not None
                and packet.payload.startswith(_PES_PREFIX)
            ):
                starts += 1
            complete.extend(assembler.push(packet))
        tail_issues = assembler.flush()
        pes_by_pid[pid] = PidPesEvidence(
            starts=starts,
            complete=tuple(complete),
            tail_issue_codes=tuple(issue.code for issue in tail_issues),
        )

    pcr_carriers: list[tuple[int, int]] = []
    for index, packet in enumerate(packets):
        af = packet.adaptation_field
        if af is not None and af.pcr is not None:
            pcr_carriers.append((index, af.pcr.ticks_27mhz))

    cc_by_pid: dict[int, PidCCWalk] = {}
    for pid in sorted({packet.pid for packet in packets}):
        if pid == 0x1FFF:
            continue  # ISO/IEC 13818-1: CC undefined on null packets
        cc_by_pid[pid] = _walk_cc([p for p in packets if p.pid == pid])

    return SelfParseEvidence(
        pat_sections=parsed_pat,
        pmt_sections=parsed_pmt,
        pes_by_pid=pes_by_pid,
        pcr_carriers=tuple(pcr_carriers),
        cc_by_pid=cc_by_pid,
    )


# --- seam 3: TSDuck tsanalyze --json subprocess -------------------------------


@dataclass(frozen=True)
class TsAnalyzeRun:
    """One ``tsanalyze --json`` execution with the #3 content gates applied."""

    exit_code: int
    json_document: dict | None
    stdout_text: str
    stderr_text: str  # display-only, errors="replace" decode (SPEC-308)
    content_gates: dict[str, bool]

    @property
    def content_valid(self) -> bool:
        """Ticket #3: validity = JSON content gates, never the exit code."""
        return all(self.content_gates.values())


def content_gates(document: dict) -> dict[str, bool]:
    """Ticket #3 validity gates on the tsanalyze JSON content itself."""
    ts_section = document.get("ts") or {}
    services = (ts_section.get("services") or {})
    return {
        "ts_bytes_positive": ts_section.get("bytes", 0) > 0,
        "services_total_at_least_one": services.get("total", 0) >= 1,
        "packets_total_positive": (ts_section.get("packets") or {}).get("total", 0) > 0,
    }


def run_tsanalyze(tsduck: TSDuckProbe, ts_file) -> TsAnalyzeRun:
    """Run ``tsanalyze --json`` on a TS file; parse stdout JSON.

    ``tsanalyze.exe`` is resolved as the sibling of the probed ``tsp.exe``
    (one TSDuck install per bin directory). List-argv spawn, no shell
    (ADR-0003/ADR-0004). stderr is display-only (GBK on Windows — decoded
    with ``errors="replace"``, never parsed semantically, SPEC-308).
    The exit code is recorded but NEVER used as a validity signal (#3).
    """
    import json
    from pathlib import Path

    tsp_path = Path(tsduck.executable)
    tsanalyze_path = tsp_path.parent / "tsanalyze.exe"
    if not tsanalyze_path.is_file():
        raise AssertionError(
            f"tsanalyze.exe not found next to the probed tsp at {tsp_path}"
        )
    completed = subprocess.run(
        [str(tsanalyze_path), "--json", str(ts_file)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=60,
    )
    stdout_text = completed.stdout.decode("utf-8", errors="replace")
    stderr_text = completed.stderr.decode("utf-8", errors="replace")
    document = json.loads(stdout_text)  # invalid JSON -> test failure, loud
    return TsAnalyzeRun(
        exit_code=completed.returncode,
        json_document=document,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        content_gates=content_gates(document),
    )
