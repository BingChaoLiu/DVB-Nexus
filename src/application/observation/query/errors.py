"""Query-plane error translation — service-plane structured errors land on
the frozen ``application.errors`` categories with their registry codes
intact (ticket #53, SPEC-305 §7 + SPEC-500 §6).

The translation table (one row per source error family, HTTP row noted):

- ``MetricError`` (#50, an ``ApplicationError`` subclass): codes
  ``OBS_METRIC_NOT_FOUND`` → NotFoundError (404 未知记录);
  ``OBS_QUERY_RANGE_TOO_LARGE`` / ``OBS_METRIC_DIMENSION_REJECTED`` /
  ``OBS_METRIC_CARDINALITY_EXCEEDED`` → SemanticValidationError (422 范围/
  语义非法); anything else re-raised (500 未分类 — never silently remapped).
- ``TimelineError`` (#51, plain Exception): ``OBS_CURSOR_EXPIRED`` →
  ConflictError (409 cursor/过滤器冲突, SPEC-305 §7 row);
  ``OBS_QUERY_RANGE_TOO_LARGE`` → SemanticValidationError (422).
- ``ValueError`` (journal limit guard, range-shape guards): BadRequestError
  (400 查询非法) unless a code is carried.
- ``sqlite3.Error`` / storage failures → ServiceUnavailableError with
  ``OBS_STORAGE_UNAVAILABLE`` (503, retryable).

The registry codes ride ON the translated exception (`error_code`), so the
SPEC-300 §13 registry entry and the HTTP envelope agree.
"""

from __future__ import annotations

import sqlite3

from application.errors import (
    ApplicationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    REQUEST_BODY_INVALID,
    SemanticValidationError,
    ServiceUnavailableError,
)
from application.observation.metrics.errors import (
    OBS_METRIC_CARDINALITY_EXCEEDED,
    OBS_METRIC_DIMENSION_REJECTED,
    OBS_METRIC_NOT_FOUND,
    MetricError,
)
from application.observation.timeline.errors import OBS_CURSOR_EXPIRED, TimelineError

#: SPEC-300 §13 reused codes (the query plane raises them; per-code
#: registration text lives in SPEC-300 §13 via the #53 scoped append).
OBS_STORAGE_UNAVAILABLE = "OBS_STORAGE_UNAVAILABLE"
OBS_QUERY_RANGE_TOO_LARGE = "OBS_QUERY_RANGE_TOO_LARGE"
#: Clock-domain semantic failures (missing/mixed/misplaced query shapes) —
#: the #51 timeline precedent for domain-shape misuse (422 row).
OBS_INVALID_TIME_DOMAIN = "OBS_INVALID_TIME_DOMAIN"
#: ``OBS_CURSOR_EXPIRED`` is NOT redeclared: the code is registered by
#: ticket #51 in :mod:`application.observation.timeline.errors` (imported
#: above) — the query plane reuses the same constant object so a spelling
#: fork cannot silently unhook the translation row (M4 review fix F1).
OBS_SCOPE_FORBIDDEN = "OBS_SCOPE_FORBIDDEN"


def translate_service_error(exc: Exception) -> Exception:
    """Translate one service-plane error onto the application categories.

    Returns the ORIGINAL exception when it already carries a registered
    raiser code on an application category (nothing to do); raises the
    mapped category otherwise. Unknown shapes propagate unchanged (the 500
    row is the honest fallback — never a silent remap).
    """
    if isinstance(exc, MetricError):
        return _translate_metric_error(exc)
    if isinstance(exc, TimelineError):
        return _translate_timeline_error(exc)
    if isinstance(exc, ApplicationError):
        return exc
    if isinstance(exc, sqlite3.Error):
        return ServiceUnavailableError(
            OBS_STORAGE_UNAVAILABLE,
            f"observation storage unavailable: {exc}",
            retryable=True,
        )
    if isinstance(exc, ValueError):
        return BadRequestError(REQUEST_BODY_INVALID, str(exc))
    return exc


def _translate_metric_error(exc: MetricError) -> ApplicationError:
    if exc.error_code == OBS_METRIC_NOT_FOUND:
        return NotFoundError(exc.error_code, exc.message, details=exc.details)
    if exc.error_code in (
        OBS_QUERY_RANGE_TOO_LARGE,
        OBS_METRIC_DIMENSION_REJECTED,
        OBS_METRIC_CARDINALITY_EXCEEDED,
    ):
        return SemanticValidationError(
            exc.error_code, exc.message, details=exc.details
        )
    return exc


def _translate_timeline_error(exc: TimelineError) -> ApplicationError:
    if exc.code == OBS_CURSOR_EXPIRED:
        return ConflictError(exc.code, exc.message, details=exc.details)
    if exc.code in (OBS_QUERY_RANGE_TOO_LARGE, OBS_INVALID_TIME_DOMAIN):
        return SemanticValidationError(exc.code, exc.message, details=exc.details)
    return exc


__all__ = ["OBS_STORAGE_UNAVAILABLE", "translate_service_error"]
