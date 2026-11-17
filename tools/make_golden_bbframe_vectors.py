"""SPEC-601 §11 / SPEC-506 §7 — golden vector constructor ``bbframe-nups3``.

Deterministic byte-level constructor for the BBFRAME golden vector
(L1 verification path: standard-table derivation → self-parse + human
review, SPEC-506 §5).  The bytes are derived **from ETSI EN 302 755
V1.4.1 §5.1.7 tables** — no ``src/ts`` import, so the constructor stays
independent of the self implementation (the conformance tests provide
the self-parser side of the cross; TSDuck has *zero* user-side BBFrame
capability per #104, so there is no L2 TSDuck cross for this layer —
recorded with the NOT TRUSTED framing in the vector's verification.md;
ruling §10-9).

Vector shape: a back-to-back **BBFRAME byte stream** — the layered
pipeline's inter-layer hand-off form (ADR-0010 §3: the BBFRAME layer
emits frames to the T2-MI encapsulator).  Every frame is exactly
``BBHEADER (10) + n_ups * upl`` bytes; the tail frame carries the
remaining UPs first, then ``0xFF`` baseband stuffing up to capacity,
with ``DFL`` declaring the real payload bits only (SPEC-601 §7
deterministic tail rule — the #105 multi-UP-tail defect class, pinned
byte-exactly).

BBHEADER (EN 302 755 §5.1.7 Normal Mode): MATYPE(2) / UPL(2, bits) /
DFL(2, bits) / SYNC(1) / SYNCD(2, bits) / CRC-8(1); the stored CRC-8
byte is CRC-8 (poly 0xD5, init 0x00, MSB-first, over the first 9 bytes)
XOR MODE (0x00 = Normal Mode).  Each NM user packet = per-UP CRC-8 +
187 body bytes (the sync byte replaced by the CRC-8, §5.1.8).

Vector geometry (frozen): 3 frames, user-packet counts ``[3, 3, 2]`` —
the third frame is the *smaller whole-UP tail frame* with one UP's worth
of ``0xFF`` stuffing (N_UPS=3; #105 shape), MATYPE ``0xD000``, UPL 1504
bits, SYNCD 0 (first UP at data-field start), SYNC 0x47.

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes; the
registered sha256 in ``manifest.json`` is the vector's frozen identity;
CI only verifies the sha, never regenerates.

Usage::

    python tools/make_golden_bbframe_vectors.py --output-dir docs/test-vectors/golden
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

VECTOR_ID = "bbframe-nups3"
RELATED_SPECS = ["SPEC-601"]
GENERATOR_VERSION = (
    "tools/make_golden_bbframe_vectors.py v1 "
    "(EN 302 755 §5.1.7 table derivation; no src/ts involvement)"
)

# --- frozen vector geometry ---
UPL_BYTES = 188
UPL_BITS = UPL_BYTES * 8  # 1504
N_UPS = 3
UPS_PER_FRAME = (3, 3, 2)  # third frame = smaller whole-UP tail + stuffing (#105 shape)
MATYPE_NM = 0xD000  # TS_GS = 11 (TS transport), NPD/ISSYI clear (matches #122 vectors)
BBHEADER_SYNC = 0x47
BBHEADER_SYNCD_BITS = 0
STUFFING_BYTE = 0xFF
BBHEADER_SIZE = 10

# --- independent CRC-8 (EN 302 755 annex F; poly 0xD5; no src/ts import) ---


def crc8_dvb(data: bytes) -> int:
    """CRC-8 poly 0xD5, init 0x00, MSB-first (BBHEADER + NM per-UP check)."""
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


def up_body(up_index: int, frame_index: int) -> bytes:
    """187 body bytes of one NM user packet (sync byte replaced by CRC-8)."""
    return bytes(
        ((up_index * 31 + i * 7 + frame_index * 11) & 0xFF)
        for i in range(UPL_BYTES - 1)
    )


def normal_mode_up(up_index: int, frame_index: int) -> bytes:
    """One NM user packet: per-UP CRC-8 + 187 body bytes (188 total)."""
    body = up_body(up_index, frame_index)
    return bytes([crc8_dvb(body)]) + body


def bbheader(datafield_bits: int) -> bytes:
    """10-byte NM BBHEADER (EN 302 755 §5.1.7): stored CRC-8 = CRC-8 XOR MODE."""
    header = struct.pack(">H", MATYPE_NM)
    header += struct.pack(">H", UPL_BITS)
    header += struct.pack(">H", datafield_bits)
    header += bytes([BBHEADER_SYNC]) + struct.pack(">H", BBHEADER_SYNCD_BITS)
    crc = crc8_dvb(header)  # XOR MODE_NM (0x00)
    return header + bytes([crc])


def build_bbframe(up_count: int, frame_index: int) -> bytes:
    """One BBFRAME: BBHEADER + UPs + deterministic 0xFF stuffing to capacity."""
    ups = b"".join(normal_mode_up(i, frame_index) for i in range(up_count))
    data_field = ups.ljust(N_UPS * UPL_BYTES, bytes([STUFFING_BYTE]))
    return bbheader(len(ups) * 8) + data_field


def build_bbframe_stream() -> bytes:
    """The full frozen vector stream: back-to-back BBFRAMEs."""
    return b"".join(
        build_bbframe(up_count, frame_index)
        for frame_index, up_count in enumerate(UPS_PER_FRAME)
    )


# --- registration trio writers ---


def config_hash() -> str:
    """sha256 over the canonical frozen-geometry JSON (provenance face)."""
    canonical = json.dumps(
        {
            "upl_bits": UPL_BITS,
            "n_ups": N_UPS,
            "ups_per_frame": list(UPS_PER_FRAME),
            "matype": MATYPE_NM,
            "syncd_bits": BBHEADER_SYNCD_BITS,
            "stuffing_byte": STUFFING_BYTE,
            "tail_padding_rule": "pad to n_ups capacity, DFL declares real payload",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_expectations() -> dict:
    """Per-frame observation expectations (data-driven conformance face).

    Detail keys mirror the ``BBFrameDTO`` wire keys (SPEC-601 §5:
    ``matype / upl / dfl / sync / syncd / crc8_valid / up_count /
    up_indices``) plus the explicit ``state`` (SPEC-601 §8).
    """
    entries = []
    for frame_index, up_count in enumerate(UPS_PER_FRAME):
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"frame_index": frame_index},
                "detail": {
                    "matype": MATYPE_NM,
                    "upl": UPL_BITS,
                    "dfl": up_count * UPL_BITS,
                    "sync": BBHEADER_SYNC,
                    "syncd": BBHEADER_SYNCD_BITS,
                    "crc8_valid": True,
                    "up_count": up_count,
                    "up_indices": [
                        offset * UPL_BYTES for offset in range(up_count)
                    ],
                    "state": "ok",
                },
            }
        )
    return {"expectations": entries}


def write_trio(output_dir: Path) -> Path:
    """Write the SPEC-506 §3 trio + verification note for ``bbframe-nups3``."""
    stream = build_bbframe_stream()
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
            "direction": (
                "en302755-§5.1.7-derivation→self-parse + human review "
                "(TSDuck 3.45 has zero user-side BBFrame capability, #104 — "
                "no L2 cross possible, NOT TRUSTED framing per ruling §10-9; "
                "self round-trip is L3 regression only, SPEC-506 §5)"
            ),
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default="docs/test-vectors/golden",
        help="SPEC-506 golden root (trio written to <dir>/bbframe-nups3/)",
    )
    args = parser.parse_args()
    base = write_trio(Path(args.output_dir))
    stream = (base / f"{VECTOR_ID}.ts").read_bytes()
    print(f"{VECTOR_ID}: {len(UPS_PER_FRAME)} BBFRAMEs, {len(stream)} bytes")
    print(f"sha256: {hashlib.sha256(stream).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
