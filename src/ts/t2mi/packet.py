"""SPEC-600 §5 — T2-MI packet model (TS 102 773 §5.1, ticket #122).

Wire layout (TS 102 773 §5.1; cross-checked against TSDuck
``tsT2MI.h``/``tsT2MIPacket.h`` and the dvb-t2mi crate review #107 —
two independent implementations of the same standard table):

- 6-byte header: ``[0]`` packet_type, ``[1]`` packet_counter,
  ``[2]`` superframe_index (high nibble) + reserved (low nibble),
  ``[3]`` reserved, ``[4..5]`` payload length **in bits** (16-bit BE);
- payload of ``ceil(bits / 8)`` bytes (the partial final byte carries
  up to 7 padding bits — the only padding the standard defines inside a
  T2-MI packet);
- 4-byte big-endian CRC-32/MPEG-2 trailer (poly ``0x04C11DB7``,
  init ``0xFFFFFFFF``) over header + payload — reused read-only from
  :mod:`ts.crc` (SPEC-100/101 face, ADR-0005 decision 3).

Packet types (SPEC-600 §2.1 MVP subset):

- ``0x00`` BBFRAME — the only payload-semantics type this ticket
  registers; the standard's full table (Aux I/Q ``0x01``, L1-current
  ``0x10``, …) is registered progressively (SPEC-600 §8 注册表渐进).
- ``0xFF`` padding/stuffing byte identity — TS 102 773 defines **no**
  padding packet_type; ``0xFF`` is the de-facto stuffing byte TSDuck
  labels ``INVALID_TYPE`` and the byte #104 measured stuffing gaps with.
  The parser surfaces it as the explicit ``"padding"`` state so
  inter-packet stuffing is visible and counted, never silent.
- every other value → explicit ``"unknown"`` state (SPEC-600 §8).

Preservation discipline (house rule, SPEC-100 precedent): the stored
CRC value is re-encoded verbatim — a packet with ``crc32_valid=False``
round-trips to the exact original bytes; reserved bits are preserved
verbatim via the ``reserved`` field. No implicit fixes.

Error codes owned here (module-owned per contract §7 归属约定):
``T2MI_PACKET_TYPE_OUT_OF_RANGE``, ``T2MI_PACKET_COUNTER_OUT_OF_RANGE``,
``T2MI_PACKET_SUPERFRAME_OUT_OF_RANGE``,
``T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE``, ``T2MI_PACKET_CRC_OUT_OF_RANGE``,
``T2MI_PACKET_RESERVED_INVALID``, ``T2MI_PACKET_ENCODED_SIZE_INVALID``.
All map to :class:`ts.t2mi.errors.T2miError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ts._bytesutil import _coerce_bytes
from ts.crc import mpeg2_crc32, verify_mpeg2_crc32
from ts.t2mi.errors import T2miError

__all__ = [
    "T2MI_BBHEADER_SIZE",
    "T2MI_CRC_SIZE",
    "T2MI_HEADER_SIZE",
    "T2MI_KNOWN_PACKET_TYPES",
    "T2MI_TYPE_BBFRAME",
    "T2MI_TYPE_PADDING",
    "T2miPacket",
    "encode_packet",
]

# --- TS 102 773 §5.1 wire constants ---

#: T2-MI packet header size in bytes.
T2MI_HEADER_SIZE = 6
#: CRC-32 trailer size in bytes.
T2MI_CRC_SIZE = 4
#: BBHEADER size carried inside a BBFRAME packet payload (EN 302 755
#: §5.1.7; the T2-MI layer knows the frame boundary offset only).
T2MI_BBHEADER_SIZE = 10
#: Maximum payload length in bits (16-bit header field).
T2MI_PAYLOAD_BITS_MAX = 0xFFFF

#: Baseband Frame — the MVP-registered payload-semantics packet type.
T2MI_TYPE_BBFRAME = 0x00
#: Padding / stuffing byte identity (see module docstring).
T2MI_TYPE_PADDING = 0xFF

#: MVP packet-type value domain (SPEC-600 §2.1: BBFRAME + padding;
#: everything else parses into the explicit unknown state).
T2MI_KNOWN_PACKET_TYPES: frozenset[int] = frozenset({T2MI_TYPE_BBFRAME, T2MI_TYPE_PADDING})

# --- error codes owned by this module ---

T2MI_PACKET_TYPE_OUT_OF_RANGE = "T2MI_PACKET_TYPE_OUT_OF_RANGE"
T2MI_PACKET_COUNTER_OUT_OF_RANGE = "T2MI_PACKET_COUNTER_OUT_OF_RANGE"
T2MI_PACKET_SUPERFRAME_OUT_OF_RANGE = "T2MI_PACKET_SUPERFRAME_OUT_OF_RANGE"
T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE = "T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE"
T2MI_PACKET_CRC_OUT_OF_RANGE = "T2MI_PACKET_CRC_OUT_OF_RANGE"
T2MI_PACKET_RESERVED_INVALID = "T2MI_PACKET_RESERVED_INVALID"
T2MI_PACKET_ENCODED_SIZE_INVALID = "T2MI_PACKET_ENCODED_SIZE_INVALID"

#: Wire payload-kind states (SPEC-600 §8 error face + §5 payload_kind).
PAYLOAD_KIND_BBFRAME = "bbframe"
PAYLOAD_KIND_PADDING = "padding"
PAYLOAD_KIND_UNKNOWN = "unknown"

_HEADER_TYPE_OFFSET = 0
_HEADER_COUNTER_OFFSET = 1
_HEADER_RESERVED_OFFSET = 2
_HEADER_PAYLOAD_BITS_OFFSET = 4
_RESERVED_SIZE = 2
_MASK8 = 0xFF
_MASK16 = 0xFFFF
_MASK32 = 0xFFFFFFFF
_MASK_NIBBLE = 0x0F


def _require_int(value: object, name: str, code: str, upper: int) -> int:
    """Range-check one unsigned int field; bool rejected as a distinct type."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{code}: {name} must be an int, got {type(value).__name__}")
    if not 0 <= value <= upper:
        raise T2miError(f"{code}: {name} out of range 0..{upper}, got {value}")
    return value


@dataclass(frozen=True)
class T2miPacket:
    """One T2-MI packet (TS 102 773 §5.1) with verbatim preservation.

    Fields carry the parsed/constructed values exactly; the CRC trailer
    value is stored (never recomputed on encode) so corrupt packets are
    byte-stable. ``crc32_valid`` is *derived* — the CRC remainder over the
    full encoding must be zero.

    For a BBFRAME-type packet the payload starts with the transport
    prefix ``frame_idx(1) + PLP_id(1) + flags(1)`` (TSDuck byte-aligned
    layout, research #104 §3.1) followed by the BBFRAME itself; the
    ``frame_index`` / ``plp_id`` / ``bbframe`` derived faces expose that
    structure for #123/#124/#125.
    """

    packet_type: int
    packet_counter: int
    #: Raw header bytes 2..3 verbatim: byte 2 = superframe_index (high
    #: nibble) + reserved low nibble, byte 3 reserved.
    reserved: bytes
    payload_bits: int
    payload: bytes
    crc32: int

    def __post_init__(self) -> None:
        _require_int(
            self.packet_type,
            "packet_type",
            T2MI_PACKET_TYPE_OUT_OF_RANGE,
            _MASK8,
        )
        _require_int(
            self.packet_counter,
            "packet_counter",
            T2MI_PACKET_COUNTER_OUT_OF_RANGE,
            _MASK8,
        )
        _require_int(
            self.payload_bits,
            "payload_bits",
            T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE,
            T2MI_PAYLOAD_BITS_MAX,
        )
        _require_int(self.crc32, "crc32", T2MI_PACKET_CRC_OUT_OF_RANGE, _MASK32)
        reserved = _coerce_bytes(self.reserved, param="reserved")
        if len(reserved) != _RESERVED_SIZE:
            raise T2miError(
                f"{T2MI_PACKET_RESERVED_INVALID}: reserved must be exactly "
                f"{_RESERVED_SIZE} bytes, got {len(reserved)}"
            )
        object.__setattr__(self, "reserved", reserved)
        payload = _coerce_bytes(self.payload, param="payload")
        object.__setattr__(self, "payload", payload)
        floor = (self.payload_bits + 7) // 8
        if len(payload) < floor:
            raise T2miError(
                f"{T2MI_PACKET_PAYLOAD_BITS_OUT_OF_RANGE}: payload of "
                f"{len(payload)} byte(s) cannot carry payload_bits="
                f"{self.payload_bits} (needs at least {floor})"
            )

    # --- derived faces ---

    @property
    def superframe_index(self) -> int:
        """4-bit T2-MI superframe index (header byte 2 high nibble)."""
        return (self.reserved[0] >> 4) & _MASK_NIBBLE

    @property
    def payload_bytes_len(self) -> int:
        """Payload size in bytes (ceil of the bit length) — wire face."""
        return len(self.payload)

    @property
    def padding_bits(self) -> int:
        """Padding bits in the partial final payload byte (0 for aligned)."""
        return len(self.payload) * 8 - self.payload_bits

    @property
    def payload_kind(self) -> str:
        """MVP payload-kind state (``bbframe`` / ``padding`` / ``unknown``)."""
        if self.packet_type == T2MI_TYPE_BBFRAME:
            return PAYLOAD_KIND_BBFRAME
        if self.packet_type == T2MI_TYPE_PADDING:
            return PAYLOAD_KIND_PADDING
        return PAYLOAD_KIND_UNKNOWN

    @property
    def crc32_valid(self) -> bool:
        """CRC-32/MPEG-2 remainder over the full encoding must be zero."""
        return verify_mpeg2_crc32(encode_packet(self))

    @property
    def total_size(self) -> int:
        """Header + payload + CRC trailer size in bytes."""
        return T2MI_HEADER_SIZE + len(self.payload) + T2MI_CRC_SIZE

    @property
    def bbframe(self) -> bytes | None:
        """The BBFRAME bytes (after the 3-byte transport prefix), or None.

        Only meaningful for BBFRAME-type packets with the byte-aligned
        transport prefix (``frame_idx / PLP_id / flags``); padding and
        unknown packets carry ``None``.
        """
        if self.packet_type != T2MI_TYPE_BBFRAME or len(self.payload) < 3:
            return None
        return self.payload[3:]

    @property
    def frame_index(self) -> int | None:
        """BBFRAME transport-prefix frame_idx, or None for non-BBFRAME."""
        if self.packet_type != T2MI_TYPE_BBFRAME or len(self.payload) < 3:
            return None
        return self.payload[0]

    @property
    def plp_id(self) -> int | None:
        """BBFRAME transport-prefix PLP_id, or None for non-BBFRAME."""
        if self.packet_type != T2MI_TYPE_BBFRAME or len(self.payload) < 3:
            return None
        return self.payload[1]

    # --- encoding / single-packet decoding ---

    def to_bytes(self) -> bytes:
        """Alias of :func:`encode_packet` (method face for call sites)."""
        return encode_packet(self)

    @classmethod
    def from_encoded(cls, encoded: bytes) -> "T2miPacket":
        """Decode exactly one T2-MI packet from an exactly-sized slice.

        Strict sizing (house ruling #11 precedent): ``encoded`` must be
        exactly header + declared payload + CRC trailer long — extra or
        missing bytes raise ``T2MI_PACKET_ENCODED_SIZE_INVALID``. Stream
        framing (continuation, truncation) belongs to
        :func:`ts.t2mi.parser.parse`.
        """
        data = _coerce_bytes(encoded, param="encoded")
        if len(data) < T2MI_HEADER_SIZE:
            raise T2miError(
                f"{T2MI_PACKET_ENCODED_SIZE_INVALID}: need at least "
                f"{T2MI_HEADER_SIZE} header bytes, got {len(data)}"
            )
        payload_bits = int.from_bytes(
            data[_HEADER_PAYLOAD_BITS_OFFSET : _HEADER_PAYLOAD_BITS_OFFSET + 2], "big"
        )
        payload_len = (payload_bits + 7) // 8
        total = T2MI_HEADER_SIZE + payload_len + T2MI_CRC_SIZE
        if len(data) != total:
            raise T2miError(
                f"{T2MI_PACKET_ENCODED_SIZE_INVALID}: header declares "
                f"payload_bits={payload_bits} → total {total} bytes, got "
                f"{len(data)}"
            )
        return cls(
            packet_type=data[_HEADER_TYPE_OFFSET],
            packet_counter=data[_HEADER_COUNTER_OFFSET],
            reserved=data[_HEADER_RESERVED_OFFSET : _HEADER_RESERVED_OFFSET + _RESERVED_SIZE],
            payload_bits=payload_bits,
            payload=data[T2MI_HEADER_SIZE : T2MI_HEADER_SIZE + payload_len],
            crc32=int.from_bytes(data[T2MI_HEADER_SIZE + payload_len : total], "big"),
        )


def encode_packet(packet: T2miPacket) -> bytes:
    """Encode one packet: header + payload + stored CRC (verbatim).

    The CRC trailer is the *stored* value — never recomputed — so a
    packet whose CRC does not match its content (the ``crc32_valid=False``
    bad-packet face) re-encodes byte-identically. This is the preservation
    discipline the golden faulted vector depends on.
    """
    header = bytes(
        [
            packet.packet_type & _MASK8,
            packet.packet_counter & _MASK8,
            packet.reserved[0] & _MASK8,
            packet.reserved[1] & _MASK8,
        ]
    ) + packet.payload_bits.to_bytes(2, "big")
    body = header + packet.payload
    return body + packet.crc32.to_bytes(T2MI_CRC_SIZE, "big")


def compute_packet_crc32(header_and_payload: bytes) -> int:
    """CRC-32/MPEG-2 over header + payload (builder-side helper).

    Thin alias over :func:`ts.crc.mpeg2_crc32` kept here so callers do
    not need to know the trailer's exact CRC parameters; the encode face
    never calls it (stored value wins).
    """
    return mpeg2_crc32(_coerce_bytes(header_and_payload, param="header_and_payload"))


def make_header_reserved(superframe_index: int) -> bytes:
    """Build the 2-byte reserved field for a given superframe index.

    Reserved low nibble and byte 3 are zeroed (builder default; parser
    preserves whatever the stream carries).
    """
    checked = _require_int(
        superframe_index,
        "superframe_index",
        T2MI_PACKET_SUPERFRAME_OUT_OF_RANGE,
        _MASK_NIBBLE,
    )
    return bytes([(checked & _MASK_NIBBLE) << 4, 0x00])
