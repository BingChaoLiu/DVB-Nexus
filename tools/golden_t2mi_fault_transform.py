"""SPEC-506 §6 / SPEC-600 §11.1 — golden fault transforms for the T2-MI
negative set (``t2mi-crc-corrupt`` / ``t2mi-unknown-type`` /
``t2mi-truncated``).

Independent transform script (house red line: faulted vectors are never
generated through the self implementation — no ``src/ts`` import): it
reads the registered ``t2mi-minimal`` baseline bytes and derives the
faulted counterparts, each pair-linked (``fault_plan_ref``) to the
baseline:

- ``t2mi-crc-corrupt`` — flips **one bit** inside packet 0's BBFRAME
  payload while leaving the stored CRC-32 trailer untouched.  Semantics
  (frozen): a CRC-32-corrupted packet must surface as the explicit
  ``crc32_valid=False`` bad-packet mark and parsing must **continue** —
  nothing is dropped (SPEC-600 §8; the TSDuck 3.45 silent-drop lesson
  #104 is the red line this vector pins).
- ``t2mi-unknown-type`` — overwrites packet 0's ``packet_type`` header
  byte with an undefined value (``0x55`` — outside the TS 102 773 §5.1
  type table and not the ``0xFF`` stuffing identity) **and recomputes**
  the CRC-32 trailer so the CRC face stays green and the type face is
  isolated.  Semantics (frozen): an unknown packet type must surface as
  the explicit ``payload_kind="unknown"`` state and parsing must
  continue (SPEC-600 §8 注册表渐进).
- ``t2mi-truncated`` — cuts the stream mid-final-packet (packets 0–1
  complete + ``KEEP_TAIL_BYTES`` bytes of packet 2).  Semantics
  (frozen): the truncated / non-integral tail must surface as the
  explicit ``truncated=True`` state plus the verbatim ``trailing``
  bytes — the parser has **no scan/resync/skip mode** (house ruling #11
  precedent; the #104 demux-stall pathology made visible).

Determinism (SPEC-506 §6): same baseline bytes + same parameters ⇒
same faulted bytes; the registered sha256 is the frozen identity.

Usage::

    python tools/golden_t2mi_fault_transform.py \
        --vector t2mi-crc-corrupt \
        --baseline docs/test-vectors/golden/t2mi-minimal/t2mi-minimal.ts \
        --output-dir docs/test-vectors/golden

(``--vector`` defaults to ``t2mi-crc-corrupt``, the original registration,
so its documented regeneration command stays valid.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

BASELINE_ID = "t2mi-minimal"
RELATED_SPECS = ["SPEC-600"]

# --- independent CRC-32/MPEG-2 (bitwise MSB-first re-derivation; no src/ts
# --- involvement; check value b"123456789" -> 0x0376E6E7) ------------------

_CRC32_MPEG2_POLY = 0x04C11DB7
_CRC32_MPEG2_INIT = 0xFFFFFFFF


def _crc32_mpeg2(data: bytes) -> int:
    """CRC-32/MPEG-2: poly 0x04C11DB7, init 0xFFFFFFFF, RefIn/RefOut off,
    XorOut 0 — the trailer value that verifies to remainder zero."""
    crc = _CRC32_MPEG2_INIT
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = (crc << 1) ^ _CRC32_MPEG2_POLY
            else:
                crc <<= 1
            crc &= 0xFFFFFFFF
    return crc


# --- baseline geometry (TS 102 773 §5.1: 6-byte header, payload in bytes,
# --- 4-byte CRC-32 trailer; back-to-back packing, no gaps) ------------------

HEADER_SIZE = 6
CRC_SIZE = 4


def _packet_spans(baseline: bytes) -> list[tuple[int, int, int]]:
    """Walk the baseline's declared packet geometry: (start, payload_len,
    total_size) per packet, derived from the 16-bit BE payload-bits field.
    """
    spans: list[tuple[int, int, int]] = []
    position = 0
    while position < len(baseline):
        payload_bits = int.from_bytes(
            baseline[position + 4 : position + 6], "big"
        )
        payload_len = (payload_bits + 7) // 8
        total = HEADER_SIZE + payload_len + CRC_SIZE
        spans.append((position, payload_len, total))
        position += total
    return spans


# --- frozen transform parameters -------------------------------------------
#
# t2mi-crc-corrupt: flip the LSB of one BBFRAME data-field byte inside
# packet 0 (header 6 + transport prefix 3 + BBHEADER 10, i.e. inside the
# first encapsulated user packet), CRC NOT recomputed.
CRC_CORRUPT_FLIP_BYTE_OFFSET = 6 + 3 + 10 + 5
CRC_CORRUPT_FLIP_MASK = 0x01
CRC_CORRUPT_TARGET_PACKET_INDEX = 0

# t2mi-unknown-type: overwrite packet 0's packet_type byte (stream offset 0
# — the first header byte of the first packet) with 0x55, an undefined
# packet_type value (outside the TS 102 773 §5.1 table, not the 0xFF
# stuffing identity), then recompute the CRC-32 trailer so the CRC face
# stays green (the type face is isolated).
UNKNOWN_TYPE_TARGET_PACKET_INDEX = 0
UNKNOWN_TYPE_TYPE_BYTE_OFFSET = 0
UNKNOWN_TYPE_VALUE = 0x55

# t2mi-truncated: keep packets 0–1 complete plus the first 100 bytes of
# packet 2 (more than the 6-byte header so the declared-length cut is
# exercised, far less than packet 2's 2279-byte total).
TRUNCATED_TARGET_PACKET_INDEX = 2
TRUNCATED_KEEP_TAIL_BYTES = 100


@dataclass(frozen=True)
class TransformSpec:
    """One faulted vector: frozen transform + expectations + registration."""

    vector_id: str
    generator_version: str
    direction: str
    fault_parameters: dict
    packet_count: int


def _transform_crc_corrupt(baseline: bytes) -> bytes:
    corrupted = bytearray(baseline)
    corrupted[CRC_CORRUPT_FLIP_BYTE_OFFSET] ^= CRC_CORRUPT_FLIP_MASK
    return bytes(corrupted)


def _transform_unknown_type(baseline: bytes) -> bytes:
    spans = _packet_spans(baseline)
    start, payload_len, _total = spans[UNKNOWN_TYPE_TARGET_PACKET_INDEX]
    type_offset = start + UNKNOWN_TYPE_TYPE_BYTE_OFFSET
    corrupted = bytearray(baseline)
    corrupted[type_offset] = UNKNOWN_TYPE_VALUE
    trailer_at = start + HEADER_SIZE + payload_len
    body = corrupted[start : trailer_at]
    crc = _crc32_mpeg2(bytes(body))
    corrupted[trailer_at : trailer_at + CRC_SIZE] = crc.to_bytes(CRC_SIZE, "big")
    return bytes(corrupted)


def _transform_truncated(baseline: bytes) -> bytes:
    spans = _packet_spans(baseline)
    start, _payload_len, total = spans[TRUNCATED_TARGET_PACKET_INDEX]
    kept = start + TRUNCATED_KEEP_TAIL_BYTES
    return baseline[:kept]


def _expectations_crc_corrupt(baseline_expectations: dict) -> dict:
    """Expectations mirroring the baseline shape, packet 0 marked bad.

    Packets 1..n keep ``crc32_valid=True`` — the continuation proof that
    a CRC failure never aborts or truncates the parse (静默丢弃为零).
    """
    entries = []
    for position, entry in enumerate(baseline_expectations["expectations"]):
        detail = dict(entry["detail"])
        detail["crc32_valid"] = position != CRC_CORRUPT_TARGET_PACKET_INDEX
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": entry["locator"]["packet_index"]},
                "detail": detail,
            }
        )
    return {"expectations": entries}


def _expectations_unknown_type(baseline_expectations: dict) -> dict:
    """Packet 0 becomes the explicit unknown-type state: ``payload_kind``
    ``"unknown"``, BBFRAME-derived faces ``None``, CRC face green (the
    trailer was recomputed — the type face is isolated).  Packets 1..n
    keep the baseline details verbatim (continuation proof)."""
    entries = []
    for position, entry in enumerate(
        baseline_expectations["expectations"]
    ):
        if position == UNKNOWN_TYPE_TARGET_PACKET_INDEX:
            detail = {
                "packet_type": UNKNOWN_TYPE_VALUE,
                "packet_counter": entry["detail"]["packet_counter"],
                "payload_kind": "unknown",
                "payload_bytes_len": entry["detail"]["payload_bytes_len"],
                "crc32_valid": True,
                "frame_index": None,
                "plp_id": None,
            }
        else:
            detail = dict(entry["detail"])
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": entry["locator"]["packet_index"]},
                "detail": detail,
            }
        )
    return {"expectations": entries}


def _expectations_truncated(baseline_expectations: dict) -> dict:
    """Only the complete packets (0..1) carry observation expectations;
    the non-integral tail is pinned by the conformance assertions against
    the manifest's frozen ``kept_tail_bytes`` (the expectations mechanism
    carries per-packet observations, not stream-level states)."""
    entries = []
    for entry in baseline_expectations["expectations"]:
        if entry["locator"]["packet_index"] >= TRUNCATED_TARGET_PACKET_INDEX:
            break
        entries.append(
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": entry["locator"]["packet_index"]},
                "detail": dict(entry["detail"]),
            }
        )
    return {"expectations": entries}


SPECS: dict[str, TransformSpec] = {
    "t2mi-crc-corrupt": TransformSpec(
        vector_id="t2mi-crc-corrupt",
        generator_version=(
            "tools/golden_t2mi_fault_transform.py v1 "
            "(independent bit-flip transform; no src/ts involvement)"
        ),
        direction=(
            "independent-bit-flip-transform→self-parse (packet 0 marked "
            "crc32_valid=False, no packet dropped, continuation proof)"
        ),
        fault_parameters={
            "layer": "T2MI",
            "transform": "crc32_bit_flip",
            "target_packet_index": CRC_CORRUPT_TARGET_PACKET_INDEX,
            "flip_byte_offset": CRC_CORRUPT_FLIP_BYTE_OFFSET,
            "flip_mask": CRC_CORRUPT_FLIP_MASK,
            "crc_recomputed": False,
            "expected_state": "crc32_valid=False on packet 0, parse continues",
        },
        packet_count=3,
    ),
    "t2mi-unknown-type": TransformSpec(
        vector_id="t2mi-unknown-type",
        generator_version=(
            "tools/golden_t2mi_fault_transform.py v2 "
            "(independent packet_type-override transform with CRC recompute; "
            "no src/ts involvement)"
        ),
        direction=(
            "independent-packet-type-override-transform→self-parse (packet 0 "
            "payload_kind=unknown with the CRC face green — type face "
            "isolated, no packet dropped, continuation proof)"
        ),
        fault_parameters={
            "layer": "T2MI",
            "transform": "packet_type_override",
            "target_packet_index": UNKNOWN_TYPE_TARGET_PACKET_INDEX,
            "type_byte_offset": UNKNOWN_TYPE_TYPE_BYTE_OFFSET,
            "new_packet_type": UNKNOWN_TYPE_VALUE,
            "undefined_value_note": (
                "0x55 is outside the TS 102 773 §5.1 packet_type table and "
                "is not the 0xFF stuffing identity"
            ),
            "crc_recomputed": True,
            "expected_state": (
                "payload_kind=unknown on packet 0 with crc32_valid=True, "
                "parse continues"
            ),
        },
        packet_count=3,
    ),
    "t2mi-truncated": TransformSpec(
        vector_id="t2mi-truncated",
        generator_version=(
            "tools/golden_t2mi_fault_transform.py v2 "
            "(independent tail-truncation transform; no src/ts involvement)"
        ),
        direction=(
            "independent-tail-truncation-transform→self-parse (truncated=True "
            "+ verbatim trailing bytes, packets 0–1 intact; no scan/resync — "
            "house ruling #11 precedent)"
        ),
        fault_parameters={
            "layer": "T2MI",
            "transform": "tail_truncation",
            "target_packet_index": TRUNCATED_TARGET_PACKET_INDEX,
            "kept_tail_bytes": TRUNCATED_KEEP_TAIL_BYTES,
            "expected_state": (
                "truncated=True, trailing = kept_tail_bytes bytes of packet 2, "
                "packets 0–1 parse intact"
            ),
        },
        packet_count=2,
    ),
}

TRANSFORMS = {
    "t2mi-crc-corrupt": _transform_crc_corrupt,
    "t2mi-unknown-type": _transform_unknown_type,
    "t2mi-truncated": _transform_truncated,
}

EXPECTATION_BUILDERS = {
    "t2mi-crc-corrupt": _expectations_crc_corrupt,
    "t2mi-unknown-type": _expectations_unknown_type,
    "t2mi-truncated": _expectations_truncated,
}


def write_trio(vector_id: str, baseline_path: Path, output_dir: Path) -> Path:
    spec = SPECS[vector_id]
    baseline = baseline_path.read_bytes()
    baseline_expectations = json.loads(
        (baseline_path.parent / "expectations.json").read_text(encoding="utf-8")
    )
    faulted = TRANSFORMS[vector_id](baseline)
    base = output_dir / vector_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{vector_id}.ts").write_bytes(faulted)
    manifest = {
        "vector_id": vector_id,
        "kind": "faulted_ts",
        "related_specs": RELATED_SPECS,
        "generator_version": spec.generator_version,
        "config_hash": None,
        "sha256": "sha256:" + hashlib.sha256(faulted).hexdigest(),
        "packet_count": spec.packet_count,
        "fault_plan_ref": BASELINE_ID,
        "fault_parameters": spec.fault_parameters,
        "verification": {
            "path": "bit-level-review",
            "direction": spec.direction,
            "evidence_ref": (
                f"docs/test-vectors/golden/{vector_id}/{vector_id}.verification.md"
            ),
        },
    }
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (base / "expectations.json").write_text(
        json.dumps(
            EXPECTATION_BUILDERS[vector_id](baseline_expectations),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--vector",
        choices=sorted(SPECS),
        default="t2mi-crc-corrupt",
        help="faulted counterpart to derive (default: the original "
        "t2mi-crc-corrupt registration)",
    )
    parser.add_argument(
        "--baseline",
        default=f"docs/test-vectors/golden/{BASELINE_ID}/{BASELINE_ID}.ts",
        help="registered baseline vector bytes",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/test-vectors/golden",
        help="SPEC-506 golden root (trio written to <dir>/<vector_id>/)",
    )
    args = parser.parse_args()
    base = write_trio(args.vector, Path(args.baseline), Path(args.output_dir))
    faulted = (base / f"{args.vector}.ts").read_bytes()
    baseline_bytes = Path(args.baseline).read_bytes()
    print(
        f"{args.vector}: {len(faulted)} bytes "
        f"(baseline {len(baseline_bytes)} bytes)"
    )
    print(f"sha256: {hashlib.sha256(faulted).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
