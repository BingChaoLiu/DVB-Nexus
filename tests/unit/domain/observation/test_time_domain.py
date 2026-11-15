"""SPEC-300 section 6 / REQ-OBS-300-004 — cross-clock-domain guard.

The envelope timepoint deliberately has no ``semantics`` field (SPEC-301 §6:
the ``source``/``observed`` field names carry the semantics); the rejection
point therefore lives at the entry where timestamps from different clock
domains would be compared or arithmetically combined. This module pins the
two-domain mutual-rejection semantics of the ``domain.observation`` time
guard: any pair of timepoints whose ``(clock_domain, clock_epoch)`` keys
disagree must be refused with ``OBS_INVALID_TIME_DOMAIN`` before a
comparison/arithmetic entry lets them through (SPEC-300 §6 rules 1/3/5).

M4 wiring point: the comparison consumers are M4 SPEC-302 (metrics engine
sampling-window math) and SPEC-303 (timeline ordering) — both must call
``ensure_same_time_domain`` (or an equivalent explicit-mapping path, §6
rule 3) instead of comparing raw ``value_ns`` across domains. No production
comparison entry exists in M3; this guard is the append-only contract seam
they bind to (orchestrator scoped-append authorization, issue #15 ruling 1).
"""

import pytest

from domain.observation.envelope import Timepoint
from domain.observation.errors import EnvelopeError, EnvelopeErrorCode
from domain.observation.time_domain import ensure_same_time_domain

SESSION_ID = "0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"


def _timepoint(value_ns: int, clock_domain: str, clock_epoch: int = 0):
    return Timepoint(
        value_ns=value_ns, clock_domain=clock_domain, clock_epoch=clock_epoch
    )


def test_same_domain_same_epoch_is_comparable():
    """Two virtual-clock timepoints of one session/epoch pass the guard."""
    virtual = _timepoint(1_200_000_000, f"sim:{SESSION_ID}")
    later = _timepoint(2_400_000_000, f"sim:{SESSION_ID}")

    assert ensure_same_time_domain(virtual, later) is None


def test_sim_vs_wall_is_refused():
    """Virtual source time vs wall observation time is the canonical cross-domain pair."""
    virtual = _timepoint(1_200_000_000, f"sim:{SESSION_ID}")
    wall = _timepoint(1_790_000_000_000_000_000, "wall:utc")

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(virtual, wall)

    assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN


def test_wall_vs_sim_is_refused_too():
    """Rejection is symmetric — argument order must not matter."""
    wall = _timepoint(1_790_000_000_000_000_000, "wall:utc")
    virtual = _timepoint(1_200_000_000, f"sim:{SESSION_ID}")

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(wall, virtual)

    assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN


def test_two_different_sim_sessions_are_refused():
    """§6 rule 1: sim values are comparable only within the same session."""
    session_a = _timepoint(1_000, f"sim:{SESSION_ID}")
    session_b = _timepoint(2_000, "sim:ffffffff-ffff-4fff-8fff-ffffffffffff")

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(session_a, session_b)

    assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN


def test_same_domain_different_epoch_is_refused():
    """§6 rule 5: a producer clock restart bumps clock_epoch; values across
    epochs are different time bases even inside one domain."""
    before_restart = _timepoint(1_000, f"sim:{SESSION_ID}", clock_epoch=0)
    after_restart = _timepoint(1_000, f"sim:{SESSION_ID}", clock_epoch=1)

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(before_restart, after_restart)

    assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN


def test_nary_comparison_rejects_on_any_outlier():
    """A batch comparison entry must refuse as soon as one key disagrees."""
    session_id_b = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    same = _timepoint(1_000, f"sim:{SESSION_ID}")
    same_again = _timepoint(2_000, f"sim:{SESSION_ID}")
    outlier = _timepoint(3_000, f"sim:{session_id_b}")

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(same, same_again, outlier)

    assert excinfo.value.code is EnvelopeErrorCode.OBS_INVALID_TIME_DOMAIN


def test_error_names_both_domains():
    """The structured message must identify the conflicting keys (§9)."""
    virtual = _timepoint(1_000, f"sim:{SESSION_ID}")
    wall = _timepoint(2_000, "wall:utc")

    with pytest.raises(EnvelopeError) as excinfo:
        ensure_same_time_domain(virtual, wall)

    message = str(excinfo.value)
    assert f"sim:{SESSION_ID}" in message
    assert "wall:utc" in message
