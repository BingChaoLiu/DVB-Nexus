"""SPEC-204 §6.2 — PMT_INVALID_CRC transform behavior tests."""

from __future__ import annotations

import pytest

from faults.filters.pmt_invalid_crc import PmtInvalidCrcTransform
from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket

from tests.unit.faults._fault_builders import (
    GOLDEN_PMT_PID,
    golden_baseline_packets,
    pmt_invalid_crc_fault,
)

pytestmark = pytest.mark.unit

#: PMT instance slots of the frozen geometry (golden expectations).
PMT_SLOTS = (1, 206, 412)


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


def _first_section(payload: bytes) -> bytes:
    start = 1 + payload[0]  # PUSI payload: pointer_field then section
    section_length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
    return payload[start : start + 3 + section_length]


class TestPersistentInvertDefaults:
    def test_every_pmt_instance_crc_inverted_from_activation(self, baseline) -> None:
        transform = PmtInvalidCrcTransform(pmt_invalid_crc_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed == list(PMT_SLOTS)

    def test_section_length_unchanged_and_other_bytes_untouched(
        self, baseline
    ) -> None:
        transform = PmtInvalidCrcTransform(pmt_invalid_crc_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        for index in PMT_SLOTS:
            before = baseline[index]
            after = faulted[index]
            assert before.pid == GOLDEN_PMT_PID
            section_before = _first_section(before.payload)
            section_after = _first_section(after.payload)
            assert len(section_before) == len(section_after)
            assert section_after[:-4] == section_before[:-4]
            assert section_after[-4:] == bytes(
                byte ^ 0xFF for byte in section_before[-4:]
            )

    def test_corrupted_pmt_fails_crc_verification(self, baseline) -> None:
        transform = PmtInvalidCrcTransform(pmt_invalid_crc_fault())
        faulted_packet = transform.apply(PMT_SLOTS[0], baseline[PMT_SLOTS[0]])
        assert verify_mpeg2_crc32(_first_section(faulted_packet.payload)) is False


class TestModesAndCorruptions:
    def test_once_mode_mutates_only_the_first_instance(self, baseline) -> None:
        transform = PmtInvalidCrcTransform(
            pmt_invalid_crc_fault(mode="once", corruption="invert")
        )
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed == [PMT_SLOTS[0]]

    def test_zero_corruption_clears_the_crc_bytes(self, baseline) -> None:
        transform = PmtInvalidCrcTransform(
            pmt_invalid_crc_fault(mode="persistent", corruption="zero")
        )
        faulted_packet = transform.apply(PMT_SLOTS[0], baseline[PMT_SLOTS[0]])
        section = _first_section(faulted_packet.payload)
        assert section[-4:] == b"\x00\x00\x00\x00"

    def test_no_pmt_instance_before_activation(self, baseline) -> None:
        from faults.definition import FaultActivation, FaultDefinition

        definition = FaultDefinition(
            fault_id="f",
            fault_type="PMT_INVALID_CRC",
            target_id="demux-0:pid:0x1000",
            parameters={"mode": "persistent", "corruption": "invert"},
            activation=FaultActivation(kind="packet_index", packet_index=2),
            expected_observations=("ts.psi_section_observed",),
        )
        transform = PmtInvalidCrcTransform(definition)
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        # activation 2: instance 1 is before the window; 206/412 remain.
        assert changed == [206, 412]


class TestFragmentedCrcTail:
    def test_pending_crc_bytes_apply_on_the_following_payload(self) -> None:
        """A PMT whose CRC tail continues into the next packet of the same
        PID still gets exactly its 4 CRC bytes corrupted (payload-stream
        tracking), and the section start stays untouched.

        Geometry: pointer 0, table_id 0x02, section_length 182 →
        crc_offset = 1 + 3 + 182 - 4 = 182 → bytes 182/183 fall inside this
        slot, bytes 184/185 land on the following packet's payload 0/1.
        """
        header = bytes([0x00, 0x02, 0xB0, 0xB6])  # pointer + tid + seclen=182
        payload_body = bytes([0x33]) * 180  # programmatic filler, no literal
        payload = header + payload_body
        assert len(payload) == 184
        packet = TSPacket(
            pid=GOLDEN_PMT_PID,
            continuity_counter=0,
            payload=payload,
            payload_unit_start_indicator=True,
        )
        follower_payload = bytes([0x44]) * 184  # programmatic filler
        follower = TSPacket(
            pid=GOLDEN_PMT_PID,
            continuity_counter=1,
            payload=follower_payload,
        )
        transform = PmtInvalidCrcTransform(pmt_invalid_crc_fault())
        # golden fault activation is packet_index 1: first slot at index 1,
        # its CRC tail continues on the following slot (index 2).
        first = transform.apply(1, packet)
        assert first.payload[182:184] == b"\xcc\xcc"  # 0x33 ^ 0xFF, 2 bytes
        assert first.payload[:182] == payload[:182]
        second = transform.apply(2, follower)
        mutated = [
            position
            for position in range(184)
            if second.payload[position] != follower_payload[position]
        ]
        assert mutated == [0, 1]
        assert second.payload[0] == 0xBB  # 0x44 ^ 0xFF (invert corruption)
        assert second.payload[1] == 0xBB
