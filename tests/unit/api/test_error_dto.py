"""Error envelope DTO unit contract (SPEC-305 §7 shape via SPEC-500 §3, ticket #24).

SPEC-500 §3: "错误信封沿用 SPEC-305 §7 形状,推广为全平台统一". SPEC-305 §7
freezes the shape:

    {
      "error": {
        "error_code": "OBS_QUERY_RANGE_TOO_LARGE",
        "message": "Requested range exceeds configured maximum",
        "retryable": false,
        "details": {"max_range_ns": 3600000000000}
      },
      "request_id": "req-001"
    }

These Pydantic DTOs in ``api.dto`` are the assembly-point pattern for all
future SPEC-500 DTOs (snake_case JSON, model authority).
"""

from __future__ import annotations

import json

from api.dto import ErrorDetail, ErrorResponse


class TestEnvelopeShape:
    def test_top_level_keys_are_exactly_error_and_request_id(self):
        response = ErrorResponse(
            error=ErrorDetail(error_code="X", message="m"), request_id="req-001"
        )
        assert set(response.model_dump(mode="json").keys()) == {"error", "request_id"}

    def test_error_keys_are_exactly_the_four_spec_fields(self):
        detail = ErrorDetail(error_code="X", message="m")
        assert set(detail.model_dump(mode="json").keys()) == {
            "error_code",
            "message",
            "retryable",
            "details",
        }

    def test_retryable_defaults_false(self):
        assert ErrorDetail(error_code="X", message="m").retryable is False

    def test_details_defaults_to_empty_dict(self):
        assert ErrorDetail(error_code="X", message="m").details == {}


class TestEnvelopeJsonRoundTrip:
    def test_roundtrip_is_lossless(self):
        payload = {
            "error": {
                "error_code": "OBS_QUERY_RANGE_TOO_LARGE",
                "message": "Requested range exceeds configured maximum",
                "retryable": False,
                "details": {"max_range_ns": 3600000000000},
            },
            "request_id": "req-001",
        }
        instance = ErrorResponse.model_validate(payload)
        through_json = json.loads(json.dumps(instance.model_dump(mode="json")))
        reloaded = ErrorResponse.model_validate(through_json)
        assert reloaded == instance

    def test_snake_case_field_names_survive_json_boundary(self):
        detail = ErrorDetail(
            error_code="SIM_FAULT_REJECTED", message="m", details={"schema_path": "$.a[0]"}
        )
        dumped = json.dumps(detail.model_dump(mode="json"))
        assert '"error_code"' in dumped
        assert '"schema_path"' in dumped
