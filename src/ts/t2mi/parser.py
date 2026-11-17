"""SPEC-600 §6/§7/§8 — T2-MI stream parser (ticket #122).

``parse(stream) -> T2miParseResult``: deterministic, allocation-light
decode of a back-to-back T2-MI packet byte stream (TS 102 773 §5.1).
The result is a ``Sequence`` of :class:`ts.t2mi.packet.T2miPacket`
(SPEC-600 §6 interface contract) plus the explicit degradation faces:

- CRC-32 failure → packet marked ``crc32_valid=False``, parsing
  **continues** — nothing is silently dropped (SPEC-600 §8; the #104
  TSDuck 3.45 lesson is a red line, 静默丢弃为零);
- unknown ``packet_type`` → explicit ``payload_kind="unknown"`` state,
  registration progresses without error stacks (§8 注册表渐进);
- padding/stuffing byte identity (type ``0xFF``) → explicit
  ``payload_kind="padding"`` state, counted, never skipped;
- truncated / non-integral tail → explicit truncation state on the
  result: ``truncated=True`` plus the verbatim ``trailing`` bytes —
  the parser has **no scan/resync/skip mode** (house ruling #11
  precedent), so inter-packet stuffing surfaces as truncation instead
  of being consumed silently (the #104 demux-stall pathology made
  visible).

Determinism (§7): same byte stream → same packet sequence, same bad
marks, same trailing bytes. No wall clock, no I/O, no state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, overload

from ts._bytesutil import _coerce_bytes
from ts.t2mi.packet import T2MI_HEADER_SIZE, T2miPacket

__all__ = [
    "T2miParseResult",
    "parse",
]


@dataclass(frozen=True)
class T2miParseResult:
    """Parse outcome: the packet sequence plus explicit degradation faces.

    Implements the ``Sequence`` protocol over :attr:`packets` so the
    ``t2mi.parse(stream) -> Sequence[T2miPacket]`` interface contract
    (SPEC-600 §6) holds literally, while the truncation state stays
    addressable on the same object.
    """

    packets: tuple[T2miPacket, ...]
    truncated: bool = False
    trailing: bytes = field(default=b"", repr=False)

    @property
    def trailing_bytes(self) -> int:
        """Size of the incomplete tail (0 when the stream is integral)."""
        return len(self.trailing)

    def __len__(self) -> int:
        return len(self.packets)

    def __iter__(self) -> Iterator[T2miPacket]:
        return iter(self.packets)

    @overload
    def __getitem__(self, index: int) -> T2miPacket: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T2miPacket, ...]: ...

    def __getitem__(self, index: int | slice) -> T2miPacket | tuple[T2miPacket, ...]:
        return self.packets[index]


def parse(stream: bytes) -> T2miParseResult:
    """Parse a back-to-back T2-MI packet stream (SPEC-600 §6).

    Args:
        stream: the T2-MI byte stream (``bytes``/``bytearray``/
            ``memoryview``) — exactly what the T2-MI layer receives from
            the outer demux framing; no PID framing here.

    Returns:
        :class:`T2miParseResult` — a ``Sequence`` of packets with
        ``truncated`` / ``trailing`` carrying the explicit truncation
        face. Bad CRC and unknown types stay in the sequence, marked
        (SPEC-600 §8: 显式标记继续解析).
    """
    data = _coerce_bytes(stream, param="stream")
    packets: list[T2miPacket] = []
    position = 0
    total = len(data)
    truncated = False
    while position < total:
        remaining = total - position
        if remaining < T2MI_HEADER_SIZE:
            truncated = True
            break
        payload_bits = int.from_bytes(data[position + 4 : position + 6], "big")
        payload_len = (payload_bits + 7) // 8
        packet_size = T2MI_HEADER_SIZE + payload_len + 4
        if remaining < packet_size:
            truncated = True
            break
        packets.append(
            T2miPacket.from_encoded(data[position : position + packet_size])
        )
        position += packet_size  # back-to-back: no gap is ever skipped
    return T2miParseResult(
        packets=tuple(packets),
        truncated=truncated,
        trailing=data[position:] if truncated else b"",
    )
