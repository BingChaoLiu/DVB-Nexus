"""SPEC-302 derived metric-series vocabulary and record models (ticket #50).

The metrics engine's domain face: metric definitions (section 3), the
baseline dimension whitelist (section 5), the derived-series quality
vocabulary and the sample record (section 6.2/6.3 — ``revision``/``is_final``
per the #12 seam-approval ruling, explicit ``semantics`` on the record-level
timepoint per SPEC-300 section 6).

Vocabulary discipline (G10, brief section 8): :class:`SeriesQuality` is the
SPEC-302 *derived series* enum (schema ``quality``):
good/missing/late/estimated/partial/revised/invalid. It is NOT the SPEC-003
section 2.5 logical :class:`domain.observation.metric.MetricQuality`
(valid/unavailable/estimated/invalid), which keeps its frozen meaning for
run-scoped logical metric records. Mapping between the two, for consumers
that hold both: valid→good, unavailable→missing, estimated→estimated,
invalid→invalid; late/partial/revised have no logical-record counterpart
(they describe derived-series arrival/revision states). The logical model in
``metric.py`` is untouched by this module.

High-cardinality dimensions (section 4 ban list: 任意 payload 文本、原始
URL、BISS 密钥、不可信完整 service 名、事件 ID) are structurally impossible
here: dimensions must come from the finite baseline whitelist (section 5).
"""

import re
from enum import Enum
from typing import Optional, Union

from pydantic import Field, field_validator, model_validator

from domain._base import DomainModel
from domain.observation.registry import is_registered

#: Metric-name shape — stable dotted identifier (SPEC-302 section 3; same
#: shape discipline as the event-type registry, SPEC-301 section 4).
_METRIC_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: Baseline dimension whitelist (SPEC-302 section 5). ``pid`` is the one
#: bounded numeric dimension; everything else is a controlled string.
BASELINE_DIMENSIONS = frozenset(
    {
        "session_id",
        "scenario_id",
        "source_id",
        "service_id",
        "pid",
        "node_id",
        "fault_type",
        "severity",
        "stream_id",
    }
)

#: Inclusive pid bound — the envelope correlation pid range (SPEC-301 §3).
_PID_MAX = 8191

#: Dimension value kinds: controlled strings, ints, booleans — never raw
#: payload text (the section 4 ban is structural, not advisory).
DimensionValue = Union[str, int, bool]


class MetricValueType(str, Enum):
    """Sample value type (SPEC-302 section 3)."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricTemporality(str, Enum):
    """Sample temporality (SPEC-302 section 3)."""

    CUMULATIVE = "cumulative"
    DELTA = "delta"
    INSTANT = "instant"


class AggregationOperation(str, Enum):
    """Aggregation operations (SPEC-302 section 6.1).

    Base ops apply to scalar series; ``count``/``quantile`` are histogram
    only; ``rate``/``increase`` are counter only (reset-detecting).
    """

    SUM = "sum"
    MIN = "min"
    MAX = "max"
    AVG = "avg"
    LAST = "last"
    COUNT = "count"
    RATE = "rate"
    INCREASE = "increase"
    QUANTILE = "quantile"


_BASE_OPS = frozenset(
    {
        AggregationOperation.SUM,
        AggregationOperation.MIN,
        AggregationOperation.MAX,
        AggregationOperation.AVG,
        AggregationOperation.LAST,
    }
)
_COUNTER_OPS = frozenset(
    {AggregationOperation.RATE, AggregationOperation.INCREASE}
)
_HISTOGRAM_OPS = frozenset(
    {AggregationOperation.COUNT, AggregationOperation.QUANTILE}
)


class SeriesQuality(str, Enum):
    """Derived-series quality flags (SPEC-302 sample schema ``quality``).

    See the module docstring for the G10 mapping to the SPEC-003 §2.5
    logical ``MetricQuality`` vocabulary.
    """

    GOOD = "good"
    MISSING = "missing"
    LATE = "late"
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    REVISED = "revised"
    INVALID = "invalid"


class SampleSemantics(str, Enum):
    """Record-level timepoint semantics (SPEC-300 section 6).

    The envelope timepoint has no semantics field (the ``source``/``observed``
    field names carry it, SPEC-301 §6); derived-series records are explicit.
    """

    SOURCE = "source"
    OBSERVED = "observed"
    DERIVED = "derived"


class QualityPolicy(DomainModel):
    """Per-metric gap/late handling (SPEC-302 section 3 ``quality_policy``).

    Defaults implement the section 6.3 discipline: gaps are null + quality
    ``missing`` — 缺失 ≠ 零 (same-source discipline as SPEC-206 §6).
    """

    zero_fill: bool = False
    #: Arrival slack after which a bucket is finalized; later samples are
    #: late (SPEC-302 section 6.2, configurable lateness window).
    lateness_window_ns: int = Field(default=0, ge=0)


class HistogramSpec(DomainModel):
    """Histogram bucket configuration, startup-validated (SPEC-302 §13).

    Bucket misconfiguration is a cardinality-explosion risk (section 13
    risk note), so edges are strictly-increasing non-empty sequences and the
    registry refuses histogram definitions without this block.
    """

    bucket_edges: tuple[float, ...]
    quantiles: tuple[float, ...] = (0.5, 0.95, 0.99)

    @field_validator("bucket_edges")
    @classmethod
    def _validate_edges(cls, edges: tuple[float, ...]) -> tuple[float, ...]:
        if not edges:
            raise ValueError("histogram bucket_edges must not be empty")
        for previous, current in zip(edges, edges[1:]):
            if not current > previous:
                raise ValueError(
                    "histogram bucket_edges must strictly increase "
                    f"(got {edges!r}); bucket config is startup-validated "
                    "(SPEC-302 section 13)"
                )
        return edges

    @field_validator("quantiles")
    @classmethod
    def _validate_quantiles(cls, quantiles: tuple[float, ...]) -> tuple[float, ...]:
        for q in quantiles:
            if not 0.0 < q <= 1.0:
                raise ValueError(f"quantiles must be in (0, 1], got {q!r}")
        return quantiles


class MetricDefinition(DomainModel):
    """Metric definition (SPEC-302 section 3)."""

    metric_name: str
    value_type: MetricValueType
    #: Explicit unit (section 3 — units are mandatory, never implied).
    unit: str = Field(min_length=1)
    description: str
    allowed_dimensions: tuple[str, ...] = ()
    source_event_types: tuple[str, ...] = ()
    #: Snapshot provenance for metrics not derived from journal events
    #: (section 3: source_event_types 和/或快照来源).
    snapshot_source: Optional[str] = None
    aggregation: tuple[AggregationOperation, ...]
    temporality: MetricTemporality
    quality_policy: QualityPolicy = QualityPolicy()
    histogram: Optional[HistogramSpec] = None
    #: Session-domain metrics carry ``session_id`` as a mandatory dimension
    #: (section 5: scope 由维度承载、不另设 scope 字段). Every MVP catalog
    #: metric is session-scoped.
    session_domain: bool = True

    @field_validator("metric_name")
    @classmethod
    def _validate_name(cls, name: str) -> str:
        if not _METRIC_NAME_PATTERN.match(name):
            raise ValueError(
                f"metric_name is not a stable dotted identifier: {name!r}"
            )
        return name

    @field_validator("allowed_dimensions")
    @classmethod
    def _validate_dimensions(cls, dims: tuple[str, ...]) -> tuple[str, ...]:
        for dim in dims:
            if dim not in BASELINE_DIMENSIONS:
                raise ValueError(
                    f"dimension {dim!r} is outside the baseline whitelist "
                    "(SPEC-302 section 5); payload text, URLs, keys, "
                    "untrusted service names and event IDs are banned "
                    "(section 4)"
                )
        if len(set(dims)) != len(dims):
            raise ValueError(f"allowed_dimensions has duplicates: {dims!r}")
        return dims

    @field_validator("source_event_types")
    @classmethod
    def _validate_sources(cls, types: tuple[str, ...]) -> tuple[str, ...]:
        for event_type in types:
            if not is_registered(event_type):
                raise ValueError(
                    f"source_event_types entry {event_type!r} is not a "
                    "registered event type (SPEC-301 section 4)"
                )
        return types

    @model_validator(mode="after")
    def _validate_shape(self) -> "MetricDefinition":
        if self.session_domain and "session_id" not in self.allowed_dimensions:
            raise ValueError(
                f"session-domain metric {self.metric_name!r} must allow the "
                "'session_id' dimension (SPEC-302 section 5: scope 由维度承载)"
            )
        if not self.source_event_types and not self.snapshot_source:
            raise ValueError(
                f"metric {self.metric_name!r} needs source_event_types "
                "and/or a snapshot_source (SPEC-302 section 3)"
            )
        if not self.aggregation:
            raise ValueError(
                f"metric {self.metric_name!r} must declare at least one "
                "aggregation operation (SPEC-302 section 6.1)"
            )
        ops = set(self.aggregation)
        illegal = set()
        if self.value_type is not MetricValueType.COUNTER:
            illegal |= ops & _COUNTER_OPS
        if self.value_type is not MetricValueType.HISTOGRAM:
            illegal |= ops & _HISTOGRAM_OPS
        if illegal:
            legal = {
                MetricValueType.COUNTER: "counters",
                MetricValueType.GAUGE: "gauges",
                MetricValueType.HISTOGRAM: "histograms",
            }[self.value_type]
            raise ValueError(
                f"aggregation ops {sorted(op.value for op in illegal)} are "
                f"not legal for {legal} (SPEC-302 section 6.1)"
            )
        if (
            self.value_type is MetricValueType.HISTOGRAM
            and self.histogram is None
        ):
            raise ValueError(
                f"histogram metric {self.metric_name!r} needs a "
                "HistogramSpec (bucket config is startup-validated, "
                "SPEC-302 section 13)"
            )
        return self


class MetricSampleTimepoint(DomainModel):
    """Record-level timepoint: value + domain + epoch + semantics.

    SPEC-300 section 6 requires record-level timepoints to carry explicit
    semantics; the envelope timepoint deliberately does not (SPEC-301 §6).
    """

    model_config = DomainModel.model_config | {"extra": "ignore"}

    value_ns: int
    clock_domain: str = Field(min_length=1, max_length=128)
    clock_epoch: int = Field(ge=0)
    semantics: SampleSemantics


class MetricProvenance(DomainModel):
    """Traceability block (SPEC-302 section 1: 每个聚合值都能追溯到来源)."""

    source_event_ids: tuple[str, ...] = ()
    journal_watermark: Optional[int] = None


class MetricSample(DomainModel):
    """One derived-series sample (SPEC-302 section 3/6.2).

    ``revision``/``is_final`` correspond 1:1 to the sample schema fields
    (SPEC-302 section 6.2, #12 ruling): revision 1 = first write;
    backfill revisions increment; ``is_final`` mirrors the containing
    bucket's finality at the time of the last write.
    """

    metric_name: str
    time: MetricSampleTimepoint
    #: ``None`` is legal only with the ``missing`` quality flag (section 6.3:
    # 缺失 ≠ 零). bool is never coerced into int.
    value: Optional[Union[int, float]]
    dimensions: dict[str, DimensionValue] = Field(default_factory=dict)
    quality: tuple[SeriesQuality, ...] = (SeriesQuality.GOOD,)
    provenance: MetricProvenance = MetricProvenance()
    revision: int = Field(default=1, ge=1)
    is_final: bool = False

    @field_validator("dimensions")
    @classmethod
    def _validate_dimensions(
        cls, dims: dict[str, DimensionValue]
    ) -> dict[str, DimensionValue]:
        for dim in dims:
            if dim not in BASELINE_DIMENSIONS:
                raise ValueError(
                    f"dimension {dim!r} is outside the baseline whitelist "
                    "(SPEC-302 section 5)"
                )
        pid = dims.get("pid")
        if pid is not None and not 0 <= int(pid) <= _PID_MAX:
            raise ValueError(
                f"pid dimension out of the bounded range 0..{_PID_MAX}: {pid!r} "
                "(SPEC-302 section 5; SPEC-301 correlation pid range)"
            )
        return dims

    @model_validator(mode="after")
    def _validate_gap_discipline(self) -> "MetricSample":
        if self.value is None and SeriesQuality.MISSING not in self.quality:
            raise ValueError(
                "a null sample value requires the 'missing' quality flag "
                "(SPEC-302 section 6.3: 缺失 ≠ 零)"
            )
        return self


__all__ = [
    "BASELINE_DIMENSIONS",
    "AggregationOperation",
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
]
