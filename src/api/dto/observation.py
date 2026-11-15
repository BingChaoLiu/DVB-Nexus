"""Observation query DTOs — SPEC-305 §6 envelope + §5 flat query shapes
(ticket #53).

The envelope authority is SPEC-305 §6 (request_id/scope/data/meta); the
data bodies are the eight endpoints' answer shapes. The api layer never
imports ``domain`` (import-linter C6): the record→DTO mappers below read
the application-plane results duck-typed (the ``ServiceDiagnosisPort``
precedent from ticket #54).

Query-parameter authority is SPEC-305 §5 (flat scalars; ISO-8601 strings
legal only in the wall:utc domain; timepoint objects are record shapes,
never query parameters). Shape enforcement lives in the query service —
the DTOs carry the wire shapes (``start_ns`` accepts both the integer and
the ISO string form; mixing is refused at the service seam with the 422
row).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --- §6 envelope -----------------------------------------------------------------


class ObservationScopeDTO(BaseModel):
    tenant_id: str
    session_id: str


class ObservationMetaDTO(BaseModel):
    schema_version: str = "1.0"
    next_cursor: Optional[str] = None
    truncated: bool = False
    clock_domain: Optional[str] = None


class ObservationResponseDTO(BaseModel):
    """The §6 response envelope (contract-test round-trip anchor)."""

    request_id: str
    scope: ObservationScopeDTO
    data: Any
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


# --- §5 flat query bodies (POST endpoints) -----------------------------------------


class MetricsQueryBody(BaseModel):
    """``POST .../metrics/query`` — the SPEC-302 §8 / SPEC-305 §5 flat
    body (mirrors examples/metric-query-example.json)."""

    metric_names: list[str] = Field(min_length=1)
    start_ns: int | str
    end_ns: int | str
    step_ns: int = Field(ge=1)
    clock_domain: str = Field(min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    max_points: Optional[int] = None
    aggregation_override: Optional[str] = None
    allow_unknown: bool = False


class ExportCreateBody(BaseModel):
    """``POST .../exports`` — creates ONLY an Observation export task
    (read-only discipline, SPEC-305 §4)."""

    formats: list[str] = Field(default_factory=lambda: ["jsonl"])
    redaction_policy: str = "none"
    record_kinds: list[str] = Field(default_factory=list)
    clock_domain: Optional[str] = None
    clock_epoch: Optional[int] = Field(default=None, ge=0)
    start_ns: Optional[int | str] = None
    end_ns: Optional[int | str] = None


# --- data bodies -----------------------------------------------------------------


class SummaryDataDTO(BaseModel):
    tenant_id: str
    session_id: str
    journal_seq_watermark: int
    event_count: int
    active_alert_count: int = 0
    schema_version: str = "1.0"


class EventsDataDTO(BaseModel):
    sort: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class TimelineLaneDTO(BaseModel):
    clock_domain: str
    clock_epoch: int
    sort_descriptor: str
    records: list[dict[str, Any]] = Field(default_factory=list)


class TimelineDataDTO(BaseModel):
    sort_descriptor: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    lanes: Optional[list[TimelineLaneDTO]] = None


class MetricPointDTO(BaseModel):
    start_ns: int
    end_ns: int
    value: Optional[float | int | dict[str, Any]] = None
    quality: list[str] = Field(default_factory=list)
    revision: int = 1
    is_final: bool = False


class MetricSeriesDTO(BaseModel):
    metric_name: str
    unit: str
    value_type: str
    aggregation: str
    clock_domain: str
    dimensions: dict[str, Any] = Field(default_factory=dict)
    points: list[MetricPointDTO] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MetricsDataDTO(BaseModel):
    series: list[MetricSeriesDTO] = Field(default_factory=list)
    bucket_convention: str = ""
    clock_domain: str


class AlertRecordDTO(BaseModel):
    alert_id: str
    fingerprint: str
    rule_id: str
    rule_version: str
    state: str
    severity: str
    scope: ObservationScopeDTO
    time: dict[str, Any]
    summary: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)
    suppression: Optional[dict[str, Any]] = None
    suppressed: bool = False


class AlertsDataDTO(BaseModel):
    items: list[AlertRecordDTO] = Field(default_factory=list)
    total: int = 0


class HealthDimensionDTO(BaseModel):
    dimension: str
    status: str
    contributing_rule_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class HealthDataDTO(BaseModel):
    session_id: str
    clock_domain: str
    evaluated_at: dict[str, Any]
    rule_set_id: str
    rule_set_version: str
    profile: str
    overall: str
    dimensions: list[HealthDimensionDTO] = Field(default_factory=list)


class ExportDataDTO(BaseModel):
    export_id: str
    session_id: str
    status: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    file_digests: dict[str, str] = Field(default_factory=dict)


# --- record → DTO mappers (duck-typed; C6: no domain imports) ----------------------


def _value(value: Any) -> Any:
    return str(getattr(value, "value", value))


def timeline_record_dto(record: Any) -> dict[str, Any]:
    """One timeline record document (flat filterable fields + payload)."""
    document = record.model_dump(mode="json")
    return document


def alert_record_dto(record: Any) -> AlertRecordDTO:
    """One alert record (SPEC-304 §5 shape; suppression is the modifier,
    not a lifecycle state)."""
    suppression = getattr(record, "suppression", None)
    return AlertRecordDTO(
        alert_id=record.alert_id,
        fingerprint=record.fingerprint,
        rule_id=record.rule_id,
        rule_version=record.rule_version,
        state=_value(record.state),
        severity=_value(record.severity),
        scope=ObservationScopeDTO(
            tenant_id=record.scope.tenant_id, session_id=record.scope.session_id
        ),
        time=record.time.model_dump(mode="json"),
        summary=record.summary,
        evidence_refs=list(record.evidence_refs),
        suppression=(
            suppression.model_dump(mode="json") if suppression is not None else None
        ),
        suppressed=suppression is not None,
    )


def health_result_dto(result: Any) -> HealthDataDTO:
    return HealthDataDTO(
        session_id=result.session_id,
        clock_domain=result.clock_domain,
        evaluated_at=result.evaluated_at.model_dump(mode="json"),
        rule_set_id=result.rule_set_id,
        rule_set_version=result.rule_set_version,
        profile=result.profile,
        overall=_value(result.overall),
        dimensions=[
            HealthDimensionDTO(
                dimension=_value(dimension.dimension),
                status=_value(dimension.status),
                contributing_rule_ids=list(dimension.contributing_rule_ids),
                evidence_refs=list(dimension.evidence_refs),
                reason_codes=list(dimension.reason_codes),
            )
            for dimension in result.dimensions
        ],
    )


def metric_series_dto(view: Any) -> MetricSeriesDTO:
    return MetricSeriesDTO(
        metric_name=view.metric_name,
        unit=view.unit,
        value_type=_value(view.value_type),
        aggregation=_value(view.aggregation),
        clock_domain=view.clock_domain,
        dimensions=dict(view.dimensions),
        points=[
            MetricPointDTO(
                start_ns=point.start_ns,
                end_ns=point.end_ns,
                value=point.value,
                quality=[_value(q) for q in point.quality],
                revision=point.revision,
                is_final=point.is_final,
            )
            for point in view.points
        ],
        provenance=view.provenance.model_dump(mode="json"),
    )


__all__ = [
    "AlertRecordDTO",
    "AlertsDataDTO",
    "EventsDataDTO",
    "ExportCreateBody",
    "ExportDataDTO",
    "HealthDataDTO",
    "HealthDimensionDTO",
    "MetricPointDTO",
    "MetricSeriesDTO",
    "MetricsDataDTO",
    "MetricsQueryBody",
    "ObservationMetaDTO",
    "ObservationResponseDTO",
    "ObservationScopeDTO",
    "SummaryDataDTO",
    "TimelineDataDTO",
    "TimelineLaneDTO",
    "alert_record_dto",
    "health_result_dto",
    "metric_series_dto",
    "timeline_record_dto",
]
