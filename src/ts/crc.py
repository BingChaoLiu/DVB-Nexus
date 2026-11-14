"""MPEG-2 CRC-32 core (SPEC-101, ticket #26).

CRC-32/MPEG-2 — the CRC used by MPEG-2 PSI sections (ITU-T H.222.0) —
implemented as a pure, incremental, standard-library-only module:

- Width 32, polynomial ``0x04C11DB7``, init ``0xFFFFFFFF``,
  RefIn/RefOut ``false``, XorOut ``0x00000000`` (SPEC-101 §3, integration
  contract §5).
- Check vector: ``b"123456789"`` -> ``0x0376E6E7``.
- The bitwise MSB-first (left-shift) loop is the reference implementation;
  a 256-entry lookup-table variant (``_mpeg2_crc32_table``) exists for
  cross-verification and optional optimization (SPEC-101 §5).
- CRC fields are 4-byte big-endian; a section that already carries its CRC
  verifies when the CRC computed over the whole byte string is zero.

The module imports no other project package and no third-party package
(ADR-0005 decision 4: ``ts`` purity). It must stay decoupled from
``TSPacket`` and PSI Section (SPEC-102) consumers.
"""

CRC32_MPEG2_POLY = 0x04C11DB7
CRC32_MPEG2_INIT = 0xFFFFFFFF

_MASK32 = 0xFFFFFFFF
_CRC_FIELD_WIDTH = 4

_BYTES_LIKE = (bytes, bytearray, memoryview)


def _coerce_bytes(data: bytes, *, param: str) -> bytes:
    """Validate a bytes-like argument and normalize it to ``bytes``.

    ``bytes`` is returned as-is; ``bytearray`` / ``memoryview`` are copied.
    Anything else raises ``TypeError`` — no silent coercion (SPEC-101 §6:
    ``str`` and ``int`` in particular must not be accepted implicitly).
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, _BYTES_LIKE):
        return bytes(data)
    raise TypeError(
        f"{param} must be a bytes-like object (bytes, bytearray, memoryview), "
        f"got {type(data).__name__}"
    )


def _validate_initial(initial: int, *, param: str = "initial") -> int:
    """Validate the 32-bit CRC initial state.

    Non-``int`` (including ``bool``, which is a semantically different flag
    type) raises ``TypeError``; values outside ``0..0xFFFFFFFF`` raise
    ``ValueError``. Nothing is silently truncated (SPEC-101 §6).
    """
    if isinstance(initial, bool) or not isinstance(initial, int):
        raise TypeError(
            f"{param} must be an int in 0..0xFFFFFFFF, got {type(initial).__name__}"
        )
    if not 0 <= initial <= _MASK32:
        raise ValueError(
            f"{param} must be in 0..0xFFFFFFFF, got {initial}"
        )
    return initial


def _advance_bitwise(crc: int, data: bytes) -> int:
    """Reference core: MSB-first, left-shift bitwise CRC step (SPEC-101 §5).

    Processes ``data`` starting from state ``crc``; the internal state is
    masked to 32 bits at every shift so no overflow can accumulate.
    """
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = (crc << 1) ^ CRC32_MPEG2_POLY
            else:
                crc <<= 1
            crc &= _MASK32
    return crc


def _build_table() -> tuple[int, ...]:
    """Build the 256-entry MSB-first lookup table from the polynomial."""
    table = []
    for index in range(256):
        entry = index << 24
        for _ in range(8):
            if entry & 0x80000000:
                entry = (entry << 1) ^ CRC32_MPEG2_POLY
            else:
                entry <<= 1
            entry &= _MASK32
        table.append(entry)
    return tuple(table)


_TABLE = _build_table()


def _advance_table(crc: int, data: bytes) -> int:
    """Table-driven variant of :func:`_advance_bitwise` (SPEC-101 §5)."""
    for byte in data:
        crc = ((crc << 8) & _MASK32) ^ _TABLE[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _mpeg2_crc32_table(
    data: bytes, *, initial: int = CRC32_MPEG2_INIT
) -> int:
    """Table-driven CRC-32/MPEG-2; cross-verified against the bitwise core.

    Private helper kept for the SPEC-101 §7.7 cross-implementation test and
    as an opt-in optimization path; the public API uses the bitwise
    reference implementation.
    """
    return _advance_table(
        _validate_initial(initial), _coerce_bytes(data, param="data")
    )


def mpeg2_crc32(data: bytes, *, initial: int = CRC32_MPEG2_INIT) -> int:
    """Compute the CRC-32/MPEG-2 of ``data`` (SPEC-101 §4).

    Only computes the CRC of the given bytes; it does not append anything.
    Empty input returns the initial state ``0xFFFFFFFF`` (SPEC-101 §5).

    Args:
        data: bytes-like input (``bytes``, ``bytearray``, ``memoryview``).
        initial: 32-bit initial state, ``0..0xFFFFFFFF``; defaults to
            ``CRC32_MPEG2_INIT``.

    Returns:
        The 32-bit unsigned CRC value.

    Raises:
        TypeError: ``data`` is not bytes-like, or ``initial`` is not an int.
        ValueError: ``initial`` is outside ``0..0xFFFFFFFF``.
    """
    return _advance_bitwise(
        _validate_initial(initial), _coerce_bytes(data, param="data")
    )


def append_mpeg2_crc32(data: bytes) -> bytes:
    """Append the big-endian CRC-32/MPEG-2 field to ``data`` (SPEC-101 §4).

    Returns ``data + crc_be32`` — e.g. a CRC value of ``0x0376E6E7`` is
    encoded as ``03 76 E6 E7`` (network byte order, SPEC-101 §5).

    Raises:
        TypeError: ``data`` is not bytes-like.
    """
    payload = _coerce_bytes(data, param="data")
    crc_value = _advance_bitwise(CRC32_MPEG2_INIT, payload)
    return payload + crc_value.to_bytes(_CRC_FIELD_WIDTH, "big")


def verify_mpeg2_crc32(data_including_crc: bytes) -> bool:
    """Verify a byte string that already carries its appended CRC field.

    Computes the CRC-32/MPEG-2 remainder over the whole input (SPEC-101 §4):
    a remainder of ``0`` means the CRC field matches, so ``True`` is
    returned. Fewer than 4 bytes cannot contain a CRC field and verify
    ``False`` (no exception) — callers decide how to report that.

    Raises:
        TypeError: ``data_including_crc`` is not bytes-like.
    """
    section = _coerce_bytes(data_including_crc, param="data_including_crc")
    if len(section) < _CRC_FIELD_WIDTH:
        return False
    return _advance_bitwise(CRC32_MPEG2_INIT, section) == 0


class MPEG2CRC32:
    """Incremental CRC-32/MPEG-2 accumulator (SPEC-101 §4).

    Feed data with :meth:`update` in any number of chunks; the result equals
    the one-shot :func:`mpeg2_crc32` over the concatenation (SPEC-101 §5).
    Not thread-safe: state is mutated in place.

    Raises:
        TypeError: ``initial`` is not an int, or ``update`` gets non-bytes.
        ValueError: ``initial`` is outside ``0..0xFFFFFFFF``.
    """

    __slots__ = ("_crc",)

    def __init__(self, initial: int = CRC32_MPEG2_INIT) -> None:
        self._crc = _validate_initial(initial)

    def update(self, data: bytes) -> None:
        """Feed more bytes into the running CRC state.

        Empty input is a no-op (SPEC-101 §5/§6).
        """
        self._crc = _advance_bitwise(
            self._crc, _coerce_bytes(data, param="data")
        )

    def value(self) -> int:
        """Return the current 32-bit unsigned CRC state."""
        return self._crc

    def copy(self) -> "MPEG2CRC32":
        """Return an independent snapshot of this accumulator."""
        return MPEG2CRC32(self._crc)
