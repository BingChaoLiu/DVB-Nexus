"""SPEC-301 contract fixtures and schema document correspondence.

Integration layer (SPEC-505 section 3): these tests load the approved spec
artifacts — the contract fixture under the Observation-Metrics module
``examples/`` and ``schemas/event-envelope.schema.json`` — read-only, and
assert the implementation matches them exactly (REQ-OBS-301-001: schema and
field contract correspond one-to-one; REQ-OBS-301-004: multi-document
compatibility policy).

jsonschema is not a runtime dependency, so correspondence is asserted by a
structural comparison against the schema document — sufficient for the
"one schema document implements 1.0, envelope loose / payload tight"
contract and kept deliberately dependency-free.
"""

import json

from domain.observation.envelope import (
    PAYLOAD_MAX_BYTES,
    Correlation,
    EventEnvelope,
    Producer,
    Scope,
    Severity,
    Time,
    Timepoint,
    parse_envelope,
)
from domain.observation.model import ConfidenceKind, ObservationSource
from domain.observation.registry import REGISTERED_EVENT_TYPES
from tests._support.paths import repo_root

OBSERVATION_MODULE_DIR = (
    repo_root()
    / "docs"
    / "spec"
    / "DVB-Sandbox-Spec-v0.4-Complete"
    / "docs"
    / "modules"
    / "Observation-Metrics"
)
SCHEMA_PATH = OBSERVATION_MODULE_DIR / "schemas" / "event-envelope.schema.json"
FIXTURE_PATH = OBSERVATION_MODULE_DIR / "examples" / "event-ts-continuity-error.json"


def _load_json(path):
    # Repo text is UTF-8 (tests/_support/paths.py rules): explicit encoding.
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def load_schema():
    return _load_json(SCHEMA_PATH)


class TestContractFixture:
    """The approved example must pass the implementation's envelope parse."""

    def test_ts_continuity_error_fixture_parses(self):
        raw = _load_json(FIXTURE_PATH)
        envelope = parse_envelope(raw)
        assert envelope.event_type == "ts.continuity_error"
        assert envelope.schema_version == "1.0"
        assert envelope.scope.tenant_id == "local"
        assert envelope.scope.run_id is not None  # run-attributed (ADR-0006)
        assert envelope.correlation.node_id == "mux-0"
        assert envelope.producer.producer_id == "ts-core"

    def test_fixture_payload_carries_observation_axes(self):
        # #13 Q3-i: observation-flavoured payloads carry source/confidence.
        raw = _load_json(FIXTURE_PATH)
        envelope = parse_envelope(raw)
        assert envelope.payload["source"] == ObservationSource.INTERNAL_PARSER.value
        assert envelope.payload["confidence"] == ConfidenceKind.PARSED.value

    def test_fixture_is_a_producer_publish_view(self):
        # Producers never fill journal_seq (ADR-0006 decision 2) — the
        # fixture is the publish view.
        raw = _load_json(FIXTURE_PATH)
        assert "journal_seq" not in raw
        envelope = parse_envelope(raw)
        envelope.ensure_publishable()  # must not raise

    def test_fixture_timepoints_match_dual_clock_model(self):
        raw = _load_json(FIXTURE_PATH)
        envelope = parse_envelope(raw)
        assert envelope.time.source.clock_domain.startswith("sim:")
        assert envelope.time.observed.clock_domain == "wall:utc"


class TestSchemaDocumentCorrespondence:
    """REQ-OBS-301-001: schema document <-> implementation, field by field."""

    def test_required_list_matches_model(self):
        schema = load_schema()
        assert set(schema["required"]) == {
            "schema_version",
            "event_id",
            "event_type",
            "producer",
            "scope",
            "time",
            "severity",
            "payload",
            "tags",
        }

    def test_envelope_layers_are_loose(self):
        # ADR-0006 decision 4: additionalProperties true at top level and in
        # producer/scope/time/correlation/timepoint — payload excepted.
        schema = load_schema()
        assert schema["additionalProperties"] is True
        assert schema["properties"]["producer"]["additionalProperties"] is True
        assert schema["properties"]["scope"]["additionalProperties"] is True
        assert schema["properties"]["time"]["additionalProperties"] is True
        assert schema["properties"]["correlation"]["additionalProperties"] is True
        timepoint = schema["$defs"]["timepoint"]
        assert timepoint["additionalProperties"] is True
        # Payload stays an object; per-type payload schemas keep it tight.
        assert schema["properties"]["payload"]["type"] == "object"

    def test_const_1_0_and_multi_document_policy_comment(self):
        # SPEC-301 section 8: const "1.0" stays in THIS document; a 1.1 is a
        # new document with a new $id (additive optional only).
        schema = load_schema()
        assert schema["properties"]["schema_version"]["const"] == "1.0"
        assert schema["$id"].endswith("event-envelope-1.0.schema.json")
        assert "1.0" in schema["$comment"]

    def test_severity_enum_matches_model(self):
        schema = load_schema()
        assert set(schema["properties"]["severity"]["enum"]) == {
            item.value for item in Severity
        }

    def test_bounds_match_model(self):
        schema = load_schema()
        props = schema["properties"]
        assert props["event_id"]["minLength"] == 8
        assert props["event_id"]["maxLength"] == 128
        assert props["tags"]["maxItems"] == 32
        assert props["tags"]["items"]["maxLength"] == 64
        assert props["correlation"]["properties"]["pid"]["maximum"] == 8191
        assert props["journal_seq"]["minimum"] == 0

    def test_journal_seq_is_optional_and_documented_as_gateway_stamped(self):
        schema = load_schema()
        assert "journal_seq" not in schema["required"]
        comment = schema["properties"]["journal_seq"]["$comment"]
        assert "生产者永不填" in comment

    def test_scope_run_id_and_correlation_port_id_present(self):
        # ADR-0006 decision 1/3 grafts: scope.run_id + correlation.port_id.
        schema = load_schema()
        scope_props = schema["properties"]["scope"]["properties"]
        assert scope_props["run_id"]["type"] == ["string", "null"]
        correlation_props = schema["properties"]["correlation"]["properties"]
        assert correlation_props["port_id"]["type"] == ["string", "null"]

    def test_timepoint_triple_without_semantics(self):
        # SPEC-301 section 6: the envelope timepoint has exactly
        # value_ns + clock_domain + clock_epoch — no semantics field.
        schema = load_schema()
        timepoint = schema["$defs"]["timepoint"]
        assert set(timepoint["required"]) == {"value_ns", "clock_domain", "clock_epoch"}
        assert "semantics" not in timepoint["properties"]

    def test_payload_cap_matches_spec(self):
        # SPEC-301 section 7: 256 KiB default cap.
        assert PAYLOAD_MAX_BYTES == 256 * 1024


class TestRegistryAgainstSchema:
    """REQ-OBS-301-006: registry is the unique legal event_type list."""

    def test_every_registered_type_matches_schema_pattern(self):
        import re

        schema = load_schema()
        pattern = re.compile(schema["properties"]["event_type"]["pattern"])
        for event_type in REGISTERED_EVENT_TYPES:
            assert pattern.match(event_type), event_type

    def test_model_typed_surface_aligns_with_schema_structures(self):
        # The typed model's nested structures mirror the schema objects.
        schema = load_schema()
        producer_required = set(schema["properties"]["producer"]["required"])
        assert producer_required == {"producer_id", "producer_version", "instance_id"}
        assert set(schema["properties"]["time"]["required"]) == {"source", "observed"}
        assert Producer.model_fields.keys() >= producer_required
        assert set(Time.model_fields) == {"source", "observed"}
        assert set(Timepoint.model_fields) == {"value_ns", "clock_domain", "clock_epoch"}
        assert set(Correlation.model_fields) == set(
            schema["properties"]["correlation"]["properties"]
        )
        assert set(Scope.model_fields) == set(schema["properties"]["scope"]["properties"])
