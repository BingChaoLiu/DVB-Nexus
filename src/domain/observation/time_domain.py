"""SPEC-300 section 6 clock model — cross-clock-domain comparison guard.

REQ-OBS-300-004: virtual time and wall time must never be compared by
accident. The envelope timepoint carries ``value_ns`` + ``clock_domain`` +
``clock_epoch`` but deliberately no ``semantics`` field (SPEC-301 §6 — the
``source``/``observed`` field names carry the semantics), so the rejection
point is NOT envelope parsing: it is the entry where timestamps from
different time bases would be compared or arithmetically combined. That
entry is this guard.

Rules implemented (SPEC-300 §6):
- rule 1: ``sim:<session_id>`` values are comparable only within the same
  session AND the same clock epoch — the guard compares the full
  ``(clock_domain, clock_epoch)`` key, not the bare domain string;
- rule 3: cross-domain correlation needs explicit mapping metadata; implicit
  arithmetic is refused here with ``OBS_INVALID_TIME_DOMAIN``;
- rule 5: a producer clock restart bumps ``clock_epoch``, so same-domain
  different-epoch values are different time bases and refused too.

There is no production comparison entry in M3; the M4 SPEC-302 metrics
engine and SPEC-303 timeline recorder bind their comparisons to this guard
(scoped append authorized by the orchestrator, issue #15 ruling 1). Existing
envelope behavior is untouched — this module only adds the refusal seam.
"""

from typing import Tuple

from domain.observation.envelope import Timepoint
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode

#: The comparable time-base key of a timepoint (SPEC-300 §6 rules 1/5).
TimeDomainKey = Tuple[str, int]


def time_domain_key(timepoint: Timepoint) -> TimeDomainKey:
    """The ``(clock_domain, clock_epoch)`` key that must match for a compare.

    Exposed so explicit-mapping correlation paths (§6 rule 3) can group
    timepoints by time base without re-deriving the key shape.
    """
    return (timepoint.clock_domain, timepoint.clock_epoch)


def ensure_same_time_domain(*timepoints: Timepoint) -> None:
    """Refuse a comparison/arithmetic entry whose timepoints disagree.

    Accepts two or more envelope timepoints (the two-domain case and batch
    windows alike). Raises :class:`EnvelopeError` with
    ``OBS_INVALID_TIME_DOMAIN`` when any ``(clock_domain, clock_epoch)``
    key differs from the first; returns ``None`` when all share one time
    base and the caller may proceed to compare ``value_ns``.
    """
    if len(timepoints) < 2:
        return
    first = time_domain_key(timepoints[0])
    for other in timepoints[1:]:
        key = time_domain_key(other)
        if key != first:
            raise EnvelopeError(
                EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN,
                "cross-clock-domain comparison refused: "
                f"{first[0]!r}@epoch{first[1]} vs {key[0]!r}@epoch{key[1]} "
                "(SPEC-300 section 6 rules 1/3, REQ-OBS-300-004); virtual "
                "and wall time never compare implicitly — cross-domain "
                "correlation requires explicit mapping metadata",
            )


__all__ = ["TimeDomainKey", "ensure_same_time_domain", "time_domain_key"]
