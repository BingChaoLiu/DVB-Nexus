"""SPEC-506 §7 #1 — golden vector ``packet-header-set`` constructor.

L1 bit-level vector (SPEC-506 §5): 10 hand-derived 188-byte header samples
covering the SPEC-100 §3 wire-table edges (TEI / PUSI / transport priority /
PID boundaries / scrambling control / AFC / CC).  Every sample's 4 header
bytes are derived here **bit by bit from the SPEC-100 §3 table** — the
script is the reviewable derivation ("spec 表推导脚本 + 人工评审", #14);
no part of ``src/ts`` is imported or consulted.

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes.  The
vector is a frozen asset: the registered sha256 in ``manifest.json`` is its
identity; this script exists to document and reproduce the derivation, and
CI only verifies the sha (never regenerates).

Usage::

    python tools/make_golden_packet_header_set.py --output-dir <dir>

writes ``<dir>/packet-header-set/{packet-header-set.ts, manifest.json,
expectations.json}`` (the SPEC-506 §3 trio).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VECTOR_ID = "packet-header-set"
PACKET_SIZE = 188
SYNC_BYTE = 0x47

# --- sample derivation table (SPEC-100 §3 wire layout) ----------------------
#
# | byte/bit | field                        |
# |----------|------------------------------|
# | 0        | sync_byte = 0x47             |
# | 1[7]     | transport_error_indicator    |
# | 1[6]     | payload_unit_start_indicator |
# | 1[5]     | transport_priority           |
# | 1[4:0]+2 | PID (13 bit)                 |
# | 3[7:6]   | transport_scrambling_control |
# | 3[5:4]   | adaptation_field_control     |
# | 3[3:0]   | continuity_counter           |
#
# Each sample: (purpose, tei, pusi, priority, pid, tsc, afc, cc, body_builder)


def _payload_filler(length: int) -> bytes:
    """Deterministic payload filler for header-only samples (0x00)."""
    return b"\x00" * length


def _build_af_only_body(flags: int) -> bytes:
    """Adaptation-only body: length 183 = flags + stuffing (SPEC-100 §5.2)."""
    return bytes([flags]) + b"\xff" * 182


def _encode_pcr(base: int, extension: int) -> bytes:
    """H.222.0 PCR packing (cross-linked to PCR-PTS.md): 33-bit base,
    6 reserved bits (111111), 9-bit extension."""
    value = (base & ((1 << 33) - 1)) << 15
    value |= 0b111111 << 9
    value |= extension & 0x1FF
    return value.to_bytes(6, "big")


def _sample_s0() -> bytes:
    """s0 — minimal section-start packet: PID 0, PUSI=1, payload-only, CC 0.

    Payload: pointer_field 0x00 followed by filler (payload content is not
    part of the header assertions; the pointer convention is documented).
    """
    header = bytes(
        [
            SYNC_BYTE,
            0x40,  # TEI 0, PUSI 1, priority 0, PID hi 5 bits 0x00
            0x00,  # PID lo
            0x10,  # tsc 00, AFC 01, CC 0
        ]
    )
    return header + b"\x00" + _payload_filler(183)


def _sample_s1() -> bytes:
    """s1 — TEI=1 edge: PID 0, payload-only, CC 1."""
    header = bytes([SYNC_BYTE, 0x80, 0x00, 0x11])
    return header + _payload_filler(184)


def _sample_s2() -> bytes:
    """s2 — transport_priority=1 + CC upper edge 15: PID 1, payload-only."""
    header = bytes([SYNC_BYTE, 0x20, 0x01, 0x1F])
    return header + _payload_filler(184)


def _sample_s3() -> bytes:
    """s3 — null-PID edge (0x1FFF): canonical null packet shape (SPEC-107
    §5.1 semantics: PID 0x1FFF, AFC 01, CC 0, 0xFF body)."""
    header = bytes([SYNC_BYTE, 0x1F, 0xFF, 0x10])
    return header + b"\xff" * 184


def _sample_s4() -> bytes:
    """s4 — largest non-null PID 0x1FFE + PUSI=1, CC 8."""
    header = bytes([SYNC_BYTE, 0x5F, 0xFE, 0x18])
    return header + _payload_filler(184)


def _sample_s5() -> bytes:
    """s5 — reserved scrambling control 01 (kept verbatim, §5.3), PID 0x10."""
    header = bytes([SYNC_BYTE, 0x00, 0x10, 0x53])
    return header + _payload_filler(184)


def _sample_s6() -> bytes:
    """s6 — even scrambling (10) + AFC=11 carrying a hand-set PCR.

    AF length 180: flags(1) + PCR(6) + stuffing(173); payload = 3 bytes.
    PCR = base 12345 / ext 0 (PCR-PTS.md bit packing).
    """
    # byte1 = PID hi 5 bits 0x01 (PUSI 0); byte3 = tsc 10 (0x80) | AFC 11
    # (0x30) | CC 4 (0x04) = 0xB4
    header = bytes([SYNC_BYTE, 0x01, 0x00, 0xB4])
    af = bytes([0x10]) + _encode_pcr(12345, 0) + b"\xff" * 173
    body = bytes([180]) + af
    return header + body + _payload_filler(3)


def _sample_s7() -> bytes:
    """s7 — odd scrambling (11) + adaptation-only CC reuse (§5.4).

    Same PID 0x100 as s6, adaptation-only ⇒ CC reuses the last payload CC
    (4), not incremented.  AF length 183 (adaptation-only must fill the
    packet), flags 0x00.
    """
    header = bytes([SYNC_BYTE, 0x01, 0x00, 0xE4])
    return header + bytes([183]) + _build_af_only_body(0x00)


def _sample_s8() -> bytes:
    """s8 — adaptation-only with discontinuity_indicator=1, PID 0x11, CC 9.

    Maximal AF length edge: 183 = flags + stuffing only (no PCR).
    """
    header = bytes([SYNC_BYTE, 0x00, 0x11, 0x29])
    return header + bytes([183]) + _build_af_only_body(0x80)


def _sample_s9() -> bytes:
    """s9 — AFC=11 with zero-length adaptation field (minimum edge).

    AF length byte 0 (no flags byte), payload = 183 bytes, PUSI=1, CC 10.
    """
    header = bytes([SYNC_BYTE, 0x40, 0x12, 0x3A])
    return header + bytes([0]) + _payload_filler(183)


SAMPLES = (
    ("section-start PAT-shaped minimal header", _sample_s0),
    ("TEI set", _sample_s1),
    ("transport priority set + CC 15 edge", _sample_s2),
    ("null PID 0x1FFF canonical null packet", _sample_s3),
    ("PID 0x1FFE largest non-null + PUSI", _sample_s4),
    ("reserved scrambling control 01 kept verbatim", _sample_s5),
    ("even scrambling + AFC=11 PCR adaptation field", _sample_s6),
    ("odd scrambling + adaptation-only CC reuse", _sample_s7),
    ("adaptation-only discontinuity flag + AF length 183", _sample_s8),
    ("AFC=11 zero-length adaptation field", _sample_s9),
)


def build_bytes() -> bytes:
    """Assemble the 10 samples into the frozen byte payload."""
    return b"".join(builder() for _, builder in SAMPLES)


def build_expectations() -> dict:
    """Expected observations (SPEC-506 §4 / ADR-0007 第 5 条 shape).

    ``ts.packet_batch_observed`` per sample; ``detail`` carries the §3 wire
    fields hand-derived above plus the sample-specific semantic extras.
    """
    headers = (
        dict(tei=0, pusi=1, priority=0, pid=0x0000, scrambling=0, afc=1, cc=0),
        dict(tei=1, pusi=0, priority=0, pid=0x0000, scrambling=0, afc=1, cc=1),
        dict(tei=0, pusi=0, priority=1, pid=0x0001, scrambling=0, afc=1, cc=15),
        dict(tei=0, pusi=0, priority=0, pid=0x1FFF, scrambling=0, afc=1, cc=0),
        dict(tei=0, pusi=1, priority=0, pid=0x1FFE, scrambling=0, afc=1, cc=8),
        dict(tei=0, pusi=0, priority=0, pid=0x0010, scrambling=1, afc=1, cc=3),
        dict(tei=0, pusi=0, priority=0, pid=0x0100, scrambling=2, afc=3, cc=4),
        dict(tei=0, pusi=0, priority=0, pid=0x0100, scrambling=3, afc=2, cc=4),
        dict(tei=0, pusi=0, priority=0, pid=0x0011, scrambling=0, afc=2, cc=9),
        dict(tei=0, pusi=1, priority=0, pid=0x0012, scrambling=0, afc=3, cc=10),
    )
    extras = {
        0: {"pointer_field": 0},
        3: {"payload_fill": "0xff (canonical null packet body)"},
        5: {"validation_issue": "TS_SCRAMBLING_RESERVED (kept verbatim)"},
        6: {"pcr": {"base": 12345, "extension": 0}},
        7: {"cc_rule": "adaptation-only reuses last payload CC (SPEC-100 §5.4)"},
        8: {"discontinuity_indicator": True, "af_length": 183},
        9: {"af_length": 0},
    }
    return {
        "expectations": [
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": index},
                "detail": {**headers[index], **extras.get(index, {})},
            }
            for index in range(len(SAMPLES))
        ]
    }


def build_manifest(sha256: str) -> dict:
    return {
        "vector_id": VECTOR_ID,
        "kind": "bit_level",
        "related_specs": ["SPEC-100"],
        "generator_version": (
            "tools/make_golden_packet_header_set.py v1 "
            "(hand-derived from SPEC-100 §3; no src/ts involvement)"
        ),
        "config_hash": None,
        "sha256": f"sha256:{sha256}",
        "packet_count": len(SAMPLES),
        "fault_plan_ref": None,
        "verification": {
            "path": "bit-level-review",
            "direction": "spec-table-derivation→self-parse",
            "evidence_ref": (
                "docs/test-vectors/PACKET-HEADER-SET.md + "
                f"docs/test-vectors/golden/{VECTOR_ID}/{VECTOR_ID}.verification.md"
            ),
        },
    }


def write_trio(output_dir: Path) -> Path:
    ts_bytes = build_bytes()
    sha256 = hashlib.sha256(ts_bytes).hexdigest()
    base = output_dir / VECTOR_ID
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{VECTOR_ID}.ts").write_bytes(ts_bytes)
    (base / "manifest.json").write_text(
        json.dumps(build_manifest(sha256), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
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
        required=True,
        help="directory that receives packet-header-set/ (the golden root)",
    )
    args = parser.parse_args()
    base = write_trio(Path(args.output_dir))
    ts_bytes = build_bytes()
    print(f"{VECTOR_ID}: {len(ts_bytes)} bytes, "
          f"sha256={hashlib.sha256(ts_bytes).hexdigest()}")
    print(f"trio written under {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
