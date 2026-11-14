"""First-batch golden vector ``section-fragmentation`` — assertions.

Conformance layer (SPEC-505 §3 / SPEC-506 §7 #6): one PSI section spanning
3 TS packets (PUSI + pointer_field on the first, payload continuation on
the next two, SPEC-102/106).  The section is a 100-program PAT (412 bytes
> 2×184 payload bytes, forcing the 3-packet span); bytes are
script-constructed with an independent CRC-32/MPEG-2 implementation, L2
verified via TSDuck ``tstables`` reassembly (registered evidence).
"""

from __future__ import annotations

import pytest

from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pat import PAT_SECTION_POLICY, parse_pat_sections

pytestmark = pytest.mark.conformance

VECTOR_ID = "section-fragmentation"
VECTOR_PID = 0x0000
VECTOR_PACKETS = 3
SECTION_TOTAL_SIZE = 412  # 100 programs: 8 + 100*4 + 4 (CRC)
PROGRAM_COUNT = 100
FIRST_PROGRAM = (1, 0x0101)
LAST_PROGRAM = (100, 0x0164)
PAYLOAD_CAPACITY_TWO_PACKETS = 183 + 184  # forces the 3rd packet


def _pid_packets(vector) -> list[TSPacket]:
    return [
        TSPacket.from_bytes(vector.ts_bytes[offset : offset + 188])
        for offset in range(0, len(vector.ts_bytes), 188)
    ]


def test_section_fragmentation_shape(golden_loader):
    vector = golden_loader.load(VECTOR_ID)
    assert vector.kind == "generated_ts"
    assert vector.packet_count == VECTOR_PACKETS
    assert len(vector.ts_bytes) == VECTOR_PACKETS * 188
    assert vector.verification is not None
    assert vector.verification.path == "tsduck-cross"


def test_section_spans_three_packets_with_pusi_only_on_first(golden_loader):
    packets = _pid_packets(golden_loader.load(VECTOR_ID))
    assert len(packets) == VECTOR_PACKETS
    assert {packet.pid for packet in packets} == {VECTOR_PID}
    pusi_packets = [p for p in packets if p.payload_unit_start_indicator]
    assert len(pusi_packets) == 1
    assert packets[0].payload_unit_start_indicator is True
    # First payload byte is the pointer_field (0x00 — section starts
    # immediately after the pointer).
    assert packets[0].payload[0] == 0
    # Continuation packets carry plain section bytes (AFC payload-only).
    for packet in packets[1:]:
        assert packet.payload_unit_start_indicator is False
        assert packet.continuity_counter == packets[packets.index(packet) - 1].continuity_counter + 1


def test_section_exceeds_two_packet_capacity(golden_loader):
    # The registered section genuinely cannot fit in two packets: its
    # reassembled size exceeds the 183+184 usable payload bytes.
    vector = golden_loader.load(VECTOR_ID)
    packets = _pid_packets(vector)
    assembler = SectionAssembler(VECTOR_PID, lambda table_id: PAT_SECTION_POLICY)
    sections = []
    for packet in packets:
        sections.extend(assembler.push(packet))
    assert assembler.flush() == []
    assert len(sections) == 1
    assert len(sections[0].raw_bytes) == SECTION_TOTAL_SIZE
    assert len(sections[0].raw_bytes) > PAYLOAD_CAPACITY_TWO_PACKETS


def test_reassembled_pat_carries_all_100_programs(golden_loader):
    vector = golden_loader.load(VECTOR_ID)
    packets = _pid_packets(vector)
    assembler = SectionAssembler(VECTOR_PID, lambda table_id: PAT_SECTION_POLICY)
    sections = []
    for packet in packets:
        sections.extend(assembler.push(packet))
    table = parse_pat_sections(sections)
    assert len(table.programs) == PROGRAM_COUNT
    first = table.programs[0]
    assert (first.program_number, first.program_map_pid) == FIRST_PROGRAM
    last = table.programs[-1]
    assert (last.program_number, last.program_map_pid) == LAST_PROGRAM


def test_section_fragmentation_expectations(golden_loader):
    vector = golden_loader.load(VECTOR_ID)
    entries = list(vector.expectations)
    by_type = {}
    for entry in entries:
        by_type.setdefault(entry["event_type"], []).append(entry)
    section_entries = by_type["ts.psi_section_observed"]
    assert len(section_entries) == 1
    detail = section_entries[0]["detail"]
    assert detail["table_id"] == 0
    assert detail["program_count"] == PROGRAM_COUNT
    assert detail["section_total_size"] == SECTION_TOTAL_SIZE
    assert detail["spans_packets"] == VECTOR_PACKETS
    packet_entries = by_type["ts.packet_batch_observed"]
    assert packet_entries[0]["locator"] == {
        "pid": VECTOR_PID,
        "packet_index": 0,
    }
    assert packet_entries[0]["detail"]["pusi"] == 1
    assert packet_entries[0]["detail"]["pointer_field"] == 0


def test_section_fragmentation_constructor_reproduces_registered_bytes(
    golden_loader, tmp_path
):
    import subprocess
    import sys
    from tests._support.paths import REPO_ROOT

    vector = golden_loader.load(VECTOR_ID)
    script = REPO_ROOT / "tools" / "make_golden_ts_vectors.py"
    result = subprocess.run(
        [
            sys.executable, "-I", str(script),
            "section-fragmentation", "--output-dir", str(tmp_path),
        ],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (tmp_path / VECTOR_ID / f"{VECTOR_ID}.ts").read_bytes()
    assert rebuilt == vector.ts_bytes
