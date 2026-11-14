"""Internal shared wire primitives for ts-core (single source, review-fix F6).

ts-core modules historically carried private per-module copies of the same
small helpers (bytes coercion, the 13-bit PID bound, the strict-int guard).
This module is their ONE authoritative home: every consumer imports from
here and no module may keep a second definition. It is an internal leaf —
imports nothing but the standard library, part of no public surface
(``ts`` re-exports nothing; the package export discipline stays intact).

Contents:

- :data:`_BYTES_LIKE` / :func:`_coerce_bytes` — the bytes-like argument
  guard shared by ``packet`` / ``crc`` / ``section`` / ``pes`` /
  ``tables.pmt`` and the bytes-typed ``packetizer`` / ``generator.json_map``
  branches (SPEC-100/101/102/104 §6 validation: ``str`` and ``int`` in
  particular must never be accepted implicitly).
- :data:`PID_MAX` — the 13-bit PID field bound (ISO/IEC 13818-1
  ``table 13-bit`` field; upper bound shared by ``packet`` / ``cc`` /
  ``section_assembler`` / ``mux.config`` / ``generator.validator`` /
  ``packetizer`` / ``tables``).
- :func:`_require_int` — the strict programming-error int guard (bool
  excluded) shared by ``mux.config`` and ``generator.validator``.
"""

from __future__ import annotations

#: The bytes-like types :func:`_coerce_bytes` accepts.
_BYTES_LIKE = (bytes, bytearray, memoryview)

#: The 13-bit PID field upper bound (single source for the whole package).
PID_MAX = 0x1FFF


def _coerce_bytes(data: object, param: str) -> bytes:
    """Accept ``bytes``/``bytearray``/``memoryview``, reject everything else.

    ``bytes`` is returned as-is; ``bytearray`` / ``memoryview`` are copied.
    Anything else raises ``TypeError`` — no silent coercion (SPEC-101 §6:
    ``str`` and ``int`` in particular must not be accepted implicitly).

    ``param`` is positional-or-keyword so call sites may keep either the
    historical keyword form (``param="data"``) or the positional form used
    by the former ``tables.pmt`` variant.
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, _BYTES_LIKE):
        return bytes(data)
    raise TypeError(
        f"{param} must be a bytes-like object (bytes, bytearray, memoryview), "
        f"got {type(data).__name__}"
    )


def _require_int(value: object, name: str) -> int:
    """Programming-error guard: strict int, bool excluded (TypeError).

    Returns ``value`` unchanged; callers may use the return inline or
    ignore it (the historical ``None``-return variant in
    ``generator.validator`` ignored nothing — it had no return at all —
    and its call sites are all plain statements).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    return value
