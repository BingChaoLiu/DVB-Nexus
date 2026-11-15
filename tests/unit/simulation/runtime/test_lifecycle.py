"""SPEC-200 section 5 — lifecycle state machine (ticket #41).

Traceability (SPEC-200 section 10):

- REQ-SIM-200-001  exhaustive transition table, illegal transitions all
  rejected with a stable error -> TestLegalEdges / TestIllegalTransitions /
  TestTransitionHelpers

The transition table is the #12 ruling authority (VALIDATING->FAILED and
FAILED->DISPOSED direct edges included). It is exhaustive: every pair NOT
listed must be refused, so the illegal matrix is generated as the complement
of the legal edges over the full state set — that is what makes the test
exhaustive instead of spot-check.
"""

from __future__ import annotations

import itertools

import pytest

pytestmark = pytest.mark.unit

from simulation.errors import (
    SIM_INVALID_LIFECYCLE_TRANSITION,
    InvalidLifecycleTransitionError,
)
from simulation.lifecycle import (
    ALLOWED_TRANSITIONS,
    FINAL_STATES,
    LifecycleState,
    allowed_transitions,
    can_transition,
    require_transition,
)

ALL_STATES = set(LifecycleState)


class TestLifecycleVocabulary:
    """SPEC-200 section 5: the nine-state set, frozen values."""

    def test_state_set_is_exactly_the_spec_nine(self) -> None:
        assert {state.value for state in LifecycleState} == {
            "created",
            "validating",
            "ready",
            "running",
            "paused",
            "stopping",
            "stopped",
            "failed",
            "disposed",
        }

    def test_final_states_are_stopped_and_disposed(self) -> None:
        # 终态 STOPPED、DISPOSED — 不可重启（DISPOSED additionally absorbs).
        assert FINAL_STATES == frozenset(
            {LifecycleState.STOPPED, LifecycleState.DISPOSED}
        )


class TestLegalEdges:
    """Every edge of the section 5 table transitions cleanly."""

    LEGAL_EDGES: tuple[tuple[LifecycleState, LifecycleState], ...] = (
        (LifecycleState.CREATED, LifecycleState.VALIDATING),
        (LifecycleState.VALIDATING, LifecycleState.READY),
        (LifecycleState.VALIDATING, LifecycleState.FAILED),
        (LifecycleState.VALIDATING, LifecycleState.STOPPING),
        (LifecycleState.READY, LifecycleState.RUNNING),
        (LifecycleState.READY, LifecycleState.FAILED),
        (LifecycleState.READY, LifecycleState.STOPPING),
        (LifecycleState.RUNNING, LifecycleState.PAUSED),
        (LifecycleState.RUNNING, LifecycleState.FAILED),
        (LifecycleState.RUNNING, LifecycleState.STOPPING),
        (LifecycleState.PAUSED, LifecycleState.RUNNING),
        (LifecycleState.PAUSED, LifecycleState.FAILED),
        (LifecycleState.PAUSED, LifecycleState.STOPPING),
        (LifecycleState.FAILED, LifecycleState.STOPPING),
        (LifecycleState.FAILED, LifecycleState.DISPOSED),
        (LifecycleState.STOPPING, LifecycleState.STOPPED),
        (LifecycleState.STOPPED, LifecycleState.DISPOSED),
    )

    def test_table_contains_exactly_the_spec_edges(self) -> None:
        listed = {
            (source, target)
            for source, targets in ALLOWED_TRANSITIONS.items()
            for target in targets
        }
        assert listed == set(self.LEGAL_EDGES)

    @pytest.mark.parametrize("source,target", LEGAL_EDGES)
    def test_legal_edge_accepted(
        self, source: LifecycleState, target: LifecycleState
    ) -> None:
        assert can_transition(source, target) is True
        # require_transition must NOT raise for a legal edge.
        require_transition(source, target)

    def test_failed_is_not_terminal_but_disposed_absorbs(self) -> None:
        # FAILED 不是终态：可清理（STOPPING）或直接回收（DISPOSED）。
        assert can_transition(LifecycleState.FAILED, LifecycleState.DISPOSED)
        assert can_transition(LifecycleState.FAILED, LifecycleState.STOPPING)
        # DISPOSED is the absorbing state: no outgoing edge at all.
        assert allowed_transitions(LifecycleState.DISPOSED) == frozenset()


class TestIllegalTransitions:
    """The complement of the legal edges over ALL state pairs is refused."""

    def test_every_unlisted_pair_rejected_with_stable_error(self) -> None:
        legal = {
            (source, target)
            for source, targets in ALLOWED_TRANSITIONS.items()
            for target in targets
        }
        illegal = [
            (source, target)
            for source, target in itertools.product(ALL_STATES, ALL_STATES)
            if (source, target) not in legal
        ]
        assert illegal, "complement generation must produce pairs"
        for source, target in illegal:
            with pytest.raises(InvalidLifecycleTransitionError) as excinfo:
                require_transition(source, target)
            assert excinfo.value.code == SIM_INVALID_LIFECYCLE_TRANSITION
            # Stable, pair-independent error surface (REQ-001 错误稳定).
            assert excinfo.value.current is source
            assert excinfo.value.target is target

    def test_error_message_lists_the_allowed_set(self) -> None:
        # SPEC-200 section 8: 拒绝，返回当前合法迁移集.
        with pytest.raises(InvalidLifecycleTransitionError) as excinfo:
            require_transition(LifecycleState.RUNNING, LifecycleState.READY)
        message = str(excinfo.value)
        for target in allowed_transitions(LifecycleState.RUNNING):
            assert target.value in message

    @pytest.mark.parametrize(
        "source,target",
        [
            # 不可重启：终态没有回运行的边。
            (LifecycleState.STOPPED, LifecycleState.RUNNING),
            (LifecycleState.STOPPED, LifecycleState.VALIDATING),
            (LifecycleState.DISPOSED, LifecycleState.RUNNING),
            # CREATED 只有唯一出边（stop 必须先经 VALIDATING 或后续态）。
            (LifecycleState.CREATED, LifecycleState.RUNNING),
            (LifecycleState.CREATED, LifecycleState.STOPPING),
            (LifecycleState.CREATED, LifecycleState.DISPOSED),
            # 跳阶段非法。
            (LifecycleState.READY, LifecycleState.PAUSED),
            (LifecycleState.RUNNING, LifecycleState.STOPPED),
            (LifecycleState.PAUSED, LifecycleState.STOPPED),
            (LifecycleState.STOPPING, LifecycleState.DISPOSED),
            (LifecycleState.STOPPING, LifecycleState.RUNNING),
        ],
    )
    def test_representative_illegal_edges(
        self, source: LifecycleState, target: LifecycleState
    ) -> None:
        with pytest.raises(InvalidLifecycleTransitionError):
            require_transition(source, target)
