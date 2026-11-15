"""Error contract: declarative exception→HTTP mapping (SPEC-500 §6, ticket #24).

The table below is the single declarative source of truth for which
application exception category renders which HTTP status. Every row of
SPEC-500 §6 is exercised by a test (``tests/integration/api/``); the 500
row ("未分类内部错误") is the *absence* of a registered category — any
unhandled exception falls through to the Exception-level handler and
renders the same envelope.

Envelope rendering follows SPEC-305 §7 (shape authority as Pydantic DTOs in
``api.dto``). Two framework-level overrides complete the contract:

- ``RequestValidationError`` → **400**. FastAPI's default is 422, but
  SPEC-500 §6 freezes 400 for "请求体/信封非法" and reserves 422 for
  semantic invalidity — so the default is overridden (spec-mandated, not a
  deviation).
- ``starlette.exceptions.HTTPException`` → the same envelope, code
  ``HTTP_<status>`` (framework-fallback convention: unknown route, method
  not allowed; SPEC-500 §6 resource-not-found codes are raiser-owned from
  M3 on).

Error codes: raiser-supplied and mandatory (registry authority SPEC-300
§13). The only api-owned codes are ``REQUEST_BODY_INVALID`` and
``INTERNAL_UNCLASSIFIED`` (see ``application.errors`` docstring).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from api.dto import ErrorDetail, ErrorResponse
from application.errors import (
    INTERNAL_UNCLASSIFIED,
    REQUEST_BODY_INVALID,
    ApplicationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    SemanticValidationError,
    ServiceUnavailableError,
    UnauthorizedError,
)

#: SPEC-500 §6 mapping, one row per raisable exception category, in spec
#: row order. The 500 row is deliberately absent: it is the fallback for
#: unhandled/unclassified exceptions (including a bare ``ApplicationError``),
#: rendered by the Exception-level handler registered in :func:`register_error_handlers`.
ERROR_HTTP_MAPPING: tuple[tuple[type[Exception], int], ...] = (
    (BadRequestError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (PayloadTooLargeError, 413),
    (SemanticValidationError, 422),
    (ServiceUnavailableError, 503),
)

#: SPEC-305 §7 inventory extension (ticket #53): the three rows the
#: observation query plane adds — 401 未认证 (no MVP raiser: Q4 无认证),
#: 403 scope 禁止 (``OBS_SCOPE_FORBIDDEN``), 429 限流 (the export-task
#: throttle). The SPEC-500 §6 table above stays byte-identical — it is
#: pinned row-exact by the #24 unit contract — so the extension rides its
#: own declarative table and the SAME registration loop.
SPEC305_ERROR_HTTP_MAPPING: tuple[tuple[type[Exception], int], ...] = (
    (UnauthorizedError, 401),
    (ForbiddenError, 403),
    (RateLimitedError, 429),
)


#: OpenAPI error-response documentation (ticket #80, REQ-API-500-002):
#: every error body is the unified SPEC-305 §7 envelope, so routes declare
#: these ``responses=`` entries to make ``ErrorResponse``/``ErrorDetail``
#: reachable components (the #61 codegen plane). The declared statuses are
#: the §6 rows a route can actually render — 400/404/409/422/501/503 for
#: every route (validation, unknown resource, lifecycle/cursor conflict,
#: semantic rejection, unbound-composition freeze, storage), plus the 429
#: variant for the export-throttled faces. Documentation only: the runtime
#: rendering is the declarative tables above, unchanged.
_OPENAPI_ERROR_STATUSES: tuple[int, ...] = (400, 404, 409, 422, 501, 503)


def _error_response_descriptions() -> dict[int, dict[str, object]]:
    return {
        status: {"model": ErrorResponse, "description": f"SPEC-500 §6 row {status}"}
        for status in _OPENAPI_ERROR_STATUSES
    }


OPENAPI_ERROR_RESPONSES: dict[int, dict[str, object]] = _error_response_descriptions()

#: The export-throttle variant: the common rows plus the SPEC-305 §9 429 row.
OPENAPI_EXPORT_ERROR_RESPONSES: dict[int, dict[str, object]] = {
    **OPENAPI_ERROR_RESPONSES,
    429: {"model": ErrorResponse, "description": "SPEC-305 §9 export throttle"},
}

#: The solution-reveal variant (ticket #80 裁定 F): the common rows plus
#: the 403 row — ``SIM_SCENARIO_SOLUTION_LEAK`` (SPEC-205 §7 row 6, the
#: SPEC-305 §7 403 mapping) is raisable exactly on that route.
OPENAPI_SOLUTION_ERROR_RESPONSES: dict[int, dict[str, object]] = {
    **OPENAPI_ERROR_RESPONSES,
    403: {"model": ErrorResponse, "description": "SPEC-500 §6 row 403"},
}


def _request_id(request: Request) -> str:
    """Per-request id stamped by ``api.app.RequestIdMiddleware``.

    Falls back to a fresh id when the middleware did not run (defensive:
    handlers must always render a complete envelope).
    """
    state = request.scope.get("state") or {}
    return state.get("request_id") or uuid4().hex


def render_error(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render one SPEC-305 §7 error envelope as a JSON response."""
    payload = ErrorResponse(
        error=ErrorDetail(
            error_code=error_code,
            message=message,
            retryable=retryable,
            details=details if details is not None else {},
        ),
        request_id=_request_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=dict(headers) if headers else None,
    )


def _application_error_handler(status_code: int):
    """Build the handler for one declarative table row (class → status)."""

    def handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return render_error(
            request,
            status_code=status_code,
            error_code=exc.error_code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    return handler


def _request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Request body/envelope schema failure → 400 (SPEC-500 §6 row 1).

    Details are path-addressed (pydantic ``loc`` chains) so clients can
    locate the offending field.
    """
    validation_errors = [
        {
            "loc": list(entry.get("loc", ())),
            "msg": str(entry.get("msg", "")),
            "type": str(entry.get("type", "")),
        }
        for entry in exc.errors()
    ]
    return render_error(
        request,
        status_code=400,
        error_code=REQUEST_BODY_INVALID,
        message="request body failed schema validation",
        details={"errors": validation_errors},
    )


def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Framework HTTP errors (unknown route, 405, ...) render the envelope."""
    return render_error(
        request,
        status_code=exc.status_code,
        error_code=f"HTTP_{exc.status_code}",
        message=str(exc.detail),
        headers=exc.headers,
    )


def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """SPEC-500 §6 row 500: 未分类内部错误. No internals leak into the body."""
    return render_error(
        request,
        status_code=500,
        error_code=INTERNAL_UNCLASSIFIED,
        message="unclassified internal error",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register the declarative tables + framework overrides onto ``app``."""
    for exception_class, status_code in ERROR_HTTP_MAPPING + SPEC305_ERROR_HTTP_MAPPING:
        app.add_exception_handler(exception_class, _application_error_handler(status_code))
    app.add_exception_handler(RequestValidationError, _request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
