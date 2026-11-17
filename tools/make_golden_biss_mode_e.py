"""SPEC-506 §7 — golden vector ``biss-mode-e-derive`` constructor
(ticket #127, SPEC-611 §11).

L1 bit-level vector: one end-to-end BISS Mode E chain — Injected ID +
ESW → session word → control word → CISSA (BISS2) scramble roundtrip
over a deterministic TS packet set.

Independence discipline (SPEC-506 §5): no part of ``src/`` is imported
or consulted.  Every algorithm step is re-implemented inline in this
script from the published standards:

- the J.96 §9.3 ENCRYPT direction (the headend face the recommendation
  leaves open; the decrypt direction is what units implement — J.96
  §9.3.3): ``SW → SW'`` (middle-6-bits-per-byte fill; the dropped MSB is
  pinned to 0 and the dropped LSB to odd parity over the low 7 bits — a
  deterministic generator pin; the decrypt face ignores both bits, J.96
  Table 3), then ``ESW = DES-ECB-encrypt(Mapped Active ID, SW')`` with
  the §9.3.3 a / Table 2 odd-parity mapping;
- the J.96 §8 session-word → CW checksum formula (cross-checked by three
  independent implementations in research #106);
- the Tech 3292-s1 session-key pin: the DES key face consumes the low 56
  bits (trailing 14 hex characters) of the 128-bit Injected ID;
- the sandbox Mode E → CISSA composition pin: ``ciss_key = CW ‖ CW``
  (the 8-byte control word repeated into the 16-byte AES-128 key);
- the TS 103 127 §6.3 CISSA rules: AES-128-CBC, fixed IV
  ``0x445642544d4350544145534349535341`` (ASCII ``DVBTMCPTAESCISSA``),
  per-packet restart, ``encrypted_payload_size = payload − payload
  mod 16`` (no AF ⇒ 176 encrypted + 8 clear tail).

The crypto primitives come from pycryptodome (an external, independently
validated library — research #106 roundtrip evidence), NOT from the
runtime implementation, so the registered bytes cross-check
``src/ts/biss`` from the outside.

Vector constants: the session word is the ITU-T J.96 §8 example (a
public standard constant, also carried by ``biss-j96-mode1``); the
Injected ID is derived from a fixed ASCII label (deterministic, no key
material provenance).  These are synthetic vector constants, not runtime
key material.

Determinism (SPEC-506 §6): same script + same Python ⇒ same bytes.  The
vector is a frozen asset: the registered sha256 in ``manifest.json`` is
its identity; CI only verifies the sha (never regenerates).

Usage::

    python tools/make_golden_biss_mode_e.py --output-dir <dir>

writes ``<dir>/biss-mode-e-derive/{biss-mode-e-derive.ts, manifest.json,
expectations.json}`` (the SPEC-506 §3 trio).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from Crypto.Cipher import AES, DES

VECTOR_ID = "biss-mode-e-derive"
PACKET_SIZE = 188
PAYLOAD_LEN = 184

# --- declared vector constants (synthetic, documented above) ---------------------

#: The ITU-T J.96 §8 example session word (public standard constant).
SESSION_WORD = "A13DBC42908F"
#: The J.96 §8 checksum formula's derivation of SESSION_WORD.
DERIVED_CW_HEX = "A13DBC9A42908F61"

#: The 128-bit Injected ID — derived from a fixed ASCII label (not chosen
#: key material); the vector pins the result in the manifest.
INJECTED_ID_LABEL = "biss-mode-e-derive injected ID constant"
INJECTED_ID = hashlib.sha256(INJECTED_ID_LABEL.encode("utf-8")).hexdigest()[
    :32
].upper()

SCRAMBLE_PID = 0x0100
PACKET_COUNT = 6

#: TS 103 127 §6.3.1.2 fixed IV (public standard constant).
CISSA_IV = bytes.fromhex("445642544d4350544145534349535341")

#: PSI table id for the section carried by every packet (a PAT-shaped
#: section keeps the descramble structural self-check meaningful).
SECTION_TABLE_ID = 0x00


# --- J.96 §9.3 / §8 inline re-implementation (independent) ------------------------


def active_id(injected_id: str) -> bytes:
    """The DES key face: the low 56 bits (trailing 14 hex chars) of the
    128-bit Injected ID (the Tech 3292-s1 session-key sandbox pin)."""
    raw = bytes.fromhex(injected_id)
    assert len(raw) == 16, "the Injected ID is 128 bit (32 hex chars)"
    return raw[-7:]


def map_active_id(active: bytes) -> bytes:
    """J.96 §9.3.3 a / Table 2: 56 bits into the upper 7 bits of 8
    bytes; each byte's LSB set for odd parity."""
    assert len(active) == 7
    value = int.from_bytes(active, "big")
    mapped = bytearray(8)
    for index in range(8):
        seven_bits = (value >> (56 - 7 * (index + 1))) & 0x7F
        byte_value = seven_bits << 1
        if bin(byte_value).count("1") % 2 == 0:
            byte_value |= 0x01
        mapped[index] = byte_value
    return bytes(mapped)


def session_word_to_sw_prime(session_word: str) -> bytes:
    """``SW → SW'`` — the encrypt-side expansion (J.96 Table 3 inverse).

    Each byte carries the next 6 SW bits in bits 6..1; the dropped MSB is
    pinned to 0 and the dropped LSB to odd parity over the low 7 bits
    (the generator's deterministic pin — the decrypt face ignores both).
    """
    value = int(session_word, 16)
    assert 0 <= value < (1 << 48), "the session word is 48 bit (12 hex)"
    block = bytearray(8)
    for index in range(8):
        low7 = ((value >> (42 - 6 * index)) & 0x3F) << 1  # MSB = 0
        if bin(low7).count("1") % 2 == 0:
            low7 |= 0x01
        block[index] = low7
    return bytes(block)


def encrypt_esw(injected_id: str, session_word: str) -> str:
    """The headend face: ``ESW = DES-ECB-encrypt(Mapped Active ID, SW')``."""
    key = map_active_id(active_id(injected_id))
    block = session_word_to_sw_prime(session_word)
    return DES.new(key, DES.MODE_ECB).encrypt(block).hex().upper()


def derive_cw_independent(session_word: str) -> bytes:
    """The Tech 3292/J.96 §8 checksum formula, re-implemented inline.

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


# --- TS 103 127 §6.3 CISSA rules (inline, pycryptodome primitives) ----------------


def cissa_encrypt_payload(payload: bytes, ciss_key: bytes) -> bytes:
    """One packet's payload region: AES-128-CBC with the fixed IV over
    ``payload − payload mod 16`` bytes; the tail stays clear; the CBC
    chain restarts per packet (fresh cipher object)."""
    encrypted_size = len(payload) - len(payload) % 16
    if encrypted_size == 0:
        return payload
    cipher = AES.new(ciss_key, AES.MODE_CBC, iv=CISSA_IV)
    return cipher.encrypt(payload[:encrypted_size]) + payload[
        encrypted_size:
    ]


# --- independent MPEG-2 CRC-32 (ISO 13818-1 annex A) -------------------------------

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
    """The Mode E chain end-to-end, then CISSA per packet (§6.3.2)."""
    esw_hex = encrypt_esw(INJECTED_ID, SESSION_WORD)
    # Decrypt-direction pin: J.96 §9.3 unit face recovers the SW exactly
    # (the registered chain is an encrypt/decrypt roundtrip).
    key = map_active_id(active_id(INJECTED_ID))
    sw_prime = DES.new(key, DES.MODE_ECB).decrypt(bytes.fromhex(esw_hex))
    recovered = 0
    for byte in sw_prime:
        recovered = (recovered << 6) | ((byte >> 1) & 0x3F)
    assert f"{recovered:012X}" == SESSION_WORD, "J.96 §9.3 roundtrip pin"

    cw = derive_cw_independent(SESSION_WORD)
    assert cw.hex().upper() == DERIVED_CW_HEX, "J.96 §8 derivation pin"
    ciss_key = cw + cw  # the sandbox Mode E → CISSA composition pin
    assert len(ciss_key) == 16

    clear = clear_packets()
    marked = bytearray()
    for index, packet in enumerate(clear):
        payload = cissa_encrypt_payload(packet[4:], ciss_key)
        out = bytearray(packet[:4])
        out[3] = (out[3] & 0x3F) | (0b10 << 6)  # TSC = `10` (BISS marker)
        encrypted_size = len(payload) - len(payload) % 16
        assert encrypted_size == 176, "TS 103 127 §6.3.2 example 1 pin"
        assert payload[176:] == clear[index][4:][176:], "clear-tail pin"
        marked += out + payload
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

    esw_hex = encrypt_esw(INJECTED_ID, SESSION_WORD)
    stream = scrambled_stream()
    (target / f"{VECTOR_ID}.ts").write_bytes(stream)

    sha = hashlib.sha256(stream).hexdigest()
    biss_config = {
        "mode": "E",
        "encrypted_sw": esw_hex,
        "injected_id": INJECTED_ID,
        "derived_session_word": SESSION_WORD,
        "derived_cw": DERIVED_CW_HEX,
        "ciss_key_composition": "CW‖CW (sandbox Mode E → CISSA pin)",
        "pid_scope": [SCRAMBLE_PID],
        "ca_pid": 8191,
        "ca_system_id": 9730,
    }
    config_hash = hashlib.sha256(
        json.dumps(biss_config, sort_keys=True).encode("utf-8")
    ).hexdigest()

    manifest = {
        "vector_id": VECTOR_ID,
        "kind": "bit_level",
        "related_specs": ["SPEC-611", "SPEC-610", "SPEC-204"],
        "generator_version": (
            "tools/make_golden_biss_mode_e.py (J.96 §9.3/§8 + TS 103 127 "
            "§6.3 inline re-implementation; pycryptodome primitives; no "
            "src/ involvement)"
        ),
        "config_hash": f"sha256:{config_hash}",
        "sha256": f"sha256:{sha}",
        "packet_count": PACKET_COUNT,
        "fault_plan_ref": None,
        "biss": biss_config,
        "verification": {
            "path": "bit-level-review",
            "direction": (
                "standard-algorithm chain (ITU-T J.96 §9.3 DES-ECB Mode E "
                "derivation with the §9.3.3 a odd-parity mapping + §8 "
                "checksum formula, cross-checked by three independent "
                "implementations in research #106; ETSI TS 103 127 §6.3 "
                "CISSA AES-128-CBC fixed-IV per-packet rules) → "
                "pycryptodome-generated scrambled stream; the runtime "
                "implementation is cross-checked against the registered "
                "bytes in the conformance suite; no DLL dependency face"
            ),
            "evidence_ref": (
                "docs/test-vectors/golden/biss-mode-e-derive/"
                "biss-mode-e-derive.verification.md"
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
                        "BISS Mode E scrambled slot (TSC=`10`, BISS "
                        "marker); payload CISSA-scrambled (TS 103 127 "
                        "§6.3) under the key composed from the J.96 §9.3 "
                        "derived chain"
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
    print(f"  injected_id: {INJECTED_ID}")
    print(f"  encrypted_sw: {esw_hex}")
    print(f"  session_word {SESSION_WORD} -> cw {DERIVED_CW_HEX}")


if __name__ == "__main__":
    main()
