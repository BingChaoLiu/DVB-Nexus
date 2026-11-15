"""Alerts-engine structured error codes (SPEC-304 §10, SPEC-300 §13 shape).

Ticket #52 per-code implementation registration (brief §1.7 discipline:
one implementation anchor + one text entry + provenance per code):

- ``OBS_RULE_INVALID`` — a rule declaration fails validation (SPEC-304 §10
  new code; raised here at declaration/registration time, fail-fast before
  any evaluation). Non-retryable: retrying the same declaration cannot
  succeed.
- ``OBS_RULE_INPUT_STALE`` — a rule's required input is missing or older
  than the rule's configured freshness (SPEC-304 §10 new code: 输入超出新鲜
  度 — roll-up degrades to ``unknown``, never a false firing). Retryable:
  a later evaluation with fresh inputs can succeed. Surfaced as a roll-up
  reason code, not necessarily a raised exception.

:class:`AlertError` subclasses :class:`application.errors.ApplicationError`
so the SPEC-305 plane inherits the frozen exception→HTTP mapping unchanged
(#53 consumes this face; the REST wiring is NOT this ticket's — R1 seam).
"""

from application.errors import ApplicationError

#: SPEC-304 §10 (new): rule declaration failed validation (fail-fast).
OBS_RULE_INVALID = "OBS_RULE_INVALID"

#: SPEC-304 §10 (new): required input missing / beyond configured freshness
#: (roll-up contributes unknown; no false firing).
OBS_RULE_INPUT_STALE = "OBS_RULE_INPUT_STALE"


class AlertError(ApplicationError):
    """Structured alerts-engine rejection (SPEC-300 §13 error shape)."""


__all__ = ["OBS_RULE_INVALID", "OBS_RULE_INPUT_STALE", "AlertError"]
