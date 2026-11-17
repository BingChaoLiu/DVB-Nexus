"""The json_map chain — structural parse JSON assembly (ticket #128).

SPEC-404 §Phase2's packet-inspector data source: the per-layer structure
JSON is assembled from the live ``ts`` objects — each layer's keys are the
upstream frozen projections read directly (禁手写 mirror):

- T2-MI per-packet: the #122 wire keys + the transport-prefix faces
  (``packet_index / packet_type / packet_counter / payload_kind /
  payload_bytes_len / crc32_valid / frame_index / plp_id``);
- BBFrame per-frame: :meth:`ts.t2mi.bbframe.BBFrame.wire_detail` (nine
  frozen keys) + the caller-side ``frame_index`` locator;
- Inner TS: :meth:`ts.t2mi.inner_ts.InnerTsResult.wire_detail` (six
  frozen keys) + ``anomalies`` + ``first_failure_ref``.

Pure assembly over bytes; the REST face (additive
``GET /artifacts/{id}/structure``, #128 composition binding) delegates
here.  Application layer: imports ``ts`` only (no api/adapters edge).
"""

from __future__ import annotations

from typing import Any

from application.errors import BadRequestError
from ts.t2mi.bbframe import parse as parse_bbframe
from ts.t2mi.inner_ts import reconstruct
from ts.t2mi.parser import parse as parse_t2mi
from ts.t2mi.plp import PlpFilterConfig

__all__ = [
    "T2MI_STRUCTURE_VIEWS",
    "bbframe_structure",
    "inner_ts_structure",
    "structure_view",
    "t2mi_structure",
]

#: The packet-inspector view vocabulary (SPEC-404 §Phase2; default "ts").
T2MI_STRUCTURE_VIEWS = ("t2mi", "bbframe", "ts")

#: MPEG-TS sync byte — a 0x47-led stream is a plain TS artifact, not a
#: T2-MI stream (the honest refusal face for MVP artifacts).
_TS_SYNC_BYTE = 0x47
_TS_PACKET_SIZE = 188


def structure_view(
    stream: bytes, view: str, *, expected_plp: int | None = None
) -> dict[str, Any]:
    """Dispatch one structure view (the composition entry face)."""
    if view not in T2MI_STRUCTURE_VIEWS:
        raise BadRequestError(
            "SIM_STRUCTURE_VIEW_UNKNOWN",
            f"unknown structure view {view!r}; supported views: "
            f"{list(T2MI_STRUCTURE_VIEWS)} (SPEC-404 §Phase2)",
        )
    _require_t2mi_stream(stream)
    if view == "t2mi":
        return t2mi_structure(stream)
    if view == "bbframe":
        return bbframe_structure(stream)
    return inner_ts_structure(stream, expected_plp=expected_plp)


def t2mi_structure(stream: bytes) -> dict[str, Any]:
    """The T2-MI layer structure (per-packet rows, stream order)."""
    parsed = parse_t2mi(stream)
    rows = []
    for index, packet in enumerate(parsed):
        rows.append(
            {
                "packet_index": index,
                "packet_type": packet.packet_type,
                "packet_counter": packet.packet_counter,
                "payload_kind": packet.payload_kind,
                "payload_bytes_len": packet.payload_bytes_len,
                "crc32_valid": packet.crc32_valid,
                "frame_index": packet.frame_index,
                "plp_id": packet.plp_id,
            }
        )
    return {
        "view": "t2mi",
        "packet_count": len(parsed),
        "truncated": parsed.truncated,
        "trailing_bytes": parsed.trailing_bytes,
        "packets": rows,
    }


def bbframe_structure(stream: bytes) -> dict[str, Any]:
    """The BBFrame layer structure (per-frame rows from the carrier packets)."""
    parsed = parse_t2mi(stream)
    blobs = [
        packet.bbframe for packet in parsed if packet.bbframe is not None
    ]
    frames = parse_bbframe(blobs) if blobs else ()
    rows = []
    for index, frame in enumerate(frames):
        rows.append({"frame_index": index, **frame.wire_detail()})
    return {
        "view": "bbframe",
        "frame_count": len(frames),
        "frames": rows,
    }


def inner_ts_structure(
    stream: bytes, *, expected_plp: int | None = None
) -> dict[str, Any]:
    """The Inner TS layer structure (the demux chain's output face).

    ``expected_plp`` drives the B1 demux expectation (缺失 ≠ 零 — the
    explicit empty failed face when the expected PLP matches nothing).
    """
    plp_filter = (
        PlpFilterConfig(mode="expected", expected_plp=expected_plp)
        if expected_plp is not None
        else None
    )
    result = reconstruct(parse_t2mi(stream), plp_filter)
    return {
        "view": "ts",
        **result.wire_detail(),
        "anomalies": [dict(anomaly) for anomaly in result.anomalies],
    }


def _require_t2mi_stream(stream: bytes) -> None:
    """Honest scope face: structure views parse T2-MI streams.

    A 0x47-led 188-aligned stream is a plain MPEG-TS artifact — its packet
    face is served by the analyze chain (SPEC-308), not by the layered
    structure views.
    """
    if stream and stream[0] == _TS_SYNC_BYTE and len(stream) % _TS_PACKET_SIZE == 0:
        raise BadRequestError(
            "SIM_STRUCTURE_NOT_T2MI",
            "the artifact parses as a plain MPEG-TS stream; structure "
            "views (t2mi/bbframe/ts) require a T2-MI stream — use the "
            "analyze face for TS artifacts (SPEC-308)",
        )
