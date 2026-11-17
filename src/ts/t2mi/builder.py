"""SPEC-600 §6/§7/§8 — T2-MI encapsulator (ticket #122).

``build(bbframes, config) -> tuple[T2miPacket, ...]``: deterministic,
one-to-one encapsulation of a BBFRAME sequence into T2-MI packets
(TS 102 773 §5.1 — one BBFRAME per BBFRAME-type T2-MI packet). Each
packet payload is the byte-aligned transport prefix
``frame_idx(1) + PLP_id(1) + flags(1)`` (interleaving_frame_start bit at
``0x80``, TSDuck byte-aligned layout, research #104 §3.1) followed by the
BBFRAME itself.

Invariants (SPEC-600 §7):

- **Determinism**: same frames + same config (+ same ``plp_ids``) → same
  packet sequence, byte for byte (§7 同 config 同输入必同输出).
- **packet_counter continuity**: counters start at
  ``config.first_packet_counter`` and advance by one per packet,
  wrapping modulo 256; frame indexes do the same from
  ``config.first_frame_index``.
- **Back-to-back tight packing**: the builder emits *nothing* between
  packets — no padding packets, no stuffing. The discipline is encoded
  in the API itself: ``T2miBuildConfig.inter_frame_padding`` exists only
  to be refused at construction time (any nonzero value raises
  ``T2MI_CONFIG_INTER_FRAME_PADDING_FORBIDDEN``), so a padded stream
  cannot be constructed by accident or by misuse (#104: padding between
  T2-MI packets stalls downstream demux permanently).
- **Prepare-before-refuse**: malformed input is rejected before the
  first packet is produced — empty sequence, non-bytes frames, frames
  shorter than a BBHEADER, and frames whose data field is not a whole
  multiple of the user-packet length (the "非 188 倍数段" face; the
  partial-UP tail frame is refused here at the T2-MI boundary, while a
  *smaller but whole-UP* tail frame is legal and preserved — the #105
  multi-UP-tail lesson).

BBFRAME internals (BBHEADER fields, CRC-8, ISSY/NPD) are SPEC-601's
domain (#123); the encapsulator only knows the 10-byte boundary and the
UP alignment discipline. Error codes owned here (contract §7 归属约定):
``T2MI_CONFIG_*`` and ``T2MI_BUILD_*``, all raised as
:class:`ts.t2mi.errors.T2miError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ts._bytesutil import _coerce_bytes
from ts.crc import mpeg2_crc32
from ts.t2mi.errors import T2miError
from ts.t2mi.packet import (
    T2MI_BBHEADER_SIZE,
    T2MI_TYPE_BBFRAME,
    T2miPacket,
    make_header_reserved,
)

__all__ = [
    "T2MI_INTERLEAVING_FRAME_START_FLAG",
    "T2miBuildConfig",
    "build",
]

# --- error codes owned by this module ---

T2MI_CONFIG_PLP_OUT_OF_RANGE = "T2MI_CONFIG_PLP_OUT_OF_RANGE"
T2MI_CONFIG_COUNTER_OUT_OF_RANGE = "T2MI_CONFIG_COUNTER_OUT_OF_RANGE"
T2MI_CONFIG_FRAME_INDEX_OUT_OF_RANGE = "T2MI_CONFIG_FRAME_INDEX_OUT_OF_RANGE"
T2MI_CONFIG_SUPERFRAME_OUT_OF_RANGE = "T2MI_CONFIG_SUPERFRAME_OUT_OF_RANGE"
T2MI_CONFIG_UPL_INVALID = "T2MI_CONFIG_UPL_INVALID"
T2MI_CONFIG_INTER_FRAME_PADDING_FORBIDDEN = "T2MI_CONFIG_INTER_FRAME_PADDING_FORBIDDEN"
T2MI_BUILD_EMPTY = "T2MI_BUILD_EMPTY"
T2MI_BUILD_FRAME_SHORT = "T2MI_BUILD_FRAME_SHORT"
T2MI_BUILD_FRAME_NOT_UP_ALIGNED = "T2MI_BUILD_FRAME_NOT_UP_ALIGNED"
T2MI_BUILD_PLP_SEQUENCE_MISMATCH = "T2MI_BUILD_PLP_SEQUENCE_MISMATCH"

#: interleaving_frame_start flag bit in the BBFRAME transport prefix.
T2MI_INTERLEAVING_FRAME_START_FLAG = 0x80

_COUNTER_MODULUS = 256


@dataclass(frozen=True)
class T2miBuildConfig:
    """Encapsulator configuration (SPEC-600 §6/§7; wire face minimal).

    Attributes:
        plp_id: PLP id stamped into every BBFRAME transport prefix
            (0..255). Per-frame PLP assignment (SPEC-602) is passed as
            the ``plp_ids`` argument of :func:`build` by #124.
        first_packet_counter: packet_counter of the first produced
            packet (0..255); continuity wraps modulo 256.
        first_frame_index: BBFRAME transport-prefix frame_idx of the
            first frame (0..255), wrapping modulo 256.
        superframe_index: 4-bit T2-MI superframe index (0..15).
        interleaving_frame_start: value of the interleaving_frame_start
            flag bit in every transport prefix (True matches the #104
            research baseline where each frame starts an interleave
            frame; #123 may drive per-frame flags via the packet face).
        upl_bytes: user-packet length the data field must be a whole
            multiple of (188 for TS Normal Mode; the UP-alignment
            rejection face is configurable for non-NM experiments).
        inter_frame_padding: must stay 0 — any nonzero value is refused
            at construction (背靠背紧排纪律, SPEC-600 §8).

    All violations raise :class:`ts.t2mi.errors.T2miError` at
    construction time (prepare 前拒绝纪律).
    """

    plp_id: int = 0
    first_packet_counter: int = 0
    first_frame_index: int = 0
    superframe_index: int = 0
    interleaving_frame_start: bool = True
    upl_bytes: int = 188
    inter_frame_padding: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.plp_id, bool) or not isinstance(self.plp_id, int) or not (
            0 <= self.plp_id <= 0xFF
        ):
            raise T2miError(
                f"{T2MI_CONFIG_PLP_OUT_OF_RANGE}: plp_id out of range 0..255, "
                f"got {self.plp_id!r}"
            )
        for name, code, upper in (
            ("first_packet_counter", T2MI_CONFIG_COUNTER_OUT_OF_RANGE, 0xFF),
            ("first_frame_index", T2MI_CONFIG_FRAME_INDEX_OUT_OF_RANGE, 0xFF),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not (
                0 <= value <= upper
            ):
                raise T2miError(
                    f"{code}: {name} out of range 0..{upper}, got {value!r}"
                )
        if isinstance(self.superframe_index, bool) or not isinstance(
            self.superframe_index, int
        ) or not 0 <= self.superframe_index <= 0x0F:
            raise T2miError(
                f"{T2MI_CONFIG_SUPERFRAME_OUT_OF_RANGE}: superframe_index out "
                f"of range 0..15, got {self.superframe_index!r}"
            )
        if (
            isinstance(self.upl_bytes, bool)
            or not isinstance(self.upl_bytes, int)
            or self.upl_bytes < 1
        ):
            raise T2miError(
                f"{T2MI_CONFIG_UPL_INVALID}: upl_bytes must be a positive int, "
                f"got {self.upl_bytes!r}"
            )
        if self.inter_frame_padding != 0:
            raise T2miError(
                f"{T2MI_CONFIG_INTER_FRAME_PADDING_FORBIDDEN}: inter-frame "
                f"padding {self.inter_frame_padding} requested — back-to-back "
                "tight packing is a correctness requirement (SPEC-600 §3/§8); "
                "the encapsulator never inserts padding between packets"
            )


def _validate_frames(bbframes: Sequence[bytes], upl_bytes: int) -> list[bytes]:
    """Prepare-time validation: nothing is produced for malformed input."""
    frames = [_coerce_bytes(frame, param="bbframes[i]") for frame in bbframes]
    for index, frame in enumerate(frames):
        if len(frame) <= T2MI_BBHEADER_SIZE:
            raise T2miError(
                f"{T2MI_BUILD_FRAME_SHORT}: bbframes[{index}] has {len(frame)} "
                f"byte(s); a BBFRAME is BBHEADER ({T2MI_BBHEADER_SIZE}) plus a "
                "non-empty data field"
            )
        datafield_len = len(frame) - T2MI_BBHEADER_SIZE
        if datafield_len % upl_bytes != 0:
            raise T2miError(
                f"{T2MI_BUILD_FRAME_NOT_UP_ALIGNED}: bbframes[{index}] data "
                f"field is {datafield_len} byte(s), not a whole multiple of "
                f"upl_bytes={upl_bytes} (非 188 倍数段 prepare 前拒绝, "
                "SPEC-600 §8)"
            )
    return frames


def build(
    bbframes: Sequence[bytes],
    config: T2miBuildConfig,
    *,
    plp_ids: Sequence[int] | None = None,
) -> tuple[T2miPacket, ...]:
    """Encapsulate BBFRAMEs back-to-back into T2-MI packets (SPEC-600 §6).

    Args:
        bbframes: one BBFRAME per element — ``BBHEADER (10 bytes) +
            data field``; the data field must be a whole multiple of
            ``config.upl_bytes`` (188 for TS Normal Mode).
        config: :class:`T2miBuildConfig` (validated at construction).
        plp_ids: optional per-frame PLP override (SPEC-602 assignment
            face, consumed by #124); must match the frame count and each
            be in 0..255.

    Returns:
        A tuple of packets whose counters are continuous, payloads are
        byte-aligned (zero padding bits), and CRC-32 trailers are
        computed over header + payload. Encoding the result with
        :func:`ts.t2mi.packet.encode_packet` and concatenating yields the
        back-to-back T2-MI byte stream.
    """
    frames = _validate_frames(bbframes, config.upl_bytes)
    if not frames:
        raise T2miError(
            f"{T2MI_BUILD_EMPTY}: bbframes sequence is empty — the "
            "encapsulator produces at least one packet or refuses"
        )
    if plp_ids is None:
        per_frame_plp: list[int] = [config.plp_id] * len(frames)
    else:
        if len(plp_ids) != len(frames):
            raise T2miError(
                f"{T2MI_BUILD_PLP_SEQUENCE_MISMATCH}: plp_ids has "
                f"{len(plp_ids)} entr(y/ies) for {len(frames)} frame(s)"
            )
        per_frame_plp = []
        for index, plp_id in enumerate(plp_ids):
            if isinstance(plp_id, bool) or not isinstance(plp_id, int) or not (
                0 <= plp_id <= 0xFF
            ):
                raise T2miError(
                    f"{T2MI_CONFIG_PLP_OUT_OF_RANGE}: plp_ids[{index}] out of "
                    f"range 0..255, got {plp_id!r}"
                )
            per_frame_plp.append(plp_id)

    reserved = make_header_reserved(config.superframe_index)
    flag = T2MI_INTERLEAVING_FRAME_START_FLAG if config.interleaving_frame_start else 0x00
    packets: list[T2miPacket] = []
    for offset, frame in enumerate(frames):
        payload = bytes(
            [
                (config.first_frame_index + offset) % _COUNTER_MODULUS,
                per_frame_plp[offset],
                flag,
            ]
        ) + frame
        header_prefix = bytes(
            [
                T2MI_TYPE_BBFRAME,
                (config.first_packet_counter + offset) % _COUNTER_MODULUS,
                reserved[0],
                reserved[1],
            ]
        ) + (len(payload) * 8).to_bytes(2, "big")
        packets.append(
            T2miPacket(
                packet_type=T2MI_TYPE_BBFRAME,
                packet_counter=(config.first_packet_counter + offset) % _COUNTER_MODULUS,
                reserved=reserved,
                payload_bits=len(payload) * 8,
                payload=payload,
                crc32=mpeg2_crc32(header_prefix + payload),
            )
        )
    return tuple(packets)
