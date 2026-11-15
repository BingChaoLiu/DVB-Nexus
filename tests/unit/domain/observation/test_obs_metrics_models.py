"""SPEC-302 derived metric-series models (ticket #50) — domain vocabulary.

Seam: construction-time validation of the SPEC-302 section 3 models exposed
through ``domain.observation`` (append-only additions, #46 frozen surface
untouched). These tests pin the contract the metrics engine relies on:

- the baseline dimension whitelist (SPEC-302 section 5) and the
  high-cardinality ban (section 4: 任意 payload 文本/原始 URL/BISS 密钥/不可信
  完整 service 名/事件 ID are never legal dimensions);
- per-value-type aggregation legality (section 6.1);
- histogram bucket startup validation (section 13);
- sample record shape: record-level timepoint with explicit ``semantics``
  (SPEC-300 section 6), ``revision``/``is_final`` (SPEC-302 section 6.2,
  #12 ruling) and the gap discipline "缺失 ≠ 零" (value=None requires the
  ``missing`` quality flag, SPEC-302 section 6.3).

G10 (brief section 8): :class:`domain.observation.metric.SeriesQuality`
(SPEC-302 derived series) is a DIFFERENT vocabulary from the SPEC-003
section 2.5 logical ``MetricQuality`` — valid/unavailable/estimated/invalid.
The logical model is untouched; the mapping is documented on the class.
"""

import pytest
from pydantic import ValidationError

from domain.observation import (
    BASELINE_DIMENSIONS,
    AggregationOperation,
    MetricDefinition,
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
    MetricValueType,
    QualityPolicy,
    SeriesQuality,
)


def _definition(**overrides) -> dict:
    fields = {
        "metric_name": "ts.continuity_error_total",
        "value_type": MetricValueType.COUNTER,
        "unit": "errors",
        "description": "continuity errors seen in the session",
        "allowed_dimensions": ("session_id", "pid"),
        "source_event_types": ("ts.continuity_error",),
        "aggregation": (AggregationOperation.LAST, AggregationOperation.INCREASE),
        "temporality": "cumulative",
    }
    fields.update(overrides)
    return fields


def _sample(**overrides) -> dict:
    fields = {
        "metric_name": "ts.continuity_error_total",
        "time": MetricSampleTimepoint(
            value_ns=1_000,
            clock_domain="sim:s-1",
            clock_epoch=0,
            semantics="derived",
        ),
        "value": 3,
        "dimensions": {"session_id": "s-1", "pid": 256},
        "provenance": MetricProvenance(
            source_event_ids=("evt-1",), journal_watermark=7
        ),
    }
    fields.update(overrides)
    return fields


# --- baseline dimension whitelist (SPEC-302 section 5) -------------------------


def test_baseline_dimensions_is_the_nine_name_finite_whitelist() -> None:
    assert BASELINE_DIMENSIONS == frozenset(
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


@pytest.mark.parametrize(
    "banned",
    ["event_id", "raw_url", "biss_key", "payload_text", "service_name"],
)
def test_definition_rejects_high_cardinality_or_off_whitelist_dimensions(
    banned: str,
) -> None:
    # SPEC-302 section 4/5: dimensions are a finite whitelist; event IDs and
    # arbitrary payload text are explicitly banned, never merely discouraged.
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(allowed_dimensions=("session_id", banned)))


def test_definition_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            **_definition(allowed_dimensions=("session_id", "session_id"))
        )


def test_session_domain_metric_requires_the_session_id_dimension() -> None:
    # SPEC-302 section 5: session_id is mandatory for session-domain metrics
    # (scope is carried by dimensions, not by a separate scope field).
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(allowed_dimensions=("pid",)))


def test_snapshot_sourced_metric_still_declares_session_id() -> None:
    definition = MetricDefinition(
        **_definition(
            metric_name="observation.alerts_active",
            value_type=MetricValueType.GAUGE,
            unit="alerts",
            source_event_types=(),
            snapshot_source="alert store (SPEC-304 records)",
            aggregation=(AggregationOperation.LAST,),
            temporality="instant",
        )
    )
    assert definition.snapshot_source == "alert store (SPEC-304 records)"


def test_definition_requires_a_source_declaration() -> None:
    # SPEC-302 section 3: source_event_types AND/OR a snapshot source —
    # a metric with neither has no provenance story and is refused.
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(source_event_types=(), snapshot_source=None))


def test_definition_rejects_unregistered_source_event_types() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(source_event_types=("observation.foo",)))


def test_definition_rejects_bad_metric_name_shape() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(metric_name="NotDotted"))


# --- aggregation legality per value type (SPEC-302 section 6.1) ----------------


def test_counter_accepts_rate_and_increase() -> None:
    definition = MetricDefinition(**_definition())
    assert AggregationOperation.INCREASE in definition.aggregation


def test_rate_is_counter_only() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            **_definition(
                value_type=MetricValueType.GAUGE,
                aggregation=(AggregationOperation.LAST, AggregationOperation.RATE),
                temporality="instant",
            )
        )


def test_quantile_is_histogram_only() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(aggregation=(AggregationOperation.QUANTILE,)))


def test_aggregation_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(**_definition(aggregation=()))


# --- histogram bucket startup validation (SPEC-302 section 13) -----------------


def test_histogram_definition_requires_bucket_configuration() -> None:
    # SPEC-302 section 13: bucket config is startup-validated; a histogram
    # without configured edges would explode cardinality at runtime.
    with pytest.raises(ValidationError):
        MetricDefinition(
            **_definition(
                value_type=MetricValueType.HISTOGRAM,
                aggregation=(
                    AggregationOperation.COUNT,
                    AggregationOperation.SUM,
                    AggregationOperation.QUANTILE,
                ),
            )
        )


def test_histogram_edges_must_strictly_increase() -> None:
    from domain.observation import HistogramSpec

    with pytest.raises(ValidationError):
        HistogramSpec(bucket_edges=(10.0, 10.0, 100.0))
    with pytest.raises(ValidationError):
        HistogramSpec(bucket_edges=(100.0, 10.0))


# --- sample record shape (SPEC-300 section 6 / SPEC-302 section 6.2/6.3) -------


def test_sample_defaults_revision_one_and_not_final() -> None:
    sample = MetricSample(**_sample())
    assert sample.revision == 1
    assert sample.is_final is False


def test_sample_quality_defaults_to_good() -> None:
    sample = MetricSample(**_sample())
    assert sample.quality == (SeriesQuality.GOOD,)


def test_sample_value_none_requires_missing_quality() -> None:
    # SPEC-302 section 6.3: 缺失 ≠ 零 — a null value is only legal together
    # with the ``missing`` quality flag, never as a silent zero.
    with pytest.raises(ValidationError):
        MetricSample(**_sample(value=None))
    sample = MetricSample(**_sample(value=None, quality=(SeriesQuality.MISSING,)))
    assert sample.value is None
    assert SeriesQuality.MISSING in sample.quality


def test_sample_timepoint_carries_explicit_semantics() -> None:
    # SPEC-300 section 6: record-level timepoints carry explicit semantics;
    # the envelope timepoint deliberately does not (SPEC-301 section 6).
    with pytest.raises(ValidationError):
        MetricSampleTimepoint(value_ns=1, clock_domain="sim:s", clock_epoch=0)


def test_sample_dimensions_must_stay_on_the_baseline_whitelist() -> None:
    with pytest.raises(ValidationError):
        MetricSample(**_sample(dimensions={"session_id": "s", "event_id": "x"}))


def test_sample_pid_is_a_bounded_numeric_dimension() -> None:
    # SPEC-302 section 5: pid is a bounded numeric dimension; the bound is
    # the envelope correlation pid range 0..8191 (SPEC-301 section 3).
    with pytest.raises(ValidationError):
        MetricSample(**_sample(dimensions={"session_id": "s", "pid": 8192}))
    sample = MetricSample(**_sample(dimensions={"session_id": "s", "pid": 8191}))
    assert sample.dimensions["pid"] == 8191


def test_sample_revisions_start_at_one_and_never_below() -> None:
    with pytest.raises(ValidationError):
        MetricSample(**_sample(revision=0))


def test_quality_policy_defaults_keep_gaps_null_and_lateness_zero() -> None:
    policy = QualityPolicy()
    assert policy.zero_fill is False  # SPEC-302 section 6.3 default
    assert policy.lateness_window_ns == 0


def test_derived_series_quality_is_not_the_spec003_logical_vocabulary() -> None:
    # G10: the derived-series vocabulary (SPEC-302 schema quality enum) and
    # the SPEC-003 section 2.5 logical MetricQuality are different sets; the
    # mapping valid→good / unavailable→missing is documented on the class and
    # the logical model itself is untouched (metric.py stays frozen).
    assert {q.value for q in SeriesQuality} == {
        "good",
        "missing",
        "late",
        "estimated",
        "partial",
        "revised",
        "invalid",
    }
    from domain.observation import MetricQuality

    assert {q.value for q in MetricQuality} == {
        "valid",
        "unavailable",
        "estimated",
        "invalid",
    }
