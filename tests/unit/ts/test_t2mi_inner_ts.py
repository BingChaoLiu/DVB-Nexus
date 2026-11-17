"""SPEC-603 §6/§7/§8 — Inner TS reconstruction unit tests (ticket #125).

Procedural fixtures only (SPEC-505 §6: no hand-assembled byte literals;
all byte material is deterministically generated or sourced from the
production builders).  The independent round-trip evidence (research
``expected_inner.ts`` baseline) lives at the conformance layer; this
module pins the interface-level behaviour:

- NM chain round-trip through the #123/#122 builders: ``ok`` status,
  byte identity, determinism (§7 同输入必同输出);
- SYNCD carry-over: a UP split across two frames (partial tail +
  ``SYNCD=0xFFFF`` continuation frame) reassembles exactly (§3/§7);
- stuffing consumption: tail-frame ``0xFF`` baseband stuffing is skipped
  and counted, never emitted (SPEC-601 §7 tail rule, consumed here);
- explicit degradation faces (§8): CRC-8 chain failure → ``partial`` +
  ``first_failure_ref`` (never silent truncation), incomplete trailing
  UP, NPD non-reinsertion honesty, padding T2-MI packet between frames =
  the explicit back-to-back-discipline anomaly (the construction-side
  prohibition mirrored on the parse side, #104);
- PLP faces (SPEC-602 承接): expected-mode zero match → explicit empty
  failed face + the ``t2mi.plp_mismatch`` candidate on the injected
  emitter; pre-filtered and internally-filtered paths agree;
- wire shape: ``wire_detail()`` carries exactly the frozen six keys
  (#129 mirrors them verbatim into ``InnerTsResultDTO``);
- ``verify_against_tsduck``: byte-level diff + NOT TRUSTED annotation
  logic (ruling §10-9 — trusted requires a version in the (empty)
  trusted-release registry, master 147deab3 unreleased).
"""

from __future__ import annotations

import hashlib

import pytest

from ts.crc import mpeg2_crc32
from ts.t2mi.bbframe import (
    BBFRAME_STATE_CRC8_INVALID,
    BBFRAME_SYNC_TS_NM,
    BBFRAME_SYNCD_CONTINUATION,
    BBFrameBuildConfig,
    build as bbframe_build,
    crc8_dvb,
)
from ts.t2mi.builder import (
    T2MI_INTERLEAVING_FRAME_START_FLAG,
    T2miBuildConfig,
    build as t2mi_build,
)
from ts.t2mi.inner_ts import (
    FIRST_FAILURE_REF_KEYS,
    INNER_TS_ARTIFACT_KIND,
    INNER_TS_TSDUCK_VERSION_INVALID,
    INNER_TS_WIRE_KEYS,
    RECONSTRUCTION_STATUS_FAILED,
    RECONSTRUCTION_STATUS_OK,
    RECONSTRUCTION_STATUS_PARTIAL,
    VERIFY_RECORD_KEYS,
    InnerTsResult,
    reconstruct,
    verify_against_tsduck,
)
from ts.t2mi.packet import (
    PAYLOAD_KIND_BBFRAME,
    T2MI_TYPE_BBFRAME,
    T2MI_TYPE_PADDING,
    T2miPacket,
    make_header_reserved,
)
from ts.t2mi.plp import (
    PLP_MISMATCH_PAYLOAD_KEYS,
    PlpFilterConfig,
    filter as plp_filter,
)

UPL_BYTES = 188
HEM_UP_BYTES = 187
N_UPS = 3

_SYNCD_CONTINUATION_BITS = BBFRAME_SYNCD_CONTINUATION


def _up_stream(seed: int, up_count: int) -> bytes:
    """Deterministic TS-shaped UP stream: 0x47 at every packet origin.

    Reconstruction restores the BBHEADER SYNC byte into each UP's first
    byte (the #123 build face transports the stream verbatim), so the
    expected round-trip target must be a real TS-shaped stream.
    """
    return bytes(
        (
            (0x47 if index % UPL_BYTES == 0 else (index * 31 + seed * 17) & 0xFF)
        )
        for index in range(up_count * UPL_BYTES)
    )


def _wrap_packets(frame_blobs, *, plp_id: int = 0) -> tuple[T2miPacket, ...]:
    """Encapsulate BBFRAME blobs through the production #122 builder."""
    return t2mi_build(frame_blobs, T2miBuildConfig(plp_id=plp_id))


def _nm_chain(seed: int, up_count: int) -> tuple[T2miPacket, ...]:
    """The encapsulator direction: UP stream → BBFRAMEs → T2-MI packets."""
    frames = bbframe_build(_up_stream(seed, up_count), BBFrameBuildConfig(n_ups=N_UPS))
    return _wrap_packets(frames)


def _frame_packet(
    data: bytes,
    *,
    mode: str,
    syncd_bits: int,
    frame_index: int,
    plp_id: int = 0,
    npd: bool = False,
    corrupt_crc8: bool = False,
) -> T2miPacket:
    """One BBFRAME T2-MI packet built procedurally (EN 302 755 §5.1.7).

    ``data`` is the data field verbatim.  ``mode="hem"`` (MATYPE 0xC000,
    UPL 187*8, MODE residue 0x01) or ``mode="nm"`` (MATYPE 0xD000, UPL
    188*8, MODE residue 0x00).  ``syncd_bits=0xFFFF`` = continuation.
    """
    if mode == "hem":
        matype = 0xC000 | (0x0400 if npd else 0x0000)
        upl_bits = HEM_UP_BYTES * 8
        mode_residue = 0x01
    else:
        matype = 0xD000
        upl_bits = UPL_BYTES * 8
        mode_residue = 0x00
    header9 = bytearray(9)
    header9[0:2] = matype.to_bytes(2, "big")
    header9[2:4] = upl_bits.to_bytes(2, "big")
    header9[4:6] = (len(data) * 8).to_bytes(2, "big")
    header9[6] = BBFRAME_SYNC_TS_NM
    header9[7:9] = syncd_bits.to_bytes(2, "big")
    stored_crc8 = crc8_dvb(bytes(header9)) ^ mode_residue
    if corrupt_crc8:
        stored_crc8 ^= 0xFF
    payload = (
        bytes([frame_index % 256, plp_id, T2MI_INTERLEAVING_FRAME_START_FLAG])
        + bytes(header9)
        + bytes([stored_crc8])
        + data
    )
    reserved = make_header_reserved(0)
    header_prefix = (
        bytes([T2MI_TYPE_BBFRAME, frame_index % 256])
        + reserved
        + (len(payload) * 8).to_bytes(2, "big")
    )
    return T2miPacket(
        packet_type=T2MI_TYPE_BBFRAME,
        packet_counter=frame_index % 256,
        reserved=reserved,
        payload_bits=len(payload) * 8,
        payload=payload,
        crc32=mpeg2_crc32(header_prefix + payload),
    )


def _with_corrupted_bbheader_crc8(packet: T2miPacket) -> T2miPacket:
    """Flip the BBHEADER CRC-8 byte inside one T2-MI packet's BBFRAME blob."""
    payload = bytearray(packet.payload)
    payload[3 + 9] ^= 0xFF  # transport prefix (3 bytes) + CRC-8 offset (9)
    reserved = packet.reserved
    header_prefix = (
        bytes([T2MI_TYPE_BBFRAME, packet.packet_counter])
        + reserved
        + (len(payload) * 8).to_bytes(2, "big")
    )
    return T2miPacket(
        packet_type=T2MI_TYPE_BBFRAME,
        packet_counter=packet.packet_counter,
        reserved=reserved,
        payload_bits=len(payload) * 8,
        payload=bytes(payload),
        crc32=mpeg2_crc32(header_prefix + bytes(payload)),
    )


def _padding_packet(byte_size: int, *, counter: int) -> T2miPacket:
    """One padding/stuffing identity T2-MI packet (type 0xFF, #122 face)."""
    payload = bytes((0xFF for _ in range(byte_size)))
    reserved = make_header_reserved(0)
    header_prefix = (
        bytes([T2MI_TYPE_PADDING, counter % 256])
        + reserved
        + (len(payload) * 8).to_bytes(2, "big")
    )
    return T2miPacket(
        packet_type=T2MI_TYPE_PADDING,
        packet_counter=counter % 256,
        reserved=reserved,
        payload_bits=len(payload) * 8,
        payload=payload,
        crc32=mpeg2_crc32(header_prefix + payload),
    )


def _procedural_body(seed: int, length: int) -> bytes:
    return bytes(((index * 13 + seed * 7) & 0xFF) for index in range(length))


class TestReconstructNMChainRoundTrip:
    """The encapsulator direction reversed: T2-MI packets → Inner TS."""

    def test_round_trip_restores_the_up_stream_byte_identically(self) -> None:
        up_count = 7  # 3 + 3 + tail(1 UP + 2-slot 0xFF stuffing)
        packets = _nm_chain(seed=5, up_count=up_count)
        result = reconstruct(packets)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert result.inner_ts == _up_stream(5, up_count)
        assert result.packet_count == up_count
        assert result.up_assembled == up_count
        capacity_slots = N_UPS * ((up_count + N_UPS - 1) // N_UPS)
        assert result.stuffing_bytes == (capacity_slots - up_count) * UPL_BYTES
        assert result.first_failure_ref is None
        assert result.anomalies == ()

    def test_result_is_deterministic_across_runs(self) -> None:
        packets = _nm_chain(seed=9, up_count=6)
        first = reconstruct(packets)
        second = reconstruct(packets)
        assert first.wire_detail() == second.wire_detail()
        assert first.inner_ts == second.inner_ts
        assert first.artifact_ref == second.artifact_ref

    def test_artifact_ref_is_the_content_address_of_the_output(self) -> None:
        result = reconstruct(_nm_chain(seed=1, up_count=3))
        assert result.artifact_ref == hashlib.sha256(result.inner_ts).hexdigest()
        assert len(result.artifact_ref) == 64
        assert result.artifact_ref == result.artifact_ref.lower()

    def test_wire_detail_carries_exactly_the_frozen_six_keys(self) -> None:
        result = reconstruct(_nm_chain(seed=2, up_count=3))
        assert set(result.wire_detail()) == set(INNER_TS_WIRE_KEYS)
        assert set(INNER_TS_WIRE_KEYS) == {
            "artifact_ref",
            "packet_count",
            "up_assembled",
            "stuffing_bytes",
            "reconstruction_status",
            "first_failure_ref",
        }

    def test_wire_detail_first_failure_ref_stays_none_when_ok(self) -> None:
        result = reconstruct(_nm_chain(seed=3, up_count=3))
        assert result.wire_detail()["reconstruction_status"] == RECONSTRUCTION_STATUS_OK
        assert result.wire_detail()["first_failure_ref"] is None

    def test_artifact_kind_constant_is_the_spec_603_face(self) -> None:
        # The ts-side kind string (ts purity: the domain enum is mirrored,
        # never imported, SPEC-603 §5).
        assert INNER_TS_ARTIFACT_KIND == "inner_ts"


class TestReconstructSynchdCarryOver:
    """SYNCD bit-distance carry-over: a UP split across two frames (§3)."""

    def _split_stream(self) -> tuple[T2miPacket, ...]:
        up0 = _procedural_body(11, HEM_UP_BYTES)
        up1_head = _procedural_body(12, 94)
        up1_tail = _procedural_body(13, HEM_UP_BYTES - 94)
        frame0 = _frame_packet(
            up0 + up1_head, mode="hem", syncd_bits=0, frame_index=0
        )
        frame1 = _frame_packet(
            up1_tail, mode="hem", syncd_bits=_SYNCD_CONTINUATION_BITS, frame_index=1
        )
        return (frame0, frame1)

    def test_continuation_frame_completes_the_split_up(self) -> None:
        result = reconstruct(self._split_stream())
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert result.up_assembled == 2
        assert result.packet_count == 2
        expected = (
            bytes([0x47])
            + _procedural_body(11, HEM_UP_BYTES)
            + bytes([0x47])
            + _procedural_body(12, 94)
            + _procedural_body(13, HEM_UP_BYTES - 94)
        )
        assert result.inner_ts == expected
        assert result.first_failure_ref is None

    def test_split_up_double_run_is_byte_identical(self) -> None:
        first = reconstruct(self._split_stream())
        second = reconstruct(self._split_stream())
        assert first.inner_ts == second.inner_ts


class TestReconstructExplicitDegradationFaces:
    """SPEC-603 §8: partial/failed are explicit states, never silent."""

    def test_crc8_failure_is_partial_with_located_first_failure(self) -> None:
        up_count = 6  # two full frames of 3 UPs
        packets = list(_nm_chain(seed=4, up_count=up_count))
        packets[0] = _with_corrupted_bbheader_crc8(packets[0])
        result = reconstruct(tuple(packets))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_PARTIAL
        assert result.first_failure_ref is not None
        assert set(result.first_failure_ref) == set(FIRST_FAILURE_REF_KEYS)
        assert result.first_failure_ref["reason"] == BBFRAME_STATE_CRC8_INVALID
        assert result.first_failure_ref["frame_index"] == 0
        # Later frames still contribute: nothing silently truncated.
        assert result.up_assembled == up_count - N_UPS
        assert result.packet_count == up_count - N_UPS

    def test_first_failure_points_at_the_first_affected_frame_only(self) -> None:
        up_count = 6
        packets = list(_nm_chain(seed=44, up_count=up_count))
        packets[1] = _with_corrupted_bbheader_crc8(packets[1])
        result = reconstruct(tuple(packets))
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["frame_index"] == 1
        assert result.first_failure_ref["reason"] == BBFRAME_STATE_CRC8_INVALID
        assert result.up_assembled == up_count - N_UPS

    def test_incomplete_trailing_up_is_partial_with_reason(self) -> None:
        up0 = _procedural_body(21, HEM_UP_BYTES)
        partial_tail = _procedural_body(22, 94)  # 0.5 UP, no continuation
        frame0 = _frame_packet(
            up0 + partial_tail, mode="hem", syncd_bits=0, frame_index=0
        )
        result = reconstruct((frame0,))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_PARTIAL
        assert result.up_assembled == 1
        assert result.packet_count == 1
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "incomplete_trailing_up"

    def test_orphan_carryover_bytes_with_no_pending_up_are_a_failure(self) -> None:
        body = _procedural_body(23, HEM_UP_BYTES)
        # Frame 0 carries a SYNCD continuation face but nothing is pending.
        frame0 = _frame_packet(
            body, mode="hem", syncd_bits=_SYNCD_CONTINUATION_BITS, frame_index=0
        )
        result = reconstruct((frame0,))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.up_assembled == 0
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "orphan_carryover_bytes"

    def test_all_frames_unrecoverable_is_failed_with_empty_output(self) -> None:
        packets = _nm_chain(seed=6, up_count=3)
        corrupted = tuple(_with_corrupted_bbheader_crc8(p) for p in packets)
        result = reconstruct(corrupted)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.up_assembled == 0
        assert result.packet_count == 0
        assert result.inner_ts == b""
        assert result.artifact_ref == hashlib.sha256(b"").hexdigest()
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["frame_index"] == 0

    def test_empty_packet_sequence_is_failed_with_located_reason(self) -> None:
        result = reconstruct(())
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "no_bbframe_packets"

    def test_npd_frame_is_an_explicit_refusal(self) -> None:
        up0 = _procedural_body(24, HEM_UP_BYTES + 1)  # 187 body + DNP byte
        frame0 = _frame_packet(
            up0, mode="hem", syncd_bits=0, frame_index=0, npd=True
        )
        result = reconstruct((frame0,))
        # Nothing recoverable from the single refused frame → the honest
        # total face; mixed streams degrade to partial instead.
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.up_assembled == 0
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "npd_reinsertion_unsupported"

    def test_npd_frame_in_a_mixed_stream_degrades_to_partial(self) -> None:
        good = _frame_packet(
            _procedural_body(27, HEM_UP_BYTES), mode="hem", syncd_bits=0, frame_index=0
        )
        npd = _frame_packet(
            _procedural_body(28, HEM_UP_BYTES + 1),
            mode="hem",
            syncd_bits=0,
            frame_index=1,
            npd=True,
        )
        result = reconstruct((good, npd))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_PARTIAL
        assert result.up_assembled == 1
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "npd_reinsertion_unsupported"
        assert result.first_failure_ref["frame_index"] == 1

    def test_up_size_change_mid_stream_is_a_located_failure(self) -> None:
        # Frame 0 establishes the HEM UP size (187); frame 1 is NM (UP size
        # 188) — the mixed-size stream has no single UP grammar, so frame 1
        # is refused with a located reason (deterministic, not guessed).
        up0 = _procedural_body(25, HEM_UP_BYTES)
        frame0 = _frame_packet(up0, mode="hem", syncd_bits=0, frame_index=0)
        frame1 = _frame_packet(
            _procedural_body(26, UPL_BYTES), mode="nm", syncd_bits=0, frame_index=1
        )
        result = reconstruct((frame0, frame1))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_PARTIAL
        assert result.up_assembled == 1
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "up_size_changed"
        assert result.first_failure_ref["frame_index"] == 1


class TestReconstructPaddingDisciplineMirror:
    """§7 mirror face: inter-frame padding is explicit evidence (#104)."""

    def test_padding_between_frames_is_recorded_and_never_consumed(self) -> None:
        packets = list(_nm_chain(seed=7, up_count=6))  # two full frames
        stream = (packets[0], _padding_packet(5, counter=99), packets[1])
        result = reconstruct(stream)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert result.inner_ts == reconstruct(tuple(packets)).inner_ts
        kinds = [anomaly["kind"] for anomaly in result.anomalies]
        assert kinds == ["padding_between_frames"]
        assert result.anomalies[0]["packet_position"] == 1
        assert result.anomalies[0]["byte_size"] == 5

    def test_trailing_padding_after_last_frame_is_still_evidence(self) -> None:
        packets = _nm_chain(seed=8, up_count=3)
        stream = tuple(packets) + (_padding_packet(2, counter=7),)
        result = reconstruct(stream)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert len(result.anomalies) == 1

    def test_unknown_packet_between_frames_is_evidence_too(self) -> None:
        unknown = T2miPacket(
            packet_type=0x10,  # L1-current: explicit unknown state (#122)
            packet_counter=3,
            reserved=make_header_reserved(0),
            payload_bits=8,
            payload=bytes([0x00]),
            crc32=0,
        )
        packets = _nm_chain(seed=10, up_count=6)  # two full frames
        result = reconstruct((packets[0], unknown, packets[1]))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert [a["kind"] for a in result.anomalies] == [
            "unknown_packet_between_frames"
        ]


class TestReconstructPlpFaces:
    """SPEC-602 承接: expected-mode selection + the explicit B1 face."""

    def test_expected_mode_selects_and_reconstructs(self) -> None:
        packets = _nm_chain(seed=14, up_count=3)
        config = PlpFilterConfig(mode="expected", expected_plp=0)
        result = reconstruct(packets, config)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_OK
        assert result.up_assembled == 3

    def test_expected_mode_zero_match_is_the_explicit_empty_face(self) -> None:
        packets = _nm_chain(seed=15, up_count=3)
        config = PlpFilterConfig(mode="expected", expected_plp=7)
        captured: list[tuple[str, dict]] = []
        result = reconstruct(
            packets, config, emitter=lambda t, p: captured.append((t, dict(p)))
        )
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.inner_ts == b""
        assert result.packet_count == 0
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "plp_filter_matched_zero_packets"
        assert result.first_failure_ref["frame_index"] is None
        assert len(captured) == 1
        event_type, payload = captured[0]
        assert event_type == "t2mi.plp_mismatch"
        assert set(payload) == set(PLP_MISMATCH_PAYLOAD_KEYS)

    def test_prefiltered_path_matches_the_internal_selection(self) -> None:
        packets = _nm_chain(seed=16, up_count=3)
        config = PlpFilterConfig(mode="expected", expected_plp=0)
        internal = reconstruct(packets, config)
        prefiltered = reconstruct(plp_filter(packets, config), None)
        assert internal.wire_detail() == prefiltered.wire_detail()
        assert internal.inner_ts == prefiltered.inner_ts

    def test_mode_all_is_the_verbatim_pass_through(self) -> None:
        packets = _nm_chain(seed=17, up_count=3)
        unfiltered = reconstruct(packets, None)
        all_mode = reconstruct(packets, PlpFilterConfig(mode="all"))
        assert unfiltered.wire_detail() == all_mode.wire_detail()

    def test_without_emitter_the_zero_match_stays_explicit(self) -> None:
        packets = _nm_chain(seed=18, up_count=3)
        config = PlpFilterConfig(mode="expected", expected_plp=9)
        result = reconstruct(packets, config)
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED


class TestVerifyAgainstTsduck:
    """L2 second-opinion diff + NOT TRUSTED annotation (ruling §10-9)."""

    def test_identical_bytes_match_but_stay_not_trusted_without_version(self) -> None:
        stream = _procedural_body(31, 512)
        record = verify_against_tsduck(stream, stream)
        assert record["match"] is True
        assert record["first_diff_offset"] is None
        assert record["trusted"] is False
        assert record["trust_annotation"] == "NOT TRUSTED"
        assert record["tsduck_version"] is None
        assert record["not_trusted_reason"]

    def test_byte_difference_is_located_exactly(self) -> None:
        baseline = bytearray(_procedural_body(32, 256))
        candidate = bytearray(baseline)
        candidate[40] ^= 0x01
        record = verify_against_tsduck(bytes(baseline), bytes(candidate))
        assert record["match"] is False
        assert record["first_diff_offset"] == 40
        assert record["prefix_match_bytes"] == 40

    def test_size_mismatch_reports_both_faces(self) -> None:
        long_stream = _procedural_body(33, 256)
        short_stream = _procedural_body(33, 100)
        record = verify_against_tsduck(long_stream, short_stream)
        assert record["match"] is False
        assert record["first_diff_offset"] == 100  # short stream ends here
        assert record["inner_byte_size"] == 256
        assert record["tsduck_byte_size"] == 100

    def test_well_formed_unregistered_version_stays_not_trusted(self) -> None:
        stream = _procedural_body(34, 64)
        record = verify_against_tsduck(stream, stream, tsduck_version="9.9-9999")
        assert record["trusted"] is False
        assert record["trust_annotation"] == "NOT TRUSTED"
        assert record["tsduck_version"] == "9.9-9999"
        assert record["not_trusted_reason"]

    def test_malformed_version_string_refuses_before_the_diff(self) -> None:
        stream = _procedural_body(35, 64)
        with pytest.raises(Exception) as excinfo:  # noqa: PT011 - T2miError family
            verify_against_tsduck(stream, stream, tsduck_version="latest")
        assert INNER_TS_TSDUCK_VERSION_INVALID in str(excinfo.value)

    def test_record_carries_exactly_the_frozen_key_set(self) -> None:
        record = verify_against_tsduck(b"a", b"b")
        assert set(record) == set(VERIFY_RECORD_KEYS)


class TestResultObjectShape:
    """The DTO-face object: frozen, wire keys, bytes face separate."""

    def test_result_is_frozen(self) -> None:
        result = reconstruct(_nm_chain(seed=41, up_count=3))
        with pytest.raises(Exception):  # noqa: PT011 - FrozenInstanceError
            result.packet_count = -1  # type: ignore[misc]

    def test_result_is_dataclass_instance(self) -> None:
        assert isinstance(reconstruct(()), InnerTsResult)

    def test_padding_only_stream_is_the_explicit_empty_face(self) -> None:
        # No BBFRAME packets → no_bbframe_packets, never fabricated bytes.
        result = reconstruct((_padding_packet(4, counter=0),))
        assert result.reconstruction_status == RECONSTRUCTION_STATUS_FAILED
        assert result.first_failure_ref is not None
        assert result.first_failure_ref["reason"] == "no_bbframe_packets"

    def test_payload_kind_face_drives_selection(self) -> None:
        packets = _nm_chain(seed=42, up_count=3)
        assert all(p.payload_kind == PAYLOAD_KIND_BBFRAME for p in packets)
        result = reconstruct(packets)
        assert result.up_assembled == 3
