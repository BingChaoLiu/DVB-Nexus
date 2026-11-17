"""SPEC-601 §5-§8 — BBFrame parse/build unit tests (ticket #123).

Pure unit face: no I/O, no wall clock (SPEC-505 §3).  Frame bytes are
built programmatically from the EN 302 755 §5.1.7 field tables — the
registered golden vectors (``bbframe-nups3`` family) provide the
byte-level cross on the conformance layer.
"""

from __future__ import annotations

import pytest

from ts.t2mi.bbframe import (
    BBFRAME_BUILD_EMPTY,
    BBFRAME_BUILD_NOT_UP_ALIGNED,
    BBFRAME_CONFIG_ISSY_UNSUPPORTED,
    BBFRAME_CONFIG_MATYPE_CONFLICT,
    BBFRAME_CONFIG_MATYPE_UNSUPPORTED,
    BBFRAME_CONFIG_NPD_UNSUPPORTED,
    BBFRAME_CONFIG_UPL_INVALID,
    BBFRAME_MATYPE_TS_NM,
    BBFRAME_STATE_CRC8_INVALID,
    BBFRAME_STATE_DFL_MISMATCH,
    BBFRAME_STATE_MALFORMED_SHORT,
    BBFRAME_STATE_MATYPE_UNSUPPORTED,
    BBFRAME_STATE_OK,
    BBFRAME_STATE_SYNCD_MISALIGNED,
    BBFRAME_STATE_SYNCD_OUT_OF_RANGE,
    BBFRAME_STATE_UPL_INVALID,
    BBFRAME_SYNCD_CONTINUATION,
    BBHEADER_SIZE,
    BBFrameBuildConfig,
    build,
    crc8_dvb,
    parse,
)

UPL_BYTES = 188
UPL_BITS = UPL_BYTES * 8
N_UPS = 3
STUFFING = 0xFF

_WIRE_DETAIL_KEYS = {
    "matype",
    "upl",
    "dfl",
    "sync",
    "syncd",
    "crc8_valid",
    "up_count",
    "up_indices",
    "state",
}


def _nm_up(index: int, seed: int) -> bytes:
    """One NM transmitted UP: per-UP CRC-8 + 187 body bytes (188 total)."""
    body = bytes(((index * 31 + i * 7 + seed * 11) & 0xFF) for i in range(UPL_BYTES - 1))
    return bytes([crc8_dvb(body)]) + body


def _bbheader9(matype: int, upl_bits: int, dfl_bits: int, syncd_bits: int) -> bytes:
    header = matype.to_bytes(2, "big")
    header += upl_bits.to_bytes(2, "big")
    header += dfl_bits.to_bytes(2, "big")
    header += bytes([0x47])
    header += syncd_bits.to_bytes(2, "big")
    return header


def _nm_frame(up_count: int, seed: int = 0) -> bytes:
    """One NM BBFRAME: BBHEADER + whole UPs (no stuffing)."""
    ups = b"".join(_nm_up(i, seed) for i in range(up_count))
    header9 = _bbheader9(BBFRAME_MATYPE_TS_NM, UPL_BITS, len(ups) * 8, 0)
    return header9 + bytes([crc8_dvb(header9)]) + ups


def _header_with_fields(
    base: bytes,
    *,
    matype: int | None = None,
    upl: int | None = None,
    dfl: int | None = None,
    syncd: int | None = None,
    keep_crc: bool = False,
) -> bytes:
    """Rewrite selected BBHEADER fields; recompute CRC-8 unless kept."""
    header9 = bytearray(base[:9])
    if matype is not None:
        header9[0:2] = matype.to_bytes(2, "big")
    if upl is not None:
        header9[2:4] = upl.to_bytes(2, "big")
    if dfl is not None:
        header9[4:6] = dfl.to_bytes(2, "big")
    if syncd is not None:
        header9[7:9] = syncd.to_bytes(2, "big")
    crc = base[9] if keep_crc else crc8_dvb(bytes(header9))
    return bytes(header9) + bytes([crc]) + base[BBHEADER_SIZE:]


class TestBBFrameBuild:
    def test_single_up_frame_layout(self) -> None:
        up = _nm_up(0, 1)
        frames = build(bytes(up), BBFrameBuildConfig())
        assert len(frames) == 1
        frame = frames[0]
        assert len(frame) == BBHEADER_SIZE + UPL_BYTES
        parsed = parse([frame])[0]
        assert parsed.matype == BBFRAME_MATYPE_TS_NM
        assert parsed.upl == UPL_BITS
        assert parsed.dfl == UPL_BITS
        assert parsed.sync == 0x47
        assert parsed.syncd == 0
        assert parsed.crc8_valid is True
        assert parsed.up_count == 1
        assert parsed.up_indices == (0,)
        assert parsed.state == BBFRAME_STATE_OK
        assert parsed.data_field == up

    def test_nups3_batch_and_deterministic_tail(self) -> None:
        stream = b"".join(_nm_up(i, i) for i in range(8))
        frames = build(stream, BBFrameBuildConfig(n_ups=N_UPS))
        assert len(frames) == 3  # 8 UPs → batches [3, 3, 2]
        for frame in frames:
            assert len(frame) == BBHEADER_SIZE + N_UPS * UPL_BYTES
        parsed = parse(frames)
        assert tuple(frame.up_count for frame in parsed) == (3, 3, 2)
        tail = parsed[2]
        assert tail.dfl == 2 * UPL_BITS  # real payload bits only
        assert tail.data_field[: 2 * UPL_BYTES] == stream[6 * UPL_BYTES :]
        assert tail.data_field[2 * UPL_BYTES :] == bytes([STUFFING]) * UPL_BYTES
        assert tail.stuffing_bytes == UPL_BYTES
        assert tail.up_indices == (0, UPL_BYTES)

    def test_deterministic_double_run(self) -> None:
        stream = b"".join(_nm_up(i, i) for i in range(7))
        config = BBFrameBuildConfig(n_ups=N_UPS)
        assert build(stream, config) == build(stream, config)

    def test_not_up_aligned_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_BUILD_NOT_UP_ALIGNED):
            build(b"\x00" * (UPL_BYTES - 1), BBFrameBuildConfig())

    def test_empty_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_BUILD_EMPTY):
            build(b"", BBFrameBuildConfig())

    def test_crc8_stored_is_xor_mode_nm(self) -> None:
        frame = build(bytes(_nm_up(0, 0)), BBFrameBuildConfig())[0]
        assert frame[9] == crc8_dvb(frame[:9])  # NM residue 0x00

    def test_matype_unsupported_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_CONFIG_MATYPE_UNSUPPORTED):
            BBFrameBuildConfig(matype_value=0x0000)  # GFPS

    def test_issy_unsupported_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_CONFIG_ISSY_UNSUPPORTED):
            BBFrameBuildConfig(issy_mode="per_up")

    def test_npd_unsupported_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_CONFIG_NPD_UNSUPPORTED):
            BBFrameBuildConfig(npd_enabled=True)

    def test_matype_conflict_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_CONFIG_MATYPE_CONFLICT):
            BBFrameBuildConfig(matype_value=0xD200)  # ISSYI bit set, absent mode

    def test_upl_invalid_refused(self) -> None:
        with pytest.raises(Exception, match=BBFRAME_CONFIG_UPL_INVALID):
            BBFrameBuildConfig(upl=0)


class TestBBFrameParse:
    def test_round_trip_parse_build_byte_identity(self) -> None:
        for up_total in (1, 7, 8):
            stream = b"".join(_nm_up(i, up_total) for i in range(up_total))
            frames = build(stream, BBFrameBuildConfig(n_ups=N_UPS))
            parsed = parse(frames)
            reassembled = b"".join(
                frame.data_field[start : start + UPL_BYTES]
                for frame in parsed
                for start in frame.up_indices
            )
            assert reassembled == stream  # stuffing never leaks into UPs
            assert build(reassembled, BBFrameBuildConfig(n_ups=N_UPS)) == frames

    def test_crc8_failure_marked_and_boundaries_withheld(self) -> None:
        frame = bytearray(_nm_frame(2))
        frame[4] ^= 0x01  # DFL bit flip, CRC-8 NOT recomputed (corruption)
        parsed = parse([bytes(frame)])[0]
        assert parsed.crc8_valid is False
        assert parsed.state == BBFRAME_STATE_CRC8_INVALID
        assert parsed.up_count == 0  # header untrusted → no UPs propagate
        assert parsed.up_indices == ()
        assert parsed.dfl == (2 * UPL_BITS) ^ 0x0100  # raw field kept as received
        assert parsed.data_field == _nm_frame(2)[BBHEADER_SIZE:]  # bytes kept

    def test_hem_parse_support(self) -> None:
        up_count = 2
        data = b"".join(
            bytes(((i * 13 + k * 5) & 0xFF) for i in range(187))
            for k in range(up_count)
        )
        header9 = bytearray(_bbheader9(0xC000, 0, len(data) * 8, 0))
        crc = crc8_dvb(bytes(header9))
        frame = bytes(header9) + bytes([crc ^ 0x01]) + data  # HEM residue
        parsed = parse([frame])[0]
        assert parsed.mode == "hem"
        assert parsed.crc8_valid is True
        assert parsed.upl == 0
        assert parsed.up_count == up_count
        assert parsed.up_indices == (0, 187)
        assert parsed.state == BBFRAME_STATE_OK

    def test_matype_unsupported_state(self) -> None:
        frame = _header_with_fields(_nm_frame(1), matype=0x4000)  # GSE
        parsed = parse([frame])[0]
        assert parsed.crc8_valid is True  # header itself consistent
        assert parsed.state == BBFRAME_STATE_MATYPE_UNSUPPORTED
        assert parsed.up_count == 0  # unregistered MATYPE → no UP slicing

    def test_upl_invalid_state(self) -> None:
        frame = _header_with_fields(_nm_frame(1), upl=UPL_BITS - 1)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_UPL_INVALID
        assert parsed.up_count == 0

    def test_dfl_mismatch_state(self) -> None:
        frame = _header_with_fields(_nm_frame(1), dfl=UPL_BITS + 8)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_DFL_MISMATCH

    def test_syncd_out_of_range_state(self) -> None:
        frame = _header_with_fields(_nm_frame(1), syncd=UPL_BITS + 8)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_SYNCD_OUT_OF_RANGE

    def test_syncd_misaligned_state(self) -> None:
        frame = _header_with_fields(_nm_frame(1), syncd=1)
        parsed = parse([frame])[0]
        assert parsed.crc8_valid is True
        assert parsed.state == BBFRAME_STATE_SYNCD_MISALIGNED
        assert parsed.up_count == 0

    def test_continuation_face(self) -> None:
        frame = _header_with_fields(_nm_frame(1), syncd=BBFRAME_SYNCD_CONTINUATION)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_OK
        assert parsed.up_count == 0
        assert parsed.carryover_bytes == UPL_BYTES

    def test_malformed_short_state_and_continuation(self) -> None:
        parsed = parse([b"\x47\x00", _nm_frame(1)])
        assert parsed[0].state == BBFRAME_STATE_MALFORMED_SHORT
        assert parsed[0].crc8_valid is False
        assert parsed[1].state == BBFRAME_STATE_OK  # parse continues

    def test_state_precedence_crc8_wins(self) -> None:
        # CRC-8 broken AND SYNCD out of range → crc8_invalid (header untrusted).
        frame = _header_with_fields(_nm_frame(1), syncd=UPL_BITS + 8, keep_crc=True)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_CRC8_INVALID

    def test_wire_detail_keys_are_frozen(self) -> None:
        detail = parse([_nm_frame(1)])[0].wire_detail()
        assert set(detail) == _WIRE_DETAIL_KEYS
        assert detail["up_indices"] == [0]

    def test_carryover_counts_partial_tail(self) -> None:
        # 2 UPs on the wire, DFL declaring 1.5 UPs → 1 complete UP + carry-over.
        frame = _header_with_fields(_nm_frame(2), dfl=UPL_BITS + UPL_BITS // 2)
        parsed = parse([frame])[0]
        assert parsed.state == BBFRAME_STATE_OK
        assert parsed.up_count == 1
        assert parsed.carryover_bytes == UPL_BYTES // 2
