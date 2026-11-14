"""Application-level API exception taxonomy (ticket #24, SPEC-500 §6).

The REST error contract keys on exception categories, so the categories must
live where both the future use-cases (M3) and the ``api`` layer can reach
them: ``application``. import-linter C6 forbids ``api`` from importing
anything but ``application`` (ADR-0005 decision 4), which is exactly why
these exceptions are application-owned rather than api-owned.

SPEC-500 §6 freezes the exception→HTTP mapping (see ``api.errors`` for the
declarative table). Each class below is one table row; the *semantic*
concrete errors (lifecycle transitions, fault prepare rejections, storage
states, ...) arrive with their routes in M3/M4 and subclass or instantiate
these categories.

Error codes: the registry authority is SPEC-300 §13 ("错误码逐码登记随实现
进 SPEC-300 §13 注册表"). Codes are therefore **required** constructor
arguments with no defaults — the skeleton itself invents no per-route codes.
The only skeleton-owned codes are the two generic ones needed to render an
envelope without a raiser-supplied code:

- ``REQUEST_BODY_INVALID`` — request body/envelope failed schema validation
  (SPEC-500 §6 row 400).
- ``INTERNAL_UNCLASSIFIED`` — unclassified internal error (SPEC-500 §6 row
  500, "未分类内部错误").

Both must be registered in SPEC-300 §13 when the first routes consume them
(M3); docs changes are outside ticket #24's allowlist (tracked in the
implementation report).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Generic code: request body/envelope failed schema validation (§6 row 400).
REQUEST_BODY_INVALID = "REQUEST_BODY_INVALID"

#: Generic code: unclassified internal error (§6 row 500, "未分类内部错误").
INTERNAL_UNCLASSIFIED = "INTERNAL_UNCLASSIFIED"


class ApplicationError(Exception):
    """Base class for every error that maps to a SPEC-500 §6 HTTP row.

    The envelope payload fields (SPEC-305 §7 shape) ride on the exception:
    ``error_code`` / ``message`` / ``retryable`` / ``details``. Concrete
    error codes are registered per implementation in SPEC-300 §13, so they
    are mandatory — a default would silently bypass that review gate.
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        # Copy: raisers keep owning their mapping; the envelope must not
        # mutate or alias raiser state.
        self.details: dict[str, Any] = dict(details) if details is not None else {}


class BadRequestError(ApplicationError):
    """SPEC-500 §6 row 400: 请求体/信封非法."""


class NotFoundError(ApplicationError):
    """SPEC-500 §6 row 404: 未知 session/run/topology/artifact/scenario."""


class ConflictError(ApplicationError):
    """SPEC-500 §6 row 409: 生命周期非法迁移、cursor/过滤器冲突、并发 run 冲突."""


class PayloadTooLargeError(ApplicationError):
    """SPEC-500 §6 row 413: 请求体过大."""


class SemanticValidationError(ApplicationError):
    """SPEC-500 §6 row 422: 语义非法(生成配置校验失败、fault prepare 拒绝、时钟域/范围语义非法)."""


class ServiceUnavailableError(ApplicationError):
    """SPEC-500 §6 row 503: 存储不可用、Artifact Storage 不可用、TSDuck 不可用."""
