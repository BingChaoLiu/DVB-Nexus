"""Observation domain: the unified event exchange interface.

Facts, metrics and evidence models plus the event publishing contract
(SPEC-001 section 4). Producers must declare source and confidence; observed
facts are never mixed with structured evidence.

The canonical event envelope (SPEC-301, ADR-0006 decision 1) lives here too:
``EventEnvelope`` + the authoritative event type registry are the single
exchange vocabulary shared with ts/simulation/adapters (simulation imports
this package and may not invent a fourth envelope — import-linter ruling on
#15). Producers keep the envelope loose and payloads tight; ``journal_seq``
is a gateway-stamped field, never a producer input (ADR-0006 decision 2).

Also hosts the run-scoped shared vocabulary every consumer may import
(ADR-0005 decision 4 hub): RunContext, the ID strategy types (ADR-0006
decision 3) and the SPEC-003 section 3 status vocabulary.
"""

from domain.observation.alert_record import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    AlertSuppression,
    HealthDimension,
    HealthStatus,
)
from domain.observation.artifact import ArtifactKind, TSArtifact
from domain.observation.envelope import (
    Correlation,
    EventEnvelope,
    Producer,
    Scope,
    Severity,
    Time,
    Timepoint,
    new_event_id,
    parse_envelope,
)
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.ids import Identifier, OpaqueEntityId
from domain.observation.metric import Metric, MetricQuality
from domain.observation.metric_series import (
    BASELINE_DIMENSIONS,
    AggregationOperation,
    HistogramSpec,
    MetricDefinition,
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
    MetricTemporality,
    MetricValueType,
    QualityPolicy,
    SampleSemantics,
    SeriesQuality,
)
from domain.observation.model import ConfidenceKind, Observation, ObservationSource
from domain.observation.registry import (
    DIAGNOSIS_CONFIDENCES,
    DIAGNOSIS_SEVERITIES,
    REGISTERED_EVENT_TYPES,
    WITHDRAWN_EVENT_TYPES,
    is_coalescable,
    is_delivery_protected,
    is_registered,
    is_withdrawn,
    validate_event_type,
    validate_payload,
)
from domain.observation.run_context import Fidelity, RunContext, RunMode
from domain.observation.time_domain import (
    TimeDomainKey,
    ensure_same_time_domain,
    time_domain_key,
)
from domain.observation.status import (
    HealthState,
    LifecycleState,
    LockState,
    OperationalState,
)
from domain.observation.timeline import (
    DEFAULT_SORT_DESCRIPTOR,
    JOURNAL_SEQ_SORT,
    SOURCE_ORDER_SORT,
    CheckpointRecord,
    ProducerStateVersion,
    TimelineRecord,
    TimelineRecordKind,
    TimelineTimepoint,
    TimepointSemantics,
    record_time_domain_key,
    timeline_record_sort_key,
)

__all__ = [
    "AlertRecord",
    "AlertScope",
    "AlertSeverity",
    "AlertState",
    "AlertSuppression",
    "ArtifactKind",
    "BASELINE_DIMENSIONS",
    "AggregationOperation",
    "CheckpointRecord",
    "ConfidenceKind",
    "HealthDimension",
    "HealthStatus",
    "HistogramSpec",
    "MetricDefinition",
    "MetricProvenance",
    "MetricSample",
    "MetricSampleTimepoint",
    "MetricTemporality",
    "MetricValueType",
    "QualityPolicy",
    "SampleSemantics",
    "SeriesQuality",
    "Correlation",
    "DEFAULT_SORT_DESCRIPTOR",
    "EnvelopeError",
    "EnvelopeErrorCode",
    "EventEnvelope",
    "Fidelity",
    "HealthState",
    "Identifier",
    "JOURNAL_SEQ_SORT",
    "LifecycleState",
    "LockState",
    "Metric",
    "MetricQuality",
    "Observation",
    "ObservationSource",
    "OperationalState",
    "OpaqueEntityId",
    "Producer",
    "ProducerStateVersion",
    "REGISTERED_EVENT_TYPES",
    "RunContext",
    "RunMode",
    "SOURCE_ORDER_SORT",
    "DIAGNOSIS_CONFIDENCES",
    "DIAGNOSIS_SEVERITIES",
    "Scope",
    "Severity",
    "Time",
    "TimeDomainKey",
    "TimelineRecord",
    "TimelineRecordKind",
    "TimelineTimepoint",
    "Timepoint",
    "TimepointSemantics",
    "TSArtifact",
    "WITHDRAWN_EVENT_TYPES",
    "ensure_same_time_domain",
    "is_coalescable",
    "is_delivery_protected",
    "is_registered",
    "is_withdrawn",
    "new_event_id",
    "parse_envelope",
    "record_time_domain_key",
    "time_domain_key",
    "timeline_record_sort_key",
    "validate_event_type",
    "validate_payload",
]
