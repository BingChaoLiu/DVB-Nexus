"""SPEC-104 — PESAssembler: TS payload reassembly (ticket #30).

Reassembles PES packets from the payloads of :class:`ts.packet.TSPacket`
objects on one PID (SPEC-104 §5/§7). The assembler consumes ONLY
``TSPacket.payload`` — adaptation field bytes are never treated as PES
payload (§7.5) and payload ``0xFF`` stuffing is never stripped (§7.7).

State machine (§7):

- ``PUSI=1`` starts a new PES from that payload. An active incomplete PES
  is resolved first per its profile: a **bounded** PES (declared length
  not reached) and any not-yet-measured PES report
  ``PES_TRUNCATED_AT_NEW_START``; an **unbounded** (zero-length video)
  PES completes at the boundary and is emitted, then the new PES starts
  (§7.1/§7.4).
- ``PUSI=0`` only appends to the active continuation. Without an active
  PES the bytes are dropped with ``PES_CONTINUATION_WITHOUT_START``
  (§7.2 — mid-stream bytes are never guessed into a PES start).
- A bounded PES is emitted when exactly ``6 + PES_packet_length`` bytes
  accumulated. Bytes after the completion boundary inside the same
  payload are dropped with ``PES_CONTINUATION_WITHOUT_START`` (§7.3
  MVP policy: a conformant TS never starts a PES mid-payload, so the
  bytes cannot belong to a new PES; they are evidenced, never silently
  lost).
- The accumulation buffer is hard-bounded by ``max_buffer_bytes``;
  exceeding it reports ``PES_BUFFER_LIMIT_EXCEEDED`` and resets the
  current PES (§7.4 — prevents unbounded memory growth, REQ-104-005).
- ``TEI=1``, PID mismatch and ``discontinuity_indicator=1`` discard the
  current PES and record an evidence issue (§7.6). MVP has no
  configuration knobs, so discard-with-evidence is the fixed behavior.

Issues accumulate internally and are drained by :meth:`flush`, which
also reports an incomplete PES at end-of-input as
``PES_TRUNCATED_AT_EOF`` (flush is issues-only per the frozen §5
signature, so an unbounded PES reaching EOF is reported rather than
fabricated-complete or silently discarded — mirroring SPEC-102's flush
discipline of never faking a complete unit). Offsets in issues refer to
positions inside the accumulated PES buffer (or ``None`` when the
problem is packet-level and not attributable to payload bytes).

Error codes owned here (SPEC-104 §9, module-owned per contract §7
归属约定): ``PES_BUFFER_LIMIT_EXCEEDED``,
``PES_CONTINUATION_WITHOUT_START``, ``PES_TRUNCATED_AT_NEW_START``,
``PES_TRUNCATED_AT_EOF``. Evidence codes required by §7.6 but not
enumerated in §9 (added per the #28 precedent of noted guard codes):
``PES_PID_MISMATCH``, ``PES_TRANSPORT_ERROR``, ``PES_DISCONTINUITY``.
All map to :class:`ts.errors.InvalidPESPacketError` (contract §7).
"""

from __future__ import annotations

from ts.errors import InvalidPESPacketError, InvalidPacketError
from ts.issues import ParseIssue
from ts.packet import TS_PID_OUT_OF_RANGE, TSPacket
from ts.pes import (
    PES_LENGTH_ZERO_NOT_ALLOWED,
    SPECIAL_STREAM_IDS,
    PESPacket,
    parse_pes,
)

# --- SPEC-104 §9 error codes owned by this module ---

PES_BUFFER_LIMIT_EXCEEDED = "PES_BUFFER_LIMIT_EXCEEDED"
PES_CONTINUATION_WITHOUT_START = "PES_CONTINUATION_WITHOUT_START"
PES_TRUNCATED_AT_NEW_START = "PES_TRUNCATED_AT_NEW_START"
PES_TRUNCATED_AT_EOF = "PES_TRUNCATED_AT_EOF"
# §7.6 evidence codes (not enumerated in §9; see docstring).
PES_PID_MISMATCH = "PES_PID_MISMATCH"
PES_TRANSPORT_ERROR = "PES_TRANSPORT_ERROR"
PES_DISCONTINUITY = "PES_DISCONTINUITY"

_START_CODE_PREFIX = b"\x00\x00\x01"
_VIDEO_STREAM_ID_LOW = 0xE0
_VIDEO_STREAM_ID_HIGH = 0xEF


def _issue_from_exception(exc: Exception, *, offset: int | None) -> ParseIssue:
    """Turn a typed ts-core error into a ParseIssue evidence record.

    Every ts-core parse error message starts with its error code
    (``CODE: details``); the prefix is reused as the issue code so the
    SPEC-104 §9 code set stays single-sourced.
    """
    text = str(exc)
    code = text.split(":", 1)[0].strip() if ":" in text else text
    return ParseIssue(code=code, message=text, offset=offset)


class PESAssembler:
    """Assemble PES packets from TS packet payloads on one PID (§5)."""

    def __init__(self, pid: int, *, max_buffer_bytes: int) -> None:
        """Bind the assembler to ``pid`` with a hard buffer cap (§7.4)."""
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise TypeError(f"pid must be int, got {type(pid).__name__}")
        if not 0 <= pid <= 0x1FFF:
            raise InvalidPacketError(
                f"{TS_PID_OUT_OF_RANGE}: pid must be in 0..8191 (13-bit), "
                f"got {pid}"
            )
        if isinstance(max_buffer_bytes, bool) or not isinstance(
            max_buffer_bytes, int
        ):
            raise TypeError(
                "max_buffer_bytes must be int, got "
                f"{type(max_buffer_bytes).__name__}"
            )
        if max_buffer_bytes < 1:
            raise ValueError(
                f"max_buffer_bytes must be >= 1, got {max_buffer_bytes}"
            )
        self._pid = pid
        self._max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()
        self._prefix_checked = False
        self._length_read = False
        self._declared_total: int | None = None  # None => unbounded/unknown
        self._issues: list[ParseIssue] = []

    # --- public API (SPEC-104 §5 frozen signatures) ---

    def push(self, packet: TSPacket) -> list[PESPacket]:
        """Consume one TS packet; return PES packets completed by it."""
        if not isinstance(packet, TSPacket):
            raise TypeError(
                f"packet must be TSPacket, got {type(packet).__name__}"
            )
        if packet.pid != self._pid:
            self._discard_active()
            self._issues.append(
                ParseIssue(
                    code=PES_PID_MISMATCH,
                    message=(
                        f"assembler is bound to pid {self._pid}, got a "
                        f"packet with pid {packet.pid}; current PES discarded"
                    ),
                    offset=None,
                )
            )
            return []
        if packet.transport_error_indicator:
            # §7.6: uncorrectable errors — payload is untrusted.
            self._discard_active()
            self._issues.append(
                ParseIssue(
                    code=PES_TRANSPORT_ERROR,
                    message=(
                        "TEI=1 packet dropped; current PES discarded and "
                        "packet payload not consumed"
                    ),
                    offset=None,
                )
            )
            return []
        af = packet.adaptation_field
        if af is not None and af.discontinuity_indicator:
            # §7.6: explicit discontinuity interrupts the current PES;
            # this packet's own payload is still processed normally.
            self._discard_active()
            self._issues.append(
                ParseIssue(
                    code=PES_DISCONTINUITY,
                    message=(
                        "adaptation field discontinuity_indicator=1; "
                        "current PES discarded as possibly incomplete"
                    ),
                    offset=None,
                )
            )

        payload = packet.payload
        if payload is None:
            return []

        out: list[PESPacket] = []
        if packet.payload_unit_start_indicator:
            self._resolve_active_at_boundary(out)
            self._buffer = bytearray(payload)
            self._prefix_checked = False
            self._length_read = False
            self._declared_total = None
        else:
            if not self._buffer:
                self._issues.append(
                    ParseIssue(
                        code=PES_CONTINUATION_WITHOUT_START,
                        message=(
                            "PUSI=0 payload with no active PES; bytes "
                            "dropped, not guessed into a PES start (§7.2)"
                        ),
                        offset=0,
                    )
                )
                return []
            self._buffer += payload

        self._process_active(out)
        return out

    def reset(self, reason: str) -> None:
        """Discard the active PES (caller-initiated recovery).

        ``reason`` documents the caller's intent; the accumulated issues
        are kept until :meth:`flush` drains them.
        """
        if not isinstance(reason, str):
            raise TypeError(f"reason must be str, got {type(reason).__name__}")
        self._discard_active()

    def flush(self) -> list[ParseIssue]:
        """Drain all accumulated issues; report an incomplete PES at EOF.

        The frozen §5 signature returns issues only, so an incomplete PES
        at end-of-input is reported as ``PES_TRUNCATED_AT_EOF`` evidence
        instead of being fabricated into a complete packet (SPEC-102
        flush discipline).
        """
        if self._buffer:
            self._issues.append(
                ParseIssue(
                    code=PES_TRUNCATED_AT_EOF,
                    message=(
                        f"end of input with {len(self._buffer)} bytes of an "
                        "incomplete PES accumulated; reported as evidence, "
                        "not fabricated complete"
                    ),
                    offset=len(self._buffer),
                )
            )
            self._discard_active()
        issues = self._issues
        self._issues = []
        return issues

    # --- internal state machine ---

    def _discard_active(self) -> None:
        self._buffer = bytearray()
        self._prefix_checked = False
        self._length_read = False
        self._declared_total = None

    def _resolve_active_at_boundary(self, out: list[PESPacket]) -> None:
        """§7.1: resolve the previous PES when a new PUSI arrives."""
        if not self._buffer:
            return
        if self._length_read and self._declared_total is None:
            # Unbounded (zero-length video) profile: the next PUSI is its
            # completion boundary (§7.4) — emit if it parses.
            try:
                out.append(parse_pes(bytes(self._buffer)))
            except InvalidPESPacketError as exc:
                self._issues.append(_issue_from_exception(exc, offset=0))
        else:
            self._issues.append(
                ParseIssue(
                    code=PES_TRUNCATED_AT_NEW_START,
                    message=(
                        "new PUSI arrived with an incomplete bounded PES "
                        f"({len(self._buffer)} bytes accumulated); discarded"
                    ),
                    offset=len(self._buffer),
                )
            )
        self._discard_active()

    def _process_active(self, out: list[PESPacket]) -> None:
        """Run the post-append checks: prefix, length, cap, completion."""
        if not self._buffer:
            return
        # Cap first: the buffer is a hard-bounded resource (§7.4,
        # REQ-104-005). Exactly at the cap is still allowed.
        if len(self._buffer) > self._max_buffer_bytes:
            self._issues.append(
                ParseIssue(
                    code=PES_BUFFER_LIMIT_EXCEEDED,
                    message=(
                        f"PES buffer reached {len(self._buffer)} bytes, "
                        f"exceeding max_buffer_bytes="
                        f"{self._max_buffer_bytes}; current PES discarded"
                    ),
                    offset=len(self._buffer),
                )
            )
            self._discard_active()
            return
        if not self._prefix_checked and len(self._buffer) >= 3:
            if bytes(self._buffer[:3]) != _START_CODE_PREFIX:
                self._issues.append(
                    ParseIssue(
                        code="PES_START_CODE_INVALID",
                        message=(
                            "PES accumulation must start with 00 00 01, got "
                            f"{bytes(self._buffer[:3]).hex(' ')}"
                        ),
                        offset=0,
                    )
                )
                self._discard_active()
                return
            self._prefix_checked = True
        if not self._length_read and len(self._buffer) >= 6:
            stream_id = self._buffer[3]
            declared = (self._buffer[4] << 8) | self._buffer[5]
            if stream_id in SPECIAL_STREAM_IDS:
                self._issues.append(
                    ParseIssue(
                        code="PES_STREAM_ID_PROFILE_UNSUPPORTED",
                        message=(
                            f"stream_id 0x{stream_id:02X} uses a special "
                            "PES grammar that the standard profile does "
                            "not implement"
                        ),
                        offset=3,
                    )
                )
                self._discard_active()
                return
            if declared == 0:
                if not (
                    _VIDEO_STREAM_ID_LOW
                    <= stream_id
                    <= _VIDEO_STREAM_ID_HIGH
                ):
                    self._issues.append(
                        ParseIssue(
                            code=PES_LENGTH_ZERO_NOT_ALLOWED,
                            message=(
                                "PES_packet_length=0 (unbounded) is only "
                                "legal for video stream_ids "
                                f"{_VIDEO_STREAM_ID_LOW:#04x}.."
                                f"{_VIDEO_STREAM_ID_HIGH:#04x}, got "
                                f"0x{stream_id:02X}"
                            ),
                            offset=4,
                        )
                    )
                    self._discard_active()
                    return
                # Unbounded profile: completion only at PUSI/EOF.
                self._length_read = True
                self._declared_total = None
                return
            self._length_read = True
            self._declared_total = 6 + declared
        if (
            self._length_read
            and self._declared_total is not None
            and len(self._buffer) >= self._declared_total
        ):
            declared_total = self._declared_total
            complete = bytes(self._buffer[:declared_total])
            leftover = bytes(self._buffer[declared_total:])
            try:
                out.append(parse_pes(complete))
            except InvalidPESPacketError as exc:
                self._issues.append(_issue_from_exception(exc, offset=0))
            finally:
                self._discard_active()
            if leftover:
                # §7.3 MVP policy: post-completion bytes cannot start a
                # new PES without PUSI; drop with explicit evidence.
                self._issues.append(
                    ParseIssue(
                        code=PES_CONTINUATION_WITHOUT_START,
                        message=(
                            f"{len(leftover)} bytes followed a completed "
                            "bounded PES inside the same payload; dropped "
                            "with evidence (no PUSI, not guessed into a "
                            "new PES start)"
                        ),
                        offset=declared_total,
                    )
                )
