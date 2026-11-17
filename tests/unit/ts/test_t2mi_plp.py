"""SPEC-602 §5/§6/§8 — PLP filter/assign/plps_seen unit tests (#124).

The three public faces of ``ts.t2mi.plp`` plus the reserved
``t2mi.plp_mismatch`` emission seam (ruling §10-7: the registry entry
lands with #129, so the seam is verified here with a mock emitter —
frozen payload key set, absence honesty, determinism). No I/O, no wall
clock; every T2-MI byte comes from the deterministic builder/parse chain
(tests/README §5 — no hand-assembled byte literals).
"""

from __future__ import annotations

import re

import pytest

from ts.crc import mpeg2_crc32
from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.packet import T2miPacket, encode_packet, make_header_reserved
from ts.t2mi.parser import parse
from ts.t2mi.plp import (
    PLP_MISMATCH_EVIDENCE_KEYS,
    PLP_MISMATCH_PAYLOAD_KEYS,
    PlpAssignment,
    PlpAssignmentEntry,
    PlpFilterConfig,
    T2MI_PLP_MISMATCH_EVENT_TYPE,
    assign,
    collect_plp_mismatch,
    emit_plp_mismatch,
    filter,
    plps_seen,
)

UPL_BYTES = 188
BBHEADER_SIZE = 10


def _frame(up_count: int, seed: int) -> bytes:
    header = bytes(((i + seed) * 13) & 0xFF for i in range(BBHEADER_SIZE))
    ups = b"".join(
        bytes(((i + j) * 17 + seed * 11) & 0xFF for j in range(UPL_BYTES))
        for i in range(up_count)
    )
    return header + ups


def _encode_one(packet_type: int, body_seed: int) -> bytes:
    payload = bytes((i * 31 + body_seed * 7) & 0xFF for i in range(8))
    reserved = make_header_reserved(0)
    prefix = bytes([packet_type, 0, reserved[0], reserved[1]]) + (
        len(payload) * 8
    ).to_bytes(2, "big")
    crc = mpeg2_crc32(prefix + payload)
    return encode_packet(
        T2miPacket(
            packet_type=packet_type,
            packet_counter=0,
            reserved=reserved,
            payload_bits=len(payload) * 8,
            payload=payload,
            crc32=crc,
        )
    )


def _multi_plp_packets() -> tuple[T2miPacket, ...]:
    return build(
        [_frame(1, 0), _frame(1, 1), _frame(1, 2), _frame(1, 3)],
        T2miBuildConfig(),
        plp_ids=[7, 3, 7, 5],
    )


def _assignment() -> PlpAssignment:
    return PlpAssignment(
        entries=(
            PlpAssignmentEntry(plp_id=7, source_tag="business"),
            PlpAssignmentEntry(plp_id=3, source_tag="si"),
        )
    )


class TestPlpAssignmentValidation:
    """SPEC-602 §8: assignment-table conflicts and out-of-range PLP IDs are
    refused before prepare (schema-face rejection)."""

    def test_valid_entries_are_preserved(self) -> None:
        table = _assignment()
        assert [entry.plp_id for entry in table.entries] == [7, 3]
        assert [entry.source_tag for entry in table.entries] == ["business", "si"]

    def test_duplicate_source_tag_is_a_conflict(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(
                entries=(
                    PlpAssignmentEntry(plp_id=7, source_tag="business"),
                    PlpAssignmentEntry(plp_id=3, source_tag="business"),
                )
            )
        assert "T2MI_PLP_ASSIGNMENT_CONFLICT" in str(excinfo.value)

    def test_duplicate_plp_id_is_a_conflict(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(
                entries=(
                    PlpAssignmentEntry(plp_id=7, source_tag="business"),
                    PlpAssignmentEntry(plp_id=7, source_tag="si"),
                )
            )
        assert "T2MI_PLP_ASSIGNMENT_CONFLICT" in str(excinfo.value)

    def test_empty_entries_are_refused(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(entries=())
        assert "T2MI_PLP_ASSIGNMENT_EMPTY" in str(excinfo.value)

    @pytest.mark.parametrize("plp_id", [-1, 256, 1000])
    def test_plp_id_out_of_range_is_refused(self, plp_id: int) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=plp_id, source_tag="a"),))
        assert "T2MI_PLP_ID_OUT_OF_RANGE" in str(excinfo.value)

    def test_bool_plp_id_is_refused_as_type_error(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=True, source_tag="a"),))
        assert "T2MI_PLP_ID_OUT_OF_RANGE" in str(excinfo.value)

    @pytest.mark.parametrize("source_tag", ["", "  "])
    def test_empty_or_blank_source_tag_is_refused(self, source_tag: str) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=0, source_tag=source_tag),))
        assert "T2MI_PLP_SOURCE_TAG_INVALID" in str(excinfo.value)

    def test_non_str_source_tag_is_refused(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=0, source_tag=7),))
        assert "T2MI_PLP_SOURCE_TAG_INVALID" in str(excinfo.value)


class TestPlpFilterConfigValidation:
    """SPEC-602 §5: ``mode: expected | all`` + ``expected_plp`` rules."""

    def test_all_mode_without_plp_is_valid(self) -> None:
        config = PlpFilterConfig(mode="all")
        assert config.mode == "all"
        assert config.expected_plp is None

    def test_expected_mode_with_plp_is_valid(self) -> None:
        config = PlpFilterConfig(mode="expected", expected_plp=7)
        assert config.expected_plp == 7

    def test_expected_mode_requires_expected_plp(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpFilterConfig(mode="expected")
        assert "T2MI_PLP_FILTER_CONFIG_INVALID" in str(excinfo.value)

    def test_unknown_mode_is_refused(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpFilterConfig(mode="some", expected_plp=1)
        assert "T2MI_PLP_FILTER_CONFIG_INVALID" in str(excinfo.value)

    def test_expected_plp_out_of_range_is_refused(self) -> None:
        with pytest.raises(Exception) as excinfo:
            PlpFilterConfig(mode="expected", expected_plp=256)
        assert "T2MI_PLP_ID_OUT_OF_RANGE" in str(excinfo.value)


class TestAssign:
    """SPEC-602 §6: ``plp.assign(sources, assignment)`` — encapsulator-side
    PLP annotation composed over the #122 ``build`` ``plp_ids`` seam."""

    def test_single_source_frames_get_the_assigned_plp(self) -> None:
        packets = assign(
            {"business": [_frame(1, 0), _frame(1, 1)]},
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=7, source_tag="business"),)),
        )
        assert [packet.plp_id for packet in packets] == [7, 7]
        assert all(packet.crc32_valid for packet in packets)
        assert [packet.frame_index for packet in packets] == [0, 1]

    def test_multi_source_frame_order_is_insertion_order(self) -> None:
        packets = assign(
            {
                "business": [_frame(1, 0), _frame(1, 1)],
                "si": [_frame(1, 2)],
            },
            _assignment(),
        )
        assert [packet.plp_id for packet in packets] == [7, 7, 3]
        assert [packet.frame_index for packet in packets] == [0, 1, 2]

    def test_same_inputs_same_packets(self) -> None:
        sources = {"business": [_frame(1, 0)], "si": [_frame(1, 1)]}
        assert assign(sources, _assignment()) == assign(sources, _assignment())

    def test_build_config_passes_through(self) -> None:
        config = T2miBuildConfig(first_packet_counter=5, first_frame_index=9)
        packets = assign(
            {"business": [_frame(1, 0)]},
            PlpAssignment(entries=(PlpAssignmentEntry(plp_id=1, source_tag="business"),)),
            config=config,
        )
        assert packets[0].packet_counter == 5
        assert packets[0].frame_index == 9

    def test_unassigned_source_is_refused_before_build(self) -> None:
        with pytest.raises(Exception) as excinfo:
            assign({"unassigned": [_frame(1, 0)]}, _assignment())
        assert "T2MI_PLP_ASSIGNMENT_UNASSIGNED_SOURCE" in str(excinfo.value)

    def test_unused_assignment_entry_is_tolerated(self) -> None:
        packets = assign(
            {"business": [_frame(1, 0)]},
            _assignment(),  # "si" has no frames this run
        )
        assert [packet.plp_id for packet in packets] == [7]


class TestFilter:
    """SPEC-602 §6: ``plp.filter(packets, config)`` — deterministic; expected
    PLP absent → explicit empty result + candidate payload (非静默空)."""

    def test_all_mode_passes_everything_through_verbatim(self) -> None:
        stream = _encode_one(0x00, 1) + _encode_one(0xFF, 2)
        packets = tuple(parse(stream))
        config = PlpFilterConfig(mode="all")
        assert tuple(filter(packets, config)) == packets
        assert len(filter(packets, config)) == 2  # padding included, not dropped

    def test_expected_mode_selects_only_matching_plp(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=7)
        selected = filter(packets, config)
        assert [packet.plp_id for packet in selected] == [7, 7]
        assert [packet.frame_index for packet in selected] == [0, 2]

    def test_expected_mode_preserves_stream_order(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=3)
        assert [packet.frame_index for packet in filter(packets, config)] == [1]

    def test_same_stream_same_config_same_result(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=5)
        assert tuple(filter(packets, config)) == tuple(filter(packets, config))

    def test_expected_plp_absent_gives_explicit_empty_result(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        selected = filter(packets, config)
        assert selected == ()
        assert collect_plp_mismatch(packets, config) is not None  # honest, not silent

    def test_expected_plp_present_produces_no_candidate(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=7)
        assert collect_plp_mismatch(packets, config) is None

    def test_all_mode_never_produces_a_candidate(self) -> None:
        stream = _encode_one(0x00, 1)
        packets = tuple(parse(stream))
        assert collect_plp_mismatch(packets, PlpFilterConfig(mode="all")) is None

    def test_absence_with_emitter_emits_the_reserved_candidate(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        captured: list[tuple[str, dict]] = []
        filter(packets, config, emitter=lambda t, p: captured.append((t, dict(p))))
        assert len(captured) == 1
        event_type, payload = captured[0]
        assert event_type == T2MI_PLP_MISMATCH_EVENT_TYPE
        assert set(payload) == PLP_MISMATCH_PAYLOAD_KEYS

    def test_matching_stream_does_not_emit(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=7)
        captured: list[tuple[str, dict]] = []
        filter(packets, config, emitter=lambda t, p: captured.append((t, dict(p))))
        assert captured == []


class TestPlpsSeen:
    """SPEC-602 §6: ``plp.plps_seen(packets)`` — the stream's actual PLP set
    (diagnostic evidence, first-appearance order, distinct)."""

    def test_multi_plp_first_appearance_order(self) -> None:
        seen = plps_seen(_multi_plp_packets())
        assert seen == {"plps_seen": [7, 3, 5]}

    def test_single_plp_stream(self) -> None:
        packets = build([_frame(1, 0)], T2miBuildConfig())
        assert plps_seen(packets) == {"plps_seen": [0]}  # builder default plp_id=0

    def test_repeated_plp_is_reported_once(self) -> None:
        packets = build([_frame(1, 0), _frame(1, 1)], T2miBuildConfig(), plp_ids=[4, 4])
        assert plps_seen(packets) == {"plps_seen": [4]}

    def test_padding_stream_has_no_plps(self) -> None:
        packets = tuple(parse(_encode_one(0xFF, 2)))
        assert plps_seen(packets) == {"plps_seen": []}

    def test_shape_matches_the_plp_seen_dto_keys(self) -> None:
        seen = plps_seen(_multi_plp_packets())
        assert set(seen) == {"plps_seen"}
        assert all(isinstance(plp, int) for plp in seen["plps_seen"])


class TestCollectPlpMismatch:
    """SPEC-602 §5: the ``t2mi.plp_mismatch`` payload shape (frozen keys)."""

    def test_payload_keys_are_the_frozen_set(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        payload = collect_plp_mismatch(packets, config)
        assert payload is not None
        assert set(payload) == PLP_MISMATCH_PAYLOAD_KEYS

    def test_single_drifted_plp_is_the_actual_plp(self) -> None:
        packets = build([_frame(1, 0), _frame(1, 1)], T2miBuildConfig(), plp_ids=[7, 7])
        config = PlpFilterConfig(mode="expected", expected_plp=3)
        payload = collect_plp_mismatch(packets, config)
        assert payload is not None
        assert payload["expected_plp"] == 3
        assert payload["actual_plp"] == 7

    def test_multi_plp_stream_leaves_actual_plp_honestly_null(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        payload = collect_plp_mismatch(packets, config)
        assert payload is not None
        assert payload["actual_plp"] is None
        assert payload["business_absent_evidence"]["plps_seen"] == [7, 3, 5]

    def test_evidence_keys_are_frozen_and_counts_are_honest(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        payload = collect_plp_mismatch(packets, config)
        evidence = payload["business_absent_evidence"]
        assert set(evidence) == PLP_MISMATCH_EVIDENCE_KEYS
        assert evidence["filtered_packet_count"] == 0
        assert evidence["bbframe_packet_count"] == 4
        assert evidence["total_packet_count"] == 4

    def test_padding_only_stream_is_an_absence_with_no_actual(self) -> None:
        packets = tuple(parse(_encode_one(0xFF, 2)))
        config = PlpFilterConfig(mode="expected", expected_plp=0)
        payload = collect_plp_mismatch(packets, config)
        assert payload is not None
        assert payload["actual_plp"] is None
        assert payload["business_absent_evidence"]["plps_seen"] == []
        assert payload["business_absent_evidence"]["total_packet_count"] == 1

    def test_collect_is_deterministic(self) -> None:
        packets = _multi_plp_packets()
        config = PlpFilterConfig(mode="expected", expected_plp=99)
        assert collect_plp_mismatch(packets, config) == collect_plp_mismatch(
            packets, config
        )


class TestEmitPlpMismatch:
    """Ruling §10-7: emitter-injected seam, frozen key set, drift refusal."""

    def test_emits_frozen_event_type_with_payload_copy(self) -> None:
        captured: list[tuple[str, dict]] = []
        payload = {
            "expected_plp": 3,
            "actual_plp": 7,
            "business_absent_evidence": {"plps_seen": [7], "a": 1, "b": 2, "c": 3},
        }
        emit_plp_mismatch(lambda t, p: captured.append((t, dict(p))), payload)
        assert len(captured) == 1
        event_type, emitted = captured[0]
        assert event_type == T2MI_PLP_MISMATCH_EVENT_TYPE
        assert emitted == payload

    def test_payload_key_drift_is_refused(self) -> None:
        with pytest.raises(ValueError, match="plp_mismatch payload key drift"):
            emit_plp_mismatch(lambda t, p: None, {"expected_plp": 1})

    def test_seam_accepts_any_callable_object(self) -> None:
        # #128 binds SimulationEventEmitter here without ts importing
        # simulation (ts purity contract) — duck-typed callable is the seam.
        captured: list[str] = []

        class RecordingEmitter:
            def __call__(self, event_type: str, payload: dict) -> None:
                captured.append(event_type)

        payload = {
            "expected_plp": 3,
            "actual_plp": None,
            "business_absent_evidence": {"x": 1, "y": 2, "z": 3, "w": 4},
        }
        emit_plp_mismatch(RecordingEmitter(), payload)
        assert captured == [T2MI_PLP_MISMATCH_EVENT_TYPE]

    def test_event_type_is_a_registered_namespace_shape(self) -> None:
        # SPEC-303 §Phase2 namespace: dotted lowercase snake (registry entry
        # lands with #129; the constant already satisfies the type regex).
        assert re.fullmatch(
            r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", T2MI_PLP_MISMATCH_EVENT_TYPE
        )
