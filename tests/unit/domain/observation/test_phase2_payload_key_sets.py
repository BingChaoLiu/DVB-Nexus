"""The #141 same-source face: ``PHASE2_PAYLOAD_KEY_SETS``.

The render table's payloadKeys were hand-maintained against the #129
REPORT §2 display order — the drift risk #141 closes: additive payload
keys on an already-registered type would be silently hidden by the
stale table.  The ordered public face here is the SINGLE source the
frontend gen module (``scripts/dump-payload-keys.mjs`` →
``payloadKeys.gen.ts``) renders from, self-checked at import against
the frozen validator key sets (both directions locked: a key added to
a ``*_KEYS`` constant without the ordered face fails at import, and
vice versa).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation import registry

#: The #129 REPORT §2 display order — the exact order the hand table
#: carried (键集语义零变化: same sets, same render order).
DISPLAY_ORDER: dict[str, tuple[str, ...]] = {
    "t2mi.stage_summary": (
        "packet_count",
        "padding_count",
        "packet_type_distribution",
        "plp_distribution",
    ),
    "t2mi.plp_mismatch": (
        "expected_plp",
        "actual_plp",
        "business_absent_evidence",
    ),
    "bbframe.stage_summary": (
        "frame_count",
        "n_ups_distribution",
        "stuffing_ratio",
    ),
    "bbframe.recovery_failed": (
        "failure_count",
        "first_failed_frame_index",
    ),
    "biss.scramble_applied": (
        "pid_scope",
        "packet_count",
        "key_fingerprint",
        "mutation_log_ref",
        "mode",
        "derivation_ref",
        "mismatch_variants",
    ),
    "biss.descramble_failed": (
        "pid_scope",
        "failed_indices_sample",
        "self_check_kind",
        "key_fingerprint_ref",
        "mode",
    ),
    "gen.stage_started": ("layer",),
    "gen.stage_completed": ("layer", "item_count"),
    "gen.packet_sampled": ("layer", "packet_index", "byte_size", "sha256"),
}


def test_face_covers_exactly_the_registered_schema_face_event_types() -> None:
    # The face began as the nine Phase 2 types (#141) and grew additively
    # with the Phase 3 state-observation registration (ticket #164): every
    # registered type that carries a strict payload schema must appear in
    # the frontend render face — the dump source stays SINGLE.
    schema_face_types = (
        registry.T2MI_EVENT_TYPES
        | registry.BBFRAME_EVENT_TYPES
        | registry.BISS_EVENT_TYPES
        | registry.GEN_EVENT_TYPES
        | registry.RF_EVENT_TYPES
        | registry.SEC_EVENT_TYPES
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS) == schema_face_types


def test_every_face_set_equals_the_frozen_validator_keys() -> None:
    """The ordered face cites the validator constants by element — no
    parallel shapes (the import-time self-check makes drift fail fast;
    this pin is the readable contract)."""
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["t2mi.stage_summary"]) == (
        registry._T2MI_STAGE_SUMMARY_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["t2mi.plp_mismatch"]) == (
        registry._T2MI_PLP_MISMATCH_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["bbframe.stage_summary"]) == (
        registry._BBFRAME_STAGE_SUMMARY_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["bbframe.recovery_failed"]) == (
        registry._BBFRAME_RECOVERY_FAILED_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["biss.descramble_failed"]) == (
        registry._BISS_DESCRAMBLE_FAILED_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["gen.stage_started"]) == (
        registry._GEN_STAGE_STARTED_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["gen.stage_completed"]) == (
        registry._GEN_STAGE_COMPLETED_KEYS
    )
    assert set(registry.PHASE2_PAYLOAD_KEY_SETS["gen.packet_sampled"]) == (
        registry._GEN_PACKET_SAMPLED_KEYS
    )


def test_scramble_applied_face_is_the_maximal_mode_set() -> None:
    """Mode 1 accepts the bare base keys; the derived modes add the
    optional derivation face — the render face is the UNION (absent
    optional keys render nothing, the hand-table discipline)."""
    face = set(registry.PHASE2_PAYLOAD_KEY_SETS["biss.scramble_applied"])
    assert face == registry._BISS_SCRAMBLE_BASE_KEYS | registry._BISS_SCRAMBLE_DERIVATION_KEYS


def test_display_order_is_stable() -> None:
    """Tuple order == the #129 REPORT display order — the gen module
    renders verbatim, so a reordering here IS a UI row reorder and must
    be a deliberate, test-pinned change."""
    for event_type, expected in DISPLAY_ORDER.items():
        assert (
            registry.PHASE2_PAYLOAD_KEY_SETS[event_type] == expected
        ), f"{event_type} display order drifted"
