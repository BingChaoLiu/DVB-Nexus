"""SPEC-600 §6/§7/§8 — T2-MI encapsulator (builder) unit tests (ticket #122).

Seams under test: :class:`ts.t2mi.builder.T2miBuildConfig` (construction
guards) and :func:`ts.t2mi.builder.build` — deterministic BBFRAME →
T2-MI packet encapsulation with packet_counter continuity, back-to-back
tight packing (no inter-frame padding is ever emitted, and any padding
request is refused at construction), and the prepare-before-refuse
discipline for non-UP-aligned frames. All frames are programmatic.
"""

from __future__ import annotations

import pytest

from ts.t2mi.builder import T2miBuildConfig, build
from ts.t2mi.errors import T2miError
from ts.t2mi.packet import (
    T2MI_BBHEADER_SIZE,
    T2MI_TYPE_BBFRAME,
    encode_packet,
)
from ts.t2mi.parser import parse

UPL_BYTES = 188
UPS_PER_FRAME = 2  # small frames keep the unit face fast


def _up(index: int, seed: int = 0) -> bytes:
    """One synthetic 188-byte user packet (NM UP body, opaque here)."""
    return bytes(((index + i) * 17 + seed * 11) & 0xFF for i in range(UPL_BYTES))


def _bbframe(up_count: int, seed: int = 0) -> bytes:
    """A synthetic BBFRAME: 10-byte BBHEADER + a whole number of UPs.

    The BBHEADER content is opaque at the T2-MI layer (SPEC-601 owns it);
    only the 10-byte boundary + UP alignment matter to the encapsulator.
    """
    header = bytes(((i + seed) * 13) & 0xFF for i in range(T2MI_BBHEADER_SIZE))
    datafield = b"".join(_up(i, seed=seed) for i in range(up_count))
    return header + datafield


def _frames(*up_counts: int) -> list[bytes]:
    return [_bbframe(count, seed=i) for i, count in enumerate(up_counts)]


class TestBuildConfigGuards:
    """Config validation happens at construction — prepare 前拒绝."""

    def test_plp_id_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(plp_id=256)
        assert error.value.code == "T2MI_CONFIG_PLP_OUT_OF_RANGE"

    def test_first_packet_counter_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(first_packet_counter=256)
        assert error.value.code == "T2MI_CONFIG_COUNTER_OUT_OF_RANGE"

    def test_first_frame_index_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(first_frame_index=256)
        assert error.value.code == "T2MI_CONFIG_FRAME_INDEX_OUT_OF_RANGE"

    def test_superframe_index_out_of_range(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(superframe_index=16)
        assert error.value.code == "T2MI_CONFIG_SUPERFRAME_OUT_OF_RANGE"

    def test_upl_must_be_positive(self) -> None:
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(upl_bytes=0)
        assert error.value.code == "T2MI_CONFIG_UPL_INVALID"

    def test_inter_frame_padding_refused_at_construction(self) -> None:
        # 背靠背紧排 is a correctness requirement (SPEC-600 §3/§8): any
        # request to insert padding between frames is refused at
        # construction time — the builder never gains a padding mode.
        with pytest.raises(T2miError) as error:
            T2miBuildConfig(inter_frame_padding=4)
        assert error.value.code == "T2MI_CONFIG_INTER_FRAME_PADDING_FORBIDDEN"


class TestBuildHappyPath:
    def test_frames_map_one_to_one_to_bbframe_packets(self) -> None:
        packets = build(_frames(UPS_PER_FRAME, UPS_PER_FRAME, UPS_PER_FRAME), T2miBuildConfig())
        assert len(packets) == 3
        for index, packet in enumerate(packets):
            assert packet.packet_type == T2MI_TYPE_BBFRAME
            assert packet.packet_counter == index  # continuity from config default
            assert packet.frame_index == index
            assert packet.plp_id == 0  # config default
            assert packet.payload_kind == "bbframe"
            assert packet.crc32_valid
            assert packet.superframe_index == 0
            # interleaving_frame_start default True → flag bit set in prefix
            assert packet.payload[2] == 0x80

    def test_counter_and_frame_index_start_at_config_values(self) -> None:
        config = T2miBuildConfig(first_packet_counter=5, first_frame_index=7)
        packets = build(_frames(UPS_PER_FRAME, UPS_PER_FRAME), config)
        assert [packet.packet_counter for packet in packets] == [5, 6]
        assert [packet.frame_index for packet in packets] == [7, 8]

    def test_counter_and_frame_index_wrap_mod_256_continuously(self) -> None:
        config = T2miBuildConfig(first_packet_counter=254, first_frame_index=255)
        packets = build(_frames(UPS_PER_FRAME, UPS_PER_FRAME, UPS_PER_FRAME), config)
        assert [packet.packet_counter for packet in packets] == [254, 255, 0]
        assert [packet.frame_index for packet in packets] == [255, 0, 1]

    def test_plp_ids_override_gives_per_frame_plp(self) -> None:
        packets = build(_frames(UPS_PER_FRAME, UPS_PER_FRAME, UPS_PER_FRAME), T2miBuildConfig(), plp_ids=[0, 0, 1])
        assert [packet.plp_id for packet in packets] == [0, 0, 1]

    def test_plp_ids_length_mismatch_refused(self) -> None:
        with pytest.raises(T2miError) as error:
            build(_frames(UPS_PER_FRAME, UPS_PER_FRAME), T2miBuildConfig(), plp_ids=[0])
        assert error.value.code == "T2MI_BUILD_PLP_SEQUENCE_MISMATCH"

    def test_plp_ids_values_validated(self) -> None:
        with pytest.raises(T2miError) as error:
            build(_frames(UPS_PER_FRAME), T2miBuildConfig(), plp_ids=[256])
        assert error.value.code == "T2MI_CONFIG_PLP_OUT_OF_RANGE"

    def test_interleaving_frame_start_flag_configurable(self) -> None:
        config = T2miBuildConfig(interleaving_frame_start=False)
        packets = build(_frames(UPS_PER_FRAME), config)
        assert packets[0].payload[2] == 0x00

    def test_encoded_stream_parses_back_without_truncation(self) -> None:
        frames = _frames(UPS_PER_FRAME, UPS_PER_FRAME, 1)  # multi-UP tail frame
        packets = build(frames, T2miBuildConfig())
        result = parse(b"".join(encode_packet(packet) for packet in packets))
        assert len(result) == 3
        assert not result.truncated
        assert all(packet.crc32_valid for packet in result)
        # Tail frame (1 UP) is preserved — no silent tail drop (#105 lesson).
        assert result[2].bbframe is not None
        assert len(result[2].bbframe) == T2MI_BBHEADER_SIZE + UPL_BYTES


class TestBuildDeterminism:
    def test_same_config_same_input_same_packets(self) -> None:
        frames = _frames(UPS_PER_FRAME, UPS_PER_FRAME, UPS_PER_FRAME)
        config = T2miBuildConfig(plp_id=0)
        first = build(frames, config)
        second = build(frames, config)
        assert first == second
        encoded_first = b"".join(encode_packet(packet) for packet in first)
        encoded_second = b"".join(encode_packet(packet) for packet in second)
        assert encoded_first == encoded_second

    def test_config_change_changes_output_bytes(self) -> None:
        frames = _frames(UPS_PER_FRAME)
        baseline = b"".join(encode_packet(p) for p in build(frames, T2miBuildConfig()))
        shifted = b"".join(
            encode_packet(p) for p in build(frames, T2miBuildConfig(first_packet_counter=1))
        )
        assert baseline != shifted


class TestBuildInputGuards:
    def test_empty_frame_sequence_refused(self) -> None:
        with pytest.raises(T2miError) as error:
            build([], T2miBuildConfig())
        assert error.value.code == "T2MI_BUILD_EMPTY"

    def test_non_bytes_frame_refused(self) -> None:
        with pytest.raises(TypeError):
            build(["not bytes"], T2miBuildConfig())  # type: ignore[list-item]

    def test_frame_shorter_than_bbheader_refused(self) -> None:
        with pytest.raises(T2miError) as error:
            build([bytes(8)], T2miBuildConfig())
        assert error.value.code == "T2MI_BUILD_FRAME_SHORT"

    def test_bare_bbheader_refused(self) -> None:
        # 10 bytes = BBHEADER only, empty datafield — degenerate frame.
        with pytest.raises(T2miError) as error:
            build([bytes(T2MI_BBHEADER_SIZE)], T2miBuildConfig())
        assert error.value.code == "T2MI_BUILD_FRAME_SHORT"

    def test_non_up_aligned_frame_refused_before_any_output(self) -> None:
        # Datafield = one whole UP + 97 stray bytes → not a 188 multiple.
        bad_frame = _bbframe(1) + bytes(97)
        with pytest.raises(T2miError) as error:
            build([_bbframe(UPS_PER_FRAME), bad_frame], T2miBuildConfig())
        assert error.value.code == "T2MI_BUILD_FRAME_NOT_UP_ALIGNED"

    def test_non_up_aligned_tail_frame_refused(self) -> None:
        # The multi-UP tail discipline: a *smaller but whole-UP* tail frame
        # is legal; a partial-UP tail frame is refused at prepare time.
        partial_tail = _bbframe(1) + bytes(97)
        with pytest.raises(T2miError) as error:
            build([_bbframe(UPS_PER_FRAME), partial_tail], T2miBuildConfig())
        assert error.value.code == "T2MI_BUILD_FRAME_NOT_UP_ALIGNED"

    def test_smaller_whole_up_tail_frame_is_accepted(self) -> None:
        packets = build(_frames(UPS_PER_FRAME, 1), T2miBuildConfig())
        assert len(packets) == 2
        assert packets[1].crc32_valid
