"""BISS2 CISSA — the DVB-CISSA AES-128 scramble/descramble packet
primitives (SPEC-611 §6/§7, ETSI TS 103 127 §6.3, ticket #127).

Algorithm face (TS 103 127 §6.3, all normative elements pinned here):

- **Block cipher** (§6.3.1.1): AES-128 (FIPS 197).
- **Initialization vector** (§6.3.1.2): the fixed IV
  ``0x445642544d4350544145534349535341`` (ASCII ``DVBTMCPTAESCISSA``).
- **Chaining mode** (§6.3.1.3): CBC (NIST SP800-38A) — **restarted per TS
  packet** (§6.3.2 "Each TS packet shall be processed separately"), so
  packets carry no inter-packet chain and the 等位替换 invariant holds at
  the BISS layer by construction (SPEC-611 §3 每包重启).
- **Per-packet region rule** (§6.3.2): the TS header and adaptation field
  stay clear (the ``TSPacket`` object model keeps them in separate fields);
  ``encrypted_payload_size = payload_size − payload_size mod 16`` — the
  first ``encrypted_payload_size`` payload bytes are encrypted, any
  remaining tail bytes stay in the clear (no AF ⇒ 176 encrypted + 8 clear).
- **Signaling** (TS 103 127 §7 / Tech 3292): CA_system_ID ``0x2602``
  (BISS2) and the scrambling_descriptor mode ``0x10`` semantics are
  *declared, not delivered* (the sandbox carries no ECM — ADR-0011 §4).
  The packet TSC bits reuse the family marker ``10`` (ISO 13818-1 leaves
  ``10``/``11`` user-defined; TS 103 127 pins no TSC — the sandbox
  convention keeps one scrambled marker across BISS faces).

Key model: a CISSA key is a 128-bit AES-128 key spelled as **32
hexadecimal characters** (BISS2 Mode 1: the session word *is* the CISSA
key, Tech 3292 v3 §4.2) or 16 raw bytes.  The BISS Mode E composition —
where the CISSA key is *derived* from the ESW + Injected ID chain — lives
in :mod:`ts.biss.mode_e` (SPEC-611 §4); this module consumes a ciss_key
only and never sees the derivation inputs.

Fingerprint/event discipline (SPEC-610 §9, inherited via SPEC-611 §6):
key material never enters mutation logs, journal events or artifacts —
only the :func:`key_fingerprint` SHA-256 prefix does.  The
``biss.scramble_applied`` / ``biss.descramble_failed`` payloads emitted
through the reserved seams (ruling §10-7) carry the ``mode`` field
(SPEC-611 §5: ``"1"``/``"E"``/``"2"``) so #129's registry and #128's
runtime can distinguish the BISS faces without key material.

Dependency face (SPEC-611 §8): AES lives in pycryptodome.  The import is
lazy — when pycryptodome is absent the first primitive call raises
:class:`PycryptodomeUnavailableError` loudly (explicit degradation, no
silent fallback; the dependency declaration face, not a DLL problem).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Callable, Sequence

from ts.biss.biss1 import (
    FAILED_INDICES_SAMPLE_LIMIT,
    SELF_CHECK_OPAQUE,
    SELF_CHECK_PSI_CRC32,
    SELF_CHECK_STRUCTURE,
    SELF_CHECK_TSC_STATE,
    DescrambleSelfCheck,
    TSC_EVEN_KEY,
    _normalize_pid_scope,
    _self_check_pusi,
)
from ts.packet import TSPacket

__all__ = [
    "BISS_SCRAMBLE_APPLIED_EVENT",
    "BISS_DESCRAMBLE_FAILED_EVENT",
    "BISS_MODE_1",
    "BISS_MODE_E",
    "BISS_MODE_2",
    "CA_SYSTEM_ID_BISS2",
    "CISSA_IV",
    "CISSA_KEY_BYTES",
    "CISSA_KEY_CHARS",
    "SCRAMBLING_MODE_CISSA_V1",
    "PycryptodomeUnavailableError",
    "parse_ciss_key",
    "key_fingerprint",
    "encrypt_payload",
    "decrypt_payload",
    "scramble",
    "descramble",
]

# --- wire constants (SPEC-611 §2.1/§5 / TS 103 127 §6.3/§7) ----------------------

#: Event type constants — inherited from the #126 seam (SPEC-610); the
#: ``biss.*`` payloads below add the SPEC-611 §5 ``mode`` field.
BISS_SCRAMBLE_APPLIED_EVENT = "biss.scramble_applied"
BISS_DESCRAMBLE_FAILED_EVENT = "biss.descramble_failed"

#: The ``biss.*`` payload ``mode`` vocabulary (SPEC-611 §5): Mode 1 (CSA1),
#: Mode E (derived key face) and BISS2 Mode 1 (declared CISSA key).  This
#: module emits ``BISS_MODE_2`` by default and accepts ``BISS_MODE_E`` for
#: the Mode E composition; ``BISS_MODE_1`` is the CSA1 face's value (biss1).
BISS_MODE_1 = "1"
BISS_MODE_E = "E"
BISS_MODE_2 = "2"

#: BISS2 signaling: CA_system_ID 0x2602 (Tech 3292 v3) and the TS 103 127
#: §7 scrambling_descriptor mode 0x10 (DVB-CISSA version 1) — declared
#: metadata, not delivered in the sandbox stream.
CA_SYSTEM_ID_BISS2 = 0x2602
SCRAMBLING_MODE_CISSA_V1 = 0x10

#: TS 103 127 §6.3.1.2 fixed initialization vector — a public standard
#: constant (ASCII ``DVBTMCPTAESCISSA``), not key material.
CISSA_IV = bytes.fromhex("445642544d4350544145534349535341")

#: CISSA key wire shape: 32 hex chars = 128-bit AES-128 key.
CISSA_KEY_CHARS = 32
CISSA_KEY_BYTES = 16

#: Modes this module may emit (the CSA1 mode value belongs to biss1).
_EMITTABLE_MODES = (BISS_MODE_2, BISS_MODE_E)


class PycryptodomeUnavailableError(RuntimeError):
    """pycryptodome is absent — the AES/DES dependency face degrades
    loudly (SPEC-611 §8: 显式降级错误, no silent fallback).  Fixing it is
    a dependency-declaration action (install pycryptodome), not a DLL
    build like the SPEC-610 CSA1 face."""


# --- pycryptodome lazy loader -----------------------------------------------------


def _load_aes():
    """Return the pycryptodome AES cipher constructor, or raise loudly.

    Both published import namespaces are probed (``Crypto`` for
    pycryptodome, ``Cryptodome`` for pycryptodomex) so either distribution
    satisfies the dependency face.
    """
    try:  # pycryptodome
        from Crypto.Cipher import AES as _aes  # noqa: PLC0415 — lazy
    except ImportError:  # pragma: no cover — probed below
        try:  # pycryptodomex
            from Cryptodome.Cipher import AES as _aes  # noqa: PLC0415
        except ImportError:
            raise PycryptodomeUnavailableError(
                "pycryptodome is not importable — the BISS2 CISSA / Mode E "
                "faces require it (SPEC-611 §8: explicit degradation; "
                "install pycryptodome, no silent fallback)"
            ) from None
    return _aes


# --- key face ---------------------------------------------------------------------


def parse_ciss_key(ciss_key: "str | bytes") -> bytes:
    """Normalize a CISSA key to its 16 AES-128 key bytes; reject bad shapes.

    Accepts a 32-hex-character string (any case) or 16 raw bytes — the two
    wire shapes a BISS2 key travels in.  A malformed key is a prepare-time
    rejection (SPEC-611 §8), so this raises ``ValueError``.
    """
    if isinstance(ciss_key, str):
        text = ciss_key.strip()
        if len(text) != CISSA_KEY_CHARS:
            raise ValueError(
                f"CISSA key must be {CISSA_KEY_CHARS} hex characters "
                f"(128-bit AES-128 key), got {len(text)} characters"
            )
        try:
            return bytes.fromhex(text)
        except ValueError:
            raise ValueError(
                "CISSA key must be 32 hex characters, got non-hex content"
            ) from None
    if isinstance(ciss_key, (bytes, bytearray)):
        raw = bytes(ciss_key)
        if len(raw) != CISSA_KEY_BYTES:
            raise ValueError(
                f"CISSA key must be {CISSA_KEY_BYTES} bytes (128-bit "
                f"AES-128 key), got {len(raw)} bytes"
            )
        return raw
    raise ValueError(
        "CISSA key must be a 32-hex-character string or 16 bytes, got "
        f"{type(ciss_key).__name__}"
    )


def key_fingerprint(ciss_key: "str | bytes") -> str:
    """The CISSA key's fingerprint: a SHA-256 hex prefix (SPEC-611 §6
    inherits the SPEC-610 §5/§9 discipline).  The ONLY key trace allowed
    in mutation logs and ``biss.*`` events for the BISS2 faces.  Hex
    string keys are normalized case-insensitively first, so the same key
    spelled in different case yields the same fingerprint."""
    raw = parse_ciss_key(ciss_key)
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest[:16]}"


# --- per-packet payload transform (TS 103 127 §6.3.2) -----------------------------


def _transform_payload(payload: bytes, key: bytes, *, encrypt: bool) -> bytes:
    """One packet's payload region under the §6.3.2 region rule.

    ``encrypted_payload_size = payload_size − payload_size mod 16``; the
    prefix is AES-128-CBC'd with the FIXED IV and a fresh cipher object
    (the §6.3 per-packet restart — no cross-packet state exists), the
    tail bytes pass through in the clear.  A payload smaller than one
    block encrypts nothing (honest §6.3.2 example 4 face).
    """
    encrypted_size = len(payload) - len(payload) % 16
    if encrypted_size == 0:
        return payload
    aes = _load_aes()
    prefix = payload[:encrypted_size]
    cipher = aes.new(key, aes.MODE_CBC, iv=CISSA_IV)
    body = cipher.encrypt(prefix) if encrypt else cipher.decrypt(prefix)
    return body + payload[encrypted_size:]


def encrypt_payload(payload: bytes, ciss_key: "str | bytes") -> bytes:
    """CISSA-scramble one payload region (§6.3.2; per-packet restart)."""
    return _transform_payload(payload, parse_ciss_key(ciss_key), encrypt=True)


def decrypt_payload(payload: bytes, ciss_key: "str | bytes") -> bytes:
    """CISSA-descramble one payload region (§6.3.2; per-packet restart)."""
    return _transform_payload(payload, parse_ciss_key(ciss_key), encrypt=False)


# --- scramble / descramble primitives --------------------------------------------


def scramble(
    packets: Sequence[TSPacket],
    ciss_key: "str | bytes",
    pid_scope: Sequence[int],
    *,
    mode: str = BISS_MODE_2,
    on_scramble_applied: "Callable[[dict[str, object]], None] | None" = None,
) -> "tuple[TSPacket, ...]":
    """BISS2 CISSA scramble: per-packet payload transform (TS 103 127
    §6.3.2, SPEC-611 §6).

    Deterministic; slot-preserving (same count/order/188-byte slots);
    header and adaptation field stay clear; in-scope packets carry the
    family TSC marker ``10``; out-of-scope packets pass through untouched.

    ``mode`` is the SPEC-611 §5 ``biss.*`` payload ``mode`` value this
    face emits — ``"2"`` (default, declared CISSA key) or ``"E"`` (the
    Mode E derived-key composition, key built by :mod:`ts.biss.mode_e`).
    ``on_scramble_applied`` is the reserved ``biss.scramble_applied``
    emission seam (ruling §10-7): called at most once with
    ``{pid_scope, packet_count, key_fingerprint, mutation_log_ref, mode}``
    (``mutation_log_ref`` is ``None`` here — the artifact binding is
    resolved by the runtime wiring, #128).
    """
    if mode not in _EMITTABLE_MODES:
        raise ValueError(
            f"biss.* mode {mode!r} is outside the CISSA face vocabulary "
            f"{list(_EMITTABLE_MODES)} (SPEC-611 §5)"
        )
    scope = _normalize_pid_scope(pid_scope)
    key = parse_ciss_key(ciss_key)
    targets = [
        (index, packet)
        for index, packet in enumerate(packets)
        if packet.pid in scope and packet.payload is not None
    ]
    transformed = {
        index: replace(
            packet,
            payload=_transform_payload(packet.payload, key, encrypt=True),
            transport_scrambling_control=TSC_EVEN_KEY,
        )
        for index, packet in targets
    }
    scrambled = tuple(
        transformed.get(index, packet) for index, packet in enumerate(packets)
    )
    if on_scramble_applied is not None:
        on_scramble_applied(
            {
                "pid_scope": sorted(scope),
                "packet_count": len(targets),
                "key_fingerprint": key_fingerprint(key),
                "mutation_log_ref": None,
                "mode": mode,
            }
        )
    return scrambled


def descramble(
    packets: Sequence[TSPacket],
    ciss_key: "str | bytes",
    pid_scope: Sequence[int],
    *,
    mode: str = BISS_MODE_2,
    on_descramble_failed: "Callable[[dict[str, object]], None] | None" = None,
) -> "tuple[tuple[TSPacket, ...], tuple[DescrambleSelfCheck, ...]]":
    """BISS2 CISSA descramble + per-packet structural self-check.

    Mirrors the SPEC-610 §6/§7 descramble contract (SPEC-611 §6 inherits
    the 事件面/结构自检纪律): in-scope packets must carry the scrambled
    TSC marker (else an explicit ``tsc_state`` evidence entry — never
    silent), decrypted payloads get the same PES/PSI structural verdicts,
    and failures fire ``on_descramble_failed`` once with
    ``{pid_scope, failed_indices_sample, self_check_kind,
    key_fingerprint_ref, mode}``.

    The verdict logic is the biss1 module's single BISS-family
    implementation (its file is frozen for #127, so the shared private
    helpers are imported rather than forked — one evidence semantics).
    """
    if mode not in _EMITTABLE_MODES:
        raise ValueError(
            f"biss.* mode {mode!r} is outside the CISSA face vocabulary "
            f"{list(_EMITTABLE_MODES)} (SPEC-611 §5)"
        )
    scope = _normalize_pid_scope(pid_scope)
    key = parse_ciss_key(ciss_key)

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
                        "in-scope packet does not carry the BISS scrambled "
                        "TSC (10) — nothing descrambled"
                    ),
                )
            )
            continue
        prechecked.append((index, packet))
        decrypted[index] = packet.payload

    for index, packet in prechecked:
        plain = _transform_payload(packet.payload, key, encrypt=False)
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
                "key_fingerprint_ref": key_fingerprint(key),
                "mode": mode,
            }
        )
    return clear, tuple(checks)


# --- module self-checks (import-time shape pins, cheap and silent) ---------------

assert len(CISSA_IV) == CISSA_KEY_BYTES  # TS 103 127 §6.3.1.2: IV is 128-bit
assert CISSA_IV == b"DVBTMCPTAESCISSA"  # the §6.3.1.2 ASCII spelling
