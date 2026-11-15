"""Alert store face (SPEC-304 §5 记录权威, ticket #52).

The alert record is the authority for alert state; this module declares the
persistence protocol and the list/page vocabulary shared by the store and
the ``AlertService`` (SPEC-300 §12 7th required interface
``AlertService.list(request) -> AlertPage`` — the frozen name).

- :class:`AlertStore` — the structural protocol (the application layer
  depends on this; the SQLite implementation lives beside the journal in
  :mod:`adapters.storage.alerts`, the platform's only SQLite writer family,
  SPEC-502 §3);
- :class:`AlertListRequest` / :class:`AlertPage` — the list contract with
  deterministic ordering (``rule_id, fingerprint, alert_id``), the SPEC-305
  §5 同源 limits (default 100, hard cap 2000) and the suppression filter
  (SPEC-304 §9: 抑制告警保持可查询 — suppression is a filter, never a
  visibility removal);
- :class:`ACTIVE_STATES` — the active set (``pending|firing|resolving``)
  behind the SPEC-302 ``observation.alerts_active`` metric (Ruling H
  wiring: the count feeds ``MetricsEngine.poll_operational``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from domain.observation import AlertRecord, AlertSeverity, AlertState

#: SPEC-305 §5 同源 limits (the journal QUERY_LIMIT constants' values; the
#: REST plane maps overruns onto the frozen HTTP table — #53's face).
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_HARD_CAP = 2000

#: Active alert states (SPEC-302 ``observation.alerts_active`` semantics):
#: settled states (resolved/inactive) leave the active set.
ACTIVE_STATES = frozenset(
    {AlertState.PENDING, AlertState.FIRING, AlertState.RESOLVING}
)


@dataclass(frozen=True)
class AlertListRequest:
    """AlertService.list / store list request (scope-first, filterable)."""

    session_id: Optional[str] = None
    rule_id: Optional[str] = None
    state: Optional[AlertState] = None
    severity: Optional[AlertSeverity] = None
    #: ``True`` = only suppressed records; ``False`` = only unsuppressed;
    #: ``None`` = both (the default — suppressed stay query-visible, §9).
    suppressed: Optional[bool] = None
    limit: int = LIST_LIMIT_DEFAULT
    offset: int = 0


@dataclass(frozen=True)
class AlertPage:
    """One deterministic page (``total`` lets the #53 REST plane decide
    cursor continuation without reaching into storage internals)."""

    items: tuple[AlertRecord, ...]
    total: int
    truncated: bool


class AlertStore(Protocol):
    """Structural persistence protocol for alert records (upsert)."""

    def save(self, record: AlertRecord) -> None: ...

    def get(self, alert_id: str) -> Optional[AlertRecord]: ...

    def find_by_fingerprint(
        self, session_id: str, fingerprint: str, *, active_only: bool = False
    ) -> Optional[AlertRecord]: ...

    def list(self, request: AlertListRequest) -> AlertPage: ...

    def count_active(self, session_id: str) -> int: ...


__all__ = [
    "ACTIVE_STATES",
    "LIST_LIMIT_DEFAULT",
    "LIST_LIMIT_HARD_CAP",
    "AlertListRequest",
    "AlertPage",
    "AlertStore",
]
