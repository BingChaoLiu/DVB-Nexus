"""Repository-authoritative alert-record schema (ticket #52, SPEC-304 §14).

G2 (brief §8): the read-only spec-package draft
``schemas/alert-record.schema.json`` puts ``suppressed`` inside the state
enum and lacks ``inactive`` (SPEC-304 §5 lifecycle + #12 ruling both have
``inactive``; suppression is a modifier, not a state). The draft is not
edited in place (docs/spec README rule 2); the implementation schema at
``docs/schemas/alert-record.schema.json`` is authoritative and this test
pins it against the domain model:

- the state enum is exactly the five lifecycle values (inactive present,
  suppressed absent — #12 裁决出处 lives in the schema ``$comment`` and the
  ticket #52 report);
- ``time`` requires ``value_ns``/``clock_domain``/``clock_epoch``/
  ``semantics`` (SPEC-300 §6 record-level timepoint discipline; the #12
  ruling extends it to record schemas);
- a dumped :class:`domain.observation.AlertRecord` satisfies the schema's
  structural constraints, and the shipped SPEC example still validates;
- the declared divergence against the draft is REAL (draft state enum lacks
  ``inactive``, contains ``suppressed``) — the divergence cannot silently
  drift.

Unit layer with one deliberate, waived read: the schema document IS the
implementation artifact under test — reading it is the subject of the test.
"""

import json

from domain.observation import (
    AlertRecord,
    AlertScope,
    AlertSeverity,
    AlertState,
    MetricSampleTimepoint,
    SampleSemantics,
)
from tests._support.paths import repo_root

SCHEMA_RELPATH = ("docs", "schemas", "alert-record.schema.json")
DRAFT_RELPATH = (
    "docs",
    "spec",
    "DVB-Sandbox-Spec-v0.4-Complete",
    "schemas",
    "alert-record.schema.json",
)
EXAMPLE_RELPATH = (
    "docs",
    "spec",
    "DVB-Sandbox-Spec-v0.4-Complete",
    "docs",
    "modules",
    "Observation-Metrics",
    "examples",
    "alert-pcr-jitter-example.json",
)


def _schema() -> dict:
    path = repo_root().joinpath(*SCHEMA_RELPATH)
    return json.loads(path.read_text(encoding="utf-8"))  # io-ok: the in-repo authoritative schema document is the artifact under test (SPEC-304 §14 / G2)


def _draft() -> dict:
    path = repo_root().joinpath(*DRAFT_RELPATH)
    return json.loads(path.read_text(encoding="utf-8"))  # io-ok: read-only divergence pin (docs/spec README rule 2 — the draft is never edited)


def _example() -> dict:
    path = repo_root().joinpath(*EXAMPLE_RELPATH)
    return json.loads(path.read_text(encoding="utf-8"))  # io-ok: the shipped SPEC example is the conformance vector (SPEC-304 §14)


def _record() -> AlertRecord:
    return AlertRecord(
        alert_id="alert-0001",
        fingerprint="sha256:demo-fingerprint",
        rule_id="PCR_JITTER_HIGH",
        rule_version="1.0",
        state=AlertState.FIRING,
        severity=AlertSeverity.WARNING,
        scope=AlertScope(tenant_id="local", session_id="sess-1"),
        time=MetricSampleTimepoint(
            value_ns=8_000_000_000,
            clock_domain="sim:sess-1",
            clock_epoch=0,
            semantics=SampleSemantics.DERIVED,
        ),
        summary="PCR jitter p95 exceeded the configured threshold",
        evidence_refs=("journal:1002",),
        suppression=None,
    )


class TestStateEnum:
    """G2 / REQ-OBS-304-002: lifecycle values, suppression as modifier."""

    def test_state_enum_is_exactly_the_five_lifecycle_values(self) -> None:
        assert _schema()["properties"]["state"]["enum"] == [
            "inactive",
            "pending",
            "firing",
            "resolving",
            "resolved",
        ]

    def test_declared_draft_divergence_is_real(self) -> None:
        draft_states = _draft()["properties"]["state"]["enum"]
        assert "inactive" not in draft_states  # the G2 defect the #12 ruling fixes
        assert "suppressed" in draft_states  # the modifier the draft misplaces


class TestTimepointDiscipline:
    """#12 / SPEC-300 §6: record-level timepoints carry epoch + semantics."""

    def test_time_requires_all_four_fields(self) -> None:
        time_schema = _schema()["properties"]["time"]
        for field in ("value_ns", "clock_domain", "clock_epoch", "semantics"):
            assert field in time_schema["required"], field


class TestRecordConformance:
    """A dumped domain record satisfies the schema's structural constraints."""

    def test_dumped_record_matches_schema_shape(self) -> None:
        schema = _schema()
        dump = _record().model_dump(mode="json")
        assert set(dump) <= set(schema["properties"])
        for field in schema["required"]:
            assert field in dump, field
        assert dump["state"] in schema["properties"]["state"]["enum"]
        assert dump["severity"] in schema["properties"]["severity"]["enum"]
        assert set(dump["scope"]) >= set(schema["properties"]["scope"]["required"])
        assert isinstance(dump["evidence_refs"], list)

    def test_suppression_property_allows_null_and_object(self) -> None:
        suppression_schema = _schema()["properties"]["suppression"]
        assert "null" in suppression_schema["type"]
        assert "reason" in suppression_schema.get("properties", {})

    def test_shipped_example_satisfies_the_schema(self) -> None:
        schema = _schema()
        document = _example()
        assert set(document) <= set(schema["properties"])
        for field in schema["required"]:
            assert field in document, field
        assert document["state"] in schema["properties"]["state"]["enum"]
        # The example's time block already carries the #12 fields.
        assert set(document["time"]) >= set(
            schema["properties"]["time"]["required"]
        )
