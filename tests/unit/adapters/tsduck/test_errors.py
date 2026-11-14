"""Error-code family and HTTP-mapping tests (SPEC-308 §9, REQ-TSK-308-006).

Every adapter error carries its SPEC-308 §9 error code and the §9-table HTTP
mapping as data. Rendering HTTP responses is the API layer's job (SPEC-500
§6, M3 wiring); the adapter only guarantees the code and the mapped status
travel together, so the §9 table can be locked here line by line.
"""

from __future__ import annotations

import pytest

from adapters.tsduck.errors import (
    TSDuckAdapterError,
    TSDuckCancelledError,
    TSDuckJsonGateError,
    TSDuckNotFoundError,
    TSDuckNotEnabledError,
    TSDuckPluginNotAllowedError,
    TSDuckSpawnFailedError,
    TSDuckTimeoutError,
    TSDuckVersionUnsupportedError,
)

#: SPEC-308 §9 table, transcribed line by line (code, HTTP status).
SPEC_308_SECTION_9_TABLE = [
    (TSDuckNotFoundError, "TSDUCK_NOT_FOUND", 503),
    (TSDuckVersionUnsupportedError, "TSDUCK_VERSION_UNSUPPORTED", 503),
    (TSDuckSpawnFailedError, "TSDUCK_SPAWN_FAILED", 500),
    (TSDuckTimeoutError, "TSDUCK_TIMEOUT", 500),
    (TSDuckCancelledError, "TSDUCK_CANCELLED", 409),
    (TSDuckJsonGateError, "TSDUCK_JSON_GATE_FAILED", 500),
    (TSDuckPluginNotAllowedError, "TSDUCK_PLUGIN_NOT_ALLOWED", 422),
]


class TestSection9Table:
    @pytest.mark.parametrize(("error_class", "code", "http_status"), SPEC_308_SECTION_9_TABLE)
    def test_error_code_and_http_mapping_match_section_9(
        self, error_class, code, http_status
    ):
        assert error_class.code == code
        assert error_class.http_status == http_status

    def test_every_family_member_is_a_tsduck_adapter_error(self):
        for error_class, _, _ in SPEC_308_SECTION_9_TABLE:
            assert issubclass(error_class, TSDuckAdapterError)

    def test_section_9_table_is_exhaustively_covered(self):
        """The seven §9 rows are the whole mapped family (no silent additions)."""
        mapped = {error_class.code for error_class, _, _ in SPEC_308_SECTION_9_TABLE}
        assert mapped == {
            "TSDUCK_NOT_FOUND",
            "TSDUCK_VERSION_UNSUPPORTED",
            "TSDUCK_SPAWN_FAILED",
            "TSDUCK_TIMEOUT",
            "TSDUCK_CANCELLED",
            "TSDUCK_JSON_GATE_FAILED",
            "TSDUCK_PLUGIN_NOT_ALLOWED",
        }


class TestReservedOperationError:
    def test_reserved_operations_reject_with_explicit_code(self):
        """inject/generate MVP refusal (SPEC-308 §4: 显式拒绝防静默半实现).

        Interpretation (recorded in the report): the §9 table has no row for
        the reserved-operation refusal; the adapter carries an explicit
        ``TSDUCK_NOT_ENABLED`` code and defers the HTTP status to the API
        layer (http_status=None, not a fabricated mapping).
        """
        assert TSDuckNotEnabledError.code == "TSDUCK_NOT_ENABLED"
        assert TSDuckNotEnabledError.http_status is None
        assert issubclass(TSDuckNotEnabledError, TSDuckAdapterError)

    def test_errors_carry_message_and_catchable_as_base(self):
        error = TSDuckTimeoutError("killed after 120s")
        assert str(error) == "killed after 120s"
        try:
            raise TSDuckJsonGateError("gate failed")
        except TSDuckAdapterError as caught:
            assert caught.code == "TSDUCK_JSON_GATE_FAILED"
