"""Timeline service structured errors (SPEC-303 §9, SPEC-300 §13 shape).

The timeline query/export face reports failures with the canonical
``error_code / message / retryable / details`` shape. Codes:

- ``OBS_CURSOR_EXPIRED`` — registered HERE by ticket #51 (裁定 E; SPEC-300
  §13 lists it for #51/#53): the opaque cursor token is malformed,
  undecodable, replayed under a changed filter or another scope, or its
  anchor record no longer sits at the recorded position (tombstoned/
  deleted). Non-retryable: the client restarts iteration from page one.
  #53 later reuses this exact code when wiring REST pagination.
- ``OBS_QUERY_RANGE_TOO_LARGE`` — SPEC-303 §9 reuses the SPEC-300 §13
  code for over-limit time ranges. The constant is declared here so the
  timeline service can raise it; the formal #53 route-wiring registration
  covers the REST mapping (this module does not pre-empt it).
- ``OBS_INVALID_TIME_DOMAIN`` — NOT redeclared: the code lives in the
  single shared vocabulary :class:`domain.observation.EnvelopeErrorCode`
  (the time-domain guard raises it); the timeline service reuses
  ``code.value`` for its own mixed-domain refusals.
"""

OBS_CURSOR_EXPIRED = "OBS_CURSOR_EXPIRED"
OBS_QUERY_RANGE_TOO_LARGE = "OBS_QUERY_RANGE_TOO_LARGE"


class TimelineError(Exception):
    """Structured timeline error (SPEC-300 §13 shape)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details: dict = dict(details or {})

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


__all__ = [
    "OBS_CURSOR_EXPIRED",
    "OBS_QUERY_RANGE_TOO_LARGE",
    "TimelineError",
]
