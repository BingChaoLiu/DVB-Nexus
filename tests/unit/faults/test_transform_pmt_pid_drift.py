"""SPEC-204 §Phase2 item 4 — PMT_PID_DRIFT transform behavior tests.

The drift fault is the per-program, mid-stream evolution of PMT_PID_MISMATCH
(ticket #139, SC-09): from the activation index the **declaration face**
drifts — the PAT's ``program_map_PID`` per ``new_pid_map`` — and the PMT's
version byte is bumped (``pmt_version_bump``), both with the CRC recomputed
so the faulted stream stays structurally parseable (the symptom is
"declaration vs data drift", never a CRC break).  Slot-preserving at the
shared frame (ADR-0007 item 4): the PAT/PMT sections keep their length, the
data keeps flowing on the real PIDs, and the newly declared PID carries no
data — the "声明 PID 无数据漂移" evidence the DIA-PMT-PID-DRIFT rule reads.
"""

from __future__ import annotations

import pytest

from faults.errors import FaultExecutionError
from faults.filters.pmt_pid_drift import PmtPidDriftTransform
from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket

from tests.unit.faults._fault_builders import (
    GOLDEN_PAT_PID,
    GOLDEN_PMT_PID,
    golden_baseline_packets,
    pmt_pid_drift_fault,
)

pytestmark = pytest.mark.unit

#: PAT / PMT slots of the frozen geometry (golden expectations; PMT period
#: 103 ms lands one slot after each PAT instance).
PAT_SLOTS = (0, 202, 404)
PMT_SLOTS = (1, 206, 412)
#: SC-09 activation (the lab pack's mid-stream drift point).
ACTIVATION = 100
#: The drifted declared pmt_pid (the SC-09 wire value).
DRIFTED_PID = 4608


@pytest.fixture(scope="module")
def baseline() -> tuple:
    return golden_baseline_packets()


def _first_section(payload: bytes) -> bytes:
    start = 1 + payload[0]
    section_length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
    return payload[start : start + 3 + section_length]


def _pat_declared_pid(section: bytes) -> int:
    # single-program PAT: the entry rides section[8:12]
    program_number = int.from_bytes(section[8:10], "big")
    assert program_number == 1
    return ((section[10] & 0x1F) << 8) | section[11]


def _pmt_version(section: bytes) -> int:
    # long-form public header byte 5: reserved '11' + version<<1 + current_next
    return (section[5] >> 1) & 0x1F


def _run(transform, baseline) -> list[TSPacket]:
    return [transform.apply(i, p) for i, p in enumerate(baseline)]


def _changed_slots(before, after) -> list[int]:
    return [
        i
        for i, (b, a) in enumerate(zip(before, after))
        if b.to_bytes() != a.to_bytes()
    ]


class TestDeclarationDriftFace:
    def test_pat_repointed_per_map_from_activation(self, baseline) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        faulted = _run(transform, baseline)
        # pre-activation slots untouched; post-activation: the two PAT
        # instances (declaration drift) + the two PMT instances (version
        # bump) — the drift fault's full wire face
        assert _changed_slots(baseline, faulted) == [202, 206, 404, 412]
        for index in (202, 404):
            section = _first_section(faulted[index].payload)
            assert _pat_declared_pid(section) == DRIFTED_PID
            # the declaration stays VALID: CRC recomputed, never corrupted
            assert verify_mpeg2_crc32(section) is True
        assert _pat_declared_pid(_first_section(faulted[0].payload)) == (
            GOLDEN_PMT_PID
        )

    def test_reserved_bits_of_pid_field_preserved(self, baseline) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        faulted_packet = transform.apply(202, baseline[202])
        section_before = _first_section(baseline[202].payload)
        section_after = _first_section(faulted_packet.payload)
        assert (section_before[10] & 0xE0) == (section_after[10] & 0xE0)
        assert section_after[:10] == section_before[:10]

    def test_int_key_map_coerces_the_same_way(self, baseline) -> None:
        # the Python int-key path (registry validator accepts both faces)
        transform = PmtPidDriftTransform(
            pmt_pid_drift_fault(new_pid_map={1: DRIFTED_PID})
        )
        faulted = _run(transform, baseline)
        assert _changed_slots(baseline, faulted) == [202, 206, 404, 412]


class TestVersionBumpFace:
    def test_pmt_version_bumped_from_activation(self, baseline) -> None:
        # golden geometry seeds version_number=0; post-activation PMT
        # instances declare version 1 (deterministic single bump — every
        # instance re-encodes the same drifted declaration)
        transform = PmtPidDriftTransform(
            pmt_pid_drift_fault(new_pid_map={9: 4100}, pmt_version_bump=True)
        )
        faulted = _run(transform, baseline)
        # the map's program 9 is absent from the stream → PAT face is a
        # no-op; the version face alone moves slots 206 / 412
        assert _changed_slots(baseline, faulted) == [206, 412]
        for index in (206, 412):
            section = _first_section(faulted[index].payload)
            assert _pmt_version(section) == 1
            assert verify_mpeg2_crc32(section) is True
        assert _pmt_version(_first_section(faulted[1].payload)) == 0

    def test_version_byte_reserved_and_current_next_preserved(
        self, baseline
    ) -> None:
        transform = PmtPidDriftTransform(
            pmt_pid_drift_fault(new_pid_map={9: 4100})
        )
        faulted_packet = transform.apply(206, baseline[206])
        section_before = _first_section(baseline[206].payload)
        section_after = _first_section(faulted_packet.payload)
        assert (section_before[5] & 0b1100_0001) == (
            section_after[5] & 0b1100_0001
        )
        # only the version nibble (byte 5) + the CRC field differ from the
        # baseline section — the drift is a declaration update, not corruption
        assert section_after[:5] == section_before[:5]
        assert section_after[8:-4] == section_before[8:-4]

    def test_version_bump_disabled_keeps_pmt_verbatim(self, baseline) -> None:
        transform = PmtPidDriftTransform(
            pmt_pid_drift_fault(pmt_version_bump=False)
        )
        faulted = _run(transform, baseline)
        for index in PMT_SLOTS:
            assert faulted[index].to_bytes() == baseline[index].to_bytes()


class TestSlotPreservation:
    def test_one_packet_in_one_packet_out_same_slot(self, baseline) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        faulted = _run(transform, baseline)
        assert len(faulted) == len(baseline)
        for index in (202, 206, 404, 412):
            before = baseline[index]
            after = faulted[index]
            assert after.pid == before.pid
            assert after.continuity_counter == before.continuity_counter
            assert (
                after.payload_unit_start_indicator
                == before.payload_unit_start_indicator
            )
            assert len(after.to_bytes()) == len(before.to_bytes())

    def test_data_pids_keep_flowing(self, baseline) -> None:
        """The drift touches only the declaration faces: everything not on
        the PAT / PMT pids passes verbatim (声明 PID 无数据 — no data ever
        appears on the drifted PID, the symptom face)."""
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        faulted = _run(transform, baseline)
        for index, packet in enumerate(baseline):
            if packet.pid in (GOLDEN_PAT_PID, GOLDEN_PMT_PID):
                continue
            assert faulted[index].to_bytes() == packet.to_bytes()
        # and nothing was ever emitted on the drifted PID itself
        assert all(p.pid != DRIFTED_PID for p in faulted)


class TestNoOpFaces:
    def test_map_without_matching_program_changes_nothing(self, baseline) -> None:
        transform = PmtPidDriftTransform(
            pmt_pid_drift_fault(
                new_pid_map={9: 4100}, pmt_version_bump=False
            )
        )
        faulted = _run(transform, baseline)
        assert _changed_slots(baseline, faulted) == []
        assert transform.records == []

    def test_non_psi_slots_pass_through(self) -> None:
        from faults.filters.pat_missing import null_packet

        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        packet = null_packet()
        assert transform.apply(0, packet) is packet


class TestFragmentedSections:
    def _fragmented(self, pid: int, table_id: int) -> TSPacket:
        # section_length 0x300 (768) > available payload: fragmentation
        # (the pmt_pid_mismatch fragmented-PAT crafting, both tables)
        payload_head = bytes([0x00, table_id, 0xB3, 0x00])
        payload = payload_head + b"\x00" * (184 - len(payload_head))
        return TSPacket(
            pid=pid,
            continuity_counter=0,
            payload=payload,
            payload_unit_start_indicator=True,
        )

    def test_fragmented_pat_is_an_explicit_run_failure(self) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        with pytest.raises(FaultExecutionError) as excinfo:
            transform.apply(202, self._fragmented(GOLDEN_PAT_PID, 0x00))
        assert excinfo.value.code == "SIM_FAULT_EXEC_FAILED"

    def test_fragmented_pmt_is_an_explicit_run_failure(self) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        with pytest.raises(FaultExecutionError) as excinfo:
            transform.apply(206, self._fragmented(GOLDEN_PMT_PID, 0x02))
        assert excinfo.value.code == "SIM_FAULT_EXEC_FAILED"


class TestMutationRecords:
    def test_one_record_per_actual_change(self, baseline) -> None:
        transform = PmtPidDriftTransform(pmt_pid_drift_fault())
        _run(transform, baseline)
        indexes = [r.packet_index for r in transform.records]
        assert indexes == [202, 206, 404, 412]
        changes = {r.change for r in transform.records}
        assert any("program_map_PID drifted" in c for c in changes)
        assert any("version" in c for c in changes)
        for record in transform.records:
            assert record.fault_type == "PMT_PID_DRIFT"
            assert record.target_pid == GOLDEN_PMT_PID
            assert record.parameters_schema_version == 1
        assert transform.applied_packet_indexes == (202, 206, 404, 412)


class TestRegistration:
    def test_real_builder_self_registers_over_the_skeleton(self) -> None:
        """Import side effect (ruling §10-4): importing the real module
        binds the drift transform over the #121 skeleton placeholder."""
        import faults.factory as factory
        import faults.filters.pmt_pid_drift  # noqa: F401 — activation import

        assert (
            factory.transform_builder_for("PMT_PID_DRIFT")
            is PmtPidDriftTransform
        )

    def test_semantic_filter_drives_the_drift_end_to_end(
        self, baseline
    ) -> None:
        from faults.filters.semantic import SemanticFaultFilter

        plan_filter = SemanticFaultFilter((pmt_pid_drift_fault(),))
        faulted = [plan_filter.apply(i, p) for i, p in enumerate(baseline)]
        assert _changed_slots(baseline, faulted) == [202, 206, 404, 412]
        log = plan_filter.mutation_log()
        assert b"PMT_PID_DRIFT" in log
