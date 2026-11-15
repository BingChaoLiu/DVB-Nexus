"""AlertService — the record-authority service face (ticket #52).

SPEC-300 §12 7th required interface (frozen name):
``AlertService.list(request) -> AlertPage``. The service composes the
validated rule set + deterministic lifecycle engine (:mod:`.engine`), the
alert store protocol (:mod:`.store`, SQLite implementation in
:mod:`adapters.storage.alerts`) and the roll-up (:mod:`.rollup`).

Notification seam (R1 ruling / 裁定 C): state changes surface as
``observation.alert_changed`` HINTS through an INJECTED
:class:`AlertHintEmitter` port — best-effort by contract (emitter failures
are counted, never propagated: SPEC-301 §5 WS 通知是提示不是存储). The
production hub binding, the WS frame shape and the hint→REST pull loop are
ticket #53's face; this module stops at the port.

REQ-OBS-304-003 (MVP 零 observation.* 信封事件): the service constructs NO
envelopes and publishes NO events — the alert record is the authority, WS
hints are topic projections and REST pulls read the store. The whole
``observation.*`` namespace is withdrawn at the registry (SPEC-301 §4); the
hint topics below are plain strings, deliberately NOT registered event
types, and every one of them is refused by ``validate_event_type`` (pinned
by tests).

Suppression (SPEC-304 §5/§9): a modifier on the record — suppressed records
stay query-visible, keep lifecycle-evolving (the engine never sees the
modifier), and their hints are withheld while suppressed. Unsuppression
restores the prior lifecycle state trivially because the state never moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from pydantic import BaseModel

from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSuppression,
    MetricSampleTimepoint,
    SampleSemantics,
)

from application.observation.alerts.engine import (
    AlertEngine,
    AlertEngineConfig,
    AlertEvaluation,
    AlertTransition,
)
from application.observation.alerts.inputs import MetricWindowReader
from application.observation.alerts.rollup import HealthResult, roll_up
from application.observation.alerts.rules import HealthRuleSet
from application.observation.alerts.store import (
    ACTIVE_STATES,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_HARD_CAP,
    AlertListRequest,
    AlertPage,
    AlertStore,
)

#: The SPEC-305 §8 WS hint topic for alert changes (a plain topic string,
#: NOT a registered event type — see the REQ-304-003 note above).
ALERT_CHANGED_TOPIC = "observation.alert_changed"

#: The five SPEC-305 §8 hint themes (the registry withdraws every one of
#: them as an event type; only the alert theme is emitted here — metric/
#: health/export themes are #53's wiring).
WS_HINT_TOPICS = (
    "observation.event_appended",
    "observation.metric_updated",
    "observation.alert_changed",
    "observation.health_changed",
    "observation.export_progress",
)


class AlertHint(BaseModel):
    """One ``observation.alert_changed`` hint payload — a projection of the
    persisted record (model config forbids extras: a hint can never grow
    envelope structure)."""

    model_config = {"extra": "forbid", "frozen": True}

    topic: str = ALERT_CHANGED_TOPIC
    session_id: str
    alert_id: str
    fingerprint: str
    rule_id: str
    state: str
    severity: str


class AlertHintEmitter(Protocol):
    """The injection seam for hint delivery (#53 binds the hub).

    Synchronous, best-effort: implementations may drop or fail; the service
    counts failures and never lets them break the record-authority write
    path.
    """

    def emit(self, hint: AlertHint) -> None: ...


@dataclass(frozen=True)
class AlertEvaluationResult:
    """One service evaluation tick: engine outcome + persisted records."""

    evaluation: AlertEvaluation
    records: tuple[AlertRecord, ...]
    hints_emitted: int
    hints_failed: int


class AlertService:
    """The record-authority alerts service (SPEC-300 §12 / SPEC-304 §5)."""

    def __init__(
        self,
        store: AlertStore,
        rule_set: HealthRuleSet,
        *,
        engine: Optional[AlertEngine] = None,
        hint_emitter: Optional[AlertHintEmitter] = None,
        alert_id_factory: Optional[AlertEngineConfig] = None,
    ) -> None:
        self._store = store
        self._rule_set = rule_set
        self._engine = engine or AlertEngine(rule_set)
        self._emitter = hint_emitter
        #: Kept for composition roots that want to pin deterministic ids
        #: (tests); the engine owns the actual factory.
        self._engine_config = alert_id_factory or AlertEngineConfig()
        self._hints_emitted = 0
        self._hints_failed = 0

    # --- evaluation / write path ---------------------------------------------

    def evaluate_session(
        self,
        session_id: str,
        *,
        reader: MetricWindowReader,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int = 0,
    ) -> AlertEvaluationResult:
        """Run one deterministic tick and persist every transition."""
        evaluation = self._engine.evaluate(
            session_id,
            reader=reader,
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
        )
        persisted: list[AlertRecord] = []
        for transition in evaluation.transitions:
            record = self._persist_transition(transition)
            persisted.append(record)
            self._emit_hint(record)
        return AlertEvaluationResult(
            evaluation=evaluation,
            records=tuple(persisted),
            hints_emitted=self._hints_emitted,
            hints_failed=self._hints_failed,
        )

    def _persist_transition(self, transition: AlertTransition) -> AlertRecord:
        existing = self._store.get(transition.alert_id)
        timepoint = MetricSampleTimepoint(
            value_ns=transition.at_ns,
            clock_domain=transition.clock_domain,
            clock_epoch=transition.clock_epoch,
            semantics=SampleSemantics.DERIVED,
        )
        if existing is None:
            record = AlertRecord(
                alert_id=transition.alert_id,
                fingerprint=transition.fingerprint,
                rule_id=transition.rule_id,
                rule_version=transition.rule_version,
                state=transition.to_state,
                severity=transition.severity,
                scope=AlertScope(
                    tenant_id="local", session_id=transition.session_id
                ),
                time=timepoint,
                summary=transition.summary or None,
                evidence_refs=transition.evidence_refs,
                suppression=None,
            )
        else:
            # A migration on an existing record: carry the suppression
            # modifier across (the lifecycle never moved under suppression).
            record = existing.model_copy(
                update={
                    "state": transition.to_state,
                    "time": timepoint,
                    "summary": transition.summary or existing.summary,
                    "evidence_refs": transition.evidence_refs,
                    "rule_version": transition.rule_version,
                }
            )
        self._store.save(record)
        return record

    # --- hint seam ---------------------------------------------------------------

    def _emit_hint(self, record: AlertRecord) -> None:
        if self._emitter is None or record.is_suppressed:
            return  # no binding composed / withheld while suppressed (§9)
        hint = AlertHint(
            session_id=record.scope.session_id,
            alert_id=record.alert_id,
            fingerprint=record.fingerprint,
            rule_id=record.rule_id,
            state=record.state.value,
            severity=record.severity.value,
        )
        try:
            self._emitter.emit(hint)
            self._hints_emitted += 1
        except Exception:  # noqa: BLE001 — best-effort by contract (§5)
            self._hints_failed += 1

    # --- read / modifier faces ------------------------------------------------------

    def list(self, request: AlertListRequest) -> AlertPage:
        """The frozen SPEC-300 §12 required interface."""
        return self._store.list(request)

    def get(self, alert_id: str) -> Optional[AlertRecord]:
        return self._store.get(alert_id)

    def suppress(
        self, alert_id: str, *, reason: str, suppressed_by: Optional[str] = None
    ) -> Optional[AlertRecord]:
        """Apply the suppression modifier (state unchanged; §5/§9).

        Unknown ids answer ``None`` — the 404 row and its error code belong
        to the #53 REST plane (no unregistered OBS_* code is invented here;
        per-code registration discipline, brief §1.7).
        """
        record = self._store.get(alert_id)
        if record is None:
            return None
        suppressed = record.with_suppression(
            AlertSuppression(reason=reason, suppressed_by=suppressed_by)
        )
        self._store.save(suppressed)
        return suppressed

    def unsuppress(self, alert_id: str) -> Optional[AlertRecord]:
        """Remove the modifier — the lifecycle state is exactly where it
        stayed (§5 解抑制恢复先前态). Unknown ids answer ``None`` (#53 plane)."""
        record = self._store.get(alert_id)
        if record is None:
            return None
        restored = record.with_suppression(None)
        self._store.save(restored)
        return restored

    def active_count(self, session_id: str) -> int:
        """Active (pending/firing/resolving) count — the
        ``observation.alerts_active`` metric input (Ruling H wiring)."""
        return self._store.count_active(session_id)

    def health(
        self,
        session_id: str,
        *,
        reader: MetricWindowReader,
        now_ns: int,
        clock_domain: str,
        clock_epoch: int = 0,
    ) -> HealthResult:
        """Evaluate + roll-up (the #53 ``GET .../health`` backend)."""
        evaluation = self._engine.evaluate(
            session_id,
            reader=reader,
            now_ns=now_ns,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
        )
        return roll_up(self._rule_set, evaluation)

    # --- helpers ----------------------------------------------------------------------


__all__ = [
    "ALERT_CHANGED_TOPIC",
    "WS_HINT_TOPICS",
    "ACTIVE_STATES",
    "LIST_LIMIT_DEFAULT",
    "LIST_LIMIT_HARD_CAP",
    "AlertEvaluationResult",
    "AlertHint",
    "AlertHintEmitter",
    "AlertListRequest",
    "AlertPage",
    "AlertService",
]
