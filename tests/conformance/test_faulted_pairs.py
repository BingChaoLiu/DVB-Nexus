"""First-batch golden faulted pairs — slot-preserving assertions.

Conformance layer (SPEC-505 §3 / SPEC-506 §7 #7-#10 / SPEC-204 §6-§7 /
ADR-0007 第 4 条).  Each fault entry registers two vectors:

- ``<id>-baseline`` (kind ``generated_ts``): the clean TS Core run
  (pull-safe geometry of the #34 examples);
- ``<id>`` (kind ``faulted_ts``, ``fault_plan_ref`` → its baseline): the
  faulted bytes produced by the independent transform script.

Assertions here: (a) the pair shares the packet-order frame — same packet
count, packet_index i points at the same slot in both streams; (b) the
differing slots and bytes follow the SPEC-204 §6 frozen transform
semantics exactly (等位替换: no insertion, no deletion, in-place edits
only); (c) the fault symptom is observable (expectations.json).
"""

from __future__ import annotations

import pytest

from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket
from ts.section_assembler import SectionAssembler
from ts.tables.pat import PAT_SECTION_POLICY
from ts.tables.pmt import PMT_SECTION_POLICY

pytestmark = pytest.mark.conformance

PAIRS = (
    "pat-missing",
    "pmt-invalid-crc",
    "cc-discontinuity",
    "pmt-pid-mismatch",
)

#: Hand-derived per-fault facts (SPEC-204 §6 + the frozen transform
#: parameters recorded in each faulted manifest's ``fault_parameters``).
PAT_MISSING_ACTIVATION = 202
PMT_INVALID_CRC_ACTIVATION = 1
CC_DISCONTINUITY_ACTIVATION = 30
CC_DISCONTINUITY_LANDING = 50  # first PID-256 payload packet after activation
CC_DISCONTINUITY_DELTA = 3
PMT_PID_MISMATCH_WRONG_PID = 4100


def _packets_of(vector) -> list[TSPacket]:
    return [
        TSPacket.from_bytes(vector.ts_bytes[offset : offset + 188])
        for offset in range(0, len(vector.ts_bytes), 188)
    ]


def _pair(golden_loader, fault_id: str):
    baseline = golden_loader.load(f"{fault_id}-baseline")
    faulted = golden_loader.load(fault_id)
    return baseline, faulted


# --- registration shape -------------------------------------------------------


@pytest.mark.parametrize("fault_id", PAIRS)
def test_pair_registration_and_plan_ref(golden_loader, fault_id: str):
    baseline, faulted = _pair(golden_loader, fault_id)
    assert baseline.kind == "generated_ts"
    assert faulted.kind == "faulted_ts"
    assert faulted.fault_plan_ref == f"{fault_id}-baseline"
    assert faulted.verification is not None
    assert faulted.verification.path == "tsduck-cross"
    # Frozen fault parameters travel in the manifest.
    frozen = faulted_manifest_frozen_params(faulted)
    assert frozen["fault_type"] == fault_id.upper().replace("-", "_")
    assert frozen["schema_version"] == 1


def faulted_manifest_frozen_params(faulted):
    import json
    from tests._support.paths import GOLDEN_ROOT

    manifest = json.loads(
        (GOLDEN_ROOT / faulted.vector_id / "manifest.json").read_text(encoding="utf-8")
    )
    return manifest["fault_parameters"]


@pytest.mark.parametrize("fault_id", PAIRS)
def test_slot_preserving_frame_shared_by_pair(golden_loader, fault_id: str):
    """ADR-0007 第 4 条 / SPEC-204 §7: baseline and faulted share the packet
    order frame — equal packet counts, CBR preserved on the faulted side."""
    baseline, faulted = _pair(golden_loader, fault_id)
    assert faulted.packet_count is None or faulted.packet_count == baseline.packet_count
    assert len(faulted.ts_bytes) == len(baseline.ts_bytes)
    assert len(faulted.ts_bytes) == baseline.packet_count * 188


# --- pat-missing ---------------------------------------------------------------


def test_pat_missing_replaces_pat_slots_with_null_packets(golden_loader):
    baseline, faulted = _pair(golden_loader, "pat-missing")
    baseline_packets = _packets_of(baseline)
    faulted_packets = _packets_of(faulted)
    baseline_pid0 = [
        i for i, p in enumerate(baseline_packets) if p.pid == 0
    ]
    assert baseline_pid0 == [0, 202, 404]  # frame fact of the frozen bytes
    for index in range(len(baseline_packets)):
        if index >= PAT_MISSING_ACTIVATION and index in baseline_pid0:
            null = faulted_packets[index]
            assert null.pid == 0x1FFF
            assert null.continuity_counter == 0
            # Canonical null body (SPEC-107 §5.1): all-0xFF, asserted
            # structurally (no hand-assembled byte material here).
            assert null.payload is not None
            assert len(null.payload) == 184
            assert set(null.payload) == {0xFF}
        else:
            assert faulted_packets[index].to_bytes() == baseline_packets[index].to_bytes()
    # Symptom: no PAT section observed from the activation slot on.
    after = [
        p
        for p in faulted_packets[PAT_MISSING_ACTIVATION:]
        if p.pid == 0
    ]
    assert after == []
    # Before the window the PAT is intact.
    assert faulted_packets[0].pid == 0


# --- pmt-invalid-crc ------------------------------------------------------------


def test_pmt_invalid_crc_inverts_only_crc_bytes(golden_loader):
    baseline, faulted = _pair(golden_loader, "pmt-invalid-crc")
    baseline_packets = _packets_of(baseline)
    faulted_packets = _packets_of(faulted)
    pmt_slots = [i for i, p in enumerate(baseline_packets) if p.pid == 4096]
    assert pmt_slots == [1, 206, 412]  # frame fact of the frozen bytes
    for index in range(len(baseline_packets)):
        if index in pmt_slots:
            diff = [
                offset
                for offset in range(188)
                if baseline_packets[index].to_bytes()[offset]
                != faulted_packets[index].to_bytes()[offset]
            ]
            assert len(diff) == 4  # exactly the CRC field
            # invert corruption: faulted CRC byte = baseline XOR 0xFF
            for offset in diff:
                assert (
                    faulted_packets[index].to_bytes()[offset]
                    == baseline_packets[index].to_bytes()[offset] ^ 0xFF
                )
        else:
            assert faulted_packets[index].to_bytes() == baseline_packets[index].to_bytes()


def test_pmt_invalid_crc_sections_fail_crc_check(golden_loader):
    _, faulted = _pair(golden_loader, "pmt-invalid-crc")
    assembler = SectionAssembler(4096, lambda table_id: PMT_SECTION_POLICY)
    emitted = []
    issues = []
    for packet in _packets_of(faulted):
        if packet.pid == 4096:
            emitted.extend(assembler.push(packet))
            # CRC-invalid sections are reported as issues, never emitted.
    issues.extend(assembler.flush())
    assert emitted == []
    codes = [issue.code for issue in issues]
    assert codes.count("SECTION_CRC_INVALID") == 3  # persistent: all instances


# --- cc-discontinuity ------------------------------------------------------------


def test_cc_discontinuity_relative_offset_persists(golden_loader):
    baseline, faulted = _pair(golden_loader, "cc-discontinuity")
    baseline_packets = _packets_of(baseline)
    faulted_packets = _packets_of(faulted)
    for index in range(len(baseline_packets)):
        b, f = baseline_packets[index], faulted_packets[index]
        if index < CC_DISCONTINUITY_LANDING or b.pid != 256:
            assert f.to_bytes() == b.to_bytes()
            continue
        if b.payload is not None:  # payload packet (AFC 01 or 11)
            expected_faulted_cc = (b.continuity_counter + CC_DISCONTINUITY_DELTA) % 16
            assert f.continuity_counter == expected_faulted_cc, f"slot {index}"
        else:  # adaptation-only: reuse rule against the faulted stream
            assert f.continuity_counter == (
                (b.continuity_counter + CC_DISCONTINUITY_DELTA) % 16
            )
    # The landing packet carries the hand-derived shifted value.
    landing = faulted_packets[CC_DISCONTINUITY_LANDING]
    assert baseline_packets[CC_DISCONTINUITY_LANDING].continuity_counter == 1
    assert landing.continuity_counter == 4  # (expected_next 1 + delta 3) mod 16


def test_cc_discontinuity_expectations_declare_the_error(golden_loader):
    _, faulted = _pair(golden_loader, "cc-discontinuity")
    entries = list(faulted.expectations)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event_type"] == "ts.continuity_error"
    assert entry["locator"] == {"pid": 256, "packet_index": CC_DISCONTINUITY_LANDING}
    assert entry["detail"]["expected_cc"] == 1
    assert entry["detail"]["actual_cc"] == 4
    assert entry["detail"]["delta"] == CC_DISCONTINUITY_DELTA
    assert entry["detail"]["persists"] is True


# --- pmt-pid-mismatch ------------------------------------------------------------


def _section_span_in_packet(packet_bytes: bytes) -> tuple[int, int]:
    """Independent wire walk (SPEC-100 §5.2 + pointer_field): (start, length)
    of the first PSI section — mirrors the transform's own derivation so the
    expected byte-diff locations come from the spec, not from the transform
    under test."""
    afc = (packet_bytes[3] >> 4) & 0x03
    offset = 5 + packet_bytes[4] if afc & 0b10 else 4
    start = offset + 1 + packet_bytes[offset]
    length = ((packet_bytes[start + 1] & 0x0F) << 8) | packet_bytes[start + 2]
    return start, 3 + length


def test_pmt_pid_mismatch_repoints_pat_and_recomputes_crc(golden_loader):
    baseline, faulted = _pair(golden_loader, "pmt-pid-mismatch")
    baseline_packets = _packets_of(baseline)
    faulted_packets = _packets_of(faulted)
    pat_slots = [i for i, p in enumerate(baseline_packets) if p.pid == 0]
    assert pat_slots == [0, 202, 404]  # frame fact of the frozen bytes
    for index in pat_slots:
        baseline_bytes = baseline_packets[index].to_bytes()
        faulted_bytes = faulted_packets[index].to_bytes()
        diff = {
            offset
            for offset in range(188)
            if baseline_bytes[offset] != faulted_bytes[offset]
        }
        start, length = _section_span_in_packet(baseline_bytes)
        # program_map_PID field low byte (4096 → 4100 share the high byte:
        # 0xF0 → 0xF0) + the 4 recomputed CRC bytes.
        field_offset = start + 10
        expected_diff = {field_offset + 1} | set(range(start + length - 4, start + length))
        assert diff == expected_diff
        # The rewritten field decodes to the wrong PID with reserved bits kept.
        field = (faulted_bytes[field_offset] << 8) | faulted_bytes[field_offset + 1]
        assert field >> 13 == 0b111  # reserved bits preserved
        assert field & 0x1FFF == PMT_PID_MISMATCH_WRONG_PID
        assert field & 0x1FFF != 4096
    for index in range(len(baseline_packets)):
        if index not in pat_slots:
            assert faulted_packets[index].to_bytes() == baseline_packets[index].to_bytes()


def test_pmt_pid_mismatch_symptom_observable(golden_loader):
    _, faulted = _pair(golden_loader, "pmt-pid-mismatch")
    # PAT is still fully valid (CRC recomputed) but points to the wrong PID.
    assembler = SectionAssembler(0, lambda table_id: PAT_SECTION_POLICY)
    sections = []
    for packet in _packets_of(faulted):
        if packet.pid == 0:
            sections.extend(assembler.push(packet))
    assert assembler.flush() == []
    assert len(sections) == 3
    for section in sections:
        # CRC was recomputed: the repointed PAT still verifies cleanly.
        assert verify_mpeg2_crc32(section.raw_bytes)
    from ts.tables.pat import parse_pat_sections

    # The three instances are identical retransmissions of one version set;
    # the §7 aggregator requires the caller to dedup retransmissions.
    table = parse_pat_sections(sections[:1])
    assert [(p.program_number, p.program_map_pid) for p in table.programs] == [
        (1, PMT_PID_MISMATCH_WRONG_PID)
    ]
    # The real PMT is untouched on its PID (orphaned by the repointing).
    packets = _packets_of(faulted)
    assert [i for i, p in enumerate(packets) if p.pid == 4096] == [1, 206, 412]
    # The wrong PID carries no packets at all.
    assert [p for p in packets if p.pid == PMT_PID_MISMATCH_WRONG_PID] == []


# --- constructor reproducibility (SPEC-506 §6 determinism) ----------------------


@pytest.mark.parametrize("fault_id", PAIRS)
def test_baseline_constructor_reproduces_registered_bytes(
    golden_loader, tmp_path, fault_id: str
):
    import subprocess
    import sys
    from tests._support.paths import REPO_ROOT

    baseline = golden_loader.load(f"{fault_id}-baseline")
    script = REPO_ROOT / "tools" / "make_golden_baseline.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), fault_id, "--output-dir", str(tmp_path)],
        capture_output=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (
        tmp_path / f"{fault_id}-baseline" / f"{fault_id}-baseline.ts"
    ).read_bytes()
    assert rebuilt == baseline.ts_bytes


@pytest.mark.parametrize("fault_id", PAIRS)
def test_fault_transform_reproduces_registered_bytes(
    golden_loader, tmp_path, fault_id: str
):
    import subprocess
    import sys
    from tests._support.paths import GOLDEN_ROOT, REPO_ROOT

    _, faulted = _pair(golden_loader, fault_id)
    script = REPO_ROOT / "tools" / "golden_fault_transform.py"
    baseline_ts = GOLDEN_ROOT / f"{fault_id}-baseline" / f"{fault_id}-baseline.ts"
    result = subprocess.run(
        [
            sys.executable, "-I", str(script), fault_id,
            "--baseline", str(baseline_ts),
            "--output-dir", str(tmp_path),
        ],
        capture_output=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rebuilt = (tmp_path / fault_id / f"{fault_id}.ts").read_bytes()
    assert rebuilt == faulted.ts_bytes
