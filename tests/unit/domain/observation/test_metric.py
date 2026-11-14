"""Metric model tests (SPEC-003 section 2.5).

Seam: public construction/validation surface of ``domain.observation``
(Metric), the ``quality`` closed set, and the scalar union type of ``value``.
Expected literals come from SPEC-003 section 2.5 text.
"""

import pytest
from pydantic import ValidationError

from domain.observation import Metric, MetricQuality, ObservationSource


def _metric(**overrides) -> Metric:
    fields = {
        "metric_id": "metric-001",
        "run_id": "3b241101-e2bb-4255-8caf-4136c566a962",
        "name": "cc_error_rate",
        "value": 0.25,
        "source": "internal_parser",
        "quality": "valid",
        "observed_at_utc_ms": 1_700_000_000_000,
    }
    fields.update(overrides)
    return Metric(**fields)


class TestEnumClosedSets:
    def test_metric_quality_has_exactly_the_four_spec_values(self):
        assert {member.value for member in MetricQuality} == {
            "valid",
            "unavailable",
            "estimated",
            "invalid",
        }


class TestMetric:
    def test_valid_construction_required_fields_only(self):
        metric = _metric()
        assert metric.source is ObservationSource.INTERNAL_PARSER
        assert metric.quality is MetricQuality.VALID
        assert metric.unit is None
        assert metric.window_start_utc_ms is None
        assert metric.window_end_utc_ms is None
        assert metric.pid is None

    def test_valid_construction_with_windows_and_pid(self):
        metric = _metric(
            unit="dB",
            window_start_utc_ms=1_699_999_000_000,
            window_end_utc_ms=1_700_000_000_000,
            pid=100,
        )
        assert metric.window_start_utc_ms == 1_699_999_000_000
        assert metric.window_end_utc_ms == 1_700_000_000_000
        assert metric.pid == 100

    def test_round_trip(self):
        metric = _metric(unit="ms", pid=0)
        assert Metric.model_validate(metric.model_dump()) == metric

    def test_value_scalar_union_keeps_each_json_type_distinct(self):
        # SPEC-003 section 2.5: value is number | string | boolean. Each JSON
        # scalar kind must survive as its own type (bool is not 0/1).
        assert type(_metric(value=1).value) is int
        assert type(_metric(value=1.5).value) is float
        assert type(_metric(value="locked").value) is str
        assert type(_metric(value=True).value) is bool

    def test_invalid_quality_rejected_at_quality_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _metric(quality="probably_fine")
        assert excinfo.value.errors()[0]["loc"] == ("quality",)

    def test_invalid_source_rejected_at_source_field(self):
        with pytest.raises(ValidationError) as excinfo:
            _metric(source="guesswork")
        assert excinfo.value.errors()[0]["loc"] == ("source",)

    def test_object_value_rejected_value_is_scalar_only(self):
        # Union member failures report the attempted member as a nested loc
        # (e.g. ('value', 'int')); the seam contract is that the error sits on
        # the value field.
        with pytest.raises(ValidationError) as excinfo:
            _metric(value={"nested": 1})
        assert all(error["loc"][:1] == ("value",) for error in excinfo.value.errors())

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            Metric(
                metric_id="metric-001",
                run_id="3b241101-e2bb-4255-8caf-4136c566a962",
                name="cc_error_rate",
                value=1,
                source="internal_parser",
                quality="valid",
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("observed_at_utc_ms",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _metric(aggregate="mean")
        assert excinfo.value.errors()[0]["loc"] == ("aggregate",)

    def test_frozen_model_rejects_assignment(self):
        metric = _metric()
        with pytest.raises(ValidationError):
            metric.quality = MetricQuality.INVALID
