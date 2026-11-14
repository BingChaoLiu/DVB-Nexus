"""SPEC-003 section 3 status vocabulary.

Four separate vocabularies instead of one overloaded ``health`` flag
(SPEC-003 section 3). Vocabulary only: allowed combinations per node type are
deferred to a later SPEC-003 revision or per-node module specs (SPEC-003
sections 3 and 6), so no aggregate status model is defined here.

Home package: these are runtime instance states that flow on the unified
exchange interface (run/session lifecycle events, health & alerting);
``domain.topology`` is the configuration model by definition (SPEC-003
section 2.1), so runtime status cannot live there.
"""

from enum import Enum


class LifecycleState(str, Enum):
    """Lifecycle of a run/node instance (SPEC-003 section 3)."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class OperationalState(str, Enum):
    """Operational state (SPEC-003 section 3)."""

    ACTIVE = "active"
    IDLE = "idle"
    UNAVAILABLE = "unavailable"


class HealthState(str, Enum):
    """Health signal (SPEC-003 section 3)."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    UNKNOWN = "unknown"


class LockState(str, Enum):
    """Lock state, only meaningful for devices with lock semantics
    (SPEC-003 section 3)."""

    LOCKED = "locked"
    UNLOCKED = "unlocked"
    ACQUIRING = "acquiring"
    NOT_APPLICABLE = "not_applicable"


__all__ = ["HealthState", "LifecycleState", "LockState", "OperationalState"]
