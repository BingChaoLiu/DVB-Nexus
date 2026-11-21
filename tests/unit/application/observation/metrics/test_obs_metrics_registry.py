"""SPEC-302 metric catalog + registry (ticket #50) — REQ-OBS-302-001.

Seam: ``MetricRegistry`` / ``default_catalog()``. These tests pin:

- catalog completeness: all 15 SPEC-302 section 4 catalog metrics plus the
  two Phase 3 alert-input gauges (ticket #166) register
  and validate (catalog integrity IS REQ-OBS-302-001);
- unknown metrics are refused with the SPEC-300 §13 code
  ``OBS_METRIC_NOT_FOUND`` unless ``allow_unknown=True``;
- dimension filters outside a metric's ``allowed_dimensions`` are refused
  with the SPEC-302 §10 code ``OBS_METRIC_DIMENSION_REJECTED`` (strict
  default);
- every catalog metric carries an explicit unit, a provenance declaration,
  legal aggregation ops and (session-domain) the mandatory ``session_id``
  dimension.
"""

import pytest
from pydantic import ValidationError

from application.observation.metrics.catalog import CATALOG_METRIC_NAMES, default_catalog
from application.observation.metrics.errors import (
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    MetricError,
)
from application.observation.metrics.registry import MetricRegistry
from domain.observation import (
    AggregationOperation,
    MetricDefinition,
    MetricValueType,
)


# --- catalog completeness (SPEC-302 section 4, REQ-OBS-302-001) ----------------


def test_catalog_declares_exactly_the_fifteen_spec_metrics() -> None:
    # The 15 SPEC-302 §4 names + the two Phase 3 alert inputs (ticket #166,
    # SPEC-304 §Phase3 — the additive registration is pinned here verbatim).
    assert set(CATALOG_METRIC_NAMES) == {
        "ts.packet_rate",
        "ts.bitrate",
        "ts.continuity_error_total",
        "ts.pcr_jitter_ns",
        "ts.pcr_repetition_gap_ns",
        "ts.null_packet_ratio",
        "ts.scrambled_packet_ratio",
        "psi.section_repetition_gap_ms",
        "simulation.virtual_time_ns",
        "simulation.event_lag_ns",
        "topology.degraded_node_count",
        "observation.ingest_events_total",
        "observation.duplicate_events_total",
        "observation.consumer_lag_events",
        "observation.alerts_active",
        "tuner.lock_state",
        "tuner.ber_state",
    }
    assert len(CATALOG_METRIC_NAMES) == 17


def test_default_catalog_registers_and_validates_all_fifteen() -> None:
    registry = default_catalog()
    assert registry.names() == tuple(sorted(CATALOG_METRIC_NAMES))


@pytest.mark.parametrize(
    "name,value_type,unit",
    [
        ("ts.packet_rate", MetricValueType.GAUGE, "packets/s"),
        ("ts.bitrate", MetricValueType.GAUGE, "bit/s"),
        ("ts.continuity_error_total", MetricValueType.COUNTER, "errors"),
        ("ts.pcr_jitter_ns", MetricValueType.HISTOGRAM, "ns"),
        ("ts.pcr_repetition_gap_ns", MetricValueType.GAUGE, "ns"),
        ("ts.null_packet_ratio", MetricValueType.GAUGE, "ratio"),
        ("ts.scrambled_packet_ratio", MetricValueType.GAUGE, "ratio"),
        ("psi.section_repetition_gap_ms", MetricValueType.GAUGE, "ms"),
        ("simulation.virtual_time_ns", MetricValueType.GAUGE, "ns"),
        ("simulation.event_lag_ns", MetricValueType.GAUGE, "ns"),
        ("topology.degraded_node_count", MetricValueType.GAUGE, "nodes"),
        ("observation.ingest_events_total", MetricValueType.COUNTER, "events"),
        ("observation.duplicate_events_total", MetricValueType.COUNTER, "events"),
        ("observation.consumer_lag_events", MetricValueType.GAUGE, "events"),
        ("observation.alerts_active", MetricValueType.GAUGE, "alerts"),
        ("tuner.lock_state", MetricValueType.GAUGE, "1"),
        ("tuner.ber_state", MetricValueType.GAUGE, "1"),
    ],
)
def test_every_catalog_metric_has_type_and_explicit_unit(
    name: str, value_type: MetricValueType, unit: str
) -> None:
    # SPEC-302 section 3: units are explicit, never implied.
    definition = default_catalog().require(name)
    assert definition.value_type is value_type
    assert definition.unit == unit


def test_every_catalog_metric_is_session_domain_with_session_id() -> None:
    # SPEC-302 section 5: session_id is mandatory for session-domain metrics.
    for name in CATALOG_METRIC_NAMES:
        definition = default_catalog().require(name)
        assert definition.session_domain is True
        assert "session_id" in definition.allowed_dimensions


def test_counter_metrics_allow_rate_and_increase() -> None:
    for name in (
        "ts.continuity_error_total",
        "observation.ingest_events_total",
        "observation.duplicate_events_total",
    ):
        definition = default_catalog().require(name)
        assert AggregationOperation.INCREASE in definition.aggregation
        assert AggregationOperation.RATE in definition.aggregation


def test_histogram_metric_declares_bucket_configuration() -> None:
    definition = default_catalog().require("ts.pcr_jitter_ns")
    assert definition.histogram is not None
    assert AggregationOperation.QUANTILE in definition.aggregation


# --- registry lookups and structured refusals ----------------------------------


def test_registry_require_refuses_unknown_metric_with_canonical_code() -> None:
    registry = MetricRegistry()
    with pytest.raises(MetricError) as excinfo:
        registry.require("no.such_metric")
    assert excinfo.value.error_code == OBS_METRIC_NOT_FOUND
    assert excinfo.value.retryable is False


def test_registry_require_with_allow_unknown_skips_instead_of_refusing() -> None:
    registry = MetricRegistry()
    assert registry.require("no.such_metric", allow_unknown=True) is None


def test_registry_register_rejects_duplicate_names() -> None:
    definition = default_catalog().require("ts.packet_rate")
    registry = MetricRegistry((definition,))
    with pytest.raises(ValueError):
        registry.register(definition)


def test_registry_dimension_filters_outside_whitelist_are_rejected() -> None:
    registry = default_catalog()
    definition = registry.require("ts.continuity_error_total")
    with pytest.raises(MetricError) as excinfo:
        registry.validate_dimension_filters(
            definition, {"session_id": "s", "stream_id": "x"}
        )
    assert excinfo.value.error_code == OBS_METRIC_DIMENSION_REJECTED
    assert "stream_id" in str(excinfo.value)


def test_registry_dimension_filters_within_whitelist_pass() -> None:
    registry = default_catalog()
    definition = registry.require("ts.continuity_error_total")
    assert (
        registry.validate_dimension_filters(
            definition, {"session_id": "s", "pid": 256}
        )
        is None
    )


def test_metric_error_carries_the_structured_shape() -> None:
    # SPEC-300 section 13: error_code / message / retryable / details.
    error = MetricError(
        OBS_METRIC_NOT_FOUND, "unknown metric", details={"metric": "x.y"}
    )
    assert error.error_code == OBS_METRIC_NOT_FOUND
    assert error.retryable is False
    assert error.details == {"metric": "x.y"}


def test_definitions_are_immutable_domain_models() -> None:
    definition = default_catalog().require("ts.packet_rate")
    assert isinstance(definition, MetricDefinition)
    with pytest.raises(ValidationError):
        definition.unit = "bit/s"
