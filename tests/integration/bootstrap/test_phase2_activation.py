"""Composition-root activation pin — the Phase 2 filter builders (#128).

Ruling §10-4: the Phase 2 filter modules self-register at import; the
composition root is the activation point (``bootstrap/app`` imports the
four modules).  This pin proves that after the composition root is
imported, every Phase 2 fault type resolves to its REAL builder — never
the #121 ``phase2_skeletons`` placeholders (a skeleton would fail loudly
mid-run; the composition must never wire one).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import bootstrap.app  # noqa: F401 — the activation import under test
from faults.factory import transform_builder_for


def _builder_module(fault_type: str) -> str:
    return transform_builder_for(fault_type).__module__


class TestPhase2BuilderActivation:
    def test_t2mi_plp_mismatch_resolves_the_real_builder(self) -> None:
        assert _builder_module("T2MI_PLP_MISMATCH") == (
            "faults.filters.t2mi_plp_mismatch"
        )

    def test_bbheader_sync_fault_resolves_the_real_builder(self) -> None:
        assert _builder_module("BBHEADER_SYNC_FAULT") == (
            "faults.filters.bbheader_sync"
        )

    def test_biss_key_mismatch_resolves_the_dispatching_builder(self) -> None:
        # The #127 dispatcher routes Mode 1 → #126's transform and the
        # Mode E variants → the SPEC-611 transform (allow_replace=True
        # over the #126 registration).
        assert _builder_module("BISS_KEY_MISMATCH") == (
            "faults.filters.biss_mode_e"
        )

    def test_no_skeleton_builder_is_ever_resolved_for_phase2_layers(self) -> None:
        # The three Phase 2-layer primitives (#122~#127 deliverables) must
        # resolve to their real builders. PMT_PID_DRIFT stays a TS-layer
        # skeleton by design (C2, no M6 implementation ticket).
        for fault_type in (
            "T2MI_PLP_MISMATCH",
            "BBHEADER_SYNC_FAULT",
            "BISS_KEY_MISMATCH",
        ):
            assert "phase2_skeletons" not in _builder_module(fault_type), (
                f"{fault_type} resolved to a #121 skeleton placeholder — "
                "the composition root failed to activate the real filter "
                "module (ruling §10-4)"
            )
