"""SPEC-304 Health & Alerts (ticket #52) — application/observation/alerts.

The alert-record-authority plane (SPEC-304 §5 暴露方式): declarative health
rules (:mod:`.rules`, REQ-304-001), the deterministic virtual-time lifecycle
engine (:mod:`.engine`, REQ-304-002), fingerprint dedup (:mod:`.fingerprint`,
REQ-304-004), the deterministic health roll-up (:mod:`.rollup`, REQ-304-005),
the store protocol + list face (:mod:`.store`, REQ-304-003) and the
``AlertService`` composition with the INJECTED hint-emitter port (R1 seam —
the hub binding is ticket #53's face).

MVP produces ZERO ``observation.*`` envelope events: the record is the
authority, state changes surface as ``observation.alert_changed`` hints
(plain topic strings, refused by ``validate_event_type``) and REST pulls
read the store. The evidence discipline (REQ-304-006: resolvable refs, no
secrets, facts vs interpretation distinguishable) lives in the engine's
fact summaries and ``metric:<name>:bucket-<start_ns>`` refs.
"""

from application.observation.alerts.engine import (
    AlertEngine,
    AlertEngineConfig,
    AlertEvaluation,
    AlertTransition,
    RuleContribution,
    metric_bucket_ref,
)
from application.observation.alerts.errors import (
    OBS_RULE_INPUT_STALE,
    OBS_RULE_INVALID,
    AlertError,
)
from application.observation.alerts.fingerprint import (
    FINGERPRINT_PREFIX,
    alert_fingerprint,
)
from application.observation.alerts.inputs import (
    MetricWindowReader,
    MetricsWindowReader,
)
from application.observation.alerts.rollup import (
    INPUT_MISSING_REASON,
    ROLLUP_POLICY,
    DimensionHealth,
    HealthResult,
    RollupPolicy,
    roll_up,
)
from application.observation.alerts.rules import (
    ComparisonOperator,
    Condition,
    EvidencePolicy,
    HealthRule,
    HealthRuleSet,
    MissingDataPolicy,
    RuleAggregation,
    default_rule_set,
    validate_health_rule,
)
from application.observation.alerts.service import (
    ALERT_CHANGED_TOPIC,
    WS_HINT_TOPICS,
    AlertEvaluationResult,
    AlertHint,
    AlertHintEmitter,
    AlertListRequest,
    AlertPage,
    AlertService,
)
from application.observation.alerts.store import (
    ACTIVE_STATES,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_HARD_CAP,
    AlertStore,
)

__all__ = [
    "ACTIVE_STATES",
    "ALERT_CHANGED_TOPIC",
    "ComparisonOperator",
    "Condition",
    "DimensionHealth",
    "EvidencePolicy",
    "FINGERPRINT_PREFIX",
    "HealthResult",
    "HealthRule",
    "HealthRuleSet",
    "INPUT_MISSING_REASON",
    "LIST_LIMIT_DEFAULT",
    "LIST_LIMIT_HARD_CAP",
    "MetricWindowReader",
    "MetricsWindowReader",
    "MissingDataPolicy",
    "OBS_RULE_INPUT_STALE",
    "OBS_RULE_INVALID",
    "ROLLUP_POLICY",
    "RuleAggregation",
    "RuleContribution",
    "AlertEngine",
    "AlertEngineConfig",
    "AlertError",
    "AlertEvaluation",
    "AlertEvaluationResult",
    "AlertHint",
    "AlertHintEmitter",
    "AlertListRequest",
    "AlertPage",
    "AlertService",
    "AlertStore",
    "AlertTransition",
    "RollupPolicy",
    "WS_HINT_TOPICS",
    "alert_fingerprint",
    "default_rule_set",
    "metric_bucket_ref",
    "roll_up",
    "validate_health_rule",
]
