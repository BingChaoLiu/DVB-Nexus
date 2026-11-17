"""SPEC-600 §6 / SPEC-303 §Phase2 — ``t2mi.stage_summary`` seam tests (#122).

The registry entry lands with #129 (ruling §10-7), so the emission seam
is verified here with a mock emitter: the frozen payload key set, the
distribution shapes, and the determinism duty. No I/O, no wall clock.
"""

from __future__ import annotations

import pytest

from ts.crc import mpeg2_crc32
from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.packet import T2miPacket, encode_packet, make_header_reserved
from ts.t2mi.parser import parse
from ts.t2mi.summary import (
    STAGE_SUMMARY_PAYLOAD_KEYS,
    T2MI_STAGE_SUMMARY_EVENT_TYPE,
    collect_stage_summary,
    emit_stage_summary,
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


class TestCollectStageSummary:
    def test_payload_keys_are_the_frozen_set(self) -> None:
        payload = collect_stage_summary([])
        assert set(payload) == STAGE_SUMMARY_PAYLOAD_KEYS

    def test_empty_stage_summary_shape(self) -> None:
        payload = collect_stage_summary([])
        assert payload["packet_count"] == 0
        assert payload["padding_count"] == 0
        assert payload["packet_type_distribution"] == {}
        assert payload["plp_distribution"] == {}

    def test_bbframe_stage_summary_counts(self) -> None:
        packets = build([_frame(1, 0), _frame(1, 1), _frame(1, 2)], T2miBuildConfig(), plp_ids=[0, 0, 1])
        payload = collect_stage_summary(packets)
        assert payload["packet_count"] == 3
        assert payload["padding_count"] == 0
        assert payload["packet_type_distribution"] == {"bbframe": 3}
        assert payload["plp_distribution"] == {"0": 2, "1": 1}

    def test_padding_packets_counted_in_padding_count(self) -> None:
        parsed = parse(_bbframe_stream_with_stuffing_type())
        payload = collect_stage_summary(parsed)
        assert payload["padding_count"] == 1
        assert payload["packet_type_distribution"]["padding"] == 1

    def test_unknown_packets_lump_into_unknown_bucket(self) -> None:
        parsed = parse(_stream_with_type(0x10))
        payload = collect_stage_summary(parsed)
        assert payload["packet_type_distribution"] == {"unknown": 1}

    def test_summary_is_deterministic(self) -> None:
        packets = build([_frame(1, 0), _frame(1, 1)], T2miBuildConfig())
        assert collect_stage_summary(packets) == collect_stage_summary(packets)


class TestEmitStageSummary:
    def test_emits_frozen_event_type_with_payload_copy(self) -> None:
        captured: list[tuple[str, dict]] = []
        emitter = lambda event_type, payload: captured.append((event_type, dict(payload)))  # noqa: E731
        payload = collect_stage_summary(build([_frame(1, 0)], T2miBuildConfig()))
        emit_stage_summary(emitter, payload)
        assert len(captured) == 1
        event_type, emitted = captured[0]
        assert event_type == T2MI_STAGE_SUMMARY_EVENT_TYPE
        assert set(emitted) == STAGE_SUMMARY_PAYLOAD_KEYS
        assert emitted["packet_count"] == 1

    def test_payload_key_drift_is_refused(self) -> None:
        emitter = lambda event_type, payload: None  # noqa: E731
        with pytest.raises(ValueError):
            emit_stage_summary(emitter, {"packet_count": 1})

    def test_seam_is_emitter_injected_no_simulation_import(self) -> None:
        # The seam accepts any callable — #128 binds SimulationEventEmitter
        # here without ts importing simulation (ts purity contract).
        captured: list[str] = []

        class RecordingEmitter:
            def __call__(self, event_type: str, payload: dict) -> None:
                captured.append(event_type)

        emit_stage_summary(RecordingEmitter(), collect_stage_summary([]))
        assert captured == [T2MI_STAGE_SUMMARY_EVENT_TYPE]


# --- programmatic helper streams (§5 discipline: no byte literals) ----


def _encode_one(packet_type: int, body_seed: int) -> bytes:
    payload = bytes((i * 31 + body_seed * 7) & 0xFF for i in range(8))
    reserved = make_header_reserved(0)
    prefix = bytes([packet_type, 0, reserved[0], reserved[1]]) + (len(payload) * 8).to_bytes(
        2, "big"
    )
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


def _bbframe_stream_with_stuffing_type() -> bytes:
    return _encode_one(0x00, 1) + _encode_one(0xFF, 2)


def _stream_with_type(packet_type: int) -> bytes:
    return _encode_one(packet_type, 3)
