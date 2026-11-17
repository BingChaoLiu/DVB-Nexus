"""The json_map chain — structural parse JSON for the packet inspector
views (ticket #128 composition binding, SPEC-404 §Phase2 data source).

键集 = the upstream frozen projections verbatim (#125 REPORT §5, 禁手写
mirror): T2-MI per-packet = the #122 wire keys + the two transport-prefix
faces; BBFrame per-frame = ``BBFrame.wire_detail()`` (nine keys); Inner TS
= ``InnerTsResult.wire_detail()`` six keys + anomalies +
first_failure_ref.  The assembly reads the live ts objects — no mirror
tables, no parallel shapes.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from application.analysis.structure import (
    T2MI_STRUCTURE_VIEWS,
    bbframe_structure,
    inner_ts_structure,
    structure_view,
    t2mi_structure,
)
from application.errors import BadRequestError
from ts.generator.generator import TSGenerator
from ts.t2mi.bbframe import build as build_bbframe
from ts.t2mi.builder import T2miBuildConfig, build as build_t2mi

from tests.unit.simulation._ts_runtime_builders import make_generator_config


def _t2mi_stream(packet_count: int = 6) -> bytes:
    """A real chain-produced T2-MI stream (generator → bbframe → t2mi)."""
    config = make_generator_config(output_packet_count=packet_count)
    inner = b"".join(
        packet.to_bytes() for packet in TSGenerator().iter_packets(config)
    )
    frames = build_bbframe(inner, _bbframe_config())
    packets = build_t2mi(frames, T2miBuildConfig())
    from ts.t2mi.packet import encode_packet

    return b"".join(encode_packet(packet) for packet in packets)


def _bbframe_config():
    from ts.t2mi.bbframe import BBFrameBuildConfig

    return BBFrameBuildConfig(n_ups=3)


class TestT2miStructure:
    """T2-MI layer per-packet rows (the #122 wire keys + prefix faces)."""

    def test_row_keys_are_the_frozen_set(self) -> None:
        document = t2mi_structure(_t2mi_stream())
        assert document["view"] == "t2mi"
        assert document["packet_count"] >= 1
        assert isinstance(document["truncated"], bool)
        for row in document["packets"]:
            assert set(row) == {
                "packet_index",
                "packet_type",
                "packet_counter",
                "payload_kind",
                "payload_bytes_len",
                "crc32_valid",
                "frame_index",
                "plp_id",
            }

    def test_rows_are_ordered_and_deterministic(self) -> None:
        stream = _t2mi_stream()
        first = t2mi_structure(stream)
        second = t2mi_structure(stream)
        assert first == second
        assert [row["packet_index"] for row in first["packets"]] == list(
            range(first["packet_count"])
        )


class TestBBFrameStructure:
    """BBFrame layer per-frame rows = ``BBFrame.wire_detail()`` + locator."""

    def test_row_keys_are_wire_detail_plus_frame_index(self) -> None:
        document = bbframe_structure(_t2mi_stream())
        assert document["view"] == "bbframe"
        assert document["frame_count"] >= 1
        for row in document["frames"]:
            assert set(row) == {
                "frame_index",
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
        assert all(row["frame_index"] == i for i, row in enumerate(document["frames"]))


class TestInnerTsStructure:
    """Inner TS layer = the six wire keys + anomalies + first_failure_ref."""

    def test_shape_keys(self) -> None:
        document = inner_ts_structure(_t2mi_stream())
        assert document["view"] == "ts"
        assert set(document) == {
            "view",
            "artifact_ref",
            "packet_count",
            "up_assembled",
            "stuffing_bytes",
            "reconstruction_status",
            "first_failure_ref",
            "anomalies",
        }
        assert document["reconstruction_status"] == "ok"
        assert document["first_failure_ref"] is None
        assert document["anomalies"] == []

    def test_expected_plp_param_drives_the_demux_face(self) -> None:
        document = inner_ts_structure(_t2mi_stream(), expected_plp=0)
        assert document["reconstruction_status"] == "ok"
        absent = inner_ts_structure(_t2mi_stream(), expected_plp=7)
        # B1 (缺失 ≠ 零): the explicit empty failed face, never fabricated.
        assert absent["reconstruction_status"] == "failed"
        assert absent["packet_count"] == 0


class TestStructureViewDispatch:
    """The composition dispatcher: views, unknown views, non-T2-MI bytes."""

    def test_views_route_to_the_layer_assemblies(self) -> None:
        stream = _t2mi_stream()
        assert structure_view(stream, "t2mi") == t2mi_structure(stream)
        assert structure_view(stream, "bbframe") == bbframe_structure(stream)
        assert structure_view(stream, "ts") == inner_ts_structure(stream)

    def test_unknown_view_is_a_bad_request(self) -> None:
        with pytest.raises(BadRequestError):
            structure_view(_t2mi_stream(), "rf")

    def test_views_vocabulary(self) -> None:
        assert T2MI_STRUCTURE_VIEWS == ("t2mi", "bbframe", "ts")

    def test_mpeg_ts_stream_is_refused_honestly(self) -> None:
        config = make_generator_config(output_packet_count=4)
        ts_stream = b"".join(
            packet.to_bytes() for packet in TSGenerator().iter_packets(config)
        )
        with pytest.raises(BadRequestError) as excinfo:
            structure_view(ts_stream, "t2mi")
        assert "T2-MI" in str(excinfo.value)
