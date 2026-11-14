"""Error mapping table unit contract (SPEC-500 §6, ticket #24).

Pure unit layer: the declarative exception→HTTP mapping table and the
application-level exception taxonomy it keys on. SPEC-500 §6 freezes the
HTTP mapping for the whole platform:

| 400 | 请求体/信封非法 |
| 404 | 未知 session/run/topology/artifact/scenario |
| 409 | 生命周期非法迁移、cursor/过滤器冲突、并发 run 冲突 |
| 413 | 请求体过大 |
| 422 | 语义非法(生成配置校验失败、fault prepare 拒绝、时钟域/范围语义非法) |
| 500 | 未分类内部错误 (fallback for unhandled exceptions — no table row) |
| 503 | 存储不可用、Artifact Storage 不可用、TSDuck 不可用 |

The exceptions live in ``application`` (import-linter C6: ``api`` may only
import ``application``); the table lives in ``api`` where the HTTP response
is rendered.
"""

from __future__ import annotations

from api.errors import ERROR_HTTP_MAPPING
from application.errors import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    SemanticValidationError,
    ServiceUnavailableError,
)


class TestMappingTableRows:
    def test_table_has_exactly_the_six_declared_rows(self):
        rows = {exception_class: status for exception_class, status in ERROR_HTTP_MAPPING}
        assert rows == {
            BadRequestError: 400,
            NotFoundError: 404,
            ConflictError: 409,
            PayloadTooLargeError: 413,
            SemanticValidationError: 422,
            ServiceUnavailableError: 503,
        }

    def test_statuses_match_spec_500_section_6(self):
        statuses = {status for _, status in ERROR_HTTP_MAPPING}
        # SPEC-500 §6 rows; 500 is intentionally absent — it is the fallback
        # for unclassified/unhandled exceptions, not a raisable category.
        assert statuses == {400, 404, 409, 413, 422, 503}

    def test_every_row_exception_is_an_application_error(self):
        for exception_class, _ in ERROR_HTTP_MAPPING:
            assert issubclass(exception_class, ApplicationError)

    def test_base_application_error_is_not_a_table_row(self):
        # A bare ApplicationError is by definition an unclassified error
        # (SPEC-500 §6 "未分类内部错误") and must fall through to the 500
        # fallback, never to a category status.
        assert ApplicationError not in {
            exception_class for exception_class, _ in ERROR_HTTP_MAPPING
        }


class TestApplicationErrorPayload:
    """The error envelope payload fields ride on the exception itself."""

    def test_error_code_and_message_are_required(self):
        try:
            ApplicationError()  # type: ignore[call-arg]
        except TypeError:
            pass
        else:
            raise AssertionError("ApplicationError must require error_code/message")

    def test_payload_fields_are_carried(self):
        error = ConflictError(
            "SESSION_INVALID_TRANSITION",
            "start is invalid in state PAUSED",
            details={"current_state": "PAUSED"},
        )
        assert error.error_code == "SESSION_INVALID_TRANSITION"
        assert error.message == "start is invalid in state PAUSED"
        assert error.retryable is False
        assert error.details == {"current_state": "PAUSED"}

    def test_retryable_defaults_false_and_details_default_empty(self):
        error = NotFoundError("SESSION_NOT_FOUND", "no session 0f0e")
        assert error.retryable is False
        assert error.details == {}

    def test_details_is_a_private_copy(self):
        source = {"schema_path": "$.fault_plan[0]"}
        error = SemanticValidationError("SIM_FAULT_REJECTED", "prepare rejected", details=source)
        source["schema_path"] = "mutated"
        assert error.details == {"schema_path": "$.fault_plan[0]"}
