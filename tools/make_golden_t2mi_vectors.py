"""SPEC-600 §11.1 / SPEC-506 §7 — golden vector constructor ``t2mi-minimal``.

Deterministic byte-level constructor for the T2-MI golden vector
(L1 verification path: standard-table derivation → self-parse + human
review, SPEC-506 §5).  The bytes are derived **from ETSI TS 102 773
V1.4.1 §5.1 / EN 302 755 §5.1.7 tables** — no ``src/ts`` import, so the
constructor stays independent of the self implementation (the conformance
tests provide the self-parser side of the cross-check; TSDuck 3.45-4798
provided the #104 research cross on the HEM sibling layout, recorded with
the NOT TRUSTED annotation in the vector's verification.md — ruling
§10-9: TSDuck 对拍 NOT TRUSTED 为默认态).

Structure per packet (TS 102 773 §5.1):

- 6-byte header: packet_type (0x00 = BBFRAME), packet_counter,
  superframe_index (byte 2 high nibble) + reserved, reserved byte 3,
  payload length **in bits** (16-bit big-endian);
- payload: transport prefix ``frame_idx(1) + PLP_id(1) +
  interleaving_frame_start flag(1) = 0x80`` followed by the BBFRAME;
- 4-byte big-endian CRC-32 (MPEG-2 polynomial 0x04C11DB7, init
  0xFFFFFFFF, MSB-first) over header + payload.

BBFRAME (EN 302 755 §5.1.7 Normal Mode): BBHEADER (10 bytes: MATYPE,
UPL, DFL, SYNC, SYNCD, CRC-8 poly 0xD5) + data field of user packets;
each NM user packet = CRC-8 + 187 body bytes (the sync byte replaced by
the CRC-8), UPL = 188 * 8 = 1504 bits.

Vector geometry (frozen): 3 BBFRAME packets, user-packet counts
``[20, 20, 12]`` — the third frame is a *smaller whole-UP tail frame*
(the #105 multi-UP-tail shape that TSDuck 3.45 loses), PLP assignment
``[0, 0, 1]``, packet_counter / frame_idx starting at 0, superframe 0.

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes; the
registered sha256 in ``manifest.json`` is the vector's frozen identity;
CI only verifies the sha, never regenerates.

Usage::

    python tools/make_golden_t2mi_vectors.py --output-dir docs/test-vectors/golden
    python tools/make_golden_t2mi_vectors.py --emit-outer <dir>   # TSDuck cross aids
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

VECTOR_ID = "t2mi-minimal"
RELATED_SPECS = ["SPEC-600"]
GENERATOR_VERSION = (
    "tools/make_golden_t2mi_vectors.py v1 "
    "(TS 102 773 §5.1 / EN 302 755 §5.1.7 table derivation; no src/ts involvement)"
)

# --- frozen vector geometry ---
T2MI_PACKET_TYPE_BBFRAME = 0x00
UPL_BYTES = 188
UPL_BITS = UPL_BYTES * 8  # 1504
UPS_PER_FRAME = (20, 20, 12)  # third frame = smaller whole-UP tail (#105 shape)
PLP_IDS = (0, 0, 1)
FIRST_PACKET_COUNTER = 0
FIRST_FRAME_INDEX = 0
SUPERFRAME_INDEX = 0
INTERLEAVING_FRAME_START_FLAG = 0x80
T2MI_PID = 0x0015  # TS 101 162 T2-MI PID (outer-framing aids only)

# NM BBHEADER constants (EN 302 755 §5.1.7, research #104 §3.1 cross-check)
MATYPE_NM = bytes([0xD0, 0x00])  # TS_GS = 11 (TS transport), NPD clear
BBHEADER_SYNC = 0x47
BBHEADER_SYNCD_BITS = 0

# --- independent CRC implementations (poly per standard; no src/ts import) ---


def crc32_mpeg(data: bytes) -> int:
    """CRC-32/MPEG-2 (TS 102 773 §5.1 trailer): poly 0x04C11DB7, MSB-first."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def crc8_dvb(data: bytes) -> int:
    """CRC-8 (EN 302 755 BBHEADER): poly 0xD5, MSB-first."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0xD5) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


# --- deterministic content generators ---


def up_body(up_index: int, frame_index: int, plp_id: int) -> bytes:
    """187 body bytes of one NM user packet (sync byte replaced by CRC-8)."""
    return bytes(
        ((up_index * 31 + i * 7 + frame_index * 11 + plp_id * 3) & 0xFF)
        for i in range(UPL_BYTES - 1)
    )


def normal_mode_up(up_index: int, frame_index: int, plp_id: int) -> bytes:
    """One NM user packet: CRC-8 + 187 body bytes (188 total)."""
    body = up_body(up_index, frame_index, plp_id)
    return bytes([crc8_dvb(body)]) + body


def high_efficiency_mode_up(up_index: int, frame_index: int, plp_id: int) -> bytes:
    """One HEM user packet: 187 body bytes (sync stripped, no CRC-8)."""
    return up_body(up_index, frame_index, plp_id)


def bbheader(datafield_bits: int, *, mode: str) -> bytes:
    """10-byte BBHEADER (EN 302 755 §5.1.7); MODE bit via CRC-8 XOR."""
    header = MATYPE_NM + struct.pack(">H", UPL_BITS if mode == "nm" else 0)
    header += struct.pack(">H", datafield_bits)
    header += bytes([BBHEADER_SYNC]) + struct.pack(">H", BBHEADER_SYNCD_BITS)
    crc = crc8_dvb(header)
    header += bytes([crc if mode == "nm" else crc ^ 0x01])
    return header


def build_bbframe(up_count: int, frame_index: int, plp_id: int, *, mode: str) -> bytes:
    """One BBFRAME: BBHEADER + data field of whole user packets."""
    if mode == "nm":
        ups = [normal_mode_up(i, frame_index, plp_id) for i in range(up_count)]
    else:
        ups = [high_efficiency_mode_up(i, frame_index, plp_id) for i in range(up_count)]
    datafield = b"".join(ups)
    return bbheader(len(datafield) * 8, mode=mode) + datafield


def build_t2mi_packet(
    packet_counter: int,
    frame_index: int,
    plp_id: int,
    bbframe: bytes,
) -> bytes:
    """Wrap one BBFRAME into a T2-MI packet (header + payload + CRC-32)."""
    payload = (
        bytes([frame_index & 0xFF, plp_id & 0xFF, INTERLEAVING_FRAME_START_FLAG])
        + bbframe
    )
    header = bytes(
        [
            T2MI_PACKET_TYPE_BBFRAME,
            packet_counter & 0xFF,
            (SUPERFRAME_INDEX & 0x0F) << 4,  # superframe high nibble, reserved low
            0x00,  # reserved byte 3
        ]
    ) + struct.pack(">H", len(payload) * 8)
    body = header + payload
    return body + struct.pack(">I", crc32_mpeg(body))


def build_t2mi_stream(*, mode: str) -> bytes:
    """The full frozen vector stream: back-to-back T2-MI packets."""
    packets = []
    for counter, (up_count, plp_id) in enumerate(zip(UPS_PER_FRAME, PLP_IDS)):
        frame_index = FIRST_FRAME_INDEX + counter
        packets.append(
            build_t2mi_packet(
                FIRST_PACKET_COUNTER + counter,
                frame_index,
                plp_id,
                build_bbframe(up_count, frame_index, plp_id, mode=mode),
            )
        )
    return b"".join(packets)


# --- outer TS framing aids (TSDuck cross-check only; NOT registered) ---


def frame_outer_ts(t2mi_stream: bytes, *, trailing_nulls: int = 50) -> bytes:
    """Wrap a bare T2-MI stream into TS packets on PID 0x0015.

    Data-piping framing per TS 102 773 Annex E.2.1 / research #104 §3.1:
    PUSI packet carries a pointer field then the first 183 payload bytes;
    continuation packets carry 184 bytes each; 0xFF stuffing only at the
    tail of the last packet (never between T2-MI packets — the #104
    demux-stall lesson).  Trailing null packets absorb the TSDuck
    output-queue drain (research #104 §4.4: without fill packets the
    queued inner packets are dropped at EOF).  No PSI: the TSDuck cross
    uses ``--pid 0x0015`` (no-signalization scenario).
    """
    out: list[bytes] = []
    position = 0
    first = True
    while position < len(t2mi_stream):
        if first:
            chunk = t2mi_stream[position : position + 183]
            body = b"\x00" + chunk  # pointer_field 0x00 + first payload bytes
            pusi = True
            position += 183
            first = False
        else:
            chunk = t2mi_stream[position : position + 184]
            body = chunk
            pusi = False
            position += 184
        body = body.ljust(184, b"\xff")  # tail stuffing only, never mid-stream
        continuity = (len(out)) & 0x0F
        header = bytes(
            [
                0x47,
                (0x40 if pusi else 0x00) | ((T2MI_PID >> 8) & 0x1F),
                T2MI_PID & 0xFF,
                0x10 | continuity,
            ]
        )
        out.append(header + body)
    for index in range(trailing_nulls):
        header = bytes([0x47, 0x1F, 0xFF, 0x10 | (index & 0x0F)])
        out.append(header + bytes(184))
    return b"".join(out)


# --- registration trio writers ---


def config_hash() -> str:
    """sha256 over the canonical frozen-geometry JSON (provenance face)."""
    canonical = json.dumps(
        {
            "upl_bits": UPL_BITS,
            "ups_per_frame": list(UPS_PER_FRAME),
            "plp_ids": list(PLP_IDS),
            "first_packet_counter": FIRST_PACKET_COUNTER,
            "first_frame_index": FIRST_FRAME_INDEX,
            "superframe_index": SUPERFRAME_INDEX,
            "mode": "nm",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_expectations() -> dict:
    """Per-packet observation expectations (data-driven conformance face).

    Detail keys mirror the ``T2miPacketDTO`` wire keys (SPEC-600 §5:
    ``packet_type / packet_counter / payload_kind / payload_bytes_len /
    crc32_valid``) plus the BBFRAME transport-prefix faces the self
    parser derives.
    """
    entries = []
    for index, (up_count, plp_id) in enumerate(zip(UPS_PER_FRAME, PLP_IDS)):
        payload_len = 3 + 10 + up_count * UPL_BYTES
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": index},
                "detail": {
                    "packet_type": T2MI_PACKET_TYPE_BBFRAME,
                    "packet_counter": FIRST_PACKET_COUNTER + index,
                    "payload_kind": "bbframe",
                    "payload_bytes_len": payload_len,
                    "crc32_valid": True,
                    "frame_index": FIRST_FRAME_INDEX + index,
                    "plp_id": plp_id,
                },
            }
        )
    return {"expectations": entries}


def write_trio(output_dir: Path) -> Path:
    """Write the SPEC-506 §3 trio + verification note for ``t2mi-minimal``."""
    stream = build_t2mi_stream(mode="nm")
    base = output_dir / VECTOR_ID
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{VECTOR_ID}.ts").write_bytes(stream)
    manifest = {
        "vector_id": VECTOR_ID,
        "kind": "generated_ts",
        "related_specs": RELATED_SPECS,
        "generator_version": GENERATOR_VERSION,
        "config_hash": config_hash(),
        "sha256": "sha256:" + hashlib.sha256(stream).hexdigest(),
        "packet_count": len(UPS_PER_FRAME),
        "fault_plan_ref": None,
        "verification": {
            "path": "bit-level-review",
            "direction": "ts102773-derivation→self-parse + TSDuck-3.45-HEM-cross (NOT TRUSTED, see verification note)",
            "evidence_ref": (
                f"docs/test-vectors/golden/{VECTOR_ID}/{VECTOR_ID}.verification.md"
            ),
        },
    }
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (base / "expectations.json").write_text(
        json.dumps(build_expectations(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return base


def emit_outer_aids(output_dir: Path) -> None:
    """Write outer-framed NM/HEM sibling streams for the TSDuck cross."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "outer_nm.ts").write_bytes(frame_outer_ts(build_t2mi_stream(mode="nm")))
    (output_dir / "outer_hem.ts").write_bytes(frame_outer_ts(build_t2mi_stream(mode="hem")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default="docs/test-vectors/golden",
        help="SPEC-506 golden root (trio written to <dir>/t2mi-minimal/)",
    )
    parser.add_argument(
        "--emit-outer",
        metavar="DIR",
        default=None,
        help="also write outer-framed NM/HEM TS streams for TSDuck cross aids",
    )
    args = parser.parse_args()
    base = write_trio(Path(args.output_dir))
    stream = (base / f"{VECTOR_ID}.ts").read_bytes()
    print(f"{VECTOR_ID}: {len(UPS_PER_FRAME)} T2-MI packets, {len(stream)} bytes")
    print(f"sha256: {hashlib.sha256(stream).hexdigest()}")
    if args.emit_outer:
        emit_outer_aids(Path(args.emit_outer))
        print(f"outer aids written to {args.emit_outer} (outer_nm.ts / outer_hem.ts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
