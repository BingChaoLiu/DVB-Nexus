"""Alert record vocabulary (SPEC-304, ticket #52) — domain model tests.

REQ-OBS-304-002: the alert lifecycle is the five-value state enum
``inactive|pending|firing|resolving|resolved`` (SPEC-304 §5). ``suppressed``
is NOT a lifecycle state — it is a modifier carried by the ``suppression``
metadata object on the record (SPEC-304 §5; brief §8 G2 ruling D: the
read-only spec-package draft schema puts ``suppressed`` in the state enum and
lacks ``inactive``; the repository schema at ``docs/schemas/`` is
authoritative and the draft is not edited in place).

The health status vocabulary of this ticket is the SPEC-304 §3 four-value
``unknown|healthy|degraded|critical`` — a DIFFERENT axis from the SPEC-003
§3 node-health word list (``HealthState`` ok/warn/error/unknown); the test
pins the disjointness so the two enumerations can never be cross-wired.

REQ-OBS-304-002 persistence shape: every record carries a timepoint with an
explicit clock domain/epoch/semantics (SPEC-300 §6 record-level discipline),
the rule version and evidence references.

The spec-package example ``alert-pcr-jitter-example.json`` is loaded as a
conformance vector: a shipped SPEC example must construct into the domain
model unchanged.
"""

import json

import pytest
from pydantic import ValidationError

from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    AlertSuppression,
    HealthDimension,
    HealthState,
    HealthStatus,
    MetricSampleTimepoint,
    SampleSemantics,
)
from tests._support.paths import repo_root

_EXAMPLE_RELPATH = (
    "docs",
    "spec",
    "DVB-Sandbox-Spec-v0.4-Complete",
    "docs",
    "modules",
    "Observation-Metrics",
    "examples",
    "alert-pcr-jitter-example.json",
)


def _timepoint(value_ns: int = 8_000_000_000) -> MetricSampleTimepoint:
    return MetricSampleTimepoint(
        value_ns=value_ns,
        clock_domain="sim:sess-1",
        clock_epoch=0,
        semantics=SampleSemantics.DERIVED,
    )


def _record(**overrides) -> AlertRecord:
    fields = {
        "alert_id": "alert-0001",
        "fingerprint": "sha256:demo-fingerprint",
        "rule_id": "PCR_JITTER_HIGH",
        "rule_version": "1.0",
        "state": AlertState.FIRING,
        "severity": AlertSeverity.WARNING,
        "scope": AlertScope(tenant_id="local", session_id="sess-1"),
        "time": _timepoint(),
        "summary": "PCR jitter p95 exceeded the configured threshold",
        "evidence_refs": (
            "journal:1002",
            "metric:ts.pcr_jitter_ns:bucket-8000000000",
        ),
        "suppression": None,
    }
    fields.update(overrides)
    return AlertRecord(**fields)


class TestAlertStateVocabulary:
    """REQ-OBS-304-002 (SPEC-304 §5): lifecycle states, suppression not one."""

    def test_state_enum_is_exactly_the_five_lifecycle_values(self) -> None:
        assert {state.value for state in AlertState} == {
            "inactive",
            "pending",
            "firing",
            "resolving",
            "resolved",
        }

    def test_suppressed_is_not_a_state(self) -> None:
        with pytest.raises(ValueError):
            AlertState("suppressed")

    def test_severity_enum_is_the_four_record_values(self) -> None:
        assert {severity.value for severity in AlertSeverity} == {
            "info",
            "warning",
            "error",
            "critical",
        }

    def test_health_dimensions_are_the_six_spec_dimensions(self) -> None:
        assert {dimension.value for dimension in HealthDimension} == {
            "transport",
            "timing",
            "service",
            "topology",
            "simulation",
            "observation",
        }

    def test_health_status_is_the_spec304_four_value_enum(self) -> None:
        # SPEC-304 §3 roll-up vocabulary — NOT the SPEC-003 §3 HealthState.
        assert {status.value for status in HealthStatus} == {
            "unknown",
            "healthy",
            "degraded",
            "critical",
        }

    def test_health_status_and_health_state_are_distinct_axes(self) -> None:
        # 双轨警示 (brief §5.3): the SPEC-304 roll-up vocabulary and the
        # SPEC-003 §3 node-health word list coincide only on "unknown" —
        # healthy/degraded/critical do NOT exist on HealthState, so the
        # roll-up can never be expressed with (nor accidentally mapped onto)
        # the node-health enum.
        assert {
            s.value for s in HealthStatus
        } - {s.value for s in HealthState} == {"healthy", "degraded", "critical"}


class TestAlertRecordShape:
    """REQ-OBS-304-002/006: record shape — timepoint, rule version, evidence."""

    def test_record_round_trip_is_stable(self) -> None:
        record = _record()
        dump = record.model_dump(mode="json")
        assert AlertRecord.model_validate(dump) == record

    def test_timepoint_requires_explicit_clock_semantics(self) -> None:
        with pytest.raises(ValidationError):
            _record(time={"value_ns": 1, "clock_domain": "sim:sess-1"})

    def test_scope_requires_tenant_and_session(self) -> None:
        with pytest.raises(ValidationError):
            AlertScope(tenant_id="local")

    def test_summary_capped_at_schema_length(self) -> None:
        with pytest.raises(ValidationError):
            _record(summary="x" * 513)

    def test_evidence_refs_capped_for_storm_bound(self) -> None:
        with pytest.raises(ValidationError):
            _record(evidence_refs=tuple(f"journal:{i}" for i in range(65)))

    def test_empty_evidence_refs_are_legal_for_non_firing_states(self) -> None:
        record = _record(state=AlertState.INACTIVE, evidence_refs=())
        assert record.evidence_refs == ()


class TestSuppressionIsAModifier:
    """SPEC-304 §5: suppression never migrates the lifecycle state."""

    def test_suppression_keeps_the_lifecycle_state_visible(self) -> None:
        record = _record()
        suppressed = record.with_suppression(
            AlertSuppression(reason="maintenance window", suppressed_by="operator")
        )
        assert suppressed.is_suppressed
        assert suppressed.state is AlertState.FIRING  # unchanged
        assert suppressed.suppression.reason == "maintenance window"
        # The original is untouched (frozen value object).
        assert not record.is_suppressed

    def test_unsuppress_restores_the_prior_lifecycle_state(self) -> None:
        record = _record(state=AlertState.PENDING)
        suppressed = record.with_suppression(AlertSuppression(reason="quiet"))
        restored = suppressed.with_suppression(None)
        assert not restored.is_suppressed
        assert restored.suppression is None
        assert restored.state is AlertState.PENDING  # the prior state


class TestSpecExampleConformance:
    """The shipped SPEC-304 example must construct into the domain model."""

    def test_alert_pcr_jitter_example_builds_an_alert_record(self) -> None:
        path = repo_root().joinpath(*_EXAMPLE_RELPATH)
        document = json.loads(path.read_text(encoding="utf-8"))  # io-ok: the SPEC package example is the conformance vector under test (SPEC-304 §14)
        record = AlertRecord.model_validate(document)
        assert record.rule_id == "PCR_JITTER_HIGH"
        assert record.state is AlertState.FIRING
        assert record.scope.tenant_id == "local"
        assert record.time.semantics is SampleSemantics.DERIVED
        assert "journal:1002" in record.evidence_refs
        assert not record.is_suppressed
