"""SPEC-003 section 3 status vocabulary tests.

Seam: enum closed-set membership only. Section 3 defines a recommended split
of status semantics into four vocabularies; allowed combinations per node type
are deferred (SPEC-003 section 3/section 6), so no aggregate status model
exists here — exactly the four enums, values verbatim.
"""

from domain.observation import (
    HealthState,
    LifecycleState,
    LockState,
    OperationalState,
)


class TestStatusVocabularyClosedSets:
    def test_lifecycle_state_values(self):
        assert {member.value for member in LifecycleState} == {
            "created",
            "starting",
            "running",
            "stopping",
            "stopped",
            "failed",
        }

    def test_operational_state_values(self):
        assert {member.value for member in OperationalState} == {
            "active",
            "idle",
            "unavailable",
        }

    def test_health_state_values(self):
        assert {member.value for member in HealthState} == {
            "ok",
            "warn",
            "error",
            "unknown",
        }

    def test_lock_state_values(self):
        assert {member.value for member in LockState} == {
            "locked",
            "unlocked",
            "acquiring",
            "not_applicable",
        }
