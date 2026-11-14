"""Deterministic test-data constructors — sanctioned source 2 (SPEC-505 §6).

测试数据纪律：TS/位级字节只允许来自 (1) SPEC-506 登记 golden、(2) 固定
seed 确定性场景生成器（本模块）、(3) 入库资产。禁手拼字节字面量。

Stability contract: built on ``random.Random`` Mersenne Twister primitives
(``randbytes`` = documented ``getrandbits`` equivalent), which CPython keeps
stable across versions for a given seed — same seed + same parameters ⇒
same bytes, on any platform (CONTEXT.md 确定性复现, SPEC-201).

Scope note: this is the scaffold-stage sanctioned constructor zone for tests
that need opaque, correctly-framed byte material. It is NOT a substitute for
SPEC-100/108 business constructors or registered golden assets; business
tests migrate to src constructors / ``golden_loader`` once those land
(ticket #22 report records the seam).
"""

from __future__ import annotations

import hashlib
import random

#: MPEG-TS packet framing constants (SPEC-100); used here purely as stream
#: framing for deterministic test material — packet *semantics* stay in src.
SYNC_BYTE: int = 0x47
PACKET_SIZE: int = 188

#: Seed domain per SPEC-200 (``seed: int  # uint64``).
SEED_MIN: int = 0
SEED_MAX: int = 2**64 - 1


def check_seed(seed: int) -> int:
    """Validate the SPEC-200 seed domain (uint64); returns the seed.

    Public single source of truth for seed-domain validation, shared by the
    deterministic constructors and the session/run factory.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"seed must be int, got {type(seed).__name__}")
    if not SEED_MIN <= seed <= SEED_MAX:
        raise ValueError(
            f"seed out of uint64 domain per SPEC-200: {seed!r} "
            f"(allowed {SEED_MIN}..{SEED_MAX})"
        )
    return seed


def seeded_bytes(seed: int, length: int) -> bytes:
    """Deterministic bytes of ``length`` derived from ``seed``.

    Append-stable: prefixes of longer generations match shorter ones.
    """
    check_seed(seed)
    if length < 0:
        raise ValueError(f"length must be >= 0, got {length}")
    rng = random.Random(seed)
    return rng.randbytes(length)


def seeded_ts_stream(seed: int, packet_count: int) -> bytes:
    """Deterministic 188-byte framed stream with sync byte at every slot.

    Payload bytes come from the seeded generator; the sync byte is stamped
    at every ``PACKET_SIZE`` boundary so framing-sensitive tests (splitting,
    buffering, multi-packet windows) have honest material.
    """
    check_seed(seed)
    if packet_count < 0:
        raise ValueError(f"packet_count must be >= 0, got {packet_count}")
    stream = bytearray(seeded_bytes(seed, packet_count * PACKET_SIZE))
    for index in range(packet_count):
        stream[index * PACKET_SIZE] = SYNC_BYTE
    return bytes(stream)


def stream_sha256(seed: int, packet_count: int) -> str:
    """sha256 hex digest of the deterministic stream (determinism probes)."""
    return hashlib.sha256(seeded_ts_stream(seed, packet_count)).hexdigest()
