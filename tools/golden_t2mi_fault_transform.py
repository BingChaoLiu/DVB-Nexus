"""SPEC-506 §6 / SPEC-600 §11.1 — golden fault transform ``t2mi-crc-corrupt``.

Independent transform script (house red line: faulted vectors are never
generated through the self implementation — no ``src/ts`` import): it
reads the registered ``t2mi-minimal`` baseline bytes, flips **one bit**
inside packet 0's BBFRAME payload while leaving the stored CRC-32
trailer untouched, and registers the result as the faulted counterpart
``t2mi-crc-corrupt`` (``fault_plan_ref`` → ``t2mi-minimal``).

Semantics (frozen): a CRC-32-corrupted packet must surface as the
explicit ``crc32_valid=False`` bad-packet mark and parsing must
**continue** — nothing is dropped (SPEC-600 §8; the TSDuck 3.45
silent-drop lesson #104 is the red line this vector pins).

Determinism (SPEC-506 §6): same baseline bytes + same parameters ⇒
same faulted bytes; the registered sha256 is the frozen identity.

Usage::

    python tools/golden_t2mi_fault_transform.py \
        --baseline docs/test-vectors/golden/t2mi-minimal/t2mi-minimal.ts \
        --output-dir docs/test-vectors/golden
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VECTOR_ID = "t2mi-crc-corrupt"
BASELINE_ID = "t2mi-minimal"
RELATED_SPECS = ["SPEC-600"]
GENERATOR_VERSION = (
    "tools/golden_t2mi_fault_transform.py v1 "
    "(independent bit-flip transform; no src/ts involvement)"
)

#: Frozen transform parameters: flip the LSB of one BBFRAME data-field
#: byte inside packet 0 (header 6 + transport prefix 3 + BBHEADER 10,
#: i.e. inside the first encapsulated user packet), CRC NOT recomputed.
FLIP_BYTE_OFFSET = 6 + 3 + 10 + 5
FLIP_MASK = 0x01
TARGET_PACKET_INDEX = 0


def transform(baseline: bytes) -> bytes:
    """Apply the frozen bit flip; the CRC trailer is left verbatim."""
    corrupted = bytearray(baseline)
    corrupted[FLIP_BYTE_OFFSET] ^= FLIP_MASK
    return bytes(corrupted)


def build_expectations(baseline_expectations: dict) -> dict:
    """Expectations mirroring the baseline shape, packet 0 marked bad.

    Packets 1..n keep ``crc32_valid=True`` — the continuation proof that
    a CRC failure never aborts or truncates the parse (静默丢弃为零).
    """
    entries = []
    for position, entry in enumerate(baseline_expectations["expectations"]):
        detail = dict(entry["detail"])
        detail["crc32_valid"] = position != TARGET_PACKET_INDEX
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": entry["locator"]["packet_index"]},
                "detail": detail,
            }
        )
    return {"expectations": entries}


def write_trio(baseline_path: Path, output_dir: Path) -> Path:
    baseline = baseline_path.read_bytes()
    baseline_expectations = json.loads(
        (baseline_path.parent / "expectations.json").read_text(encoding="utf-8")
    )
    faulted = transform(baseline)
    base = output_dir / VECTOR_ID
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{VECTOR_ID}.ts").write_bytes(faulted)
    manifest = {
        "vector_id": VECTOR_ID,
        "kind": "faulted_ts",
        "related_specs": RELATED_SPECS,
        "generator_version": GENERATOR_VERSION,
        "config_hash": None,
        "sha256": "sha256:" + hashlib.sha256(faulted).hexdigest(),
        "packet_count": 3,
        "fault_plan_ref": BASELINE_ID,
        "fault_parameters": {
            "layer": "T2MI",
            "transform": "crc32_bit_flip",
            "target_packet_index": TARGET_PACKET_INDEX,
            "flip_byte_offset": FLIP_BYTE_OFFSET,
            "flip_mask": FLIP_MASK,
            "crc_recomputed": False,
            "expected_state": "crc32_valid=False on packet 0, parse continues",
        },
        "verification": {
            "path": "bit-level-review",
            "direction": (
                "independent-bit-flip-transform→self-parse (packet 0 marked "
                "crc32_valid=False, no packet dropped, continuation proof)"
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
        json.dumps(
            build_expectations(baseline_expectations), indent=2, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--baseline",
        default=f"docs/test-vectors/golden/{BASELINE_ID}/{BASELINE_ID}.ts",
        help="registered baseline vector bytes",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/test-vectors/golden",
        help="SPEC-506 golden root (trio written to <dir>/t2mi-crc-corrupt/)",
    )
    args = parser.parse_args()
    base = write_trio(Path(args.baseline), Path(args.output_dir))
    faulted = (base / f"{VECTOR_ID}.ts").read_bytes()
    print(f"{VECTOR_ID}: {len(faulted)} bytes (baseline {len(faulted)} bytes, 1 bit flipped)")
    print(f"sha256: {hashlib.sha256(faulted).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
