"""Alert record vocabulary (SPEC-304, ticket #52).

The alert record is the AUTHORITY for alert state (SPEC-304 §5 暴露方式):
lifecycle changes persist here; WebSocket hints and the REST pull plane are
projections. MVP produces ZERO ``observation.*`` envelope events — the whole
namespace is withdrawn (SPEC-301 §4, ``registry.WITHDRAWN_NAMESPACE_PREFIXES``;
缝合批准 #12) — so this module deliberately declares no event types.

Vocabulary (all SPEC-304 §3/§5):

- :class:`AlertState` — the FIVE lifecycle values
  ``inactive → pending → firing → resolving → resolved``. ``suppressed`` is
  deliberately NOT a state: it is a modifier on the record (SPEC-304 §5
  抑制不是生命周期迁移态), carried by :class:`AlertSuppression`; suppressed
  records stay query-visible and unsuppression restores the prior lifecycle
  state because the state never moved (brief §8 G2 ruling D).
- :class:`AlertSeverity` — the record severity axis (info/warning/error/
  critical). A different axis from the envelope ``Severity`` (debug..critical)
  and from the diagnosis confidence/severity vocabularies.
- :class:`HealthDimension` — the six health dimensions (transport/timing/
  service/topology/simulation/observation).
- :class:`HealthStatus` — the roll-up status enum
  ``unknown|healthy|degraded|critical`` (SPEC-304 §3). NOT the SPEC-003 §3
  node-health word list (:class:`domain.observation.HealthState`
  ok/warn/error/unknown) — the two axes share no member.

Record shape: the 11 fields of the repository-authoritative schema
``docs/schemas/alert-record.schema.json`` (= the frozen ``alerts`` table
columns, SPEC-502 §4 / ticket #23 R8). The ``time`` block reuses the record
timepoint with explicit ``clock_epoch`` + ``semantics`` (SPEC-300 §6
record-level discipline; the ENVELOPE timepoint deliberately has none,
SPEC-301 §6). No business logic may live here (domain/_base.py contract);
lifecycle evaluation belongs to ``application.observation.alerts``.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Optional

from pydantic import Field, StringConstraints

from domain._base import DomainModel
from domain.observation.metric_series import MetricSampleTimepoint


class AlertState(str, Enum):
    """Alert lifecycle states (SPEC-304 §5). ``suppressed`` is not here."""

    INACTIVE = "inactive"
    PENDING = "pending"
    FIRING = "firing"
    RESOLVING = "resolving"
    RESOLVED = "resolved"


class AlertSeverity(str, Enum):
    """Alert record severity (SPEC-304 schema enum)."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class HealthDimension(str, Enum):
    """The six health dimensions (SPEC-304 §3)."""

    TRANSPORT = "transport"
    TIMING = "timing"
    SERVICE = "service"
    TOPOLOGY = "topology"
    SIMULATION = "simulation"
    OBSERVATION = "observation"


class HealthStatus(str, Enum):
    """Roll-up status (SPEC-304 §3) — NOT the SPEC-003 §3 HealthState axis."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class AlertScope(DomainModel):
    """Alert scope: tenant + session (SPEC-304 §6 分组守 scope; MVP tenant
    is the constant ``local`` per SPEC-301 §3)."""

    tenant_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class AlertSuppression(DomainModel):
    """Suppression metadata (SPEC-304 §9): who silenced the alert and why.

    Presence on the record IS the suppressed modifier — the lifecycle state
    is untouched, the record stays query-visible, and removing the object
    (``with_suppression(None)``) restores the prior state trivially.
    """

    reason: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    suppressed_by: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=128)]
    ] = None


class AlertRecord(DomainModel):
    """The durable alert record (SPEC-304 §5; schema
    ``docs/schemas/alert-record.schema.json``; ``alerts`` table 11 columns).

    ``time`` is the LAST transition's timepoint (each migration persists its
    timestamp with an explicit clock domain/epoch/semantics, SPEC-304 §5).
    ``evidence_refs`` are opaque strings resolvable to immutable source
    records (REQ-OBS-304-006); the MVP engine emits ``metric:<name>:
    bucket-<start_ns>`` refs and accepts ``journal:<seq>`` refs from
    producers — the resolvable formats are pinned by the alerts engine tests.
    """

    alert_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    fingerprint: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    rule_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    rule_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    state: AlertState
    severity: AlertSeverity
    scope: AlertScope
    time: MetricSampleTimepoint
    summary: Optional[Annotated[str, StringConstraints(max_length=512)]] = None
    #: Storm bound (SPEC-304 §13): the engine never attaches more than 64
    #: evidence refs to one record; each ref stays a short opaque token.
    evidence_refs: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=256)], ...
    ] = Field(default=(), max_length=64)
    suppression: Optional[AlertSuppression] = None

    @property
    def is_suppressed(self) -> bool:
        """The suppressed modifier: metadata present, lifecycle untouched."""
        return self.suppression is not None

    def with_suppression(self, suppression: Optional[AlertSuppression]) -> "AlertRecord":
        """Return the record with the suppression modifier applied/removed.

        Modifier semantics (SPEC-304 §5): the lifecycle state does NOT move —
        unsuppression therefore restores the prior state deterministically.
        """
        return self.model_copy(update={"suppression": suppression})


__all__ = [
    "AlertRecord",
    "AlertScope",
    "AlertSeverity",
    "AlertState",
    "AlertSuppression",
    "HealthDimension",
    "HealthStatus",
]
