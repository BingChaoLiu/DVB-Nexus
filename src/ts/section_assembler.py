"""SPEC-102 — PSI SectionAssembler: TS packet payload -> sections (ticket #29).

Reassembles PSI sections from the payload of one configured PID
(SPEC-102 §5/§6.2): PUSI/pointer_field framing, cross-packet continuation,
multiple sections per payload, 0xFF stuffing, discontinuity resets and
explicit end-of-input handling. Table-specific semantics stay in SPEC-103.

State machine (per §6.2):

- ``push`` feeds one :class:`ts.packet.TSPacket`. Packets of other PIDs
  and payload-less packets (AFC=10/00) contribute no data (§6.2: "Packet
  必须携带 Payload"). ``discontinuity_indicator=1`` in the adaptation
  field drops the active partial section and resets (recorded as
  ``SECTION_DISCARDED_ON_DISCONTINUITY``); CC-gap driven resets arrive as
  caller-invoked :meth:`reset` — the assembler never stitches across a
  reported gap silently.
- PUSI=1: the first payload byte is ``pointer_field``; the prefix before
  the pointed offset completes the previous partial section (bytes after
  that completion up to the pointer are pre-pointer filler and are
  discarded, §6.2); with no partial section the prefix is unused stuffing.
  A pointer beyond the payload is ``SECTION_POINTER_FIELD_INVALID``: the
  issue is recorded and the framing state is cleared (wait for the next
  PUSI, "恢复行为可预测").
- PUSI=0 without an active partial section is
  ``SECTION_CONTINUATION_WITHOUT_START``: the payload is never scanned for
  an arbitrary section start (§6.2).
- At every section boundary a ``0xFF`` byte starts stuffing: the rest of
  the payload region is ignored and never parsed as a ``table_id`` (§6.2).
- Policies come from ``policy_resolver(table_id) -> SectionPolicy | None``
  per section start (one PID may carry several table_ids, §5). An unknown
  table_id yields ``SECTION_TABLE_ID_UNEXPECTED`` and the section is
  skipped by its wire length — no default policy fallback (ruling #11).
  A section length beyond the table profile raises
  ``SECTION_LENGTH_EXCEEDS_POLICY`` and clears the state: the wire length
  is untrustworthy, so assembly resumes only at the next PUSI.
  All buffers are bounded by ``3 + 4095`` bytes, and every length-derived
  slice is bounds-checked: malformed lengths can neither over-read nor
  loop (§9/REQ-TS-102-006).
- Complete sections are parsed strict with :func:`ts.section.parse_section`;
  a rejected section (e.g. ``SECTION_CRC_INVALID``) is recorded as a
  :class:`ts.issues.ParseIssue` and dropped, assembly continues with the
  next section.

Issue surface (contract §6/§7): wire problems never crash ``push`` — they
accumulate as :class:`~ts.issues.ParseIssue` and :meth:`flush` drains them.
``flush`` is the end-of-input call: an unfinished partial section is
reported as ``SECTION_TRUNCATED_AT_EOF`` and never padded into a fake
complete section (§6.2). ``reset``/``flush`` clear the partial state so the
next PUSI=1 packet starts clean.

Error codes owned here (SPEC-102 §8, module-owned per contract §7 归属约定;
all recorded as ParseIssue codes and raised as ``InvalidSectionError``
codes by the underlying parser): ``SECTION_POINTER_FIELD_INVALID``,
``SECTION_CONTINUATION_WITHOUT_START``, ``SECTION_DISCARDED_ON_DISCONTINUITY``,
``SECTION_TRUNCATED_AT_EOF``. Framing codes live in :mod:`ts.section`.
"""

from __future__ import annotations

from ts.errors import InvalidSectionError
from ts.issues import ParseIssue
from ts.packet import TSPacket
from ts.section import (
    SECTION_LENGTH_WIRE_MAX,
    SECTION_TABLE_ID_UNEXPECTED,
    PSISection,
    SectionPolicy,
    parse_section,
    section_total_size,
)

# --- SPEC-102 §8 error codes owned by this module (assembly side) ---

SECTION_POINTER_FIELD_INVALID = "SECTION_POINTER_FIELD_INVALID"
SECTION_CONTINUATION_WITHOUT_START = "SECTION_CONTINUATION_WITHOUT_START"
SECTION_DISCARDED_ON_DISCONTINUITY = "SECTION_DISCARDED_ON_DISCONTINUITY"
SECTION_TRUNCATED_AT_EOF = "SECTION_TRUNCATED_AT_EOF"

_HEADER_SIZE = 3  # section header size (ts.section.SECTION_HEADER_SIZE)

_PID_MAX = 0x1FFF


class _LengthFault(Exception):
    """Internal: section length beyond policy — state cleared, abort packet."""


def _error_code(error: InvalidSectionError) -> str:
    """Extract the §8 code from the ``"CODE: message"`` error convention."""
    return str(error).split(":", 1)[0]


class SectionAssembler:
    """Reassemble PSI sections from one PID's TS packet payloads (§5/§6.2).

    ``policy_resolver(table_id)`` must return the :class:`SectionPolicy`
    for that table_id or ``None`` (unknown -> discard, ruling #11). Wire
    problems accumulate as :class:`~ts.issues.ParseIssue`; :meth:`flush`
    is the end-of-input drain. Not thread-safe: state mutates in place.
    """

    def __init__(self, pid: int, policy_resolver) -> None:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise TypeError(f"pid must be int, got {type(pid).__name__}")
        if not 0 <= pid <= _PID_MAX:
            raise ValueError(f"pid must be in 0..{_PID_MAX} (13-bit), got {pid}")
        if not callable(policy_resolver):
            raise TypeError(
                "policy_resolver must be callable(table_id) -> "
                f"SectionPolicy | None, got {type(policy_resolver).__name__}"
            )
        self._pid = pid
        self._resolver = policy_resolver
        self._buffer = bytearray()
        self._active = False  # a section run is in progress (maybe partial)
        self._total: int | None = None  # resolved 3 + section_length
        self._policy: SectionPolicy | None = None  # None -> skip mode
        self._issues: list[ParseIssue] = []
        self._emitted: list[PSISection] = []

    # --- public interface (SPEC-102 §5) ---

    def push(self, packet: TSPacket) -> list[PSISection]:
        """Feed one TS packet; return the sections completed by it.

        Packets of other PIDs and payload-less packets return ``[]``
        without state change. Wire problems are recorded as issues (see
        :meth:`flush`), never raised.
        """
        if not isinstance(packet, TSPacket):
            raise TypeError(
                f"packet must be TSPacket, got {type(packet).__name__}"
            )
        if packet.pid != self._pid:
            return []  # the assembler owns exactly one PID (§5)
        payload = packet.payload
        if payload is None:
            return []  # no payload -> no data contribution (§6.2)
        af = packet.adaptation_field
        if af is not None and af.discontinuity_indicator:
            self._discard_partial(
                "adaptation field discontinuity_indicator=1 (§6.2)"
            )
        self._emitted = []
        end = len(payload)
        try:
            if packet.payload_unit_start_indicator:
                pointer_field = payload[0]
                section_start = 1 + pointer_field
                if section_start > end:
                    self._issues.append(
                        ParseIssue(
                            code=SECTION_POINTER_FIELD_INVALID,
                            message=f"pointer_field {pointer_field} points "
                            f"to offset {section_start}, beyond the "
                            f"{end}-byte payload; framing state cleared",
                            offset=0,
                        )
                    )
                    self._clear()
                    return self._drain_emitted()
                # Prefix: completes the previous partial section when one
                # is active; otherwise unused stuffing (§6.2). Bytes left
                # after an in-prefix completion are pre-pointer filler.
                if self._active:
                    self._consume(payload, 1, section_start, allow_new=False)
                # The pointer fixes the new section start (§6.2).
                self._consume(payload, section_start, end, allow_new=True)
            else:
                if not self._active:
                    self._issues.append(
                        ParseIssue(
                            code=SECTION_CONTINUATION_WITHOUT_START,
                            message="PUSI=0 payload arrived with no active "
                            "partial section; payload dropped, no arbitrary "
                            "section start assumed (§6.2)",
                            offset=None,
                        )
                    )
                    return self._drain_emitted()
                self._consume(payload, 0, end, allow_new=True)
        except _LengthFault:
            pass  # state cleared and issue recorded at the fault site
        return self._drain_emitted()

    def reset(self, reason: str) -> None:
        """Drop the active partial section (CC-gap notification, §6.2).

        Records ``SECTION_DISCARDED_ON_DISCONTINUITY`` when a partial
        section was actually discarded; clearing an idle assembler is a
        no-op. The ``reason`` string is quoted in the issue message.
        """
        if not isinstance(reason, str):
            raise TypeError(f"reason must be str, got {type(reason).__name__}")
        self._discard_partial(f"caller reset: {reason}")

    def flush(self) -> list[ParseIssue]:
        """End-of-input drain (§6.2): report an unfinished partial section
        as ``SECTION_TRUNCATED_AT_EOF`` — never padded with 0x00/0xFF —
        and return (and clear) every accumulated :class:`ParseIssue`.

        After ``flush`` the assembler is idle: the next PUSI=1 packet
        starts a fresh section run. Calling ``flush`` again returns ``[]``.
        """
        if self._active:
            detail = ""
            if self._buffer:
                detail = f" (table_id {self._buffer[0]:#04x})"
            self._issues.append(
                ParseIssue(
                    code=SECTION_TRUNCATED_AT_EOF,
                    message=f"partial section{detail} still unfinished at "
                    f"end of input ({len(self._buffer)} of "
                    f"{self._total if self._total is not None else '?'} "
                    "bytes); not padded to a fake complete section",
                    offset=None,
                )
            )
            self._clear()
        issues = self._issues
        self._issues = []
        return issues

    # --- internal machinery ---

    def _consume(
        self, data: bytes, pos: int, end: int, *, allow_new: bool
    ) -> None:
        """Feed ``data[pos:end]`` through the reassembly state machine.

        ``allow_new=False`` marks the PUSI prefix region: it may only
        continue the active section — after an in-region completion the
        remaining bytes are pre-pointer filler and are dropped without
        interpretation. ``allow_new=True`` marks a region where new
        sections may start; a ``0xFF`` boundary byte ends the region as
        stuffing (§6.2).
        """
        while pos < end:
            if not self._active:
                if not allow_new or data[pos] == 0xFF:
                    return  # filler/stuffing: region ends here
                self._active = True
                self._total = None
                self._policy = None
            if self._total is None:
                # Resolve the 3-byte header first (it may span packets).
                need = _HEADER_SIZE - len(self._buffer)
                take = min(need, end - pos)
                self._buffer += data[pos : pos + take]
                pos += take
                if len(self._buffer) < _HEADER_SIZE:
                    return  # header still split; wait for more payload
                header = bytes(self._buffer[:_HEADER_SIZE])
                policy = self._resolver(header[0])
                if policy is None:
                    # Ruling #11: unknown table_id -> issue + discard the
                    # section by its wire length; no default policy.
                    self._issues.append(
                        ParseIssue(
                            code=SECTION_TABLE_ID_UNEXPECTED,
                            message=f"table_id {header[0]:#04x} has no "
                            "configured policy; section discarded, no "
                            "default policy fallback",
                            offset=None,
                        )
                    )
                    self._total = section_total_size(
                        header, max_section_length=SECTION_LENGTH_WIRE_MAX
                    )
                    self._policy = None  # skip mode: drop at completion
                else:
                    try:
                        self._total = section_total_size(
                            header,
                            max_section_length=policy.max_section_length,
                        )
                    except InvalidSectionError as error:
                        # Untrustworthy wire length: no bounds-checked way
                        # to find the section end — clear and wait for the
                        # next PUSI (predictable recovery, §10/REQ-005).
                        self._issues.append(
                            ParseIssue(
                                code=_error_code(error),
                                message=str(error),
                                offset=None,
                            )
                        )
                        self._clear()
                        raise _LengthFault() from error
                    self._policy = policy
                if len(self._buffer) >= self._total:
                    # Declared section_length 0: the 3-byte header IS the
                    # whole section and the payload boundary may end right
                    # here — complete in place (§6.2; #35 difference report
                    # §4) instead of waiting for a next packet that would
                    # leave flush() reporting a "truncated" section that is
                    # actually complete.
                    self._finish_current_section()
                continue  # accumulation branch handles take=0 completion
            take = min(self._total - len(self._buffer), end - pos)
            self._buffer += data[pos : pos + take]
            pos += take
            if len(self._buffer) < self._total:
                return  # section still split; keep for the next packet
            self._finish_current_section()
            # loop continues at the section boundary

    def _finish_current_section(self) -> None:
        """Complete the buffered section: parse-emit it or skip-drop it.

        Called with ``len(self._buffer) >= self._total`` (the total was
        resolved and every section byte is buffered); clears the framing
        state so the next boundary byte starts a fresh section. Parse
        rejection is recorded as a :class:`ParseIssue`; skip mode (unknown
        table_id, ``self._policy is None``) just drops the bytes.
        """
        chunk = bytes(self._buffer[: self._total])
        del self._buffer[: self._total]
        self._active = False
        self._total = None
        policy = self._policy
        self._policy = None
        if policy is not None:
            try:
                self._emitted.append(parse_section(chunk, policy, strict=True))
            except InvalidSectionError as error:
                self._issues.append(
                    ParseIssue(
                        code=_error_code(error),
                        message=str(error),
                        offset=None,
                    )
                )

    def _discard_partial(self, reason: str) -> None:
        """Drop an active partial section, recording the event (§6.2/§8)."""
        if self._active:
            detail = ""
            if self._buffer:
                detail = f" (table_id {self._buffer[0]:#04x})"
            self._issues.append(
                ParseIssue(
                    code=SECTION_DISCARDED_ON_DISCONTINUITY,
                    message=f"partial section{detail} discarded: {reason}",
                    offset=None,
                )
            )
        self._clear()

    def _clear(self) -> None:
        """Reset framing state; assembly resumes at the next PUSI=1."""
        self._buffer = bytearray()
        self._active = False
        self._total = None
        self._policy = None

    def _drain_emitted(self) -> list[PSISection]:
        emitted = self._emitted
        self._emitted = []
        return emitted
