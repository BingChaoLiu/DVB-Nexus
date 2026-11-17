"""BISS Mode E — ESW + Injected ID → session word derivation and the
Mode E → CISSA key composition (SPEC-611 §4/§6, ITU-T J.96 §9.3,
EBU Tech 3292-s1, ticket #127).

Key model (SPEC-611 §3/§5, roadmap §4 C1 订正口径):

- **ESW** (Encrypted Session Word): 16 hex characters = 64-bit DES block,
  handed to receivers out of band (Tech 3292-s1 Mode E: "the SW is
  encrypted with a fixed Session Key (SK) and the resulting Encrypted
  Session Word (ESW) is transmitted out of band to the receivers").
- **Injected/Buried ID**: 128-bit (32 hex) unique identifier statically
  provisioned in the receiver — **never transmitted in the stream**
  (the C1 teaching point: it is not dynamic data).
- **session word**: 48-bit (12 hex), the same wire shape Mode 1 uses —
  the derived SW feeds the Mode 1 CW derivation unchanged.

Derivation chain (SPEC-611 §4, J.96 §9.3 normative steps + the Tech
3292-s1 128-bit ID naming; every step below is pinned by the registered
golden ``biss-mode-e-derive``):

1. The DES session-key face consumes the **low 56 bits** of the 128-bit
   Injected ID (its trailing 14 hex characters) as the J.96 Active ID
   (the sandbox pin for the Tech 3292-s1 "session key derived from the
   Injected ID" semantics — J.96 §9.3.2 defines the ID as 56 bit).
2. **Mapping** (J.96 §9.3.3 a / Table 2): the 56 Active ID bits fill the
   upper seven bits of 8 bytes; each byte's LSB is set so the byte has
   odd parity → the Mapped Active ID (the DES key, parity included).
3. ``SW' = DES-ECB-decrypt(Mapped Active ID, ESW)`` (J.96 §9.3.3 b —
   FIPS 46-3 ECB, decrypt state; parity bits are ignored by DES).
4. **Reduction** (J.96 §9.3.3 / Table 3): drop the MSB and LSB of every
   SW' byte, concatenate the remaining 6 bits per byte → SW" (48 bit).
5. **P()** (J.96 §9.3.4): injected ID ⇒ the identity function (the
   buried-ID rotation is out of scope — the sandbox config carries only
   ``injected_id``).  ``SW = SW"``.
6. ``CW`` = the J.96 §8 checksum formula (:func:`ts.biss.biss1.derive_cw`
   — the single Mode 1 implementation, imported read-only).

Mode E → CISSA composition (sandbox pin, golden-pinned): the TS
scrambling face of a Mode E config is CISSA (``ca_system_id`` 0x2602 =
BISS2, SPEC-611 §5), whose AES-128 key cannot be the 64-bit CW directly.
The sandbox derives it deterministically as ``ciss_key = CW ‖ CW`` (the
8-byte CW repeated into the 16-byte AES-128 key).  This is a documented
composition rule (not a standard operation) — it keeps the derivation
chain traceable end-to-end without inventing key material, and the
golden manifest pins it.  Teaching framing only: declared keys in the
sandbox are plaintext configuration (ADR-0011 §3), never a production
key-management claim.

Mismatch faces (SPEC-611 §7/§8 — the two wrong-key variants are
distinguishable in evidence):

- **wrong ESW** (format valid): the derivation *succeeds* — it yields a
  WRONG session word (J.96 defines no checkable redundancy on SW' — the
  dvbipitools encrypt-side convention fills the dropped MSB/LSB bits
  arbitrarily — so no structural validation is possible without forking
  the standard).  Evidence: derivation-chain fingerprints with the
  ``esw`` face mismatching the declared chain.
- **wrong Injected ID**: likewise derivable to a wrong session word; the
  evidence distinguishes the faces by naming *which* chain input
  fingerprints differ (``wrong_esw`` vs ``wrong_injected_id`` redacted
  parameter keys — the filter layer in
  ``faults.filters.biss_mode_e`` attaches the per-face fingerprints).
- Format-illegal ESW/ID: prepare-time rejection (:func:`parse_esw` /
  :func:`parse_injected_id` raise ``ValueError``) — never a silent
  fallback.

Dependency face: DES lives in pycryptodome (lazy import — absence
raises :class:`ts.biss.cissa.PycryptodomeUnavailableError`, SPEC-611 §8
explicit degradation).

Key discipline (SPEC-610 §9 inherited): the redacted
:func:`derivation_ref` chain reference carries only fingerprints — key
bodies never enter mutation logs, journal events or artifacts.
"""

from __future__ import annotations

import hashlib

from ts.biss.biss1 import parse_session_word
from ts.biss.biss1 import derive_cw as _derive_cw_from_session_word
from ts.biss.cissa import CISSA_KEY_BYTES, PycryptodomeUnavailableError

__all__ = [
    "ESW_CHARS",
    "ESW_BYTES",
    "INJECTED_ID_CHARS",
    "INJECTED_ID_BYTES",
    "ACTIVE_ID_BYTES",
    "SESSION_WORD_CHARS",
    "parse_esw",
    "parse_injected_id",
    "map_active_id",
    "active_id_from_injected_id",
    "derive_sw",
    "derive_cw",
    "derive_ciss_key",
    "key_fingerprint",
    "derivation_ref",
]

# --- wire shapes (SPEC-611 §5 / J.96 §9) ------------------------------------------

#: ESW wire shape: 16 hex chars = 64-bit DES block.
ESW_CHARS = 16
ESW_BYTES = 8

#: Injected/Buried ID wire shape (Tech 3292-s1): 32 hex chars = 128 bit.
INJECTED_ID_CHARS = 32
INJECTED_ID_BYTES = 16

#: J.96 §9.3 Active ID: 56 bit = 7 bytes (the DES key face of the ID).
ACTIVE_ID_BYTES = 7

#: Derived session word: the Mode 1 wire shape (12 hex / 48 bit).
SESSION_WORD_CHARS = 12


# --- wire parsers (prepare-time rejection, value-free errors) ---------------------


def _parse_hex(value: "str | bytes", *, chars: int, nbytes: int,
               label: str) -> bytes:
    if isinstance(value, str):
        text = value.strip()
        if len(text) != chars:
            raise ValueError(
                f"BISS Mode E {label} must be {chars} hex characters, got "
                f"{len(text)} characters"
            )
        try:
            return bytes.fromhex(text)
        except ValueError:
            raise ValueError(
                f"BISS Mode E {label} must be {chars} hex characters, got "
                "non-hex content"
            ) from None
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) != nbytes:
            raise ValueError(
                f"BISS Mode E {label} must be {nbytes} bytes, got "
                f"{len(raw)} bytes"
            )
        return raw
    raise ValueError(
        f"BISS Mode E {label} must be a {chars}-hex-character string or "
        f"{nbytes} bytes, got {type(value).__name__}"
    )


def parse_esw(esw: "str | bytes") -> bytes:
    """Normalize an ESW to its 8 DES-block bytes; reject bad shapes.

    SPEC-611 §8: format-illegal ESW is a prepare-time rejection (16 hex),
    never a silent fallback.  Error details are value-free (key
    discipline — the ESW body never appears in the rejection text).
    """
    return _parse_hex(esw, chars=ESW_CHARS, nbytes=ESW_BYTES, label="ESW")


def parse_injected_id(injected_id: "str | bytes") -> bytes:
    """Normalize an Injected ID to its 16 bytes; reject bad shapes.

    SPEC-611 §8: format-illegal Injected ID is a prepare-time rejection
    (32 hex / 128-bit).  Error details are value-free (key discipline —
    the ID body never appears in the rejection text).
    """
    return _parse_hex(
        injected_id,
        chars=INJECTED_ID_CHARS,
        nbytes=INJECTED_ID_BYTES,
        label="injected ID",
    )


# --- J.96 §9.3 derivation steps ----------------------------------------------------


def active_id_from_injected_id(injected_id: "str | bytes") -> bytes:
    """The J.96 Active ID (56 bit) this Injected ID yields.

    Sandbox pin for the Tech 3292-s1 session-key face: the DES key is
    derived from the **low 56 bits** of the 128-bit Injected ID (its
    trailing 7 bytes / trailing 14 hex characters).
    """
    raw = parse_injected_id(injected_id)
    return raw[-ACTIVE_ID_BYTES:]


def map_active_id(active_id: "str | bytes") -> bytes:
    """J.96 §9.3.3 a / Table 2: 56 Active ID bits → 64-bit Mapped Active ID.

    The 56 bits fill the upper seven bits of a sequence of 8 bytes; the
    LSB of each byte is set so the byte has odd parity.  The result is
    the DES key (DES itself ignores the parity bits, FIPS 46-3).
    """
    if isinstance(active_id, str):
        try:
            raw = bytes.fromhex(active_id.strip())
        except ValueError:
            raise ValueError(
                "the J.96 Active ID must be 14 hex characters, got "
                "non-hex content"
            ) from None
    else:
        raw = bytes(active_id)
    if len(raw) != ACTIVE_ID_BYTES:
        raise ValueError(
            f"the J.96 Active ID must be {ACTIVE_ID_BYTES} bytes (56 bit), "
            f"got {len(raw)} bytes"
        )
    value = int.from_bytes(raw, "big")  # bit 55 (msb) .. bit 0 (lsb)
    mapped = bytearray(8)
    for index in range(8):
        # Active ID bits 55-7i .. 49-7i into mapped byte i, bits 7..1
        # (msb-first); bit 0 stays free for the parity bit.
        seven_bits = (value >> (56 - 7 * (index + 1))) & 0x7F
        byte_value = seven_bits << 1
        # Odd parity over the full byte.
        if bin(byte_value).count("1") % 2 == 0:
            byte_value |= 0x01
        mapped[index] = byte_value
    return bytes(mapped)


def _des_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    """One DES-ECB block decrypt (J.96 §9.3.3 b — FIPS 46-3/81).

    pycryptodome is the AES/DES dependency face; absence raises loudly
    (SPEC-611 §8 explicit degradation, no fallback implementation).
    """
    try:
        from Crypto.Cipher import DES  # noqa: PLC0415 — lazy
    except ImportError:  # pragma: no cover — pycryptodomex probe
        try:
            from Cryptodome.Cipher import DES  # noqa: PLC0415
        except ImportError:
            raise PycryptodomeUnavailableError(
                "pycryptodome is not importable — the BISS Mode E "
                "derivation requires it (SPEC-611 §8: explicit "
                "degradation; install pycryptodome, no silent fallback)"
            ) from None
    return DES.new(key, DES.MODE_ECB).decrypt(data)


def derive_sw(esw: "str | bytes", injected_id: "str | bytes") -> str:
    """Derive the clear session word from an ESW + Injected ID.

    Deterministic (SPEC-611 §6): J.96 §9.3 steps 1–4 with the injected-ID
    identity P() (§9.3.4) — Active ID (low 56 bit of the ID) → Mapped
    Active ID (odd-parity expansion) → ``SW' = DES-ECB-decrypt(MappedID,
    ESW)`` → 6-bits-per-byte reduction → the 48-bit session word as a
    12-hex-character string.  The formula is pinned by the registered
    golden ``biss-mode-e-derive`` (SPEC-611 §11/§12 AC-611-02).

    Raises ``ValueError`` on format-illegal inputs (prepare-time
    rejection, value-free errors) and
    :class:`ts.biss.cissa.PycryptodomeUnavailableError` when the DES
    dependency face is absent.
    """
    esw_bytes = parse_esw(esw)
    active = active_id_from_injected_id(injected_id)
    mapped = map_active_id(active)
    sw_prime = _des_ecb_decrypt(mapped, esw_bytes)
    # J.96 Table 3 reduction: drop each byte's MSB and LSB (parity),
    # concatenate the remaining six bits msb-first → 48-bit SW".
    value = 0
    for byte in sw_prime:
        value = (value << 6) | ((byte >> 1) & 0x3F)
    # P() identity for the injected ID (J.96 §9.3.4) — SW = SW".
    return f"{value:0{SESSION_WORD_CHARS}X}"


def derive_cw(esw: "str | bytes", injected_id: "str | bytes") -> "tuple[bytes, bytes]":
    """Derive the Mode 1 control word from the Mode E chain.

    ``session word → CW`` rides the single J.96 §8 checksum
    implementation (:func:`ts.biss.biss1.derive_cw`); both parity slots
    carry the identical CW (Mode 1 defines one control word).  Returns
    ``(odd_cw, even_cw)`` in the biss1 shape.
    """
    return _derive_cw_from_session_word(derive_sw(esw, injected_id))


def derive_ciss_key(esw: "str | bytes", injected_id: "str | bytes") -> bytes:
    """The Mode E → CISSA key composition (sandbox pin, golden ``biss-mode-e-derive``).

    ``ciss_key = CW ‖ CW`` — the derived 8-byte control word repeated
    into the 16-byte AES-128 key the CISSA face (:mod:`ts.biss.cissa`)
    consumes.  See the module docstring for the composition rationale
    (documented sandbox rule, not a standard operation; the derivation
    chain stays fingerprint-traceable end-to-end).
    """
    cw = derive_cw(esw, injected_id)[1]
    if len(cw) * 2 != CISSA_KEY_BYTES:  # pragma: no cover — shape guard
        raise ValueError(
            "the CISSA composition expects an 8-byte control word, got "
            f"{len(cw)} bytes"
        )
    return cw + cw


# --- redacted evidence face ---------------------------------------------------------


def key_fingerprint(value: "str | bytes") -> str:
    """A Mode E key-material fingerprint: SHA-256 hex prefix (SPEC-610 §9
    discipline, SPEC-611 §6 inherited).  Accepts the Mode E wire shapes —
    ESW (16 hex / 8 bytes), Injected ID (32 hex / 16 bytes), derived
    session word (12 hex / 6 bytes) and derived CISSA key (32 hex / 16
    bytes).  Hex strings normalize case-insensitively; the ONLY key trace
    allowed in mutation logs and ``biss.*`` events."""
    if isinstance(value, str):
        text = value.strip().lower()
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            raise ValueError(
                "key_fingerprint expects hex characters or raw bytes, got "
                "non-hex content"
            ) from None
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        raise ValueError(
            "key_fingerprint expects a hex string or raw bytes, got "
            f"{type(value).__name__}"
        )
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest[:16]}"


def derivation_ref(esw: "str | bytes", injected_id: "str | bytes") -> dict[str, str]:
    """The redacted derivation-chain reference for ``biss.*`` payloads
    (SPEC-611 §5: 派生链引用，不落密钥本体).

    Fingerprints only — the ESW/ID faces, the derived session word and
    the derived CISSA key.  The two wrong-key fault variants are
    distinguishable in evidence precisely by which of these fingerprints
    diverges from the declared chain (SPEC-611 §8).
    """
    session_word = derive_sw(esw, injected_id)
    ciss_key = derive_ciss_key(esw, injected_id)
    return {
        "esw_fingerprint": key_fingerprint(parse_esw(esw)),
        "injected_id_fingerprint": key_fingerprint(
            parse_injected_id(injected_id)
        ),
        "session_word_fingerprint": key_fingerprint(
            parse_session_word(session_word)
        ),
        "ciss_key_fingerprint": key_fingerprint(ciss_key),
    }
