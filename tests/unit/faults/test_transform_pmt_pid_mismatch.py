"""SPEC-204 §6.4 — PMT_PID_MISMATCH transform behavior tests."""

from __future__ import annotations

import pytest

from faults.errors import FaultExecutionError
from faults.filters.pmt_pid_mismatch import PmtPidMismatchTransform
from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket

from tests.unit.faults._fault_builders import (
    GOLDEN_PAT_PID,
    GOLDEN_PMT_PID,
    golden_baseline_packets,
    pmt_pid_mismatch_fault,
)

pytestmark = pytest.mark.unit

#: PAT slots of the frozen geometry (golden expectations).
PAT_SLOTS = (0, 202, 404)


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


def _first_section(payload: bytes) -> bytes:
    start = 1 + payload[0]
    section_length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
    return payload[start : start + 3 + section_length]


class TestRepointSemantics:
    def test_pat_repointed_and_crc_recomputed(self, baseline) -> None:
        transform = PmtPidMismatchTransform(pmt_pid_mismatch_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        # activation 0: every PAT instance is repointed (golden parity).
        assert changed == list(PAT_SLOTS)
        for index in PAT_SLOTS:
            section = _first_section(faulted[index].payload)
            # single-program PAT: entry at section[8:12]
            program_number = int.from_bytes(section[8:10], "big")
            pmt_pid = ((section[10] & 0x1F) << 8) | section[11]
            assert program_number == 1
            assert pmt_pid == 4100
            # PAT stays VALID: CRC recomputed, not corrupted.
            assert verify_mpeg2_crc32(section) is True

    def test_reserved_bits_of_pid_field_preserved(self, baseline) -> None:
        transform = PmtPidMismatchTransform(pmt_pid_mismatch_fault())
        faulted_packet = transform.apply(0, baseline[0])
        section_before = _first_section(baseline[0].payload)
        section_after = _first_section(faulted_packet.payload)
        assert (section_before[10] & 0xE0) == (section_after[10] & 0xE0)
        assert section_after[:10] == section_before[:10]

    def test_pmt_stays_on_its_real_pid(self, baseline) -> None:
        transform = PmtPidMismatchTransform(pmt_pid_mismatch_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        for index in (1, 206, 412):
            assert faulted[index].pid == GOLDEN_PMT_PID
            assert faulted[index].to_bytes() == baseline[index].to_bytes()

    def test_program_zero_entry_never_rewritten(self, baseline) -> None:
        """A network_PID entry (program_number 0) keeps its value; with the
        single-program golden PAT the whole rewrite is the one entry."""
        transform = PmtPidMismatchTransform(pmt_pid_mismatch_fault())
        faulted_packet = transform.apply(0, baseline[0])
        section = _first_section(faulted_packet.payload)
        crc_offset = len(section) - 4
        # no bytes outside the single entry + CRC changed
        assert section[:8] == _first_section(baseline[0].payload)[:8]
        assert section[12:crc_offset] == (
            _first_section(baseline[0].payload)[12:crc_offset]
        )


class TestFragmentedPat:
    def test_fragmented_pat_is_an_explicit_run_failure(self) -> None:
        """A PAT claiming a section longer than one slot cannot be repacked
        in place — explicit SIM_FAULT_EXEC_FAILED, never a silent skip."""
        # section_length 0x300 (768) > available payload: fragmentation.
        payload_head = bytes([0x00, 0x00, 0xB3, 0x00])
        payload = payload_head + b"\x00" * (184 - len(payload_head))
        packet = TSPacket(
            pid=GOLDEN_PAT_PID,
            continuity_counter=0,
            payload=payload,
            payload_unit_start_indicator=True,
        )
        transform = PmtPidMismatchTransform(pmt_pid_mismatch_fault())
        with pytest.raises(FaultExecutionError) as excinfo:
            transform.apply(0, packet)
        assert excinfo.value.code == "SIM_FAULT_EXEC_FAILED"


class TestActivationWindow:
    def test_pat_before_activation_untouched(self, baseline) -> None:
        from faults.definition import FaultActivation, FaultDefinition

        definition = FaultDefinition(
            fault_id="f",
            fault_type="PMT_PID_MISMATCH",
            target_id="demux-0:pid:0x0000",
            parameters={"wrong_pmt_pid": 4100},
            activation=FaultActivation(kind="packet_index", packet_index=203),
            expected_observations=("ts.psi_section_observed",),
        )
        transform = PmtPidMismatchTransform(definition)
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed == [404]
