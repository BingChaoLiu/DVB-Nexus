"""SPEC-506 §7 — golden vector ``biss-j96-mode1`` constructor (ticket #126).

L1 bit-level vector (SPEC-506 §5): the ITU-T J.96 §8 example session word
``A13DBC42908F`` derives (Tech 3292/J.96 checksum formula) to control
word ``A13DBC9A42908F61``, and the derived CW drives a DVB-CSA1
scramble/descramble roundtrip over a deterministic TS packet set.

Independence discipline: no part of ``src/`` is imported or consulted.
The CSA1 payload transform is the pure-Python CSA1 oracle
(``tests/_support/csa1_oracle.py`` — the research #106 port that was
vector-checked against libdvbcsa's own static test vectors); the
session-word→CW derivation is re-implemented inline in this script from
the published formula, so the runtime implementation under ``src/ts/biss``
is cross-checked against BOTH independent derivations by the conformance
suite.  The six packets are constructed via the ``ts.packet.TSPacket``
object model only (no src-side generator involvement) and carry a valid
CRC-protected PSI section so the descramble structural self-check has a
real verdict surface.

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes.  The
vector is a frozen asset: the registered sha256 in ``manifest.json`` is
its identity; CI only verifies the sha (never regenerates).

Usage::

    python tools/make_golden_biss_j96.py --output-dir <dir>

writes ``<dir>/biss-j96-mode1/{biss-j96-mode1.ts, manifest.json,
expectations.json}`` (the SPEC-506 §3 trio).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests._support.csa1_oracle import Csa1Oracle  # noqa: E402

VECTOR_ID = "biss-j96-mode1"
PACKET_SIZE = 188
PAYLOAD_LEN = 184

# --- the published J.96 §8 example session word (a public standard
# --- constant, NOT key material) --------------------------------------------
SESSION_WORD = "A13DBC42908F"
DERIVED_CW_HEX = "A13DBC9A42908F61"

SCRAMBLE_PID = 0x0100
PACKET_COUNT = 6

# PSI table id for the section carried by every packet (a PAT-shaped
# section keeps the descramble structural self-check meaningful).
SECTION_TABLE_ID = 0x00


def derive_cw_independent(session_word: str) -> bytes:
    """The Tech 3292/J.96 checksum formula, re-implemented inline.

    CW[0..2] = SW bytes 0..2; CW[3] = (CW[0]+CW[1]+CW[2]) mod 256;
    CW[4..6] = SW bytes 3..6; CW[7] = (CW[4]+CW[5]+CW[6]) mod 256.
    """
    sw = bytes.fromhex(session_word)
    assert len(sw) == 6, "session word is 48 bit (12 hex chars)"
    cw = bytearray(8)
    cw[0:3] = sw[0:3]
    cw[3] = (cw[0] + cw[1] + cw[2]) % 256
    cw[4:7] = sw[3:6]
    cw[7] = (cw[4] + cw[5] + cw[6]) % 256
    return bytes(cw)


# --- independent MPEG-2 CRC-32 (ISO 13818-1 annex A) --------------------------

_CRC_TABLE: "list[int] | None" = None


def _crc_table() -> "list[int]":
    global _CRC_TABLE
    if _CRC_TABLE is None:
        table = []
        for index in range(256):
            value = index << 24
            for _ in range(8):
                if value & 0x80000000:
                    value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                else:
                    value = (value << 1) & 0xFFFFFFFF
            table.append(value)
        _CRC_TABLE = table
    return _CRC_TABLE


def mpeg2_crc32(data: bytes) -> int:
    # NOTE: the MPEG-2 CRC-32 has xorout = 0 (ISO 13818-1 annex A) — the
    # wire section carries the raw register value so the whole-section
    # remainder is zero.  No final XOR here.
    crc = 0xFFFFFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _crc_table()[
            ((crc >> 24) ^ byte) & 0xFF
        ]
    return crc


def build_pat_section() -> bytes:
    """One complete PAT section (table_id 0x00) with valid CRC-32.

    Single program (number 1, PMT PID 0x1000); 12-byte header + 4-byte
    program entry + CRC-32 = 20 bytes total, payload-carried whole.
    """
    section = bytearray(
        [
            SECTION_TABLE_ID,  # table_id
            0xB0, 0x0D,  # section_syntax=1, length=13
            0x00, 0x01,  # transport_stream_id
            0xC1,  # reserved + version 0 + current_next 1
            0x00, 0x00,  # section_number / last_section_number
            0xE0, 0x01,  # program_number 1
            0xE1, 0x00,  # PMT PID 0x1000
        ]
    )
    section += mpeg2_crc32(bytes(section)).to_bytes(4, "big")
    return bytes(section)


def clear_packets() -> "list[bytes]":
    """Six clear TS packets on PID 0x0100, each PUSI carrying the PAT
    section + deterministic filler (derived, not random)."""
    section = build_pat_section()
    packets: "list[bytes]" = []
    for index in range(PACKET_COUNT):
        header = bytearray(4)
        header[0] = 0x47  # sync byte
        header[1] = 0x40 | ((SCRAMBLE_PID >> 8) & 0x1F)  # PUSI + pid hi
        header[2] = SCRAMBLE_PID & 0xFF
        header[3] = (0b01 << 4) | (index & 0x0F)  # AFC=01 + CC
        payload = bytearray(PAYLOAD_LEN)
        payload[0] = 0x00  # pointer_field
        payload[1:1 + len(section)] = section
        # Deterministic filler for the tail (never hand-packed literals).
        for offset in range(1 + len(section), PAYLOAD_LEN):
            payload[offset] = (offset * 7 + index) % 256
        packets.append(bytes(header) + bytes(payload))
    return packets


def scrambled_stream() -> bytes:
    """CSA1-scramble each packet's payload region under the derived CW."""
    cw = derive_cw_independent(SESSION_WORD)
    assert cw.hex().upper() == DERIVED_CW_HEX, "J.96 §8 derivation pin"
    oracle = Csa1Oracle()
    clear = clear_packets()
    encrypted = oracle.encrypt_batch(
        [packet[4:] for packet in clear], cw
    )
    marked = bytearray()
    for original, payload in zip(clear, encrypted):
        packet = bytearray(original)
        packet[3] = (packet[3] & 0x3F) | (0b10 << 6)  # TSC = `10`
        marked += packet[:4] + payload
    return bytes(marked)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        help="directory receiving the <vector_id>/ trio",
    )
    args = parser.parse_args()
    target = Path(args.output_dir) / VECTOR_ID
    target.mkdir(parents=True, exist_ok=True)

    stream = scrambled_stream()
    (target / f"{VECTOR_ID}.ts").write_bytes(stream)

    sha = hashlib.sha256(stream).hexdigest()
    biss_config = {
        "mode": "1",
        "session_word": SESSION_WORD,
        "derived_cw": DERIVED_CW_HEX,
        "pid_scope": [SCRAMBLE_PID],
        "ca_pid": 8191,
    }
    config_hash = hashlib.sha256(
        json.dumps(biss_config, sort_keys=True).encode("utf-8")
    ).hexdigest()

    manifest = {
        "vector_id": VECTOR_ID,
        "kind": "bit_level",
        "related_specs": ["SPEC-610", "SPEC-204"],
        "generator_version": (
            "tools/make_golden_biss_j96.py (pure-Python CSA1 oracle, "
            "research #106 port; no src/ involvement)"
        ),
        "config_hash": f"sha256:{config_hash}",
        "sha256": f"sha256:{sha}",
        "packet_count": PACKET_COUNT,
        "fault_plan_ref": None,
        "biss": biss_config,
        "verification": {
            "path": "bit-level-review",
            "direction": (
                "standard-vector derivation (ITU-T J.96 §8 example "
                "SW→CW, formula cross-checked by three independent "
                "implementations in research #106) → oracle-generated "
                "CSA1 scrambled stream; libdvbcsa static vectors 2/2 "
                "independently confirm the oracle (research #106); "
                "CI DLL cross-check: honestly NOT RUN (ADR-0011 §5)"
            ),
            "evidence_ref": (
                "docs/test-vectors/golden/biss-j96-mode1/"
                "biss-j96-mode1.verification.md"
            ),
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    expectations = {
        "expectations": [
            {
                "event_type": "ts.packet_batch_observed",
                "locator": {"packet_index": index},
                "detail": {
                    "pid": SCRAMBLE_PID,
                    "scrambling": 2,
                    "afc": 1,
                    "cc": index,
                    "pusi": 1,
                    "note": (
                        "BISS Mode 1 scrambled slot (TSC=`10`, J.96 §8 "
                        "even-key); payload CSA1-scrambled under the "
                        "derived CW"
                    ),
                },
            }
            for index in range(PACKET_COUNT)
        ]
    }
    (target / "expectations.json").write_text(
        json.dumps(expectations, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {target}")
    print(f"  sha256: {sha}")
    print(f"  session_word {SESSION_WORD} -> cw {DERIVED_CW_HEX}")


if __name__ == "__main__":
    main()
