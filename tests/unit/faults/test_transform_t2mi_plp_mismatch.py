"""T2MI_PLP_MISMATCH real transform (SPEC-602 §7 B1 path, ticket #124).

The fault transform replaces the #121 skeleton via import-time
self-registration (ruling §10-4 — ``factory.py`` is never edited again).
Semantics (SPEC-602 §7 / ticket #124): the faulted encapsulator stamps
the business PLP with ``actual_plp`` while the demux still filters on
``expected_plp`` — the slot-preserving wire face of that drift is a
transport-prefix PLP re-stamp on matching BBFRAME T2-MI packets:

- ``session_start`` activation (default): every matching packet, whole run;
- ``packet_index`` activation (+ the ``plp_version_switch`` variant,
  #111): the PLP switches mid-stream at the activation index — expected
  before, actual from there through run end;
- non-BBFRAME packets (padding/unknown) and packets already carrying a
  different PLP pass untouched; only the PLP byte changes (CRC-32
  recomputed so the faulted stream stays structurally parseable — the
  corruption is semantic, not structural).

Layer discipline: this is a T2MI-layer transform; the layer chain drives
it with :class:`ts.t2mi.packet.T2miPacket` inputs.  A TS-packet input
refuses loudly — silently passing a TS slot through would fake a green
run (the skeleton's honest-NotImplementedError discipline, continued).
"""

from __future__ import annotations

import re

import pytest

from ts.packet import TSPacket
from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.parser import parse

from faults.definition import FaultActivation, FaultDefinition
from faults.factory import transform_builder_for
from faults.filters.pat_missing import null_packet
from faults.filters.t2mi_plp_mismatch import T2miPlpMismatchTransform
from faults.registry import (
    FAULT_TYPE_T2MI_PLP_MISMATCH,
    PARAMETERS_SCHEMA_VERSION,
)

pytestmark = pytest.mark.unit

EXPECTED_PLP = 3
ACTUAL_PLP = 7
UPL_BYTES = 188
BBHEADER_SIZE = 10


def _frame(up_count: int, seed: int) -> bytes:
    header = bytes(((i + seed) * 13) & 0xFF for i in range(BBHEADER_SIZE))
    ups = b"".join(
        bytes(((i + j) * 17 + seed * 11) & 0xFF for j in range(UPL_BYTES))
        for i in range(up_count)
    )
    return header + ups


def _packets(plp_ids: list[int]) -> tuple:
    return build(
        [_frame(1, i) for i in range(len(plp_ids))],
        T2miBuildConfig(),
        plp_ids=plp_ids,
    )


def _definition(
    parameters: dict | None = None,
    activation: FaultActivation | None = None,
    target_id: str = "t2mi-enc-0",
) -> FaultDefinition:
    return FaultDefinition(
        fault_id="f-t2mi-plp-001",
        fault_type=FAULT_TYPE_T2MI_PLP_MISMATCH,
        target_id=target_id,
        parameters=(
            parameters
            if parameters is not None
            else {"expected_plp": EXPECTED_PLP, "actual_plp": ACTUAL_PLP}
        ),
        activation=(
            activation if activation is not None else FaultActivation(kind="session_start")
        ),
        expected_observations=("t2mi.plp_mismatch",),
        layer="T2MI",
    )


class TestSelfRegistration:
    def test_resolves_to_the_real_transform(self) -> None:
        # Importing the owning module self-registers (ruling §10-4); the
        # resolution order puts it ahead of the #121 skeleton tier.
        assert transform_builder_for(FAULT_TYPE_T2MI_PLP_MISMATCH) is (
            T2miPlpMismatchTransform
        )


class TestWholeRunRestamp:
    """session_start activation: the whole run drifts to ``actual_plp``."""

    def test_matching_packets_are_restamped(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = T2miPlpMismatchTransform(_definition())
        faulted = [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert [packet.plp_id for packet in faulted] == [ACTUAL_PLP] * 3
        assert all(packet.crc32_valid for packet in faulted)

    def test_identity_faces_are_preserved(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = T2miPlpMismatchTransform(_definition())
        faulted = [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert [p.packet_counter for p in faulted] == [p.packet_counter for p in packets]
        assert [p.frame_index for p in faulted] == [p.frame_index for p in packets]
        assert [p.total_size for p in faulted] == [p.total_size for p in packets]
        assert [p.payload_bits for p in faulted] == [p.payload_bits for p in packets]

    def test_only_the_plp_byte_changes(self) -> None:
        packets = _packets([EXPECTED_PLP] * 2)
        transform = T2miPlpMismatchTransform(_definition())
        for index, packet in enumerate(packets):
            faulted = transform.apply(index, packet)
            original = packet.to_bytes()
            result = faulted.to_bytes()
            assert len(result) == len(original)
            differing = [
                offset for offset in range(len(original)) if result[offset] != original[offset]
            ]
            # Header+payload region: only the transport-prefix PLP byte
            # (header 6 bytes + prefix byte 0 → PLP byte at offset 7).
            body_diff = [offset for offset in differing if offset < len(original) - 4]
            assert body_diff == [1 + 6]
            # The 4-byte CRC trailer differs — recomputed over the new
            # payload so the faulted packet stays structurally valid.
            assert differing[1:] == [
                len(original) - 4,
                len(original) - 3,
                len(original) - 2,
                len(original) - 1,
            ]

    def test_non_matching_plp_passes_untouched(self) -> None:
        packets = _packets([EXPECTED_PLP, 5, EXPECTED_PLP])
        transform = T2miPlpMismatchTransform(_definition())
        faulted = [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert [packet.plp_id for packet in faulted] == [ACTUAL_PLP, 5, ACTUAL_PLP]
        assert faulted[1] == packets[1]
        assert len(transform.records) == 2  # only actual changes are recorded

    def test_deterministic(self) -> None:
        packets = _packets([EXPECTED_PLP] * 2)
        first = T2miPlpMismatchTransform(_definition())
        second = T2miPlpMismatchTransform(_definition())
        assert [first.apply(i, p) for i, p in enumerate(packets)] == [
            second.apply(i, p) for i, p in enumerate(packets)
        ]


class TestMidStreamVersionSwitch:
    """plp_version_switch: the PLP switches at the packet_index activation."""

    def _transform(self) -> T2miPlpMismatchTransform:
        return T2miPlpMismatchTransform(
            _definition(
                parameters={
                    "expected_plp": EXPECTED_PLP,
                    "actual_plp": ACTUAL_PLP,
                    "plp_version_switch": True,
                },
                activation=FaultActivation(kind="packet_index", packet_index=1),
            )
        )

    def test_plp_switches_at_the_activation_index(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = self._transform()
        faulted = [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert [packet.plp_id for packet in faulted] == [EXPECTED_PLP, ACTUAL_PLP, ACTUAL_PLP]

    def test_records_carry_the_switch_point(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = self._transform()
        [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert transform.applied_packet_indexes == (1, 2)

    def test_version_switch_requires_a_packet_index_activation(self) -> None:
        with pytest.raises(ValueError, match="packet_index"):
            T2miPlpMismatchTransform(
                _definition(
                    parameters={
                        "expected_plp": EXPECTED_PLP,
                        "actual_plp": ACTUAL_PLP,
                        "plp_version_switch": True,
                    },
                    activation=FaultActivation(kind="session_start"),
                )
            )

    def test_switch_flag_absent_still_gates_from_the_activation(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = T2miPlpMismatchTransform(
            _definition(
                activation=FaultActivation(kind="packet_index", packet_index=1),
            )
        )
        faulted = [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert [packet.plp_id for packet in faulted] == [EXPECTED_PLP, ACTUAL_PLP, ACTUAL_PLP]


class TestNonBbframePackets:
    def test_padding_packets_pass_untouched(self) -> None:
        from ts.t2mi.packet import T2miPacket, encode_packet, make_header_reserved
        from ts.crc import mpeg2_crc32

        payload = bytes((i * 23 + 5) & 0xFF for i in range(8))
        reserved = make_header_reserved(0)
        prefix = bytes([0xFF, 0, reserved[0], reserved[1]]) + (len(payload) * 8).to_bytes(
            2, "big"
        )
        padding = T2miPacket(
            packet_type=0xFF,
            packet_counter=3,
            reserved=reserved,
            payload_bits=len(payload) * 8,
            payload=payload,
            crc32=mpeg2_crc32(prefix + payload),
        )
        transform = T2miPlpMismatchTransform(_definition())
        assert transform.apply(0, padding) == padding
        assert transform.records == []


class TestTsPacketInputIsRefused:
    def test_ts_layer_slot_input_refused_loudly(self) -> None:
        # The T2MI-layer chain drives T2miPacket inputs; a TS slot here
        # means the fault was routed to the wrong layer — refuse loudly
        # instead of faking a pass-through.
        transform = T2miPlpMismatchTransform(_definition())
        with pytest.raises(TypeError, match="T2miPacket"):
            transform.apply(0, null_packet())


class TestRecordsAndSummary:
    def test_mutation_records_shape(self) -> None:
        packets = _packets([EXPECTED_PLP] * 2)
        transform = T2miPlpMismatchTransform(_definition())
        [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert len(transform.records) == 2
        record = transform.records[0]
        assert record.fault_id == "f-t2mi-plp-001"
        assert record.fault_type == FAULT_TYPE_T2MI_PLP_MISMATCH
        assert record.target_node_id == "t2mi-enc-0"
        assert record.target_pid == -1  # node-level bare slug target
        assert record.packet_index == 0
        assert record.change == "t2mi_plp_restamp"
        assert record.parameters["expected_plp"] == EXPECTED_PLP
        assert record.parameters["actual_plp"] == ACTUAL_PLP
        assert record.parameters_schema_version == PARAMETERS_SCHEMA_VERSION
        assert record.before["plp_id"] == EXPECTED_PLP
        assert record.after["plp_id"] == ACTUAL_PLP
        assert re.fullmatch(r"[0-9a-f]{64}", record.before["slot_sha256"])
        assert record.before["slot_sha256"] != record.after["slot_sha256"]

    def test_restamp_summary_counts(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = T2miPlpMismatchTransform(
            _definition(
                parameters={
                    "expected_plp": EXPECTED_PLP,
                    "actual_plp": ACTUAL_PLP,
                    "plp_version_switch": True,
                },
                activation=FaultActivation(kind="packet_index", packet_index=1),
            )
        )
        [transform.apply(index, packet) for index, packet in enumerate(packets)]
        summary = transform.restamp_summary()
        assert summary == {
            "restamped_packet_count": 2,
            "expected_plp": EXPECTED_PLP,
            "actual_plp": ACTUAL_PLP,
            "plp_version_switch": True,
            "first_restatement_index": 1,
        }

    def test_no_matching_packets_gives_an_honest_zero_summary(self) -> None:
        packets = _packets([5, 5])
        transform = T2miPlpMismatchTransform(_definition())
        [transform.apply(index, packet) for index, packet in enumerate(packets)]
        assert transform.restamp_summary()["restamped_packet_count"] == 0
        assert transform.restamp_summary()["first_restatement_index"] is None
        assert transform.records == []


class TestFaultedStreamStaysParseable:
    """The drift is semantic: the faulted T2-MI stream must still parse
    cleanly (structural validity = the B1 'outer green light' face)."""

    def test_faulted_stream_parses_with_valid_crc(self) -> None:
        packets = _packets([EXPECTED_PLP] * 3)
        transform = T2miPlpMismatchTransform(_definition())
        faulted_bytes = b"".join(
            transform.apply(index, packet).to_bytes() for index, packet in enumerate(packets)
        )
        result = parse(faulted_bytes)
        assert not result.truncated
        assert all(packet.crc32_valid for packet in result)
        assert [packet.plp_id for packet in result] == [ACTUAL_PLP] * 3

    def test_faulted_stream_packet_counters_stay_continuous(self) -> None:
        packets = _packets([EXPECTED_PLP] * 4)
        transform = T2miPlpMismatchTransform(_definition())
        faulted_bytes = b"".join(
            transform.apply(index, packet).to_bytes() for index, packet in enumerate(packets)
        )
        counters = [packet.packet_counter for packet in parse(faulted_bytes)]
        assert counters == [(0 + offset) % 256 for offset in range(4)]
