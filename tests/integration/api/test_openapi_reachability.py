"""OpenAPI reachability gate (SPEC-500 §4 amendment acceptance, ticket
#80): paths 30→32+ and the #61 codegen plane fully typed.

Two acceptance clauses live here, both against the PRODUCTION
composition's generated schema:

1. **Paths**: the brief-baseline 30 (6e69471 OpenAPI dump) + the two
   approved additive rows (§4.7 solution reveal, §4.8 TSDuck call
   records) ⇒ ≥ 32 paths, each new row present under the frozen prefix.
2. **Models**: the 17 previously-unreachable DTOs (brief §3.3 — the #61
   codegen ruling input) are now reachable. 16 carry their literal names
   in ``components.schemas``; the 17th (the ``ObservationResponseDTO``
   base) is reachable as the per-route typed envelopes — every
   observation 200 schema carries the request_id/scope/data/meta envelope
   keys with a TYPED data body (orchestrator OQ-2: 16 literal + shape
   reachability; the base-with-``data: Any`` schema would defeat the
   codegen purpose).
"""

from __future__ import annotations

import pytest

from api.versioning import API_V1_PREFIX
from bootstrap import build_production_app

pytestmark = pytest.mark.integration

#: The brief §3.3 unreachable-models inventory, minus the base envelope
#: (OQ-2: reachable as the typed per-route envelopes below).
LITERAL_MODEL_NAMES = {
    "ErrorDetail",
    "ErrorResponse",
    "ObservationScopeDTO",
    "ObservationMetaDTO",
    "SummaryDataDTO",
    "EventsDataDTO",
    "TimelineLaneDTO",
    "TimelineDataDTO",
    "MetricPointDTO",
    "MetricSeriesDTO",
    "MetricsDataDTO",
    "AlertRecordDTO",
    "AlertsDataDTO",
    "HealthDimensionDTO",
    "HealthDataDTO",
    "ExportDataDTO",
}

#: The ticket #80 route-level DTOs (the approved §4.7/§4.8 wire shapes).
NEW_ROUTE_MODEL_NAMES = {
    "TopologyDTO",
    "TopologySummaryDTO",
    "TopologyValidationDTO",
    "TopologyCreateRequest",
    "ScenarioSummaryDTO",
    "ScenarioDetailDTO",
    "ScenarioSolutionDTO",
    "TSDuckCallDTO",
}

OBSERVATION_ENVELOPE_KEYS = {"request_id", "scope", "data", "meta"}

OBSERVATION_PATHS = (
    ("/api/v1/sessions/{session_id}/observation/summary", "get", "SummaryDataDTO"),
    ("/api/v1/sessions/{session_id}/events", "get", "EventsDataDTO"),
    ("/api/v1/sessions/{session_id}/timeline", "get", "TimelineDataDTO"),
    ("/api/v1/sessions/{session_id}/metrics/query", "post", "MetricsDataDTO"),
    ("/api/v1/sessions/{session_id}/alerts", "get", "AlertsDataDTO"),
    ("/api/v1/sessions/{session_id}/health", "get", "HealthDataDTO"),
    ("/api/v1/sessions/{session_id}/exports/{export_id}", "get", "ExportDataDTO"),
    ("/api/v1/sessions/{session_id}/exports", "post", "ExportDataDTO"),
)

NEW_PATHS = (
    "/api/v1/scenarios/{scenario_id}/solution",
    "/api/v1/sessions/{session_id}/tsduck/calls",
)


@pytest.fixture(scope="module")
def schema():
    # Module-scoped tmp db: one composition for the whole module.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        stack = build_production_app(db_path=Path(tmp) / "openapi.sqlite3")
        try:
            yield stack.app.openapi()
        finally:
            stack.close()


class TestPathInventory:
    def test_paths_grew_to_at_least_32(self, schema):
        api_paths = [p for p in schema["paths"] if p.startswith(API_V1_PREFIX)]
        assert len(api_paths) >= 32, sorted(api_paths)

    def test_the_two_additive_rows_are_mounted_under_the_frozen_prefix(
        self, schema
    ):
        for path in NEW_PATHS:
            assert path in schema["paths"], path
            assert path.startswith(API_V1_PREFIX)

    def test_solution_reveal_documents_the_error_models(self, schema):
        operation = schema["paths"]["/api/v1/scenarios/{scenario_id}/solution"]["get"]
        documented = set(operation.get("responses", {}))
        assert {"400", "404", "403"} <= documented


class TestModelReachability:
    def test_the_16_literal_names_are_components(self, schema):
        components = set(schema.get("components", {}).get("schemas", {}))
        missing = LITERAL_MODEL_NAMES - components
        assert not missing, f"unreachable models: {sorted(missing)}"

    def test_the_new_route_dtos_are_components(self, schema):
        components = set(schema.get("components", {}).get("schemas", {}))
        missing = NEW_ROUTE_MODEL_NAMES - components
        assert not missing, f"unreachable new-route models: {sorted(missing)}"

    def test_every_observation_200_is_the_typed_envelope(self, schema):
        """OQ-2: the base envelope shape is reachable on all eight §4.5
        routes — request_id/scope/data/meta with a $ref'd typed data body
        (never ``data: Any``)."""
        components = schema["components"]["schemas"]
        for path, method, data_model in OBSERVATION_PATHS:
            response = schema["paths"][path][method]["responses"]["200"]
            ref = response["content"]["application/json"]["schema"]["$ref"]
            name = ref.rsplit("/", 1)[-1]
            properties = components[name]["properties"]
            assert OBSERVATION_ENVELOPE_KEYS <= set(properties), path
            data_ref = properties["data"]["$ref"]
            assert data_ref.rsplit("/", 1)[-1] == data_model, path

    def test_error_envelope_is_documented_on_the_new_routes(self, schema):
        calls = schema["paths"]["/api/v1/sessions/{session_id}/tsduck/calls"]["get"]
        documented = set(calls.get("responses", {}))
        assert {"404", "503"} <= documented
