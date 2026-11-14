"""SPEC-104 — MPEG-2 PES packet core: header parse/serialize (ticket #30).

Standard-profile PES packet model (SPEC-104 §3/§4, ITU-T H.222.0 PES
packet syntax). Wire layout after the fixed 3-byte start code prefix
``00 00 01``:

- ``stream_id`` (8-bit), ``PES_packet_length`` (16-bit big-endian);
- 3 fixed control bytes: ``'10'`` marker + scrambling/priority/alignment/
  copyright/original bits, PES flags byte, ``PES_header_data_length``;
- header data (PTS/DTS fields only in MVP), then the PES payload.

Design invariants (SPEC-104 §3, contract §2):

- ``PES_packet_length`` counts the bytes following the 16-bit length
  field (3 control bytes + header data + payload), never the 6-byte
  prefix (§8).
- Timestamp encoding is delegated to SPEC-105 ``ts.timestamp``
  (``encode_pts``/``decode_pts``) — exactly one algorithm, none duplicated
  here (§6). This module only assembles/disassembles header bytes.
- Optional header features outside MVP (ESCR, ES rate, DSM trick mode,
  additional copy info, PES CRC, PES extension) raise
  ``PES_OPTIONAL_FIELD_UNSUPPORTED`` when flagged; their bytes are never
  misread as PTS or payload (§3). MVP carries no raw optional-header
  field (ruling #11 decision on SPEC-104).
- No implicit fixes: malformed input raises a typed
  :class:`ts.errors.InvalidPESPacketError` whose message starts with a
  SPEC-104 §9 error code. PTS/DTS value-range violations come from
  SPEC-105's own :class:`ts.errors.InvalidTimestampError` (range is
  33-bit domain semantics, SPEC-105 §7).

Error codes owned here (SPEC-104 §9, module-owned per contract §7
归属约定): ``PES_START_CODE_INVALID``, ``PES_HEADER_TRUNCATED``,
``PES_STREAM_ID_PROFILE_UNSUPPORTED``, ``PES_FLAGS_RESERVED``,
``PES_HEADER_DATA_LENGTH_INVALID``, ``PES_OPTIONAL_FIELD_UNSUPPORTED``,
``PES_PTS_DTS_FLAGS_INVALID``, ``PES_TIMESTAMP_MARKER_INVALID``,
``PES_PACKET_LENGTH_MISMATCH``, ``PES_LENGTH_ZERO_NOT_ALLOWED``.
Construction/serializer guards not enumerated by §9 (mirroring the #28
precedent of adding a noted construction-guard code):
``PES_PACKET_LENGTH_OUT_OF_RANGE`` (16-bit field capacity),
``PES_PACKET_LENGTH_MODE_INVALID`` (unknown ``packet_length_mode``).
Assembler-side codes live in :mod:`ts.pes_assembler`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ts.errors import InvalidPESPacketError, InvalidTimestampError
from ts.timestamp import (
    PTS_MAX,
    PTS_PREFIX_DTS,
    PTS_PREFIX_ONLY,
    PTS_PREFIX_PTS_DTS,
    PTS_VALUE_OUT_OF_RANGE,
    decode_pts,
    encode_pts,
)

# --- SPEC-104 §9 error codes owned by this module ---

PES_START_CODE_INVALID = "PES_START_CODE_INVALID"
PES_HEADER_TRUNCATED = "PES_HEADER_TRUNCATED"
PES_STREAM_ID_PROFILE_UNSUPPORTED = "PES_STREAM_ID_PROFILE_UNSUPPORTED"
PES_FLAGS_RESERVED = "PES_FLAGS_RESERVED"
PES_HEADER_DATA_LENGTH_INVALID = "PES_HEADER_DATA_LENGTH_INVALID"
PES_OPTIONAL_FIELD_UNSUPPORTED = "PES_OPTIONAL_FIELD_UNSUPPORTED"
PES_PTS_DTS_FLAGS_INVALID = "PES_PTS_DTS_FLAGS_INVALID"
PES_TIMESTAMP_MARKER_INVALID = "PES_TIMESTAMP_MARKER_INVALID"
PES_PACKET_LENGTH_MISMATCH = "PES_PACKET_LENGTH_MISMATCH"
PES_LENGTH_ZERO_NOT_ALLOWED = "PES_LENGTH_ZERO_NOT_ALLOWED"
# Construction/serializer guards (not enumerated in §9; see docstring).
PES_PACKET_LENGTH_OUT_OF_RANGE = "PES_PACKET_LENGTH_OUT_OF_RANGE"
PES_PACKET_LENGTH_MODE_INVALID = "PES_PACKET_LENGTH_MODE_INVALID"

# --- SPEC-104 §3 layout constants ---

#: Fixed PES start code prefix.
START_CODE_PREFIX: bytes = b"\x00\x00\x01"
#: 6-byte prefix (start code + stream_id + length) plus the 3 fixed
#: control bytes that every standard-profile PES header carries.
PES_HEADER_SIZE: int = 9
PTS_FIELD_SIZE: int = 5
DTS_FIELD_SIZE: int = 5

#: Special stream_ids use their own (non-standard) header grammar and are
#: rejected in the ``standard`` profile (H.222.0 2.4.3.7 list).
SPECIAL_STREAM_IDS: frozenset[int] = frozenset(
    {
        0xBC,  # program_stream_map
        0xBE,  # padding_stream
        0xBF,  # private_stream_2
        0xF0,  # ECM stream
        0xF1,  # EMM stream
        0xF2,  # DSMCC_stream
        0xF8,  # ITU-T H.222.1 type E
        0xFF,  # program_stream_directory
    }
)

#: Unbounded (``PES_packet_length == 0``) PES packets are only legal for
#: video stream_ids (H.222.0: 110x xxxx).
VIDEO_STREAM_ID_LOW: int = 0xE0
VIDEO_STREAM_ID_HIGH: int = 0xEF

#: The only parse profile in MVP (SPEC-104 §3: ``StandardPES``).
STANDARD_PROFILE: str = "standard"
#: Serialize modes: ``auto`` computes the length, ``zero`` writes the
#: unbounded video profile (SPEC-104 §3/§8).
PACKET_LENGTH_MODE_AUTO: str = "auto"
PACKET_LENGTH_MODE_ZERO: str = "zero"

#: ``analysis_only`` generation profile name (SPEC-104 §8): deterministic
#: test payloads, explicitly not playback-capable.
ANALYSIS_ONLY_PROFILE: str = "analysis_only"

_BYTES_LIKE = (bytes, bytearray, memoryview)


def _coerce_bytes(data: bytes, *, param: str) -> bytes:
    """Accept ``bytes``/``bytearray``/``memoryview``, reject everything else."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, _BYTES_LIKE):
        return bytes(data)
    raise TypeError(f"{param} must be a bytes-like object, got {type(data).__name__}")


def _is_video_stream_id(stream_id: int) -> bool:
    """True for video stream_ids 0xE0..0xEF (the unbounded-length profile)."""
    return VIDEO_STREAM_ID_LOW <= stream_id <= VIDEO_STREAM_ID_HIGH


@dataclass(frozen=True)
class AnalysisOnlyProfileMetadata:
    """Analysis-only generation profile metadata (SPEC-104 §8, REQ-104-006).

    Describes PES packets whose payload is a deterministic synthetic test
    payload: they are marked for analysis only and must never be presented
    as playback-capable (SPEC-104 §8: synthetic payloads must be flagged
    in Generator config/UI, never claimed decodable). ``playback_ready``
    is a frozen ``False`` by construction — the profile cannot assert
    decoding capability.
    """

    profile: str = ANALYSIS_ONLY_PROFILE
    playback_ready: bool = False
    payload_is_synthetic: bool = True
    deterministic: bool = True


#: Singleton metadata for the MVP analysis-only profile (REQ-104-006).
ANALYSIS_ONLY_PROFILE_METADATA = AnalysisOnlyProfileMetadata()

#: Deterministic default payload for analysis-only PES packets (§8: a
#: deterministic test payload with no decoding claim; no wall clock, no
#: randomness — same inputs give byte-identical output).
ANALYSIS_ONLY_DEFAULT_PAYLOAD: bytes = (
    b"DVB-Nexus analysis-only synthetic payload"
)


@dataclass(frozen=True)
class PESHeader:
    """Standard-profile PES header fields (SPEC-104 §4, exact shape).

    ``pts``/``dts`` are 33-bit 90 kHz ticks (0..2**33-1) or ``None``.
    Out-of-range values are rejected at the model boundary using
    SPEC-105's own constants and error code (SPEC-104 §6: 超范围拒绝，
    不静默 mask; the bit-level encoding itself stays single-sourced in
    ``ts.timestamp.encode_pts``).
    """

    stream_id: int
    pes_packet_length: int  # 0..65535
    pts: int | None = None  # 33-bit, 90 kHz
    dts: int | None = None  # 33-bit, 90 kHz
    pes_scrambling_control: int = 0
    pes_priority: bool = False
    data_alignment_indicator: bool = False
    copyright: bool = False
    original_or_copy: bool = False

    def __post_init__(self) -> None:
        """Reject field shapes that could never exist on the wire (§3/§4).

        ``stream_id`` must be an 8-bit value in a supported profile;
        ``pes_packet_length`` must fit the 16-bit wire field. Non-integer
        scalars are programming errors (``TypeError``).
        """
        if isinstance(self.stream_id, bool) or not isinstance(self.stream_id, int):
            raise TypeError(
                f"stream_id must be int, got {type(self.stream_id).__name__}"
            )
        if not 0 <= self.stream_id <= 0xFF:
            raise InvalidPESPacketError(
                f"{PES_STREAM_ID_PROFILE_UNSUPPORTED}: stream_id must be in "
                f"0..255 (8-bit), got {self.stream_id}"
            )
        if isinstance(self.pes_packet_length, bool) or not isinstance(
            self.pes_packet_length, int
        ):
            raise TypeError(
                "pes_packet_length must be int, got "
                f"{type(self.pes_packet_length).__name__}"
            )
        if not 0 <= self.pes_packet_length <= 0xFFFF:
            raise InvalidPESPacketError(
                f"{PES_PACKET_LENGTH_OUT_OF_RANGE}: pes_packet_length must "
                f"be in 0..65535 (16-bit), got {self.pes_packet_length}"
            )
        for name in ("pts", "dts"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"{name} must be int or None, got {type(value).__name__}"
                )
            if not 0 <= value <= PTS_MAX:
                raise InvalidTimestampError(
                    f"{PTS_VALUE_OUT_OF_RANGE}: {name} must be in "
                    f"0..{PTS_MAX} (33-bit, 90 kHz), got {value}"
                )
        if not 0 <= self.pes_scrambling_control <= 0b11:
            raise InvalidPESPacketError(
                f"{PES_FLAGS_RESERVED}: pes_scrambling_control must be in "
                f"0..3 (2-bit field), got {self.pes_scrambling_control}"
            )


@dataclass(frozen=True)
class PESPacket:
    """One PES packet: header + payload (SPEC-104 §4, exact shape).

    ``analysis_only`` marks deterministic synthetic test payloads
    (REQ-TS-104-006, SPEC-104 §8). It is construction-time metadata only:
    :func:`parse_pes` always yields ``False`` (the wire format carries no
    such bit — contract principle "协议字节是权威结果") and
    :func:`serialize_pes` ignores it, so the mark never alters PES bytes.
    """

    header: PESHeader
    payload: bytes
    analysis_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.header, PESHeader):
            raise TypeError(
                f"header must be PESHeader, got {type(self.header).__name__}"
            )
        payload = self.payload
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError(
                f"payload must be bytes, got {type(payload).__name__}"
            )
        object.__setattr__(self, "payload", bytes(payload))
        if not isinstance(self.analysis_only, bool):
            raise TypeError(
                f"analysis_only must be bool, got {type(self.analysis_only).__name__}"
            )


def _expected_header_data_length(pts: int | None, dts: int | None) -> int:
    """Header-data length implied by the PTS/DTS flags (§3: 0 / 5 / 10)."""
    if pts is None and dts is None:
        return 0
    if dts is None:
        return PTS_FIELD_SIZE
    return PTS_FIELD_SIZE + DTS_FIELD_SIZE


def make_analysis_only_pes(
    *,
    stream_id: int,
    payload: bytes | None = None,
    pts: int | None = None,
    dts: int | None = None,
    pes_packet_length: int = 0,
) -> PESPacket:
    """Build a deterministic synthetic PES marked analysis-only (§8).

    Analysis-only PES packets carry deterministic test payloads and are
    explicitly marked via :attr:`PESPacket.analysis_only`; they must never
    be presented as playback-capable (REQ-TS-104-006). The default payload
    is a fixed literal — the builder never reads wall clocks or random
    sources. The mark is construction metadata only: it does not alter
    serialized bytes and is never invented by :func:`parse_pes`.
    """
    return PESPacket(
        header=PESHeader(
            stream_id=stream_id,
            pes_packet_length=pes_packet_length,
            pts=pts,
            dts=dts,
        ),
        payload=(
            ANALYSIS_ONLY_DEFAULT_PAYLOAD if payload is None else bytes(payload)
        ),
        analysis_only=True,
    )


def _pes_flags_byte(header: PESHeader) -> int:
    """Byte 6: '10' marker | scrambling(2) | priority | align | cpr | orig."""
    return (
        0x80
        | ((header.pes_scrambling_control & 0b11) << 4)
        | (0x08 if header.pes_priority else 0x00)
        | (0x04 if header.data_alignment_indicator else 0x00)
        | (0x02 if header.copyright else 0x00)
        | (0x01 if header.original_or_copy else 0x00)
    )


def _pes_flags2_byte(header: PESHeader) -> int:
    """Byte 7: PTS_DTS_flags(2) | ESCR | ES_rate | DSM | copy | CRC | ext.

    MVP sets only the PTS_DTS_flags; every other optional feature is
    absent, so their flag bits are always 0 (§3).
    """
    if header.pts is None and header.dts is None:
        flags = 0b00
    elif header.dts is None:
        flags = 0b10
    else:
        flags = 0b11
    return flags << 6


def serialize_pes(
    packet: PESPacket, *, packet_length_mode: str = PACKET_LENGTH_MODE_AUTO
) -> bytes:
    """Serialize a :class:`PESPacket` to exact PES bytes (SPEC-104 §5/§8).

    ``packet_length_mode``:
    - ``"auto"``: compute ``PES_packet_length`` from content (3 control
      bytes + header data + payload, excluding the 6-byte prefix). A
      stored non-zero ``pes_packet_length`` must match the computed value
      (no silent rewrite — 无隐式修复); values above 65535 are rejected.
    - ``"zero"``: write the unbounded profile (``PES_packet_length == 0``),
      legal only for video stream_ids (§3).
    """
    if not isinstance(packet, PESPacket):
        raise TypeError(f"packet must be PESPacket, got {type(packet).__name__}")
    header = packet.header
    if header.stream_id in SPECIAL_STREAM_IDS:
        raise InvalidPESPacketError(
            f"{PES_STREAM_ID_PROFILE_UNSUPPORTED}: stream_id "
            f"0x{header.stream_id:02X} uses a special PES grammar that the "
            "standard profile does not implement"
        )
    if header.dts is not None and header.pts is None:
        raise InvalidPESPacketError(
            f"{PES_PTS_DTS_FLAGS_INVALID}: a DTS without a PTS has no legal "
            "PTS_DTS_flags encoding"
        )
    header_data_length = _expected_header_data_length(header.pts, header.dts)
    header_data = b""
    if header.pts is not None:
        prefix = (
            PTS_PREFIX_ONLY if header.dts is None else PTS_PREFIX_PTS_DTS
        )
        header_data += encode_pts(header.pts, prefix=prefix)
    if header.dts is not None:
        header_data += encode_pts(header.dts, prefix=PTS_PREFIX_DTS)
    computed_length = 3 + header_data_length + len(packet.payload)

    if packet_length_mode == PACKET_LENGTH_MODE_AUTO:
        if header.pes_packet_length != 0 and header.pes_packet_length != computed_length:
            raise InvalidPESPacketError(
                f"{PES_PACKET_LENGTH_MISMATCH}: stored pes_packet_length "
                f"{header.pes_packet_length} does not match the computed "
                f"length {computed_length}; rebuild the header with "
                "pes_packet_length=0 or fix the payload"
            )
        if computed_length > 0xFFFF:
            raise InvalidPESPacketError(
                f"{PES_PACKET_LENGTH_OUT_OF_RANGE}: computed "
                f"PES_packet_length {computed_length} exceeds the 16-bit "
                "field; reject or serialize with the zero-length video "
                "profile (SPEC-104 §8, no automatic truncation)"
            )
        length = computed_length
    elif packet_length_mode == PACKET_LENGTH_MODE_ZERO:
        if not _is_video_stream_id(header.stream_id):
            raise InvalidPESPacketError(
                f"{PES_LENGTH_ZERO_NOT_ALLOWED}: PES_packet_length=0 "
                f"(unbounded) is only legal for video stream_ids "
                f"{VIDEO_STREAM_ID_LOW:#04x}..{VIDEO_STREAM_ID_HIGH:#04x}, "
                f"got 0x{header.stream_id:02X}"
            )
        length = 0
    else:
        raise InvalidPESPacketError(
            f"{PES_PACKET_LENGTH_MODE_INVALID}: packet_length_mode must be "
            f"'{PACKET_LENGTH_MODE_AUTO}' or '{PACKET_LENGTH_MODE_ZERO}', "
            f"got {packet_length_mode!r}"
        )

    out = bytearray()
    out += START_CODE_PREFIX
    out.append(header.stream_id)
    out += length.to_bytes(2, "big")
    out.append(_pes_flags_byte(header))
    out.append(_pes_flags2_byte(header))
    out.append(header_data_length)
    out += header_data
    out += packet.payload
    return bytes(out)


def parse_pes(data: bytes, *, profile: str = STANDARD_PROFILE) -> PESPacket:
    """Parse exact PES bytes into a :class:`PESPacket` (SPEC-104 §5).

    Strict by design (contract §7): any structural violation raises
    :class:`ts.errors.InvalidPESPacketError` carrying a SPEC-104 §9 error
    code as message prefix. The declared-length check follows ruling #11
    trailing-bytes semantics: ``PES_packet_length != 0`` requires the
    input to be exactly ``6 + PES_packet_length`` bytes — no truncation
    and no trailing-byte consumption.
    """
    data = _coerce_bytes(data, param="data")
    if profile != STANDARD_PROFILE:
        raise InvalidPESPacketError(
            f"{PES_STREAM_ID_PROFILE_UNSUPPORTED}: profile {profile!r} is "
            f"not implemented; MVP supports '{STANDARD_PROFILE}' only"
        )
    if len(data) < PES_HEADER_SIZE:
        raise InvalidPESPacketError(
            f"{PES_HEADER_TRUNCATED}: a standard-profile PES header needs "
            f"{PES_HEADER_SIZE} bytes, got {len(data)}"
        )
    if data[:3] != START_CODE_PREFIX:
        raise InvalidPESPacketError(
            f"{PES_START_CODE_INVALID}: start code prefix must be "
            f"00 00 01, got {data[:3].hex(' ')}"
        )
    stream_id = data[3]
    if stream_id in SPECIAL_STREAM_IDS:
        raise InvalidPESPacketError(
            f"{PES_STREAM_ID_PROFILE_UNSUPPORTED}: stream_id "
            f"0x{stream_id:02X} uses a special PES grammar that the "
            "standard profile does not implement"
        )
    pes_packet_length = (data[4] << 8) | data[5]
    if data[6] & 0xC0 != 0x80:
        raise InvalidPESPacketError(
            f"{PES_FLAGS_RESERVED}: PES optional header must start with "
            f"the '10' marker, got bits {data[6] >> 6:#04b}"
        )
    pes_scrambling_control = (data[6] >> 4) & 0b11
    pes_priority = bool(data[6] & 0x08)
    data_alignment_indicator = bool(data[6] & 0x04)
    copyright = bool(data[6] & 0x02)
    original_or_copy = bool(data[6] & 0x01)
    pts_dts_flags = (data[7] >> 6) & 0b11
    unsupported_flags = data[7] & 0b0011_1111
    if pts_dts_flags == 0b01:
        raise InvalidPESPacketError(
            f"{PES_PTS_DTS_FLAGS_INVALID}: PTS_DTS_flags=01 is reserved/illegal"
        )
    if unsupported_flags:
        raise InvalidPESPacketError(
            f"{PES_OPTIONAL_FIELD_UNSUPPORTED}: optional header features "
            f"outside MVP are flagged (flags byte 0x{data[7]:02X}); their "
            "bytes would be misread as PTS/payload"
        )
    header_data_length = data[8]
    expected_hdl = _expected_header_data_length_from_flags(pts_dts_flags)
    if header_data_length != expected_hdl:
        raise InvalidPESPacketError(
            f"{PES_HEADER_DATA_LENGTH_INVALID}: PES_header_data_length "
            f"must be {expected_hdl} for PTS_DTS_flags={pts_dts_flags:#04b}, "
            f"got {header_data_length}"
        )
    if len(data) < PES_HEADER_SIZE + header_data_length:
        raise InvalidPESPacketError(
            f"{PES_HEADER_TRUNCATED}: header data needs "
            f"{PES_HEADER_SIZE + header_data_length} bytes, got {len(data)}"
        )

    pts: int | None = None
    dts: int | None = None
    header_data = data[PES_HEADER_SIZE : PES_HEADER_SIZE + header_data_length]
    try:
        if pts_dts_flags == 0b10:
            pts = decode_pts(header_data[0:5], expected_prefix=PTS_PREFIX_ONLY)
        elif pts_dts_flags == 0b11:
            pts = decode_pts(header_data[0:5], expected_prefix=PTS_PREFIX_PTS_DTS)
            dts = decode_pts(header_data[5:10], expected_prefix=PTS_PREFIX_DTS)
    except InvalidPESPacketError:
        raise
    except Exception as exc:  # SPEC-105 marker/prefix violations
        raise InvalidPESPacketError(
            f"{PES_TIMESTAMP_MARKER_INVALID}: PTS/DTS field rejected by "
            f"SPEC-105 decode: {exc}"
        ) from exc

    payload_start = PES_HEADER_SIZE + header_data_length
    if pes_packet_length == 0:
        if not _is_video_stream_id(stream_id):
            raise InvalidPESPacketError(
                f"{PES_LENGTH_ZERO_NOT_ALLOWED}: PES_packet_length=0 "
                f"(unbounded) is only legal for video stream_ids "
                f"{VIDEO_STREAM_ID_LOW:#04x}..{VIDEO_STREAM_ID_HIGH:#04x}, "
                f"got 0x{stream_id:02X}"
            )
        payload = data[payload_start:]
    else:
        total = 6 + pes_packet_length
        if len(data) != total:
            raise InvalidPESPacketError(
                f"{PES_PACKET_LENGTH_MISMATCH}: declared length implies "
                f"{total} bytes (6 + {pes_packet_length}), got {len(data)}"
            )
        payload = data[payload_start:total]
    header = PESHeader(
        stream_id=stream_id,
        pes_packet_length=pes_packet_length,
        pts=pts,
        dts=dts,
        pes_scrambling_control=pes_scrambling_control,
        pes_priority=pes_priority,
        data_alignment_indicator=data_alignment_indicator,
        copyright=copyright,
        original_or_copy=original_or_copy,
    )
    return PESPacket(header=header, payload=payload)


def _expected_header_data_length_from_flags(pts_dts_flags: int) -> int:
    """Wire-direction twin of ``_expected_header_data_length`` (0/5/10)."""
    if pts_dts_flags == 0b00:
        return 0
    if pts_dts_flags == 0b10:
        return PTS_FIELD_SIZE
    return PTS_FIELD_SIZE + DTS_FIELD_SIZE
