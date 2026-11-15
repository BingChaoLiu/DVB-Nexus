"""SPEC-204 §6.1 — PAT_MISSING transform behavior tests.

Real-packet fixtures come from the golden-geometry generator chain
(tests/unit/faults/_fault_builders); expectations are derived from the
frozen geometry (PAT slots at 0/202/404) and the canonical Null packet
shape of the oracle transform script.
"""

from __future__ import annotations

import pytest

from faults.filters.pat_missing import PatMissingTransform, null_packet
from ts.packet import PID_NULL

from tests.unit.faults._fault_builders import (
    GOLDEN_PACKET_COUNT,
    GOLDEN_PAT_PID,
    golden_baseline_packets,
    pat_missing_fault,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


class TestNullPacketShape:
    def test_canonical_null_serializes_to_the_oracle_shape(self) -> None:
        packet = null_packet()
        data = packet.to_bytes()
        assert len(data) == 188
        assert data[0] == 0x47
        assert data[1] == 0x1F  # PUSI=0, PID high bits
        assert data[2] == 0xFF
        assert data[3] == 0x10  # AFC=01, CC=0
        assert set(data[4:]) == {0xFF}

    def test_null_pid_constant(self) -> None:
        assert PID_NULL == 0x1FFF


class TestPatMissingTransform:
    def test_window_replaces_pid0_slots_from_activation(self, baseline) -> None:
        transform = PatMissingTransform(pat_missing_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        assert len(faulted) == GOLDEN_PACKET_COUNT
        # window start 202: slots 202 and 404 (the only PID-0 slots after
        # the activation) become Null packets; slot 0 stays PAT.
        for index in (202, 404):
            assert faulted[index].pid == PID_NULL
        assert faulted[0].pid == GOLDEN_PAT_PID
        assert faulted[0].to_bytes() == baseline[0].to_bytes()

    def test_non_pat_slots_untouched(self, baseline) -> None:
        transform = PatMissingTransform(pat_missing_fault())
        for index, packet in enumerate(baseline):
            if packet.pid == GOLDEN_PAT_PID and index >= 202:
                continue
            faulted = transform.apply(index, packet)
            assert faulted.to_bytes() == packet.to_bytes()

    def test_slot_preserving_every_index(self, baseline) -> None:
        transform = PatMissingTransform(pat_missing_fault())
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        assert len(faulted) == len(baseline)
        for index, (before, after) in enumerate(zip(baseline, faulted)):
            assert after.to_bytes() == transform.apply(index, before).to_bytes()
        # each mutated slot differs ONLY at a declared slot; untouched slots
        # are byte-identical (等位替换 invariant, SPEC-204 §7).
        changed = [
            i
            for i, (before, after) in enumerate(zip(baseline, faulted))
            if before.to_bytes() != after.to_bytes()
        ]
        assert changed == [202, 404]

    def test_cc_recover_clause_has_no_instance_in_mvp(self, baseline) -> None:
        """The MVP window runs to the run end: no PID-0 PAT follows the
        window, so the §6.1 CC 重盖 clause has nothing to re-cover and no
        secondary PID-0 continuity symptom exists."""
        pid0_after_window = [
            packet
            for index, packet in enumerate(baseline)
            if index >= 202 and packet.pid == GOLDEN_PAT_PID
        ]
        # (sanity of the geometry: 202/404 are the only windowed PID-0 slots)
        assert len(pid0_after_window) == 2

    def test_mutation_records_locate_each_substitution(self, baseline) -> None:
        transform = PatMissingTransform(pat_missing_fault())
        for index, packet in enumerate(baseline):
            transform.apply(index, packet)
        assert [record.packet_index for record in transform.records] == [202, 404]
        first = transform.records[0]
        assert first.fault_type == "PAT_MISSING"
        assert first.target_pid == GOLDEN_PAT_PID
        assert first.before["pid"] == GOLDEN_PAT_PID
        assert first.after["pid"] == PID_NULL
        assert first.parameters_schema_version == 1

    def test_session_start_activation_covers_pid0_from_slot_0(
        self, baseline
    ) -> None:
        from faults.definition import FaultActivation, FaultDefinition

        definition = FaultDefinition(
            fault_id="f",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            activation=FaultActivation(kind="session_start"),
            expected_observations=("ts.psi_section_observed",),
        )
        transform = PatMissingTransform(definition)
        faulted = [transform.apply(i, p) for i, p in enumerate(baseline)]
        # The baseline already carries stuffing Nulls (PID 0x1FFF); the
        # fault adds exactly the three PAT slots as canonical Nulls.
        canonical = null_packet().to_bytes()
        for index in (0, 202, 404):
            assert baseline[index].pid == GOLDEN_PAT_PID
            assert faulted[index].to_bytes() == canonical
        for index, packet in enumerate(baseline):
            if packet.pid != GOLDEN_PAT_PID:
                assert faulted[index].to_bytes() == packet.to_bytes()
