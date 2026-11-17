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

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


# --- per-route typed envelopes (ticket #80) ---------------------------------------
#
# The eight §4.5 routes declare these as ``response_model`` so every data
# body becomes an OpenAPI-reachable component (REQ-API-500-002; the #61
# codegen plane). They mirror the base envelope field-for-field with
# ``data`` typed per route — composition, not inheritance: a Pydantic v2
# subclass that overrides a field inlines every property, so inheriting
# would neither reference the base nor change the generated shape.
# Wire shapes are UNCHANGED: handlers already built these DTOs and returned
# ``model_dump(mode="json")``; the response model re-validates and
# serializes identically (the #53 contract tests pin the shapes unchanged).


class SummaryResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: SummaryDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class EventsResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: EventsDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class TimelineResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: TimelineDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class MetricsResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: MetricsDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class AlertsResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: AlertsDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class HealthResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: HealthDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


class ExportResponseDTO(BaseModel):
    request_id: str
    scope: ObservationScopeDTO
    data: ExportDataDTO
    meta: ObservationMetaDTO = Field(default_factory=ObservationMetaDTO)


# --- Phase 2 event payload faces (ticket #129) -------------------------------------
#
# The four encapsulation namespaces' payload shapes (SPEC-303 §Phase2)
# as Pydantic models — the same frozen key sets the registry validators
# enforce (``domain.observation.registry``; the payload schemas travel
# the WS journal frames, which are outside OpenAPI). Mirror discipline:
# the round-trip unit test validates each model against the registry
# test fixtures AND re-checks the dumps through ``validate_payload`` —
# the two faces cannot drift apart silently. The api layer cannot import
# ``domain`` (import-linter C6), so the vocabularies are restated here
# and pinned identical by tests (the ticket #54 precedent).
#
# These payloads are NOT observation faces: no source/confidence axes.


class _StrictDTO(BaseModel):
    """snake_case wire contract: extra keys are a schema violation."""

    model_config = ConfigDict(extra="forbid")


#: The generation ``layer`` axis (CONTEXT.md 作用层; ADR-0010 §3).
GenerationLayer = Literal["TS", "BBFRAME", "T2MI", "BISS"]

#: The ``biss.*`` mode vocabulary — owner is ``ts.biss.cissa``.
BissMode = Literal["1", "E", "2"]

#: The T2-MI packet payload-kind vocabulary (#122 三态).
T2miPayloadKind = Literal["bbframe", "padding", "unknown"]

#: 13-bit DVB PID (SPEC-301 §3 correlation.pid).
Pid = Annotated[int, Field(ge=0, le=8191)]

#: 8-bit transport-prefix PLP id (TS 102 773).
PlpId = Annotated[int, Field(ge=0, le=255)]

#: Lowercase 64-hex digest (the sampled slot's sha256).
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class T2miStageSummaryPayloadDTO(_StrictDTO):
    """``t2mi.stage_summary`` — the per-stage transport summary (#122).

    Distributions map decimal id / kind strings to packet counts; the
    PLP distribution covers BBFRAME packets only (SPEC-602 §6). 摘要面 —
    NOT an observation stream (禁把 PLP 分布当观测流).
    """

    packet_count: int = Field(ge=0)
    padding_count: int = Field(ge=0)
    packet_type_distribution: dict[T2miPayloadKind, int]
    plp_distribution: dict[str, int]


class BusinessAbsentEvidenceDTO(_StrictDTO):
    """``t2mi.plp_mismatch`` evidence object (#124; 缺失 ≠ 零)."""

    plps_seen: list[PlpId]
    bbframe_packet_count: int = Field(ge=0)
    filtered_packet_count: int = Field(ge=0)
    total_packet_count: int = Field(ge=0)


class T2miPlpMismatchPayloadDTO(_StrictDTO):
    """``t2mi.plp_mismatch`` — the B1 candidate (#124).

    ``actual_plp`` is honest about ambiguity: the single observed PLP
    when the stream carries exactly one, ``None`` otherwise — the full
    observation travels in ``business_absent_evidence``.
    """

    expected_plp: PlpId
    actual_plp: PlpId | None
    business_absent_evidence: BusinessAbsentEvidenceDTO


class BbframeStageSummaryPayloadDTO(_StrictDTO):
    """``bbframe.stage_summary`` — the per-stage frame summary (#123).

    ``n_ups_distribution`` maps decimal UP counts to frame counts;
    ``stuffing_ratio`` is tail stuffing bytes / data-field bytes.
    """

    frame_count: int = Field(ge=0)
    n_ups_distribution: dict[str, int]
    stuffing_ratio: Annotated[float, Field(ge=0, le=1)]


class BbframeRecoveryFailedPayloadDTO(_StrictDTO):
    """``bbframe.recovery_failed`` — the B2 recovery evidence (#123).

    The SPEC-307 BBHEADER_SYNC_FAULT rule's expected evidence symbol;
    the count covers CRC-8 failures (+malformed_short) per #123 REPORT.
    """

    failure_count: int = Field(ge=0)
    first_failed_frame_index: Annotated[int, Field(ge=0)] | None


class BissScrambleAppliedPayloadDTO(_StrictDTO):
    """``biss.scramble_applied`` — the shared scrambler face (#126/#127).

    ``key_fingerprint`` is a fingerprint reference, never key material
    (SPEC-610 §9). ``mutation_log_ref`` is ``None`` on the emission seam
    (the runtime binds the log artifact at delivery) — the KEY stays
    present (honest None, never an absent face). The mode-coupled key-set
    rule (Mode 1 = exactly the five shared keys; the derived modes carry
    EITHER the bare five on the construction path or + the derivation
    face on the fault path) is the REGISTRY validator's authority
    (``domain.observation.registry``); the optional ``derivation_ref`` /
    ``mismatch_variants`` fields mirror the #127 derivation face here —
    the redacted chain fingerprints (esw/injected_id/session_word/
    ciss_key) plus the declared wrong-key variants, making the two 错配
    evidence faces distinguishable (SPEC-611 §8).
    """

    pid_scope: list[Pid] = Field(min_length=1)
    packet_count: int = Field(ge=0)
    key_fingerprint: str = Field(min_length=1)
    mutation_log_ref: str | None
    mode: BissMode
    derivation_ref: dict[str, str] | None = None
    mismatch_variants: list[str] | None = None


class BissDescrambleFailedPayloadDTO(_StrictDTO):
    """``biss.descramble_failed`` — 解扰失败 ≠ 码流损坏 (ADR-0011 §4).

    ``failed_indices_sample`` is bounded (≤16) so the evidence stays
    bounded; ``key_fingerprint_ref`` links the candidate to the key
    fingerprint (互链 with the mutation log, never the key itself).
    """

    pid_scope: list[Pid] = Field(min_length=1)
    failed_indices_sample: list[Annotated[int, Field(ge=0)]] = Field(
        max_length=16
    )
    self_check_kind: str = Field(min_length=1)
    key_fingerprint_ref: str = Field(min_length=1)
    mode: BissMode


class GenStageStartedPayloadDTO(_StrictDTO):
    """``gen.stage_started`` — one pipeline stage begins (#128)."""

    layer: GenerationLayer


class GenStageCompletedPayloadDTO(_StrictDTO):
    """``gen.stage_completed`` — one pipeline stage ends (#128)."""

    layer: GenerationLayer
    item_count: int = Field(ge=0, description="The stage's slot count.")


class GenPacketSampledPayloadDTO(_StrictDTO):
    """``gen.packet_sampled`` — one sampled slot (#128; window policy).

    Stage-level + sampled-packet-level only: the full per-packet stream
    is closed (#112). ``byte_size`` is the slot's byte length; ``sha256``
    is the slot bytes' digest (the packet inspector's jump target).
    """

    layer: GenerationLayer
    packet_index: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    sha256: Sha256


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
    "AlertsResponseDTO",
    "BbframeRecoveryFailedPayloadDTO",
    "BbframeStageSummaryPayloadDTO",
    "BissDescrambleFailedPayloadDTO",
    "BissMode",
    "BissScrambleAppliedPayloadDTO",
    "BusinessAbsentEvidenceDTO",
    "EventsDataDTO",
    "EventsResponseDTO",
    "ExportCreateBody",
    "ExportDataDTO",
    "ExportResponseDTO",
    "GenPacketSampledPayloadDTO",
    "GenStageCompletedPayloadDTO",
    "GenStageStartedPayloadDTO",
    "GenerationLayer",
    "HealthDataDTO",
    "HealthDimensionDTO",
    "HealthResponseDTO",
    "MetricPointDTO",
    "MetricSeriesDTO",
    "MetricsDataDTO",
    "MetricsQueryBody",
    "MetricsResponseDTO",
    "ObservationMetaDTO",
    "ObservationResponseDTO",
    "ObservationScopeDTO",
    "SummaryDataDTO",
    "SummaryResponseDTO",
    "T2miPayloadKind",
    "T2miPlpMismatchPayloadDTO",
    "T2miStageSummaryPayloadDTO",
    "TimelineDataDTO",
    "TimelineLaneDTO",
    "TimelineResponseDTO",
    "alert_record_dto",
    "health_result_dto",
    "metric_series_dto",
    "timeline_record_dto",
]
