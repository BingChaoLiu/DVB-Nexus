"""SPEC-601 §5 / SPEC-303 §Phase2 — ``bbframe.*`` emission seam tests (#123).

The registry entries land with #129 (ruling §10-7), so the emission
seams are verified here with a mock emitter: the frozen payload key
sets, the deterministic collection shapes, and the drift refusal.  No
I/O, no wall clock.
"""

from __future__ import annotations

import pytest

from ts.t2mi.bbframe import (
    BBFRAME_STATE_CRC8_INVALID,
    BBFRAME_STATE_MALFORMED_SHORT,
    BBFRAME_STATE_OK,
    BBFrame,
    crc8_dvb,
)
from ts.t2mi.bbframe_summary import (
    BBFRAME_RECOVERY_FAILED_EVENT_TYPE,
    BBFRAME_STAGE_SUMMARY_EVENT_TYPE,
    RECOVERY_FAILED_PAYLOAD_KEYS,
    STAGE_SUMMARY_PAYLOAD_KEYS,
    collect_recovery_failed,
    collect_stage_summary,
    emit_recovery_failed,
    emit_stage_summary,
)

UPL_BYTES = 188
UPL_BITS = UPL_BYTES * 8
DATA_FIELD_BYTES = 3 * UPL_BYTES  # n_ups=3 full frame


def _frame(up_count: int, *, stuffing: int = 0, crc_ok: bool = True, short: bool = False) -> BBFrame:
    """A synthetic BBFrame face (no wire bytes needed for seam shapes)."""
    if short:
        return BBFrame(
            matype=0,
            upl=0,
            dfl=0,
            sync=0,
            syncd=0,
            crc8_valid=False,
            up_count=0,
            up_indices=(),
            state=BBFRAME_STATE_MALFORMED_SHORT,
            mode="unknown",
            npd_enabled=False,
            issy_present=False,
            crc8_stored=0,
            data_field=b"\x47\x00",
        )
    data_field = bytes(DATA_FIELD_BYTES)
    header9 = (
        b"\xd0\x00" + UPL_BITS.to_bytes(2, "big") + (up_count * UPL_BITS).to_bytes(2, "big")
        + b"\x47" + b"\x00\x00"
    )
    crc = crc8_dvb(header9) if crc_ok else crc8_dvb(header9) ^ 0x55
    return BBFrame(
        matype=0xD000,
        upl=UPL_BITS,
        dfl=up_count * UPL_BITS,
        sync=0x47,
        syncd=0,
        crc8_valid=crc_ok,
        up_count=up_count,
        up_indices=tuple(i * UPL_BYTES for i in range(up_count)),
        state=BBFRAME_STATE_OK if crc_ok else BBFRAME_STATE_CRC8_INVALID,
        mode="nm",
        npd_enabled=False,
        issy_present=False,
        crc8_stored=crc,
        data_field=data_field[: len(data_field) - stuffing] + bytes([0xFF]) * stuffing,
    )


class TestCollectStageSummary:
    def test_payload_keys_are_the_frozen_set(self) -> None:
        assert set(collect_stage_summary([])) == STAGE_SUMMARY_PAYLOAD_KEYS

    def test_empty_stage_shape(self) -> None:
        payload = collect_stage_summary([])
        assert payload["frame_count"] == 0
        assert payload["n_ups_distribution"] == {}
        assert payload["stuffing_ratio"] == 0.0

    def test_n_ups_distribution_and_stuffing_ratio(self) -> None:
        frames = [_frame(3), _frame(3), _frame(2, stuffing=UPL_BYTES)]
        payload = collect_stage_summary(frames)
        assert payload["frame_count"] == 3
        assert payload["n_ups_distribution"] == {"3": 2, "2": 1}
        expected_ratio = UPL_BYTES / (3 * DATA_FIELD_BYTES)
        assert payload["stuffing_ratio"] == pytest.approx(expected_ratio)

    def test_deterministic(self) -> None:
        frames = [_frame(3), _frame(1)]
        assert collect_stage_summary(frames) == collect_stage_summary(frames)


class TestCollectRecoveryFailed:
    def test_payload_keys_are_the_frozen_set(self) -> None:
        assert set(collect_recovery_failed([])) == RECOVERY_FAILED_PAYLOAD_KEYS

    def test_clean_stage(self) -> None:
        payload = collect_recovery_failed([_frame(3), _frame(2)])
        assert payload["failure_count"] == 0
        assert payload["first_failed_frame_index"] is None

    def test_crc8_failures_counted_with_first_index(self) -> None:
        frames = [_frame(3), _frame(3, crc_ok=False), _frame(1, crc_ok=False)]
        payload = collect_recovery_failed(frames)
        assert payload["failure_count"] == 2
        assert payload["first_failed_frame_index"] == 1

    def test_malformed_short_counts_as_failure(self) -> None:
        payload = collect_recovery_failed([_frame(0, short=True)])
        assert payload["failure_count"] == 1
        assert payload["first_failed_frame_index"] == 0


class TestEmitSeams:
    def test_stage_summary_emit_freezes_event_type_and_copies(self) -> None:
        captured: list[tuple[str, dict]] = []
        payload = collect_stage_summary([_frame(3)])
        emit_stage_summary(lambda event_type, body: captured.append((event_type, dict(body))), payload)
        event_type, emitted = captured[0]
        assert event_type == BBFRAME_STAGE_SUMMARY_EVENT_TYPE
        assert set(emitted) == STAGE_SUMMARY_PAYLOAD_KEYS

    def test_recovery_failed_emit_freezes_event_type(self) -> None:
        captured: list[tuple[str, dict]] = []
        payload = collect_recovery_failed([_frame(3, crc_ok=False)])
        emit_recovery_failed(lambda event_type, body: captured.append((event_type, dict(body))), payload)
        event_type, emitted = captured[0]
        assert event_type == BBFRAME_RECOVERY_FAILED_EVENT_TYPE
        assert set(emitted) == RECOVERY_FAILED_PAYLOAD_KEYS
        assert emitted["failure_count"] == 1

    def test_stage_summary_key_drift_refused(self) -> None:
        with pytest.raises(ValueError):
            emit_stage_summary(lambda event_type, body: None, {"frame_count": 1})

    def test_recovery_failed_key_drift_refused(self) -> None:
        with pytest.raises(ValueError):
            emit_recovery_failed(lambda event_type, body: None, {"failure_count": 0})

    def test_seams_are_emitter_injected(self) -> None:
        # #128 binds SimulationEventEmitter here without ts importing
        # simulation (ts purity contract); any callable works.

        class RecordingEmitter:
            def __init__(self) -> None:
                self.events: list[str] = []

            def __call__(self, event_type: str, payload: dict) -> None:
                self.events.append(event_type)

        emitter = RecordingEmitter()
        emit_stage_summary(emitter, collect_stage_summary([]))
        emit_recovery_failed(emitter, collect_recovery_failed([]))
        assert emitter.events == [
            BBFRAME_STAGE_SUMMARY_EVENT_TYPE,
            BBFRAME_RECOVERY_FAILED_EVENT_TYPE,
        ]
