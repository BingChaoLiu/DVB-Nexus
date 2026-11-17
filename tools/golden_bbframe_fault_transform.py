"""SPEC-506 §6 / SPEC-601 §11 — B2 golden fault transforms (``bbframe-b2-*``).

Independent transform script (house red line: faulted vectors are never
generated through the self implementation — no ``src/ts`` import): it
reads the registered ``bbframe-nups3`` baseline bytes and produces the
**faulted形态对** for the B2 primitive (SPEC-204 §Phase2
``BBHEADER_SYNC_FAULT``, SYNCD field):

- ``bbframe-b2-corrupt`` (``--mode corrupt``): flip bit 1 of frame 0's
  SYNCD high byte, CRC-8 **not** recomputed — the integrity break.  The
  parse-side face is ``crc8_valid=false`` / state ``crc8_invalid`` /
  UP boundaries withheld → the ``bbframe.recovery_failed`` evidence
  (SPEC-601 §8; TSDuck 3.45 propagates this silently — #104 — the red
  line this vector pins).
- ``bbframe-b2-shift`` (``--mode shift``): advance SYNCD by one bit
  (0x0000 → 0x0001) **with** the BBHEADER CRC-8 recomputed (MODE
  preserved) — the internally-consistent mis-declaration.  The parse-side
  face is ``crc8_valid=true`` / state ``syncd_misaligned`` / UP 边界错位
  (the teaching point: SYNCD 是数据字段内首个 UP 的位距离，不是同步字节).

Both vectors pair-link the baseline (``fault_plan_ref=bbframe-nups3``);
the two evidence shapes are byte-distinguishable — corrupt differs from
the baseline at one offset, shift at two (field byte + recomputed CRC-8).

Field offsets come straight from the EN 302 755 §5.1.7 table
(SYNCD = bytes 7..8, CRC-8 = byte 9, poly 0xD5); determinism (SPEC-506
§6): same baseline bytes + same mode ⇒ same faulted bytes.

Usage::

    python tools/golden_bbframe_fault_transform.py --mode corrupt \
        --baseline docs/test-vectors/golden/bbframe-nups3/bbframe-nups3.ts \
        --output-dir docs/test-vectors/golden
    python tools/golden_bbframe_fault_transform.py --mode shift ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASELINE_ID = "bbframe-nups3"
RELATED_SPECS = ["SPEC-601"]
GENERATOR_VERSION = (
    "tools/golden_bbframe_fault_transform.py v1 "
    "(independent EN 302 755 §5.1.7 field transform; no src/ts involvement)"
)

#: Frozen transform target: frame 0's BBHEADER SYNCD field (bytes 7..8).
#: Frame geometry: BBHEADER (10) + 3 UPs * 188 → frame 0 spans [0, 574).
TARGET_FRAME_INDEX = 0
SYNCD_OFFSET = 7  # byte offset of the SYNCD field inside the frame
CRC8_OFFSET = 9  # byte offset of the stored CRC-8 (CRC-8 XOR MODE)
CORRUPT_MASK = 0x02  # bit 1: cannot alias NM↔HEM (residue outside {0,1})
SHIFT_DELTA = 1  # SYNCD +1 bit (0x0000 → 0x0001)

FRAME_SIZE = 574  # 10 + 3 * 188 (frozen baseline geometry)
FRAME_START = TARGET_FRAME_INDEX * FRAME_SIZE
SYNC_D_START = FRAME_START + SYNCD_OFFSET
CRC8_ABS = FRAME_START + CRC8_OFFSET


def crc8_dvb(data: bytes) -> int:
    """CRC-8 poly 0xD5, init 0x00, MSB-first (independent re-implementation)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0xD5) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def transform_corrupt(baseline: bytes) -> bytes:
    """SYNCD bit flip; the stored CRC-8 byte is left verbatim."""
    faulted = bytearray(baseline)
    faulted[SYNC_D_START] ^= CORRUPT_MASK
    return bytes(faulted)


def transform_shift(baseline: bytes) -> bytes:
    """SYNCD +1 bit; the BBHEADER CRC-8 is recomputed (MODE preserved)."""
    faulted = bytearray(baseline)
    syncd = int.from_bytes(faulted[SYNC_D_START : SYNC_D_START + 2], "big")
    shifted = (syncd + SHIFT_DELTA) & 0xFFFF
    faulted[SYNC_D_START : SYNC_D_START + 2] = shifted.to_bytes(2, "big")
    # MODE residue comes from the ORIGINAL header (pre-shift), so the
    # faulted header stays internally consistent in the same mode.
    original_header9 = baseline[FRAME_START : FRAME_START + CRC8_OFFSET]
    original_mode = baseline[CRC8_ABS] ^ crc8_dvb(bytes(original_header9))
    faulted_header9 = faulted[FRAME_START : FRAME_START + CRC8_OFFSET]
    faulted[CRC8_ABS] = crc8_dvb(bytes(faulted_header9)) ^ original_mode
    return bytes(faulted)


MODE_SPECS = {
    "corrupt": {
        "vector_id": "bbframe-b2-corrupt",
        "transform": transform_corrupt,
        "fault_parameters": {
            "layer": "BBFRAME",
            "fault_type": "BBHEADER_SYNC_FAULT",
            "field": "SYNCD",
            "mode": "corrupt",
            "target_frame_index": TARGET_FRAME_INDEX,
            "target_byte_offset": SYNCD_OFFSET,
            "corrupt_mask": CORRUPT_MASK,
            "crc8_recomputed": False,
            "expected_state": (
                "crc8_valid=false on frame 0, UP boundaries withheld → "
                "bbframe.recovery_failed evidence (TSDuck 3.45 propagates "
                "this silently, #104)"
            ),
        },
        "expected_detail_overrides": {
            # byte 7 flipped: SYNCD 0x0000 → 0x0200 (512 bits)
            "syncd": 0x0200,
            "crc8_valid": False,
            "up_count": 0,
            "up_indices": [],
            "state": "crc8_invalid",
        },
    },
    "shift": {
        "vector_id": "bbframe-b2-shift",
        "transform": transform_shift,
        "fault_parameters": {
            "layer": "BBFRAME",
            "fault_type": "BBHEADER_SYNC_FAULT",
            "field": "SYNCD",
            "mode": "shift",
            "target_frame_index": TARGET_FRAME_INDEX,
            "target_byte_offset": SYNCD_OFFSET,
            "shifted_syncd_bits": SHIFT_DELTA,
            "crc8_recomputed": True,
            "expected_state": (
                "crc8_valid=true, state=syncd_misaligned on frame 0 (UP 边界"
                "错位 — SYNCD 是数据字段内首个 UP 的位距离，不是同步字节)"
            ),
        },
        "expected_detail_overrides": {
            "syncd": SHIFT_DELTA,  # 0x0000 → 0x0001 (1 bit, not a byte multiple)
            "crc8_valid": True,
            "up_count": 0,
            "up_indices": [],
            "state": "syncd_misaligned",
        },
    },
}


def write_trio(mode: str, baseline_path: Path, output_dir: Path) -> Path:
    spec = MODE_SPECS[mode]
    vector_id = spec["vector_id"]
    baseline = baseline_path.read_bytes()
    baseline_expectations = json.loads(
        (baseline_path.parent / "expectations.json").read_text(encoding="utf-8")
    )
    faulted = spec["transform"](baseline)

    entries = []
    for entry in baseline_expectations["expectations"]:
        detail = dict(entry["detail"])
        if entry["locator"]["frame_index"] == TARGET_FRAME_INDEX:
            detail.update(spec["expected_detail_overrides"])
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": dict(entry["locator"]),
                "detail": detail,
            }
        )

    base = output_dir / vector_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{vector_id}.ts").write_bytes(faulted)
    manifest = {
        "vector_id": vector_id,
        "kind": "faulted_ts",
        "related_specs": RELATED_SPECS,
        "generator_version": GENERATOR_VERSION,
        "config_hash": None,
        "sha256": "sha256:" + hashlib.sha256(faulted).hexdigest(),
        "packet_count": 3,
        "fault_plan_ref": BASELINE_ID,
        "fault_parameters": spec["fault_parameters"],
        "verification": {
            "path": "bit-level-review",
            "direction": (
                f"independent-{mode}-transform→self-parse (frame 0 SYNCD "
                f"{mode} face pinned byte-exactly; TSDuck 3.45 has zero "
                "user-side BBFrame capability, #104 — no L2 cross possible, "
                "NOT TRUSTED framing per ruling §10-9)"
            ),
            "evidence_ref": (
                f"docs/test-vectors/golden/{vector_id}/{vector_id}.verification.md"
            ),
        },
    }
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (base / "expectations.json").write_text(
        json.dumps({"expectations": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=sorted(MODE_SPECS), required=True)
    parser.add_argument(
        "--baseline",
        default=f"docs/test-vectors/golden/{BASELINE_ID}/{BASELINE_ID}.ts",
        help="registered baseline vector bytes",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/test-vectors/golden",
        help="SPEC-506 golden root (trio written to <dir>/bbframe-b2-<mode>/)",
    )
    args = parser.parse_args()
    base = write_trio(args.mode, Path(args.baseline), Path(args.output_dir))
    faulted = (base / f"{MODE_SPECS[args.mode]['vector_id']}.ts").read_bytes()
    print(f"{MODE_SPECS[args.mode]['vector_id']}: {len(faulted)} bytes")
    print(f"sha256: {hashlib.sha256(faulted).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
