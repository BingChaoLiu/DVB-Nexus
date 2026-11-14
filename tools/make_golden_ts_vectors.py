"""SPEC-506 §7 #4/#5 — golden vector constructors ``cc-wrap`` / ``pcr-wrap``.

Deterministic byte-level constructors for the script-built positive golden
vectors (L2 verification path: script-construct → TSDuck analyze, SPEC-506
§5/#14).  The bytes are hand-assembled **from the SPEC-100 §3 wire table**
— no ``src/ts`` import, so the constructor stays independent of the self
implementation (the conformance tests provide the self-parser side of the
cross-check; TSDuck provides the independent side, recorded in each
vector's verification note).

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes.  The
registered sha256 in each ``manifest.json`` is the vector's frozen
identity; CI only verifies the sha (never regenerates).

Usage::

    python tools/make_golden_ts_vectors.py <cc-wrap|pcr-wrap> --output-dir <dir>

writes ``<dir>/<vector_id>/`` (SPEC-506 §3 trio).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TS_PACKET_SIZE = 188
SYNC_BYTE = 0x47
PID_NULL = 0x1FFF


def _header(pid: int, cc: int, *, pusi: int = 0, afc: int = 1) -> bytes:
    """4-byte TS header derived bit-by-bit from the SPEC-100 §3 table."""
    byte1 = (pusi & 1) << 6 | ((pid >> 8) & 0x1F)
    byte3 = (0 << 6) | (afc & 0x03) << 4 | (cc & 0x0F)
    return bytes([SYNC_BYTE, byte1, pid & 0xFF, byte3])


def _encode_pcr(base: int, extension: int) -> bytes:
    """H.222.0 PCR packing: 33-bit base, 6 reserved bits 111111, 9-bit ext."""
    value = (base & ((1 << 33) - 1)) << 15
    value |= 0b111111 << 9
    value |= extension & 0x1FF
    return value.to_bytes(6, "big")


# --- cc-wrap (SPEC-506 §7 #4) -----------------------------------------------

CC_WRAP_ID = "cc-wrap"
CC_WRAP_PID = 0x0123
CC_WRAP_PACKETS = 18  # CC 0..15 then 0,1 — the 15→0 wrap at index 15→16


def build_cc_wrap_bytes() -> bytes:
    """18 payload-only packets on one PID with CC riding modulo-16 wrap."""
    packets = []
    for index in range(CC_WRAP_PACKETS):
        header = _header(CC_WRAP_PID, index % 16)
        packets.append(header + b"\x00" * (TS_PACKET_SIZE - 4))
    return b"".join(packets)


def build_cc_wrap_expectations() -> dict:
    """Pin the wrap-adjacent slots (the full sequence is asserted by the
    conformance test against the §5.4 rule)."""
    return {
        "expectations": [
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": CC_WRAP_PID, "packet_index": 0},
                "detail": {"cc": 0, "note": "sequence start"},
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": CC_WRAP_PID, "packet_index": 15},
                "detail": {"cc": 15, "note": "CC upper edge"},
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": CC_WRAP_PID, "packet_index": 16},
                "detail": {"cc": 0, "note": "modulo-16 wrap 15→0 (SPEC-100 §5.4)"},
            },
        ]
    }


def build_cc_wrap_manifest(sha256: str) -> dict:
    return {
        "vector_id": CC_WRAP_ID,
        "kind": "generated_ts",
        "related_specs": ["SPEC-100"],
        "generator_version": (
            "tools/make_golden_ts_vectors.py v1 (script-construct; no src/ts involvement)"
        ),
        "config_hash": None,
        "sha256": f"sha256:{sha256}",
        "packet_count": CC_WRAP_PACKETS,
        "fault_plan_ref": None,
        "verification": {
            "path": "tsduck-cross",
            "direction": "script-construct→tsduck-analyze",
            "evidence_ref": (
                f"docs/test-vectors/golden/{CC_WRAP_ID}/{CC_WRAP_ID}.verification.md"
            ),
        },
    }


# --- pcr-wrap (SPEC-506 §7 #5) ----------------------------------------------

PCR_WRAP_ID = "pcr-wrap"
PCR_WRAP_PID = 0x0100
PCR_WRAP_BASES = (
    (1 << 33) - 3,
    (1 << 33) - 2,
    (1 << 33) - 1,  # largest legal base (SPEC-105 §11)
    0,              # the wrap step
    1,
    2,
)
PCR_WRAP_EXT = 0


def build_pcr_wrap_bytes() -> bytes:
    """6 adaptation-only packets with hand-set PCR values around the wrap.

    Hand-set per §7 (2^33−δ 前后手工置值): base walks 2^33−3 → 0 → 2 with
    ext 0, so combined 27 MHz ticks jump (2^33−1)·300 → 0 — the wrap is a
    small forward modular delta (300 ticks), inside the direction-decidable
    half-period window (SPEC-105 §6).  All packets adaptation-only ⇒ CC
    reuses the initial value 0 (SPEC-100 §5.4).
    """
    packets = []
    for base in PCR_WRAP_BASES:
        # AFC=10 adaptation-only: AF length must fill the packet (183).
        header = _header(PCR_WRAP_PID, 0, afc=2)
        af = bytes([0x10]) + _encode_pcr(base, PCR_WRAP_EXT) + b"\xff" * 176
        packets.append(header + bytes([183]) + af)
    return b"".join(packets)


def build_pcr_wrap_expectations() -> dict:
    return {
        "expectations": [
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": PCR_WRAP_PID, "packet_index": index},
                "detail": {
                    "pcr_base": base,
                    "pcr_extension": PCR_WRAP_EXT,
                    "note": (
                        "wrap step" if index == 3 else
                        "largest legal base" if index == 2 else
                        "hand-set around 2^33 boundary"
                    ),
                },
            }
            for index, base in enumerate(PCR_WRAP_BASES)
        ]
    }


def build_pcr_wrap_manifest(sha256: str) -> dict:
    return {
        "vector_id": PCR_WRAP_ID,
        "kind": "generated_ts",
        "related_specs": ["SPEC-105"],
        "generator_version": (
            "tools/make_golden_ts_vectors.py v1 (script-construct; no src/ts involvement)"
        ),
        "config_hash": None,
        "sha256": f"sha256:{sha256}",
        "packet_count": len(PCR_WRAP_BASES),
        "fault_plan_ref": None,
        "verification": {
            "path": "tsduck-cross",
            "direction": "script-construct→tsduck-analyze",
            "evidence_ref": (
                f"docs/test-vectors/golden/{PCR_WRAP_ID}/{PCR_WRAP_ID}.verification.md"
            ),
        },
    }


# --- section-fragmentation (SPEC-506 §7 #6) ----------------------------------

SECTION_FRAGMENTATION_ID = "section-fragmentation"
SECTION_FRAGMENTATION_PID = 0x0000
SECTION_PROGRAM_COUNT = 100


def _crc32_mpeg2(data: bytes) -> int:
    """Independent CRC-32/MPEG-2 (poly 0x04C11DB7, init/xorout 0xFFFFFFFF,
    no reflection) — the PSI CRC convention covers the whole section minus
    the CRC field (H.222.0 Annex A).  Verified against the published check
    value: ``crc32_mpeg2(b\"123456789\") == 0x0376E6E7`` (CRC32-MPEG2.md)."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _build_100_program_pat_section() -> bytes:
    """One 412-byte PAT section with 100 programs (exceeds 2×184 payload
    bytes ⇒ spans 3 packets).  Wire bytes hand-derived from SPEC-103 §5
    (PAT = table_id 0x00, section_syntax 1, program entries: 16-bit
    program_number + 3 reserved bits 111 + 13-bit PMT PID)."""
    body = bytearray()
    body += bytes([0x00, 0xB0, 0x00])  # table_id, section_syntax+len placeholder
    body += (1).to_bytes(2, "big")     # transport_stream_id
    body.append(0xC1)                  # reserved 11, version 0, current_next 1
    body += bytes([0x00, 0x00])        # section_number 0 / last_section 0
    for number in range(1, SECTION_PROGRAM_COUNT + 1):
        pmt_pid = 0x0100 + number
        body += number.to_bytes(2, "big")
        body += (0xE000 | pmt_pid).to_bytes(2, "big")
    section_length = len(body) + 4 - 3  # counts bytes after the 3-byte header
    body[1] |= (section_length >> 8) & 0x0F
    body[2] = section_length & 0xFF
    body += _crc32_mpeg2(bytes(body)).to_bytes(4, "big")
    return bytes(body)


def build_section_fragmentation_bytes() -> bytes:
    """3 packets: PUSI+pointer on the first, 184-byte continuation, tail."""
    section = _build_100_program_pat_section()
    # Packet 1: pointer_field 0x00 + first 183 section bytes (184 payload).
    p1 = bytes([0x00]) + section[:183]
    # Packet 2: next 184 section bytes (full payload).
    p2 = section[183:367]
    # Packet 3: remaining tail, then stuffing.
    p3 = section[367:]
    packets = []
    for index, (pusi, payload) in enumerate(
        ((1, p1), (0, p2), (0, p3)), start=0
    ):
        header = _header(SECTION_FRAGMENTATION_PID, index, pusi=pusi)
        chunk = header + payload
        chunk += b"\xff" * (TS_PACKET_SIZE - len(chunk))
        packets.append(chunk)
    return b"".join(packets)


def build_section_fragmentation_expectations() -> dict:
    return {
        "expectations": [
            {
                "event_type": "ts.psi_section_observed",
                "locator": {"pid": SECTION_FRAGMENTATION_PID},
                "detail": {
                    "table_id": 0,
                    "transport_stream_id": 1,
                    "program_count": SECTION_PROGRAM_COUNT,
                    "section_total_size": 412,
                    "spans_packets": 3,
                    "first_program": {"program_number": 1, "pmt_pid": 0x0101},
                    "last_program": {"program_number": 100, "pmt_pid": 0x0164},
                },
            },
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"pid": SECTION_FRAGMENTATION_PID, "packet_index": 0},
                "detail": {"pusi": 1, "pointer_field": 0, "cc": 0},
            },
        ]
    }


def build_section_fragmentation_manifest(sha256: str) -> dict:
    return {
        "vector_id": SECTION_FRAGMENTATION_ID,
        "kind": "generated_ts",
        "related_specs": ["SPEC-102", "SPEC-106"],
        "generator_version": (
            "tools/make_golden_ts_vectors.py v1 (script-construct; no src/ts involvement)"
        ),
        "config_hash": None,
        "sha256": f"sha256:{sha256}",
        "packet_count": 3,
        "fault_plan_ref": None,
        "verification": {
            "path": "tsduck-cross",
            "direction": "script-construct→tsduck-analyze",
            "evidence_ref": (
                "docs/test-vectors/golden/"
                f"{SECTION_FRAGMENTATION_ID}/{SECTION_FRAGMENTATION_ID}.verification.md"
            ),
        },
    }


# --- trio writer -------------------------------------------------------------


def write_trio(output_dir: Path, vector_id: str, ts_bytes: bytes,
               manifest: dict, expectations: dict) -> Path:
    sha256 = hashlib.sha256(ts_bytes).hexdigest()
    base = output_dir / vector_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{vector_id}.ts").write_bytes(ts_bytes)
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (base / "expectations.json").write_text(
        json.dumps(expectations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return base


CONSTRUCTORS = {
    "cc-wrap": (
        build_cc_wrap_bytes,
        build_cc_wrap_manifest,
        build_cc_wrap_expectations,
    ),
    "pcr-wrap": (
        build_pcr_wrap_bytes,
        build_pcr_wrap_manifest,
        build_pcr_wrap_expectations,
    ),
    "section-fragmentation": (
        build_section_fragmentation_bytes,
        build_section_fragmentation_manifest,
        build_section_fragmentation_expectations,
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vector", choices=sorted(CONSTRUCTORS))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    build_bytes, build_manifest, build_expectations = CONSTRUCTORS[args.vector]
    ts_bytes = build_bytes()
    base = write_trio(
        Path(args.output_dir), args.vector, ts_bytes,
        build_manifest(hashlib.sha256(ts_bytes).hexdigest()), build_expectations(),
    )
    print(f"{args.vector}: {len(ts_bytes)} bytes, "
          f"sha256={hashlib.sha256(ts_bytes).hexdigest()}")
    print(f"trio written under {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
