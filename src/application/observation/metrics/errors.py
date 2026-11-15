"""Metrics-engine structured error codes (SPEC-302 §10, SPEC-300 §13).

Ticket #50 per-code implementation registration (brief §1.7 discipline:
one implementation anchor + one text entry + provenance per code):

- ``OBS_METRIC_DIMENSION_REJECTED`` — a filter/ingest dimension outside the
  metric's ``allowed_dimensions`` whitelist (SPEC-302 §10, strict default;
  non-retryable). NEW code of this module.
- ``OBS_METRIC_CARDINALITY_EXCEEDED`` — the per-metric active-series limit
  is full (SPEC-302 §10; non-retryable — retrying the same sample cannot
  succeed while the limit stands). NEW code of this module.
- ``OBS_METRIC_NOT_FOUND`` — unknown metric in a query (SPEC-300 §13 lists
  the code; this module registers the raise point, "除非 allow_unknown=true",
  SPEC-302 §8). Reused code — string owned by SPEC-300 §13.
- ``OBS_QUERY_RANGE_TOO_LARGE`` — ``start_ns >= end_ns``, a range or a point
  count over the configured limit (SPEC-302 §8/§10 复用; SPEC-300 §13 lists
  the code; this module registers the metrics-engine raise point — the #53
  API plane maps it onto the frozen HTTP table). Reused code.

Request-shape violations that carry no SPEC-302 §10 code (missing/ambiguous
``clock_domain``, ``step_ns < 1``, an ``aggregation_override`` outside the
metric's allowed operations) raise the application taxonomy's
:class:`application.errors.BadRequestError` with the generic
``REQUEST_BODY_INVALID`` code — the #53 API plane already maps that category
to HTTP 400, so no unregistered code is invented here.

:class:`MetricError` subclasses :class:`application.errors.ApplicationError`
so the SPEC-305 plane inherits the frozen exception→HTTP mapping unchanged.
"""

from application.errors import ApplicationError

#: SPEC-302 §10 (new): non-whitelisted dimension, strict default.
OBS_METRIC_DIMENSION_REJECTED = "OBS_METRIC_DIMENSION_REJECTED"

#: SPEC-302 §10 (new): per-metric active-series limit exceeded.
OBS_METRIC_CARDINALITY_EXCEEDED = "OBS_METRIC_CARDINALITY_EXCEEDED"

#: SPEC-300 §13 (reuse): unknown metric in a query; raise point registered
#: here by ticket #50 (SPEC-302 §8 "未知指标（除非 allow_unknown=true）").
OBS_METRIC_NOT_FOUND = "OBS_METRIC_NOT_FOUND"

#: SPEC-300 §13 (reuse): empty/inverted range or point-count overrun;
#: raise point registered here by ticket #50 (SPEC-302 §8).
OBS_QUERY_RANGE_TOO_LARGE = "OBS_QUERY_RANGE_TOO_LARGE"


class MetricError(ApplicationError):
    """Structured metrics-engine rejection (SPEC-300 §13 error shape)."""


__all__ = [
    "OBS_METRIC_CARDINALITY_EXCEEDED",
    "OBS_METRIC_DIMENSION_REJECTED",
    "OBS_METRIC_NOT_FOUND",
    "OBS_QUERY_RANGE_TOO_LARGE",
    "MetricError",
]
