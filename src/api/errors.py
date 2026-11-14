"""Error contract: declarative exception→HTTP mapping (SPEC-500 §6, ticket #24).

The table below is the single declarative source of truth for which
application exception category renders which HTTP status. Every row of
SPEC-500 §6 is exercised by a test (``tests/integration/api/``); the 500
row ("未分类内部错误") is the *absence* of a registered category — any
unhandled exception falls through to the fallback handler and renders the
same envelope.

The response-rendering handlers are registered by ``api.app`` onto the
FastAPI app from this table; the envelope shape itself is the Pydantic
authority in ``api.dto`` (SPEC-305 §7 shape).
"""

from __future__ import annotations

from application.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    SemanticValidationError,
    ServiceUnavailableError,
)

#: SPEC-500 §6 mapping, one row per raisable exception category, in spec
#: row order. The 500 row is deliberately absent: it is the fallback for
#: unhandled/unclassified exceptions (including a bare ``ApplicationError``),
#: rendered by the Exception-level handler registered in ``api.app``.
ERROR_HTTP_MAPPING: tuple[tuple[type[Exception], int], ...] = (
    (BadRequestError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (PayloadTooLargeError, 413),
    (SemanticValidationError, 422),
    (ServiceUnavailableError, 503),
)
