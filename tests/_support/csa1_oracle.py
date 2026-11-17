"""Pure-Python DVB-CSA1 oracle — CI correctness fixture (ticket #126).

A faithful port of the libdvbcsa single-packet path (dvbcsa_key.c /
dvbcsa_block.c / dvbcsa_stream.c / dvbcsa_algo.c) produced by research
ticket #106 and vector-checked there against libdvbcsa's own static test
vectors (2 enc + 2 dec PASS, generic DLL and pure-Python mutually
confirmed).

Purpose and hard boundary (ADR-0011 §1, SPEC-610 §9): pure-Python CSA1
measured ~0.305 Mbps — **forbidden on any runtime path**; this module
exists ONLY as the CI correctness oracle for :mod:`ts.biss.biss1` and the
:class:`adapters.dvbcsa.DvbcsaBatchCipher` binding (正确性对拍, 性能无关)
and for generating the independent ``biss-j96-mode1`` golden bytes via
``tools/make_golden_biss_j96.py``.

It satisfies the :class:`ts.biss.biss1.BatchCipherBackend` structural
protocol so it can be injected wherever the production dlopen backend
would go.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from tests._support.csa1_tables import (
    BLOCK_PERM,
    BLOCK_SBOX,
    KPERM,
    STREAM_CDEF,
    STREAM_OUT,
    STREAM_SBOX,
)

KEYSBUFF = 56  # DVBCSA_KEYSBUFF_SIZE
MASK64 = 0xFFFFFFFFFFFFFFFF


def load_csa1_static_vectors() -> "list[tuple[bytes, bytes, bytes]]":
    """The libdvbcsa static vectors (checked-in tests/data asset).

    Each entry is ``(control_word, scrambled_payload, plaintext)`` with a
    184-byte payload — the independent truth for both this oracle and the
    DLL binding tests.
    """
    vectors_path = (
        Path(__file__).resolve().parent.parent / "data" / "biss" /
        "csa1_static_vectors.json"
    )
    document = json.loads(vectors_path.read_text(encoding="utf-8"))
    return [
        (
            bytes.fromhex(entry["cw"]),
            bytes.fromhex(entry["scrambled"]),
            bytes.fromhex(entry["plaintext"]),
        )
        for entry in document["vectors"]
    ]


# ---------------------------------------------------------------- key schedule


def _key_permute_block(k: int) -> int:
    n = 0
    for i in range(8):
        n |= KPERM[i * 256 + (k & 0xFF)]
        k >>= 8
    return n


def _key_schedule_block(cw: bytes) -> bytes:
    """cw: 8 bytes -> 56 round-key bytes."""
    k = [0] * 7
    k[6] = int.from_bytes(cw, "little")
    for i in range(6, 0, -1):
        k[i - 1] = _key_permute_block(k[i])
    kk = bytearray(KEYSBUFF)
    for i in range(7):
        for j in range(8):
            kk[i * 8 + j] = ((k[i] >> (j * 8)) & 0xFF) ^ i
    return bytes(kk)


def key_set(cw: bytes) -> "tuple[bytes, bytes]":
    """Expanded key: (stream-cipher word schedule, block schedule)."""
    k = int.from_bytes(cw, "little")
    cws = bytes(((b >> 4) | (b << 4)) & 0xFF for b in cw)
    return cws, _key_schedule_block(cw)


# ------------------------------------------------------------- block cipher


def _block_decrypt(sch: bytes, w: bytes) -> bytes:
    w = bytearray(w)
    for i in range(KEYSBUFF - 1, -1, -1):
        s = BLOCK_SBOX[sch[i] ^ w[6]]
        low = w[7] ^ s
        w[7] = w[6]
        w[6] = w[5] ^ BLOCK_PERM[s]
        w[5] = w[4]
        w[4] = w[3] ^ low
        w[3] = w[2] ^ low
        w[2] = w[1] ^ low
        w[1] = w[0]
        w[0] = low
    return bytes(w)


def _block_encrypt(sch: bytes, w: bytes) -> bytes:
    w = bytearray(w)
    for i in range(KEYSBUFF):
        s = BLOCK_SBOX[sch[i] ^ w[7]]
        low = w[1]
        w[1] = w[2] ^ w[0]
        w[2] = w[3] ^ w[0]
        w[3] = w[4] ^ w[0]
        w[4] = w[5]
        w[5] = w[6] ^ BLOCK_PERM[s]
        w[6] = w[7]
        w[7] = w[0] ^ s
        w[0] = low
    return bytes(w)


# ------------------------------------------------------------- stream cipher


def _stream_sboxes(a: int) -> int:
    res = 0
    for idx, mask, shifts in (
        (1, 0x2018004200, (37, 27, 25, 11, 5)),
        (4, 0x4201480000, (38, 32, 22, 16, 18)),
        (5, 0x8040122000, (39, 29, 18, 14, 9)),
        (0, 0x1082010040, (36, 30, 23, 3, 12)),
        (2, 0x0004A00180, (26, 22, 19, 5, 3)),
        (3, 0x0100048820, (32, 17, 9, 2, 11)),
        (6, 0x0C20001400, (35, 33, 27, 9, 6)),
    ):
        t = a & mask
        acc = 0
        for s in shifts:
            acc ^= (t >> s) & 0x1F
        res |= STREAM_SBOX[idx * 32 + acc]
    return res


def _stream_b_sel(b: int) -> int:
    t = b >> 9
    return (
        (((t) ^ (t >> 27)) & 0x8)
        ^ (((t >> 18)) & 0x9)
        ^ (((t >> 22) ^ (t >> 7)) & 0x4)
        ^ (((t >> 4)) & 0x5)
        ^ (((t >> 24) ^ (t >> 6) ^ (t >> 11)) & 0x2)
        ^ (((t >> 29) ^ (t >> 23)) & 0x1)
        ^ (((t >> 13)) & 0xE)
    )


def _stream_cfed(pqzyx: int, cfed: int) -> int:
    return ((cfed & 0x0F00) >> 4) | STREAM_CDEF[
        ((cfed & 0x10FF) | (pqzyx & 0x2F00)) >> 4
    ]


def _stream_init_round(iv: int, a: int, b: int, pqzyx: int, cfed: int):
    a = (a << 4) & MASK64
    a |= ((a >> 40) ^ (pqzyx & 0xF) ^ (cfed & 0xF) ^ (iv >> 4)) & 0x0F
    tmp = ((b >> 24) ^ (b >> 36) ^ ((pqzyx >> 4) & 0xF) ^ iv) & 0x0F
    if pqzyx & 0x1000:
        tmp = ((tmp << 1) | ((tmp >> 3) & 1)) & 0xF
    b = (b << 4) & MASK64
    b |= tmp
    cfed = _stream_cfed(pqzyx, cfed) ^ _stream_b_sel(b)
    pqzyx = _stream_sboxes(a)
    return a, b, pqzyx, cfed


def _stream_round(a: int, b: int, pqzyx: int, cfed: int):
    a = (a << 4) & MASK64
    a |= ((a >> 40) ^ (pqzyx & 0xF)) & 0xF
    tmp = ((b >> 24) ^ (b >> 36) ^ ((pqzyx >> 4) & 0xF)) & 0xF
    if pqzyx & 0x1000:
        tmp = ((tmp << 1) | ((tmp >> 3) & 1)) & 0xF
    b = (b << 4) & MASK64
    b |= tmp
    cfed = _stream_cfed(pqzyx, cfed) ^ _stream_b_sel(b)
    pqzyx = _stream_sboxes(a)
    return a, b, pqzyx, cfed


def _stream_xor(cws: bytes, iv: bytes, data: bytearray, start: int, end: int):
    a = int.from_bytes(cws[0:4], "little")
    b = int.from_bytes(cws[4:8], "little")
    pqzyx = 0
    cfed = 0
    for byte in iv:
        for v in (byte, ((byte >> 4) | (byte << 4)) & 0xFF, byte,
                  ((byte >> 4) | (byte << 4)) & 0xFF):
            a, b, pqzyx, cfed = _stream_init_round(v, a, b, pqzyx, cfed)
    for i in range(start, end):
        for mask in (0xC0, 0x30, 0x0C, 0x03):
            a, b, pqzyx, cfed = _stream_round(a, b, pqzyx, cfed)
            data[i] ^= STREAM_OUT[cfed & 0xF] & mask


# ----------------------------------------------------------------- full CSA


def dvbcsa_encrypt(cws: bytes, sch: bytes, data: bytearray) -> None:
    """CSA1 encrypt one payload in place (len ≤ 184, libdvbcsa semantics)."""
    n = len(data)
    alen = n & ~7
    w = data[alen - 8:alen]
    data[alen - 8:alen] = _block_encrypt(sch, w)
    for i in range(alen - 16, -1, -8):
        for j in range(8):
            data[i + j] ^= data[i + 8 + j]
        data[i:i + 8] = _block_encrypt(sch, data[i:i + 8])
    _stream_xor(cws, data[0:8], data, 8, n)


def dvbcsa_decrypt(cws: bytes, sch: bytes, data: bytearray) -> None:
    """CSA1 decrypt one payload in place (len ≤ 184, libdvbcsa semantics)."""
    n = len(data)
    alen = n & ~7
    _stream_xor(cws, data[0:8], data, 8, n)
    data[0:8] = _block_decrypt(sch, data[0:8])
    for i in range(8, alen, 8):
        for j in range(8):
            data[i - 8 + j] ^= data[i + j]
        data[i:i + 8] = _block_decrypt(sch, data[i:i + 8])


class Csa1Oracle:
    """BatchCipherBackend-shaped pure-Python CSA1 (test oracle only).

    Implements the same per-packet independent transform as the
    libdvbcsa batch API: every payload is processed standalone with the
    given control word — no cross-packet chaining.
    """

    def encrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> "tuple[bytes, ...]":
        cws, sch = key_set(cw)
        return tuple(
            self._transform(payloads_item, cws, sch, dvbcsa_encrypt)
            for payloads_item in payloads
        )

    def decrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> "tuple[bytes, ...]":
        cws, sch = key_set(cw)
        return tuple(
            self._transform(payloads_item, cws, sch, dvbcsa_decrypt)
            for payloads_item in payloads
        )

    @staticmethod
    def _transform(payload: bytes, cws: bytes, sch: bytes, fn) -> bytes:
        buf = bytearray(payload)
        fn(cws, sch, buf)
        return bytes(buf)
