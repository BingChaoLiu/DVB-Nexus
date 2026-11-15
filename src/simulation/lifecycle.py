"""SPEC-200 section 5 — session lifecycle state machine (ticket #41).

The exhaustive transition table is the single authority for session
lifecycle legality (issue #12 ruling: the ``VALIDATING -> FAILED`` and
``FAILED -> DISPOSED`` direct edges are explicit; ``VALIDATING/READY ->
STOPPING`` carries the validation-period cancellation path). Every
transition not listed is illegal and raises
:class:`simulation.errors.InvalidLifecycleTransitionError` with the current
legal transition set attached (SPEC-200 section 8 ``SIM_INVALID_LIFECYCLE_
TRANSITION`` row).

Semantics:

- Terminal states are ``STOPPED`` and ``DISPOSED`` (不可重启 — a new session
  means a new session record). ``DISPOSED`` additionally absorbs: it has no
  outgoing edge at all.
- ``FAILED`` is NOT terminal: the session may still own tasks/subprocesses,
  so it must go through ``STOPPING`` (bounded cleanup) or straight to
  ``DISPOSED`` (reclaim) — SPEC-200 section 5.
- Each committed transition produces one strictly monotonic in-session
  ``revision`` and one lifecycle event per the section 6 rules (the
  runtime owns both; this module owns only the legality gate).

This module is pure: no IO, no clock, no asyncio — the FSM gate is
importable and testable without an event loop.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from simulation.errors import InvalidLifecycleTransitionError

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FINAL_STATES",
    "LifecycleState",
    "allowed_transitions",
    "can_transition",
    "require_transition",
]


class LifecycleState(str, Enum):
    """The nine session lifecycle states (SPEC-200 section 5).

    ``str``-mixin Enum like the existing simulation vocabulary enums
    (``simulation.state.graph.PortDirection`` / ``Health``) — the runtime
    pins Python 3.10, where ``enum.StrEnum`` does not exist yet; the string
    values below are the wire vocabulary either way.
    """

    CREATED = "created"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    DISPOSED = "disposed"


#: The exhaustive transition table (SPEC-200 section 5). Unlisted = illegal.
ALLOWED_TRANSITIONS: Mapping[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.CREATED: frozenset({LifecycleState.VALIDATING}),
    LifecycleState.VALIDATING: frozenset(
        {LifecycleState.READY, LifecycleState.FAILED, LifecycleState.STOPPING}
    ),
    LifecycleState.READY: frozenset(
        {LifecycleState.RUNNING, LifecycleState.FAILED, LifecycleState.STOPPING}
    ),
    LifecycleState.RUNNING: frozenset(
        {LifecycleState.PAUSED, LifecycleState.FAILED, LifecycleState.STOPPING}
    ),
    LifecycleState.PAUSED: frozenset(
        {LifecycleState.RUNNING, LifecycleState.FAILED, LifecycleState.STOPPING}
    ),
    # FAILED 不是终态：可经 STOPPING 清理，或直接 DISPOSED 回收。
    LifecycleState.FAILED: frozenset(
        {LifecycleState.STOPPING, LifecycleState.DISPOSED}
    ),
    LifecycleState.STOPPING: frozenset({LifecycleState.STOPPED}),
    LifecycleState.STOPPED: frozenset({LifecycleState.DISPOSED}),
    # DISPOSED absorbs: no outgoing edge (不可重启).
    LifecycleState.DISPOSED: frozenset(),
}

#: 不可重启的状态（SPEC-200 section 5 终态行）；DISPOSED 是唯一的吸收态.
FINAL_STATES: frozenset[LifecycleState] = frozenset(
    {LifecycleState.STOPPED, LifecycleState.DISPOSED}
)


def allowed_transitions(state: LifecycleState) -> frozenset[LifecycleState]:
    """The legal target set from ``state`` (empty for terminal states)."""
    return ALLOWED_TRANSITIONS[state]


def can_transition(current: LifecycleState, target: LifecycleState) -> bool:
    """True when ``current -> target`` is a listed (legal) edge."""
    return target in ALLOWED_TRANSITIONS[current]


def require_transition(
    current: LifecycleState, target: LifecycleState
) -> None:
    """Raise :class:`InvalidLifecycleTransitionError` for an unlisted edge.

    Legal edges return silently — the caller commits the state change and
    bumps the session revision.
    """
    if not isinstance(current, LifecycleState):
        raise TypeError(
            f"current must be LifecycleState, got {type(current).__name__}"
        )
    if not isinstance(target, LifecycleState):
        raise TypeError(
            f"target must be LifecycleState, got {type(target).__name__}"
        )
    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        raise InvalidLifecycleTransitionError(current, target, allowed)
