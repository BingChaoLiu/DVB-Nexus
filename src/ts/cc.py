"""SPEC-100 — generation-side Continuity Counter allocator (ticket #28).

CCAllocator maintains one independent state machine per PID (SPEC-100
§5.4): payload-bearing packets advance the CC of their PID, adaptation-only
packets reuse the PID's most recent CC without advancing, and everything
wraps modulo 16. There is deliberately NO wall-clock coupling and no
automatic discontinuity handling — explicit discontinuity strategy belongs
to the caller via :meth:`CCAllocator.reset` (§5.4).

The state rule is the verbatim equivalent of the SPEC-100 §6 pseudocode::

    if pid_has_no_previous_packet:
        cc = initial_cc
    elif has_payload:
        cc = initial_cc if last_payload_cc is None else (last_payload_cc + 1) & 0x0F
    else:
        cc = last_emitted_cc

    last_emitted_cc = cc
    if has_payload:
        last_payload_cc = cc
    return cc

``initial_cc`` is the current generation's starting value for the PID;
``reset(pid, next_value)`` clears that PID's history and installs a new
generation initial. Input CC continuity diagnostics, duplicate-packet
detection and anomaly statistics are out of scope here (§2.2/§5.4 —
SPEC-302/306/307 territory).

Error codes used here (SPEC-100 §8, constants owned by ``ts.packet``):
``TS_PID_OUT_OF_RANGE`` and ``TS_CC_OUT_OF_RANGE`` map to
:class:`ts.errors.InvalidPacketError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ts._bytesutil import PID_MAX
from ts.errors import InvalidPacketError
from ts.packet import TS_CC_OUT_OF_RANGE, TS_PID_OUT_OF_RANGE

_CC_MAX = 0x0F
_CC_MASK = 0x0F


@dataclass
class _PidCCState:
    """Mutable per-PID generation state (SPEC-100 §5.4)."""

    initial_cc: int
    last_emitted_cc: int | None = None
    last_payload_cc: int | None = None


class CCAllocator:
    """PID-scoped continuity counter allocator for the generation side."""

    def __init__(self, initial_cc: int = 0) -> None:
        """Create an allocator whose fresh PIDs start at ``initial_cc``."""
        if isinstance(initial_cc, bool) or not isinstance(initial_cc, int):
            raise TypeError(
                f"initial_cc must be int, got {type(initial_cc).__name__}"
            )
        if not 0 <= initial_cc <= _CC_MAX:
            raise InvalidPacketError(
                f"{TS_CC_OUT_OF_RANGE}: initial_cc must be in 0..{_CC_MAX}, "
                f"got {initial_cc}"
            )
        self._initial_cc = initial_cc
        self._states: dict[int, _PidCCState] = {}

    def allocate(self, pid: int, *, has_payload: bool) -> int:
        """Return the CC for this packet and record the emission state.

        Implements the SPEC-100 §6 state rule exactly: fresh PIDs use the
        generation ``initial_cc``; payload packets increment the PID's last
        payload CC (modulo 16); adaptation-only packets reuse the PID's
        last emitted CC without advancing anything.
        """
        self._validate_pid(pid)
        state = self._states.get(pid)
        if state is None:
            state = _PidCCState(initial_cc=self._initial_cc)
            self._states[pid] = state
        if state.last_emitted_cc is None:
            cc = state.initial_cc
        elif has_payload:
            if state.last_payload_cc is None:
                cc = state.initial_cc
            else:
                cc = (state.last_payload_cc + 1) & _CC_MASK
        else:
            cc = state.last_emitted_cc
        state.last_emitted_cc = cc
        if has_payload:
            state.last_payload_cc = cc
        return cc

    def reset(self, pid: int, next_value: int) -> None:
        """Clear this PID's history and start a new generation at ``next_value``.

        Explicit discontinuity boundary (§5.4): the caller's policy drives
        it; the allocator never resets on its own.
        """
        self._validate_pid(pid)
        if isinstance(next_value, bool) or not isinstance(next_value, int):
            raise TypeError(
                f"next_value must be int, got {type(next_value).__name__}"
            )
        if not 0 <= next_value <= _CC_MAX:
            raise InvalidPacketError(
                f"{TS_CC_OUT_OF_RANGE}: next_value must be in 0..{_CC_MAX}, "
                f"got {next_value}"
            )
        self._states[pid] = _PidCCState(initial_cc=next_value)

    def clear(self) -> None:
        """Forget every PID; fresh PIDs use the allocator ``initial_cc`` again."""
        self._states.clear()

    @staticmethod
    def _validate_pid(pid: int) -> None:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise TypeError(f"pid must be int, got {type(pid).__name__}")
        if not 0 <= pid <= PID_MAX:
            raise InvalidPacketError(
                f"{TS_PID_OUT_OF_RANGE}: pid must be in 0..{PID_MAX} "
                f"(13-bit), got {pid}"
            )
