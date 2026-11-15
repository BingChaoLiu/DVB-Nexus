"""Repository-authoritative metric-sample schema (ticket #50, SPEC-302 §14).

G1 (brief section 8): the read-only spec-package draft
``schemas/metric-sample.schema.json`` lacks four fields the approved #12
ruling and SPEC-300 §6 / SPEC-302 §6.2 mandate — ``time.clock_epoch``,
``time.semantics``, top-level ``revision`` and top-level ``is_final``. The
draft is not edited in place (docs/spec README rule 2); the implementation
schema at ``docs/schemas/metric-sample.schema.json`` is authoritative and
this test pins it against the domain model:

- the four G1 fields exist in the required sets (the #12 裁决出处 lives in
  the schema's ``$comment`` and the ticket #50 report);
- the quality enum is exactly the seven SPEC-302 derived-series values;
- a dumped :class:`domain.observation.MetricSample` satisfies the schema's
  structural constraints, and a sample stripped of ``revision``/``is_final``
  is rejected (the fields are structural, not decorative).

Unit layer with one deliberate, waived read: the schema document IS the
implementation artifact under test — reading it is the subject of the test.
"""

import json
import re
from pathlib import Path

import pytest

from domain.observation import (
    MetricProvenance,
    MetricSample,
    MetricSampleTimepoint,
)

from tests._support.paths import repo_root

SCHEMA_RELPATH = ("docs", "schemas", "metric-sample.schema.json")


def _schema() -> dict:
    path = repo_root().joinpath(*SCHEMA_RELPATH)
    return json.loads(path.read_text(encoding="utf-8"))  # io-ok: the in-repo authoritative schema document is the artifact under test (SPEC-302 §14 / G1)


def _sample_dump() -> dict:
    sample = MetricSample(
        metric_name="ts.continuity_error_total",
        time=MetricSampleTimepoint(
            value_ns=1_000,
            clock_domain="sim:sess-1",
            clock_epoch=0,
            semantics="derived",
        ),
        value=3,
        dimensions={"session_id": "sess-1"},
        quality=("good",),
        provenance=MetricProvenance(
            source_event_ids=("evt-1",), journal_watermark=7
        ),
        revision=1,
        is_final=False,
    )
    return sample.model_dump(mode="json")


# --- G1: the four #12-mandated fields are structural ----------------------------


def test_schema_requires_time_clock_epoch_and_semantics() -> None:
    time_block = _schema()["properties"]["time"]
    assert "clock_epoch" in time_block["required"]
    assert "semantics" in time_block["required"]
    assert time_block["properties"]["clock_epoch"]["minimum"] == 0
    assert time_block["properties"]["semantics"]["enum"] == [
        "source",
        "observed",
        "derived",
    ]


def test_schema_requires_revision_and_is_final() -> None:
    schema = _schema()
    assert "revision" in schema["required"]
    assert "is_final" in schema["required"]
    assert schema["properties"]["revision"]["minimum"] == 1
    assert schema["properties"]["is_final"]["type"] == "boolean"


def test_schema_records_the_12_ruling_provenance() -> None:
    comment = _schema()["$comment"]
    assert "#12" in comment
    assert "revision" in comment and "is_final" in comment
    assert "SPEC-302" in comment


def test_quality_enum_is_the_seven_derived_series_values() -> None:
    quality = _schema()["properties"]["quality"]["items"]["enum"]
    assert quality == [
        "good",
        "missing",
        "late",
        "estimated",
        "partial",
        "revised",
        "invalid",
    ]


def test_schema_keeps_the_draft_base_shape() -> None:
    # The draft's base required set stays pinned, with one declared
    # divergence: value_type moves out of required — SPEC-302 §3 lists the
    # sample fields and value_type belongs to the metric DEFINITION (the
    # §8 response series metadata carries it instead).
    schema = _schema()
    for field in (
        "metric_name",
        "value",
        "time",
        "dimensions",
        "quality",
        "provenance",
    ):
        assert field in schema["required"]
    assert "value_type" not in schema["required"]
    assert "value_type" in schema["properties"]  # still a legal property
    pattern = schema["properties"]["metric_name"]["pattern"]
    assert re.match(pattern, "ts.continuity_error_total")
    assert not re.match(pattern, "NotDotted")
    provenance = schema["properties"]["provenance"]
    assert provenance["required"] == ["source_event_ids"]


# --- model ⇄ schema round-trip (structural validator over the subset) -----------


def _validate_subset(document: dict, schema: dict) -> list[str]:
    """Minimal structural check of the schema constraints we implement."""
    errors: list[str] = []
    for field in schema["required"]:
        if field not in document:
            errors.append(f"missing required field {field!r}")
    properties = schema["properties"]
    if "metric_name" in document and not re.match(
        properties["metric_name"]["pattern"], document["metric_name"]
    ):
        errors.append("metric_name pattern mismatch")
    if "value_type" in document and document["value_type"] not in properties[
        "value_type"
    ]["enum"]:
        errors.append("value_type not in enum")
    time_block = document.get("time") or {}
    for field in properties["time"]["required"]:
        if field not in time_block:
            errors.append(f"time.{field} missing")
    if "semantics" in time_block and time_block["semantics"] not in properties[
        "time"
    ]["properties"]["semantics"]["enum"]:
        errors.append("time.semantics not in enum")
    revision = document.get("revision")
    if not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer >= 1")
    if not isinstance(document.get("is_final"), bool):
        errors.append("is_final must be a boolean")
    for flag in document.get("quality", []):
        if flag not in properties["quality"]["items"]["enum"]:
            errors.append(f"quality flag {flag!r} not in enum")
    return errors


def test_a_dumped_metric_sample_satisfies_the_schema() -> None:
    errors = _validate_subset(_sample_dump(), _schema())
    assert errors == []


@pytest.mark.parametrize("stripped", ["revision", "is_final"])
def test_a_sample_without_the_12_fields_fails_the_schema(stripped: str) -> None:
    dump = _sample_dump()
    del dump[stripped]
    errors = _validate_subset(dump, _schema())
    assert any(stripped in error for error in errors)
