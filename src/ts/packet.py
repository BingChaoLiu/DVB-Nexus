"""SPEC-100 — MPEG-2 TS packet core (ticket #28).

188-byte transport stream packet model (SPEC-100 §4), header bit layout
(SPEC-100 §3, ITU-T H.222.0), strict boundary-checked parsing and exact
re-encoding. Design invariants (contract §2, SPEC-100 §4/§5):

- Fixed 188 bytes; ``from_bytes`` requires exactly that length and never
  scans for sync bytes (resynchronization belongs to SPEC-631).
- Header fields are packed bit-by-bit per the §3 table — byte 1 =
  TEI/PUSI/priority/PID-high(5), byte 2 = PID-low(8), byte 3 =
  TSC/AFC/CC. No native-struct alignment is relied upon.
- ``adaptation_field_control`` is derived from ``payload`` and
  ``adaptation_field`` presence; an object with neither is illegal (§4).
  The length-0 AF case is carried by
  :data:`ts.adaptation_field.ZERO_LENGTH_ADAPTATION_FIELD` so every
  constructed object stays serializable.
- No implicit fixes: malformed input either parses losslessly or raises a
  typed :class:`ts.errors.InvalidPacketError` carrying a SPEC-100 §8
  error code; reserved values are preserved verbatim and reported via
  :meth:`TSPacket.validate` / ``parse_issues`` instead of rewritten.

Error codes owned here (SPEC-100 §8, module-owned per contract §7
归属约定): ``TS_PACKET_SIZE_INVALID``, ``TS_SYNC_BYTE_INVALID``,
``TS_AFC_RESERVED``, ``TS_PID_OUT_OF_RANGE``, ``TS_CC_OUT_OF_RANGE``,
``TS_SCRAMBLING_RESERVED``, plus the construction guard
``TS_SCRAMBLING_OUT_OF_RANGE`` for non-2-bit scrambling values (§8
condition list does not enumerate it). All map to ``InvalidPacketError``.

Ruling #11 trailing-bytes semantics: strict parsers reject extra bytes —
``from_bytes`` rejects any input longer than 188 with
``TS_PACKET_SIZE_INVALID`` instead of silently consuming a prefix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ts._bytesutil import PID_MAX, _coerce_bytes
from ts.adaptation_field import (
    ZERO_LENGTH_ADAPTATION_FIELD,
    AdaptationField,
    AdaptationFieldControl,
    TS_AF_LENGTH_INVALID,
    af_encoded_length,
    encode_adaptation_field,
    parse_adaptation_field,
)
from ts.errors import InvalidPacketError
from ts.issues import ParseIssue, ValidationIssue

# --- SPEC-100 §3 constants ---

#: Fixed transport stream packet size (ITU-T H.222.0).
TS_PACKET_SIZE = 188
#: 4-byte packet header preceding the AF/payload region.
TS_HEADER_SIZE = 4
#: Fixed header sync byte.
TS_SYNC_BYTE = 0x47
#: Null packet PID (this module only provides the constant, §5.1).
PID_NULL = 0x1FFF

# --- SPEC-100 §8 error codes owned by this module ---

TS_PACKET_SIZE_INVALID = "TS_PACKET_SIZE_INVALID"
TS_SYNC_BYTE_INVALID = "TS_SYNC_BYTE_INVALID"
TS_AFC_RESERVED = "TS_AFC_RESERVED"
TS_PID_OUT_OF_RANGE = "TS_PID_OUT_OF_RANGE"
TS_CC_OUT_OF_RANGE = "TS_CC_OUT_OF_RANGE"
TS_SCRAMBLING_RESERVED = "TS_SCRAMBLING_RESERVED"
TS_SCRAMBLING_OUT_OF_RANGE = "TS_SCRAMBLING_OUT_OF_RANGE"

_CC_MAX = 0x0F
_TSC_MAX = 0b11

#: Canonical frame-geometry constants (review-fix F6: 183/184 single source).
#: The 184-byte post-header AF/payload region splits into the adaptation-only
#: AF body (length byte + body) and the payload-only region; every other
#: module derives its 183/184 names from these two.
#: Adaptation-only AF body: length byte + AF body == 183.
AF_ONLY_BODY_LENGTH = TS_PACKET_SIZE - TS_HEADER_SIZE - 1  # 183
#: Payload-only region: the full post-header region == 184.
PAYLOAD_ONLY_LENGTH = TS_PACKET_SIZE - TS_HEADER_SIZE  # 184


@dataclass(frozen=True)
class TSPacket:
    """One 188-byte MPEG-2 TS packet (fields exactly as SPEC-100 §4).

    ``parse_issues`` is the non-strict parse surface: issues found while
    parsing leniently (``from_bytes(..., strict=False)``) are recorded
    there instead of being silently swallowed. A strict-mode parse success
    always yields ``parse_issues == ()``. The field defaults to ``()`` so
    programmatically built packets are unaffected.
    """

    pid: int
    continuity_counter: int
    payload: bytes | None
    adaptation_field: AdaptationField | None = None
    transport_error_indicator: bool = False
    payload_unit_start_indicator: bool = False
    transport_priority: bool = False
    transport_scrambling_control: int = 0
    parse_issues: tuple[ParseIssue, ...] = field(default=())

    @property
    def adaptation_field_control(self) -> AdaptationFieldControl:
        """AFC derived from payload/AF presence (SPEC-100 §4)."""
        if self.payload is not None and self.adaptation_field is not None:
            return AdaptationFieldControl.ADAPTATION_AND_PAYLOAD
        if self.payload is not None:
            return AdaptationFieldControl.PAYLOAD_ONLY
        if self.adaptation_field is not None:
            return AdaptationFieldControl.ADAPTATION_ONLY
        raise InvalidPacketError(
            f"{TS_AFC_RESERVED}: a packet needs a payload or an adaptation "
            "field (AFC=00 is reserved/invalid)"
        )

    def __post_init__(self) -> None:
        """Reject field-range and frame-shape violations at construction.

        §8 assigns out-of-range PID/CC/TSC to 构造/序列化 rejection, and §4
        forbids non-serializable objects, so the payload/AF frame shape is
        fully checked here (sizes that could never encode to 188 bytes).
        Non-integer scalars and wrong-typed blobs are programming errors
        and raise ``TypeError``.
        """
        if isinstance(self.pid, bool) or not isinstance(self.pid, int):
            raise TypeError(f"pid must be int, got {type(self.pid).__name__}")
        if not 0 <= self.pid <= PID_MAX:
            raise InvalidPacketError(
                f"{TS_PID_OUT_OF_RANGE}: pid must be in 0..{PID_MAX} "
                f"(13-bit), got {self.pid}"
            )
        if isinstance(self.continuity_counter, bool) or not isinstance(
            self.continuity_counter, int
        ):
            raise TypeError(
                f"continuity_counter must be int, got "
                f"{type(self.continuity_counter).__name__}"
            )
        if not 0 <= self.continuity_counter <= _CC_MAX:
            raise InvalidPacketError(
                f"{TS_CC_OUT_OF_RANGE}: continuity_counter must be in "
                f"0..{_CC_MAX} (4-bit), got {self.continuity_counter}"
            )
        if isinstance(self.transport_scrambling_control, bool) or not isinstance(
            self.transport_scrambling_control, int
        ):
            raise TypeError(
                f"transport_scrambling_control must be int, got "
                f"{type(self.transport_scrambling_control).__name__}"
            )
        if not 0 <= self.transport_scrambling_control <= _TSC_MAX:
            raise InvalidPacketError(
                f"{TS_SCRAMBLING_OUT_OF_RANGE}: transport_scrambling_control "
                f"must be in 0..{_TSC_MAX} (2-bit), got "
                f"{self.transport_scrambling_control}"
            )
        payload = self.payload
        if payload is not None:
            if not isinstance(payload, (bytes, bytearray)):
                raise TypeError(
                    f"payload must be bytes or None, got {type(payload).__name__}"
                )
            payload = bytes(payload)
            object.__setattr__(self, "payload", payload)
        af = self.adaptation_field
        if af is not None and not isinstance(af, AdaptationField):
            raise TypeError(
                f"adaptation_field must be AdaptationField or None, got "
                f"{type(af).__name__}"
            )
        if payload is None and af is None:
            raise InvalidPacketError(
                f"{TS_AFC_RESERVED}: payload and adaptation_field are both "
                "absent (AFC=00 is reserved/invalid, SPEC-100 §4)"
            )
        if payload is not None and af is None:
            if len(payload) != PAYLOAD_ONLY_LENGTH:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: payload-only packets (AFC=01) "
                    f"carry exactly {PAYLOAD_ONLY_LENGTH} payload bytes, "
                    f"got {len(payload)}"
                )
        elif payload is None:
            # Adaptation-only (AFC=10): length byte + AF body fill 184.
            if af.is_zero_length:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: a zero-length adaptation field "
                    "cannot fill an adaptation-only packet"
                )
            if af_encoded_length(af) > AF_ONLY_BODY_LENGTH:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: adaptation field content "
                    f"({af_encoded_length(af)} bytes) exceeds the "
                    f"{AF_ONLY_BODY_LENGTH}-byte body of an "
                    "adaptation-only packet"
                )
        else:
            # Adaptation+payload (AFC=11): at least 1 payload byte (§5.2).
            if len(payload) < 1 or len(payload) > AF_ONLY_BODY_LENGTH:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: adaptation+payload packets "
                    f"carry 1..{AF_ONLY_BODY_LENGTH} payload bytes, got "
                    f"{len(payload)}"
                )
            body_target = AF_ONLY_BODY_LENGTH - len(payload)
            if af.is_zero_length:
                if len(payload) != AF_ONLY_BODY_LENGTH:
                    raise InvalidPacketError(
                        f"{TS_AF_LENGTH_INVALID}: a zero-length adaptation "
                        f"field leaves exactly {AF_ONLY_BODY_LENGTH} bytes "
                        f"of payload, got {len(payload)}"
                    )
            elif af_encoded_length(af) > body_target:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: adaptation field content "
                    f"({af_encoded_length(af)} bytes) exceeds the "
                    f"{body_target}-byte body left by a "
                    f"{len(payload)}-byte payload"
                )

    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = True) -> "TSPacket":
        """Parse exactly 188 bytes into a :class:`TSPacket` (SPEC-100 §6).

        ``strict=True`` (default) raises :class:`InvalidPacketError` on
        every structural error. ``strict=False`` is the diagnostic surface:
        recoverable findings are recorded in ``parse_issues`` (never
        silently swallowed), while errors that would produce a
        non-serializable object (wrong length, AFC=00, AF length outside
        the packet) still raise — §4 forbids non-serializable packets.

        Trailing bytes are rejected (ruling #11): inputs longer than
        ``TS_PACKET_SIZE`` raise ``TS_PACKET_SIZE_INVALID``; the parser
        never consumes a 188-byte prefix of a longer stream.
        """
        data = _coerce_bytes(data, param="data")
        if len(data) != TS_PACKET_SIZE:
            raise InvalidPacketError(
                f"{TS_PACKET_SIZE_INVALID}: expected exactly "
                f"{TS_PACKET_SIZE} bytes, got {len(data)} (no sync scan, no "
                "trailing-byte slicing)"
            )
        issues: list[ParseIssue] = []
        if data[0] != TS_SYNC_BYTE:
            if strict:
                raise InvalidPacketError(
                    f"{TS_SYNC_BYTE_INVALID}: sync byte must be 0x"
                    f"{TS_SYNC_BYTE:02X}, got 0x{data[0]:02X}"
                )
            issues.append(
                ParseIssue(
                    code=TS_SYNC_BYTE_INVALID,
                    message=(
                        f"sync byte must be 0x{TS_SYNC_BYTE:02X}, got "
                        f"0x{data[0]:02X}; packet re-serializes with the "
                        "canonical sync byte"
                    ),
                    offset=0,
                )
            )
        transport_error_indicator = bool(data[1] & 0x80)
        payload_unit_start_indicator = bool(data[1] & 0x40)
        transport_priority = bool(data[1] & 0x20)
        pid = ((data[1] & 0x1F) << 8) | data[2]
        transport_scrambling_control = (data[3] >> 6) & 0x03
        afc = (data[3] >> 4) & 0x03
        continuity_counter = data[3] & 0x0F
        if afc == int(AdaptationFieldControl.RESERVED):
            raise InvalidPacketError(
                f"{TS_AFC_RESERVED}: adaptation_field_control=00 is "
                "reserved/invalid (byte 3 bits 5-4)"
            )
        adaptation_field: AdaptationField | None = None
        payload: bytes | None = None
        pos = TS_HEADER_SIZE
        if afc & 0b10:  # adaptation field present
            af_length = data[pos]
            body_start = pos + 1
            body_end = body_start + af_length
            if body_end > TS_PACKET_SIZE:
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: adaptation field length "
                    f"{af_length} reaches offset {body_end}, beyond the "
                    f"{TS_PACKET_SIZE}-byte packet"
                )
            if afc == int(AdaptationFieldControl.ADAPTATION_ONLY):
                # §5.2: adaptation-only AF must fill all 184 bytes.
                if af_length != AF_ONLY_BODY_LENGTH:
                    raise InvalidPacketError(
                        f"{TS_AF_LENGTH_INVALID}: adaptation-only packets "
                        f"(AFC=10) need adaptation_field_length "
                        f"{AF_ONLY_BODY_LENGTH} (length byte + body = 184), "
                        f"got {af_length}"
                    )
            elif af_length > AF_ONLY_BODY_LENGTH - 1:
                # §5.2: AFC=11 leaves room for at least 1 payload byte.
                raise InvalidPacketError(
                    f"{TS_AF_LENGTH_INVALID}: adaptation_field_length "
                    f"{af_length} leaves no payload for an AFC=11 packet "
                    f"(max {AF_ONLY_BODY_LENGTH - 1})"
                )
            if af_length == 0:
                adaptation_field = ZERO_LENGTH_ADAPTATION_FIELD
            else:
                adaptation_field, info_codes = parse_adaptation_field(
                    data, body_start, body_end
                )
                if not strict:
                    # §8: TS_AF_EXTENSION_OPAQUE is an information item, not
                    # an error; it surfaces on the lenient diagnostic path
                    # only, so strict parse success keeps parse_issues == ().
                    issues.extend(
                        ParseIssue(
                            code=code,
                            message="adaptation field extension preserved "
                            "opaquely (not interpreted)",
                            offset=body_start,
                            severity="info",
                        )
                        for code in info_codes
                    )
            pos = body_end
        if afc & 0b01:  # payload present
            payload = data[pos:]
        return cls(
            pid=pid,
            continuity_counter=continuity_counter,
            payload=payload,
            adaptation_field=adaptation_field,
            transport_error_indicator=transport_error_indicator,
            payload_unit_start_indicator=payload_unit_start_indicator,
            transport_priority=transport_priority,
            transport_scrambling_control=transport_scrambling_control,
            parse_issues=tuple(issues),
        )

    def to_bytes(self) -> bytes:
        """Serialize to exactly 188 bytes, recomputing AFC/AF length (§7.6)."""
        afc = self.adaptation_field_control
        header = bytearray(TS_HEADER_SIZE)
        header[0] = TS_SYNC_BYTE
        header[1] = (
            (0x80 if self.transport_error_indicator else 0x00)
            | (0x40 if self.payload_unit_start_indicator else 0x00)
            | (0x20 if self.transport_priority else 0x00)
            | ((self.pid >> 8) & 0x1F)
        )
        header[2] = self.pid & 0xFF
        header[3] = (
            ((self.transport_scrambling_control & 0x03) << 6)
            | (int(afc) << 4)
            | (self.continuity_counter & 0x0F)
        )
        out = bytearray(header)
        if self.adaptation_field is not None:
            if afc == AdaptationFieldControl.ADAPTATION_ONLY:
                target = AF_ONLY_BODY_LENGTH
            else:
                target = AF_ONLY_BODY_LENGTH - len(self.payload or b"")
            out += encode_adaptation_field(self.adaptation_field, target)
        if self.payload is not None:
            out += self.payload
        if len(out) != TS_PACKET_SIZE:  # pragma: no cover - post_init guards
            raise InvalidPacketError(
                f"{TS_AF_LENGTH_INVALID}: serialization produced "
                f"{len(out)} bytes instead of {TS_PACKET_SIZE}"
            )
        return bytes(out)

    def validate(self) -> list[ValidationIssue]:
        """Semantic validation findings (contract §6 issue shape, §5.3).

        Structural rules are enforced at construction/parse time, so the
        semantic layer only reports reserved-value usages: scrambling
        control ``01`` is preserved verbatim and flagged here.
        """
        issues: list[ValidationIssue] = []
        if self.transport_scrambling_control == 0b01:
            issues.append(
                ValidationIssue(
                    code=TS_SCRAMBLING_RESERVED,
                    message="transport_scrambling_control=01 is a reserved "
                    "value; the original 2-bit value is preserved",
                    severity="warning",
                    field="transport_scrambling_control",
                )
            )
        return issues
