"""SPEC-100 — MPEG-2 TS adaptation field model, parse and encode.

Ownership (ticket #28): the ``AdaptationField`` value model (SPEC-100 §4),
its wire-length accounting and 188-byte frame fitting (SPEC-100 §5.2, §7.3
- §7.6). ``ts.packet`` imports the model from here; this module never
imports ``ts.packet`` (one-way dependency, no cycles).

Wire form (ITU-T H.222.0 adaptation_field):

- ``adaptation_field_length`` counts the bytes AFTER the length byte
  (0..183; 183 legal only for adaptation-only packets, ≤182 when a payload
  follows — SPEC-100 §5.2).
- Length 0 means no flags byte at all; it is represented by the
  :data:`ZERO_LENGTH_ADAPTATION_FIELD` marker (a field-less frozen
  subclass) so an object never sits in a non-serializable state (§4).
- Length ≥ 1: first body byte is the 8 flags, then — in flag order —
  PCR (6 bytes), OPCR (6 bytes), splice countdown (signed 8-bit),
  transport private data (1 length byte + data), adaptation extension.
- PCR/OPCR 6-byte encoding is SPEC-105's and is called, never duplicated
  (ruling #11, contract §9).
- Bytes after the last optional field up to the AF boundary are stuffing;
  they are preserved verbatim on parse (lossless round trip) and generated
  as ``0xFF`` on encode when a constructed field set falls short (§5.2).
- Unrecognized extension content is preserved opaquely in
  ``extension_raw`` (whole field incl. its length byte) — never silently
  dropped (§5.2, §7.5).

Error codes owned here (SPEC-100 §8, module-owned per contract §7 归属约定):
``TS_AF_LENGTH_INVALID``, ``TS_AF_FIELD_TRUNCATED``,
``TS_AF_EXTENSION_OPAQUE`` (informational), plus the construction guard
``TS_AF_FIELD_OUT_OF_RANGE`` (value/length violations of single AF fields
that §8 does not enumerate). All map to
:class:`ts.errors.InvalidPacketError` (contract §7 ``TS_*`` family).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ts.errors import InvalidPacketError
from ts.pcr import PCR, decode_pcr, encode_pcr

# --- SPEC-100 §8 error codes owned by this module ---

TS_AF_LENGTH_INVALID = "TS_AF_LENGTH_INVALID"
TS_AF_FIELD_TRUNCATED = "TS_AF_FIELD_TRUNCATED"
TS_AF_EXTENSION_OPAQUE = "TS_AF_EXTENSION_OPAQUE"
TS_AF_FIELD_OUT_OF_RANGE = "TS_AF_FIELD_OUT_OF_RANGE"

#: Splice countdown is a signed 8-bit two's-complement field.
SPLICE_COUNTDOWN_MIN = -128
SPLICE_COUNTDOWN_MAX = 127

#: transport_private_data_length is an 8-bit field (§5.2).
PRIVATE_DATA_MAX = 0xFF

#: adaptation_field_extension_length is an 8-bit field.
EXTENSION_MAX = 0xFF


class AdaptationFieldControl(IntEnum):
    """2-bit ``adaptation_field_control`` (SPEC-100 §3; ISO Table 2-4)."""

    RESERVED = 0b00
    PAYLOAD_ONLY = 0b01
    ADAPTATION_ONLY = 0b10
    ADAPTATION_AND_PAYLOAD = 0b11


@dataclass(frozen=True)
class AdaptationField:
    """One adaptation field, fields exactly as SPEC-100 §4.

    ``stuffing`` holds the raw bytes between the last optional field and
    the adaptation-field boundary. Parsed packets always carry an
    exactly-sized ``stuffing`` (so parse→serialize is byte-exact);
    programmatically built packets may leave it empty and let
    :func:`encode_adaptation_field` pad ``0xFF`` up to the frame target.
    """

    discontinuity_indicator: bool = False
    random_access_indicator: bool = False
    elementary_stream_priority_indicator: bool = False
    pcr: PCR | None = None
    opcr: PCR | None = None
    splice_countdown: int | None = None  # signed 8-bit
    transport_private_data: bytes | None = None
    extension_raw: bytes | None = None  # opaque extension body for round-trip
    stuffing: bytes = b""

    @property
    def is_zero_length(self) -> bool:
        """True for the length-0 AF marker (no flags byte on the wire)."""
        return False

    def __post_init__(self) -> None:
        """Validate field ranges; never mask or auto-fix values (§5.2/§8).

        Non-``PCR`` clock fields, non-bytes blobs and non-integer splice
        values are programming errors and raise ``TypeError``. Value range
        violations raise ``InvalidPacketError`` with module-owned codes.
        """
        for name in ("pcr", "opcr"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, PCR):
                raise TypeError(
                    f"AdaptationField.{name} must be ts.pcr.PCR or None, "
                    f"got {type(value).__name__}"
                )
        splice = self.splice_countdown
        if splice is not None:
            if isinstance(splice, bool) or not isinstance(splice, int):
                raise TypeError(
                    "AdaptationField.splice_countdown must be int or None, "
                    f"got {type(splice).__name__}"
                )
            if not SPLICE_COUNTDOWN_MIN <= splice <= SPLICE_COUNTDOWN_MAX:
                raise InvalidPacketError(
                    f"{TS_AF_FIELD_OUT_OF_RANGE}: splice_countdown must be "
                    f"{SPLICE_COUNTDOWN_MIN}..{SPLICE_COUNTDOWN_MAX} "
                    f"(signed 8-bit), got {splice}"
                )
        private = self.transport_private_data
        if private is not None:
            if not isinstance(private, (bytes, bytearray)):
                raise TypeError(
                    "AdaptationField.transport_private_data must be bytes "
                    f"or None, got {type(private).__name__}"
                )
            if len(private) > PRIVATE_DATA_MAX:
                raise InvalidPacketError(
                    f"{TS_AF_FIELD_OUT_OF_RANGE}: transport_private_data "
                    f"exceeds the 8-bit length field, got {len(private)} > "
                    f"{PRIVATE_DATA_MAX}"
                )
        extension = self.extension_raw
        if extension is not None:
            if not isinstance(extension, (bytes, bytearray)):
                raise TypeError(
                    "AdaptationField.extension_raw must be bytes or None, "
                    f"got {type(extension).__name__}"
                )
            # The whole extension field (length byte included) is opaque;
            # the leading length byte must still describe it exactly.
            if len(extension) < 1 or len(extension) != extension[0] + 1:
                raise InvalidPacketError(
                    f"{TS_AF_FIELD_OUT_OF_RANGE}: extension_raw must carry "
                    "the leading adaptation_field_extension_length byte "
                    f"(len == raw[0] + 1), got {len(extension)} bytes with "
                    f"declared length "
                    f"{extension[0] if len(extension) else 'n/a'}"
                )
        stuffing = self.stuffing
        if not isinstance(stuffing, (bytes, bytearray)):
            raise TypeError(
                f"AdaptationField.stuffing must be bytes, got "
                f"{type(stuffing).__name__}"
            )


@dataclass(frozen=True)
class _ZeroLengthAdaptationField(AdaptationField):
    """Marker for ``adaptation_field_length == 0`` (no flags byte).

    The public singleton is :data:`ZERO_LENGTH_ADAPTATION_FIELD`. It is a
    distinct class so an ``adaptation_field is not None`` packet can still
    carry AFC=11/length-0 without ambiguity against a length-1
    all-flags-zero field (SPEC-100 §5.2 "AF length 为 0 时，不存在 flags
    byte").
    """

    @property
    def is_zero_length(self) -> bool:
        """Always ``True`` — the wire form has no flags byte (§5.2)."""
        return True


#: Public length-0 adaptation field marker (all fields default).
ZERO_LENGTH_ADAPTATION_FIELD: AdaptationField = _ZeroLengthAdaptationField()


def af_encoded_length(af: AdaptationField) -> int:
    """Body byte count (after the length byte) the fields would encode to.

    For :data:`ZERO_LENGTH_ADAPTATION_FIELD` this is ``0``; otherwise
    flags + optional fields + explicit stuffing (the ``0xFF`` frame
    padding is added by :func:`encode_adaptation_field`, not counted here).
    """
    if af.is_zero_length:
        return 0
    length = 1  # flags byte
    if af.pcr is not None:
        length += 6
    if af.opcr is not None:
        length += 6
    if af.splice_countdown is not None:
        length += 1
    if af.transport_private_data is not None:
        length += 1 + len(af.transport_private_data)
    if af.extension_raw is not None:
        length += len(af.extension_raw)
    return length + len(af.stuffing)


def encode_adaptation_field(af: AdaptationField, target_body_length: int) -> bytes:
    """Encode ``af`` as length byte + body, fitting ``target_body_length``.

    ``target_body_length`` is 183 for adaptation-only packets and
    ``183 - len(payload)`` for adaptation+payload packets (SPEC-100 §5.2:
    length byte + AF body must exactly fill the 184 bytes after the
    header together with the payload). Short field sets are padded with
    ``0xFF`` stuffing; oversized field sets raise ``TS_AF_LENGTH_INVALID``
    — no silent truncation (contract §2.5).
    """
    if not isinstance(target_body_length, int) or isinstance(
        target_body_length, bool
    ):
        raise TypeError(
            f"target_body_length must be int, got "
            f"{type(target_body_length).__name__}"
        )
    if af.is_zero_length:
        if target_body_length != 0:
            raise InvalidPacketError(
                f"{TS_AF_LENGTH_INVALID}: a zero-length adaptation field "
                f"(no flags byte) requires target body length 0, got "
                f"{target_body_length}"
            )
        return b"\x00"
    if target_body_length < 1:
        raise InvalidPacketError(
            f"{TS_AF_LENGTH_INVALID}: a flags-bearing adaptation field "
            f"needs a body of at least 1 byte, got {target_body_length}"
        )
    flags = (
        (0x80 if af.discontinuity_indicator else 0x00)
        | (0x40 if af.random_access_indicator else 0x00)
        | (0x20 if af.elementary_stream_priority_indicator else 0x00)
        | (0x10 if af.pcr is not None else 0x00)
        | (0x08 if af.opcr is not None else 0x00)
        | (0x04 if af.splice_countdown is not None else 0x00)
        | (0x02 if af.transport_private_data is not None else 0x00)
        | (0x01 if af.extension_raw is not None else 0x00)
    )
    body = bytearray((flags,))
    if af.pcr is not None:
        body += encode_pcr(af.pcr)
    if af.opcr is not None:
        body += encode_pcr(af.opcr)
    if af.splice_countdown is not None:
        body.append(af.splice_countdown & 0xFF)
    if af.transport_private_data is not None:
        body.append(len(af.transport_private_data))
        body += af.transport_private_data
    if af.extension_raw is not None:
        body += af.extension_raw
    body += af.stuffing
    if len(body) > target_body_length:
        raise InvalidPacketError(
            f"{TS_AF_LENGTH_INVALID}: adaptation field content "
            f"({len(body)} bytes) does not fit the target body length "
            f"{target_body_length} for this payload size"
        )
    body += b"\xff" * (target_body_length - len(body))
    return bytes((target_body_length,)) + bytes(body)


def parse_adaptation_field(
    data: bytes, body_start: int, body_end: int
) -> tuple[AdaptationField, list[str]]:
    """Parse the AF body ``data[body_start:body_end]``.

    ``body_start`` is the offset of the flags byte (i.e. right after the
    length byte), ``body_end`` the exclusive AF boundary inside the
    188-byte packet. Every optional field is bounds-checked against
    ``body_end`` before it is consumed (SPEC-100 §7.3-7.4); truncated
    fields raise ``TS_AF_FIELD_TRUNCATED``. PCR/OPCR decoding is
    delegated to SPEC-105 (:func:`ts.pcr.decode_pcr`).

    Returns the field object plus informational codes collected during the
    lenient surface (currently ``TS_AF_EXTENSION_OPAQUE`` when an
    extension is preserved without being interpreted — §8 "信息项，不是
    错误").
    """
    info_codes: list[str] = []
    if body_end <= body_start:
        raise InvalidPacketError(
            f"{TS_AF_LENGTH_INVALID}: adaptation field body is empty but "
            "the length byte claims at least a flags byte"
        )
    flags = data[body_start]
    pos = body_start + 1
    if flags & 0x10:  # PCR_flag
        if pos + 6 > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: PCR field needs 6 bytes at "
                f"offset {pos}, only {body_end - pos} remain inside the "
                f"adaptation field"
            )
        pcr = decode_pcr(data[pos : pos + 6])
        pos += 6
    else:
        pcr = None
    if flags & 0x08:  # OPCR_flag
        if pos + 6 > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: OPCR field needs 6 bytes at "
                f"offset {pos}, only {body_end - pos} remain inside the "
                f"adaptation field"
            )
        opcr = decode_pcr(data[pos : pos + 6])
        pos += 6
    else:
        opcr = None
    splice_countdown = None
    if flags & 0x04:  # splice_countdown_flag
        if pos + 1 > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: splice countdown needs 1 byte "
                f"at offset {pos}, only {body_end - pos} remain inside the "
                f"adaptation field"
            )
        raw = data[pos]
        splice_countdown = raw - 256 if raw >= 0x80 else raw
        pos += 1
    transport_private_data = None
    if flags & 0x02:  # transport_private_data_flag
        if pos + 1 > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: transport_private_data_length "
                f"needs 1 byte at offset {pos}, only {body_end - pos} "
                "remain inside the adaptation field"
            )
        private_length = data[pos]
        pos += 1
        if pos + private_length > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: transport private data declares "
                f"{private_length} bytes at offset {pos}, only "
                f"{body_end - pos} remain inside the adaptation field"
            )
        transport_private_data = bytes(data[pos : pos + private_length])
        pos += private_length
    extension_raw = None
    if flags & 0x01:  # adaptation_field_extension_flag
        if pos + 1 > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: adaptation_field_extension_"
                f"length needs 1 byte at offset {pos}, only "
                f"{body_end - pos} remain inside the adaptation field"
            )
        extension_length = data[pos]
        pos += 1
        if pos + extension_length > body_end:
            raise InvalidPacketError(
                f"{TS_AF_FIELD_TRUNCATED}: adaptation extension declares "
                f"{extension_length} bytes at offset {pos}, only "
                f"{body_end - pos} remain inside the adaptation field"
            )
        # Opaque preservation, length byte included, never dropped (§7.5).
        extension_raw = bytes(data[pos - 1 : pos + extension_length])
        pos += extension_length
        info_codes.append(TS_AF_EXTENSION_OPAQUE)
    stuffing = bytes(data[pos:body_end])
    af = AdaptationField(
        discontinuity_indicator=bool(flags & 0x80),
        random_access_indicator=bool(flags & 0x40),
        elementary_stream_priority_indicator=bool(flags & 0x20),
        pcr=pcr,
        opcr=opcr,
        splice_countdown=splice_countdown,
        transport_private_data=transport_private_data,
        extension_raw=extension_raw,
        stuffing=stuffing,
    )
    return af, info_codes
