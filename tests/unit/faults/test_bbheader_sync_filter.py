"""SPEC-204 §Phase2 item 2 — BBHEADER_SYNC_FAULT transform tests (#123).

The B2 primitive's BBFRAME-layer filter: corrupt/shift semantics over the
six BBHEADER fields (EN 302 755 §5.1.7), register_transform self-
registration (orchestrator ruling §10-4), mutation records, activation
gating, and the B2 注入→观测 chain at the in-process face (ruling §10-4:
候选链 mock/进程内验证 — cross-ticket end-to-end lands with #128/#131).
Pure unit face: no I/O, no wall clock.
"""

from __future__ import annotations

import pytest

from ts.t2mi.bbframe import (
    BBFRAME_STATE_CRC8_INVALID,
    BBFRAME_STATE_DFL_MISMATCH,
    BBFRAME_STATE_SYNCD_MISALIGNED,
    BBFRAME_STATE_UPL_INVALID,
    BBHEADER_FIELD_RANGES,
    BBHEADER_SIZE,
    BBFrameBuildConfig,
    build,
    parse,
)
from faults.definition import FaultActivation, FaultDefinition
from faults.filters.bbheader_sync import BBHeaderSyncFaultTransform
from faults.filters.semantic import SemanticFaultFilter
from faults.registry import (
    FAULT_TYPE_BBHEADER_SYNC_FAULT,
    transform_builder_for,
    validate_fault_definition,
)

UPL_BYTES = 188
UPL_BITS = UPL_BYTES * 8
N_UPS = 3
DATA_FIELD_BYTES = N_UPS * UPL_BYTES

EXPECTED_OBSERVATION = "bbframe.recovery_failed"


def _up(index: int, seed: int) -> bytes:
    from ts.t2mi.bbframe import crc8_dvb

    body = bytes(((index * 31 + i * 7 + seed * 11) & 0xFF) for i in range(UPL_BYTES - 1))
    return bytes([crc8_dvb(body)]) + body


def _frames(up_total: int = N_UPS) -> tuple[bytes, ...]:
    stream = b"".join(_up(i, i) for i in range(up_total))
    return build(stream, BBFrameBuildConfig(n_ups=N_UPS))


def _definition(field: str, mode: str, packet_index: int = 0) -> FaultDefinition:
    return FaultDefinition(
        fault_id="11111111-1111-4111-8111-111111111111",
        fault_type=FAULT_TYPE_BBHEADER_SYNC_FAULT,
        target_id="enc-1",
        parameters={"field": field, "mode": mode},
        activation=FaultActivation(kind="packet_index", packet_index=packet_index),
        expected_observations=(EXPECTED_OBSERVATION,),
        layer="BBFRAME",
    )


def _transform(field: str, mode: str, packet_index: int = 0) -> BBHeaderSyncFaultTransform:
    return BBHeaderSyncFaultTransform(_definition(field, mode, packet_index))


def _byte_offsets(before: bytes, after: bytes) -> list[int]:
    return [i for i, (a, b) in enumerate(zip(before, after)) if a != b]


class TestRegistryWiring:
    def test_definition_validates_clean(self) -> None:
        assert validate_fault_definition(_definition("SYNCD", "corrupt")) == ()

    def test_transform_builder_resolves_real_transform_after_import(self) -> None:
        # B2 注入段 (ruling §10-4): the module-level self-registration makes
        # the real transform resolvable without editing factory.py.
        assert transform_builder_for(FAULT_TYPE_BBHEADER_SYNC_FAULT) is (
            BBHeaderSyncFaultTransform
        )

    def test_semantic_filter_composes_and_applies(self) -> None:
        # 候选链进程内面: the plan → SemanticFaultFilter → frames path works
        # and lands a mutation record keyed to the fault identity.
        frames = _frames()
        filter_chain = SemanticFaultFilter((_definition("SYNCD", "corrupt"),))
        faulted = filter_chain.apply(0, frames[0])
        assert isinstance(faulted, bytes)
        log = filter_chain.mutation_log()
        assert FAULT_TYPE_BBHEADER_SYNC_FAULT.encode() in log
        assert EXPECTED_OBSERVATION.encode() in log

    def test_semantic_filter_passes_pre_activation_frames(self) -> None:
        frames = _frames(up_total=8)  # 3 frames: batches [3, 3, 2]
        definition = _definition("SYNCD", "corrupt", packet_index=1)
        filter_chain = SemanticFaultFilter((definition,))
        assert filter_chain.apply(0, frames[0]) == frames[0]
        assert filter_chain.apply(1, frames[1]) != frames[1]


class TestCorruptMode:
    def test_syncd_corrupt_breaks_crc8_and_withholds_ups(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("SYNCD", "corrupt").transform_frame(0, baseline)
        assert len(faulted) == len(baseline)  # slot-preserving
        assert _byte_offsets(baseline, faulted) == [7]  # SYNCD first byte, LSB
        parsed = parse([faulted])[0]
        assert parsed.crc8_valid is False
        assert parsed.state == BBFRAME_STATE_CRC8_INVALID
        assert parsed.up_count == 0  # never silent propagation

    def test_all_fields_corrupt_yield_visible_changes(self) -> None:
        baseline = _frames()[0]
        for field in BBHEADER_FIELD_RANGES:
            faulted = _transform(field, "corrupt").transform_frame(0, baseline)
            offsets = _byte_offsets(baseline, faulted)
            start, _end = BBHEADER_FIELD_RANGES[field]
            assert offsets and offsets[0] == start
            assert len(faulted) == len(baseline)
            assert parse([faulted])[0].crc8_valid is False

    def test_deterministic_double_run(self) -> None:
        baseline = _frames()[0]
        first = _transform("MATYPE", "corrupt").transform_frame(0, baseline)
        second = _transform("MATYPE", "corrupt").transform_frame(0, baseline)
        assert first == second


class TestShiftMode:
    def test_syncd_shift_stays_crc_valid_but_misaligns(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("SYNCD", "shift").transform_frame(0, baseline)
        assert _byte_offsets(baseline, faulted) == [8, 9]  # field + recomputed CRC
        parsed = parse([faulted])[0]
        assert parsed.crc8_valid is True  # internally consistent header
        assert parsed.syncd == 1  # +1 bit — not a byte multiple
        assert parsed.state == BBFRAME_STATE_SYNCD_MISALIGNED
        assert parsed.up_count == 0

    def test_upl_shift_surfaces_upl_invalid(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("UPL", "shift").transform_frame(0, baseline)
        parsed = parse([faulted])[0]
        assert parsed.crc8_valid is True
        assert parsed.state == BBFRAME_STATE_UPL_INVALID

    def test_dfl_shift_surfaces_dfl_mismatch(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("DFL", "shift").transform_frame(0, baseline)
        parsed = parse([faulted])[0]
        assert parsed.crc8_valid is True
        assert parsed.state == BBFRAME_STATE_DFL_MISMATCH

    def test_crc8_field_shift_has_no_recompute(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("CRC-8", "shift").transform_frame(0, baseline)
        assert _byte_offsets(baseline, faulted) == [9]
        assert parse([faulted])[0].state == BBFRAME_STATE_CRC8_INVALID

    def test_matype_shift_changes_value_keeps_crc_valid(self) -> None:
        baseline = _frames()[0]
        faulted = _transform("MATYPE", "shift").transform_frame(0, baseline)
        parsed = parse([faulted])[0]
        assert parsed.matype == 0xD001  # +1 on the 16-bit value
        assert parsed.crc8_valid is True
        assert parsed.state != BBFRAME_STATE_CRC8_INVALID

    def test_all_fields_shift_preserve_length(self) -> None:
        baseline = _frames()[0]
        for field in BBHEADER_FIELD_RANGES:
            faulted = _transform(field, "shift").transform_frame(0, baseline)
            assert len(faulted) == len(baseline)
            assert _byte_offsets(baseline, faulted)  # always a visible change


class TestRecordsAndProtocol:
    def test_mutation_record_shape(self) -> None:
        transform = _transform("SYNCD", "corrupt")
        transform.transform_frame(3, _frames()[0])
        assert len(transform.records) == 1
        record = transform.records[0]
        assert record.fault_type == FAULT_TYPE_BBHEADER_SYNC_FAULT
        assert record.target_node_id == "enc-1"
        assert record.target_pid == -1  # node-internal layer, no pid
        assert record.packet_index == 3
        assert record.parameters == {"field": "SYNCD", "mode": "corrupt"}
        assert record.parameters_schema_version == 1
        assert record.before["frame_sha256"] != record.after["frame_sha256"]
        assert record.before["frame_len"] == record.after["frame_len"]
        assert transform.applied_packet_indexes == (3,)

    def test_activation_gate_leaves_earlier_frames_untouched(self) -> None:
        frames = _frames(up_total=8)  # 3 frames: batches [3, 3, 2]
        transform = _transform("SYNCD", "corrupt", packet_index=2)
        assert transform.apply(1, frames[1]) == frames[1]
        assert transform.apply(2, frames[2]) != frames[2]

    def test_tspacket_input_rejected_loudly(self) -> None:
        from ts.packet import TSPacket

        transform = _transform("SYNCD", "corrupt")
        packet = TSPacket(pid=0x0000, continuity_counter=0, payload=bytes(184))
        with pytest.raises(TypeError, match="BBFRAME layer"):
            transform.apply(0, packet)
        with pytest.raises(TypeError, match="BBFRAME layer"):
            transform.transform(0, packet)

    def test_short_frame_refused(self) -> None:
        with pytest.raises(ValueError, match="BBHEADER"):
            _transform("SYNCD", "corrupt").transform_frame(0, b"\x47\x00")

    def test_unknown_field_and_mode_refused(self) -> None:
        with pytest.raises(ValueError):
            BBHeaderSyncFaultTransform(_definition("NOPE", "corrupt"))
        with pytest.raises(ValueError):
            BBHeaderSyncFaultTransform(_definition("SYNCD", "rotate"))
