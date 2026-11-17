"""BISS Mode 1 — session word → control word derivation, key fingerprints
and the scramble/descramble packet primitives (SPEC-610, ticket #126).

Key model (SPEC-610 §5 / ADR-0011 §3): a BISS Mode 1 session word is a
48-bit key spelled as **12 hexadecimal characters** (NOT the outdated
"16-byte key" wording).  The 64-bit control word is derived from the
session word by the Tech 3292 / ITU-T J.96 checksum formula (three
independent implementations cross-checked in research #106)::

    CW[0..2] = SW bytes 0..2
    CW[3]    = (CW[0] + CW[1] + CW[2]) mod 256
    CW[4..6] = SW bytes 3..5
    CW[7]    = (CW[4] + CW[5] + CW[6]) mod 256

Pinned by the J.96 §8 example vector: SW ``A13DBC42908F`` → CW
``A13DBC9A42908F61`` (registered golden ``biss-j96-mode1``).

Mode 1 defines ONE control word; the packet TSC bit is pinned to ``10``
(the even-key slot, J.96 §8.1).  :func:`derive_cw` returns the same
derived CW for both parity positions so the odd/even interface shape is
stable for the CSA core.

Key discipline (SPEC-610 §9, hard red line): key material never enters
the mutation log, journal events, artifacts or assertions — only the
:func:`key_fingerprint` hash prefix does.

The CSA1 payload transform is backend-injected: ``ts`` stays pure (no
adapter imports, ADR-0005 D4-1) and callers hand in an object satisfying
:class:`BatchCipherBackend` — the production backend is the dlopen
adapter :mod:`adapters.dvbcsa` (wired by the scrambler filter /
composition root), the CI oracle is the pure-Python CSA1 fixture in
``tests/_support/csa1_oracle.py`` (never a runtime path, ADR-0011 §1).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Callable, Protocol, Sequence

from ts.crc import verify_mpeg2_crc32
from ts.packet import TSPacket

__all__ = [
    "BISS_SCRAMBLE_APPLIED_EVENT",
    "BISS_DESCRAMBLE_FAILED_EVENT",
    "CA_SYSTEM_ID_BISS_MODE_1",
    "CA_PID_BISS",
    "SESSION_WORD_CHARS",
    "SESSION_WORD_BYTES",
    "TSC_EVEN_KEY",
    "TRANSPORT_SCRAMBLED_TSC",
    "SELF_CHECK_TSC_STATE",
    "SELF_CHECK_PSI_CRC32",
    "SELF_CHECK_OPAQUE",
    "SELF_CHECK_STRUCTURE",
    "FAILED_INDICES_SAMPLE_LIMIT",
    "BatchCipherBackend",
    "DescrambleSelfCheck",
    "derive_cw",
    "key_fingerprint",
    "parse_session_word",
    "scramble",
    "descramble",
    "unseen_pid_scope",
]

# --- wire constants (SPEC-610 §5 / Tech 3292) -----------------------------------

#: Event type constants — the reserved emission seam (ruling §10-7).
#: Registration in the domain observation registry lands with #129; until
#: then these constants are consumed only through the injectable emitter
#: hooks (unit tests with mock emitters; end-to-end delivery is #128/#129).
BISS_SCRAMBLE_APPLIED_EVENT = "biss.scramble_applied"
BISS_DESCRAMBLE_FAILED_EVENT = "biss.descramble_failed"

#: BISS carries no ECM/EMM (Tech 3292): CA_system_ID 0x2600 for Mode 1 and
#: the fixed CA_PID 0x1FFF.  Signaling metadata — declared, not delivered.
CA_SYSTEM_ID_BISS_MODE_1 = 0x2600
CA_PID_BISS = 0x1FFF

#: Session word wire shape: 12 hex chars = 48 bit (roadmap §4 C1 口径).
SESSION_WORD_CHARS = 12
SESSION_WORD_BYTES = 6

#: Transport scrambling control values this mode uses: packets scrambled
#: under BISS Mode 1 carry TSC = ``10`` (the even-key slot, J.96 §8.1 —
#: Mode 1 only defines the even key); descrambled (clear) packets carry 0.
TSC_EVEN_KEY = 0b10
TRANSPORT_SCRAMBLED_TSC = TSC_EVEN_KEY

#: Structural self-check kinds for :func:`descramble` (SPEC-610 §3/§7:
#: 解扰后结构自检 = 解扰失败证据形态).
SELF_CHECK_TSC_STATE = "tsc_state"
SELF_CHECK_PSI_CRC32 = "psi_section_crc32"
SELF_CHECK_OPAQUE = "opaque_payload"
SELF_CHECK_STRUCTURE = "payload_structure"

#: PSI table ids whose sections carry the MPEG-2 CRC-32 (ISO 13818-1
#: §2.4.4.10-ish subset the sandbox traffic uses; wrong-key descrambles
#: overwhelmingly land outside this set, which is itself evidence).
_PSI_CRC_TABLE_IDS = frozenset(
    {
        0x00,  # PAT
        0x01,  # CAT
        0x02,  # PMT
        0x03,  # TSDT
        0x04,  # 13818-1 §2.5.3 reserved downstream set
        0x42,  # SDT (actual TS)
        0x4E,  # EIT (present/following, this TS)
        0x14,  # network/program stream map family
        0x72,  # reserved downstream set
    }
)

#: PES start-code prefix (ISO 13818-1 §2.4.3.6) — a PUSI payload starting
#: with it is a PES packet: no integrity field, honestly opaque.
_PES_START_PREFIX = b"\x00\x00\x01"

#: Cap on ``failed_indices_sample`` so the evidence payload stays bounded.
FAILED_INDICES_SAMPLE_LIMIT = 16


class BatchCipherBackend(Protocol):
    """CSA1 payload-transform backend injected into this module.

    Structural protocol (no import edge): the production implementation
    is :class:`adapters.dvbcsa.DvbcsaBatchCipher` (dlopen libdvbcsa SSE2
    batch API); the test oracle is the pure-Python CSA1 fixture.  Each
    payload is one TS packet payload region (≤184 bytes); the transform
    is per-packet independent (no cross-packet chaining — the 等位替换
    invariant holds at the BISS layer).
    """

    def encrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> tuple[bytes, ...]: ...

    def decrypt_batch(
        self, payloads: Sequence[bytes], cw: bytes
    ) -> tuple[bytes, ...]: ...


# --- key face --------------------------------------------------------------------


def parse_session_word(session_word: "str | bytes") -> bytes:
    """Normalize a session word to its 6 key bytes; reject bad shapes.

    Accepts a 12-hex-character string (any case) or 6 raw bytes — the two
    wire shapes BISS Mode 1 keys travel in.  A malformed session word is a
    prepare-time rejection (SPEC-610 §8), so this raises ``ValueError``.
    """
    if isinstance(session_word, str):
        text = session_word.strip()
        if len(text) != SESSION_WORD_CHARS:
            raise ValueError(
                f"BISS session word must be {SESSION_WORD_CHARS} hex "
                f"characters (48 bit), got {len(text)} characters"
            )
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            raise ValueError(
                "BISS session word must be 12 hex characters, got "
                "non-hex content"
            ) from None
        return raw
    if isinstance(session_word, (bytes, bytearray)):
        raw = bytes(session_word)
        if len(raw) != SESSION_WORD_BYTES:
            raise ValueError(
                f"BISS session word must be {SESSION_WORD_BYTES} bytes "
                f"(48 bit), got {len(raw)} bytes"
            )
        return raw
    raise ValueError(
        "BISS session word must be a 12-hex-character string or 6 bytes, "
        f"got {type(session_word).__name__}"
    )


def derive_cw(session_word: "str | bytes") -> "tuple[bytes, bytes]":
    """Derive the 64-bit control word from a session word.

    Returns ``(odd_cw, even_cw)`` — BISS Mode 1 defines a single control
    word (J.96 §8; the packet TSC bit is pinned to ``10``), so both parity
    positions carry the identical derived CW.
    """
    sw = parse_session_word(session_word)
    cw = bytearray(8)
    cw[0:3] = sw[0:3]
    cw[3] = (cw[0] + cw[1] + cw[2]) % 256
    cw[4:7] = sw[3:6]
    cw[7] = (cw[4] + cw[5] + cw[6]) % 256
    derived = bytes(cw)
    return derived, derived


def key_fingerprint(key: "str | bytes") -> str:
    """The key's fingerprint: a SHA-256 hex prefix (SPEC-610 §5/§9).

    The ONLY key trace allowed in mutation logs and ``biss.*`` events.
    Hex-string keys are normalized case-insensitively first, so the same
    key spelled in different case yields the same fingerprint.
    """
    raw = parse_session_word(key)
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest[:16]}"


# --- scramble / descramble primitives -------------------------------------------


@dataclass(frozen=True)
class DescrambleSelfCheck:
    """One packet's structural self-check result (SPEC-610 §6/§7).

    ``ok=False`` entries are the 解扰失败 evidence shape — candidates, not
    facts (解扰失败 ≠ 码流损坏; the diagnosis rule linkage is SPEC-307).
    """

    index: int
    pid: int
    self_check_kind: str
    ok: bool
    detail: str


def _normalize_pid_scope(pid_scope: Sequence[int]) -> "frozenset[int]":
    scope = frozenset(pid_scope)
    if not scope:
        raise ValueError(
            "pid_scope must be a non-empty collection of 13-bit PIDs"
        )
    for pid in scope:
        if isinstance(pid, bool) or not isinstance(pid, int) or not (
            0 <= pid <= 0x1FFF
        ):
            raise ValueError(
                f"pid_scope entries must be 13-bit ints (0..0x1FFF), got "
                f"{pid!r}"
            )
    return scope


def unseen_pid_scope(
    packets: Sequence[TSPacket], pid_scope: Sequence[int]
) -> "frozenset[int]":
    """Declared pids absent from the packet stream (SPEC-610 §8 裁量面).

    pid_scope 含不存在 PID 的显式警告态: prepare-time wiring (composition
    root / #128) calls this and surfaces the result as an explicit
    warning — silence would be the dishonest option.
    """
    scope = _normalize_pid_scope(pid_scope)
    present = {packet.pid for packet in packets}
    return frozenset(scope - present)


def _scramblable(
    packets: Sequence[TSPacket], scope: "frozenset[int]"
) -> "list[tuple[int, TSPacket]]":
    """In-scope packets that carry a payload region to transform.

    Adaptation-only slots (``payload is None``) carry no payload region —
    nothing to transform, honestly untouched (and never TSC-marked).
    """
    return [
        (index, packet)
        for index, packet in enumerate(packets)
        if packet.pid in scope and packet.payload is not None
    ]


def scramble(
    packets: Sequence[TSPacket],
    session_word: "str | bytes",
    pid_scope: Sequence[int],
    *,
    backend: BatchCipherBackend,
    on_scramble_applied: "Callable[[dict[str, object]], None] | None" = None,
) -> "tuple[TSPacket, ...]":
    """BISS Mode 1 scramble: per-packet payload transform (SPEC-610 §6).

    Deterministic; slot-preserving (same count/order/188-byte slots);
    header 4 bytes stay clear; in-scope packets carry TSC = ``10`` (J.96
    §8.1 even-key slot); out-of-scope packets pass through untouched.

    ``on_scramble_applied`` is the reserved ``biss.scramble_applied``
    emission seam (ruling §10-7): called at most once with the payload
    ``{pid_scope, packet_count, key_fingerprint, mutation_log_ref}``
    (``mutation_log_ref`` is ``None`` here — the artifact binding is
    resolved by the runtime wiring, #128).
    """
    scope = _normalize_pid_scope(pid_scope)
    cw = derive_cw(session_word)[1]
    targets = _scramblable(packets, scope)
    encrypted = backend.encrypt_batch(
        [packet.payload for _, packet in targets], cw
    )
    transformed = {
        index: replace(
            packet,
            payload=payload,
            transport_scrambling_control=TSC_EVEN_KEY,
        )
        for (index, packet), payload in zip(targets, encrypted)
    }
    scrambled = tuple(
        transformed.get(index, packet) for index, packet in enumerate(packets)
    )
    if on_scramble_applied is not None:
        on_scramble_applied(
            {
                "pid_scope": sorted(scope),
                "packet_count": len(targets),
                "key_fingerprint": key_fingerprint(session_word),
                "mutation_log_ref": None,
            }
        )
    return scrambled


def descramble(
    packets: Sequence[TSPacket],
    session_word: "str | bytes",
    pid_scope: Sequence[int],
    *,
    backend: BatchCipherBackend,
    on_descramble_failed: "Callable[[dict[str, object]], None] | None" = None,
) -> "tuple[tuple[TSPacket, ...], tuple[DescrambleSelfCheck, ...]]":
    """BISS Mode 1 descramble + per-packet structural self-check.

    Returns ``(packets, self_check_results)`` (SPEC-610 §6): in-scope
    scrambled packets are decrypted with the declared key, their TSC
    reset to clear, and their structure checked:

    - ``tsc_state`` — the packet must actually carry TSC ``10`` (a clear
      packet in scope is an explicit evidence state, never silent);
    - PUSI payloads must parse as a PES packet (start-code prefix, no
      integrity field → honestly opaque) or as a PSI section with a known
      CRC-protected table id — where the MPEG-2 CRC-32 verdict is the
      self-check;
    - non-PUSI continuation payloads have no structural anchor →
      honestly opaque.

    Failures are the 解扰失败 evidence shape (candidates ≠ facts).  When
    any check fails, ``on_descramble_failed`` (the reserved
    ``biss.descramble_failed`` seam, ruling §10-7) fires once with
    ``{pid_scope, failed_indices_sample, self_check_kind,
    key_fingerprint_ref}``.
    """
    scope = _normalize_pid_scope(pid_scope)
    cw = derive_cw(session_word)[1]

    checks: list[DescrambleSelfCheck] = []
    decrypted: dict[int, bytes] = {}
    prechecked: list[tuple[int, TSPacket]] = []
    for index, packet in enumerate(packets):
        if packet.pid not in scope or packet.payload is None:
            continue
        if packet.transport_scrambling_control != TSC_EVEN_KEY:
            checks.append(
                DescrambleSelfCheck(
                    index=index,
                    pid=packet.pid,
                    self_check_kind=SELF_CHECK_TSC_STATE,
                    ok=False,
                    detail=(
                        "in-scope packet does not carry the BISS Mode 1 "
                        "scrambled TSC (10) — nothing descrambled"
                    ),
                )
            )
            continue
        prechecked.append((index, packet))
        decrypted[index] = packet.payload

    if prechecked:
        plain_payloads = backend.decrypt_batch(
            [packet.payload for _, packet in prechecked], cw
        )
        for (index, packet), plain in zip(prechecked, plain_payloads):
            ok, kind, detail = _self_check_pusi(packet, plain)
            checks.append(
                DescrambleSelfCheck(
                    index=index, pid=packet.pid, self_check_kind=kind,
                    ok=ok, detail=detail,
                )
            )
            decrypted[index] = plain

    def rebuild(packet: TSPacket, index: int) -> TSPacket:
        if index not in decrypted:
            return packet
        return replace(
            packet,
            payload=decrypted[index],
            transport_scrambling_control=0,
        )

    clear = tuple(
        rebuild(packet, index) for index, packet in enumerate(packets)
    )

    failures = [check for check in checks if not check.ok]
    if failures and on_descramble_failed is not None:
        on_descramble_failed(
            {
                "pid_scope": sorted(scope),
                "failed_indices_sample": [
                    check.index for check in failures
                ][:FAILED_INDICES_SAMPLE_LIMIT],
                "self_check_kind": failures[0].self_check_kind,
                "key_fingerprint_ref": key_fingerprint(session_word),
            }
        )
    return clear, tuple(checks)


def _self_check_pusi(
    packet: TSPacket, plain: bytes
) -> "tuple[bool, str, str]":
    """Structural verdict over one descrambled payload (SPEC-610 §7)."""
    if plain[:3] == _PES_START_PREFIX:
        return True, SELF_CHECK_OPAQUE, "PES start code — no integrity field"
    if not packet.payload_unit_start_indicator:
        return (
            True,
            SELF_CHECK_OPAQUE,
            "non-PUSI continuation payload has no structural anchor",
        )
    if len(plain) < 4:
        return False, SELF_CHECK_STRUCTURE, "PUSI payload truncated"
    pointer = plain[0]
    start = 1 + pointer
    if start + 3 > len(plain):
        return (
            False,
            SELF_CHECK_STRUCTURE,
            "pointer_field beyond the payload region",
        )
    table_id = plain[start]
    if table_id not in _PSI_CRC_TABLE_IDS:
        return (
            False,
            SELF_CHECK_STRUCTURE,
            f"PUSI payload is neither PES nor a CRC-protected PSI "
            f"section (table_id {table_id:#04x} unrecognized)",
        )
    section_length = ((plain[start + 1] & 0x0F) << 8) | plain[start + 2]
    section_end = start + 3 + section_length
    if section_end > len(plain):
        return (
            False,
            SELF_CHECK_STRUCTURE,
            "section_length beyond the payload region",
        )
    ok = verify_mpeg2_crc32(plain[start:section_end])
    return (
        ok,
        SELF_CHECK_PSI_CRC32,
        "PSI section CRC-32 valid" if ok else "PSI section CRC-32 invalid",
    )
