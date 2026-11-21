"""The Phase 3 state-observation payload face (ticket #164).

Two obligations pinned here:

1. The frontend same-source face: ``PHASE2_PAYLOAD_KEY_SETS`` (the
   ``scripts/dump-payload-keys.mjs`` → ``payloadKeys.gen.ts`` render
   source) carries the two new namespaces in a frozen display order —
   the #141 mechanism extended additively, the biss.scramble_applied
   "maximal face" discipline (``sat_selected`` renders nothing on a
   universal-LNB or switch snapshot).
2. The vocabulary drift lock: ``domain.observation.registry`` RESTATES
   the closed-set vocabularies and metric key sets (domain cannot import
   ``simulation`` — the importlinter edge points the other way, the same
   posture as the #54 diagnosis restatement) — the tests layer pins the
   two faces item-for-item against ``simulation.state.evaluators._vocab``
   (the #161 payload-registration source) and the walk's ``Health``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation import registry
from simulation.state.evaluators import _vocab


RF_TUNER_FACE: tuple[str, ...] = (
    "node_id",
    "health",
    "causes",
    "source",
    "confidence",
    "lock_state",
    "if_frequency_khz",
    "ber_state",
    "locked_transponder_id",
    "stale",
)

# The maximal sec.* face: lnb metrics + the legacy additive + switch
# metrics — no concrete payload ever carries all of them at once (the
# shapes are exact per node type; the render face is the union).
SEC_MAXIMAL_FACE: tuple[str, ...] = (
    "node_id",
    "health",
    "causes",
    "source",
    "confidence",
    "voltage",
    "tone_commanded",
    "tone_actual",
    "tone_composite",
    "band_selected",
    "lo_frequency_khz",
    "polarization_delivered",
    "short_circuit_state",
    "ub_assignments",
    "sat_selected",
    "committed_switch_state",
    "uncommitted_switch_state",
    "port_selected",
    "power_pass",
)


class TestSameSourceFace:
    """The dump-source display order (the gen module renders verbatim)."""

    def test_rf_face_is_the_tuner_projection(self) -> None:
        assert registry.PHASE2_PAYLOAD_KEY_SETS["rf.state_observed"] == (
            RF_TUNER_FACE
        )

    def test_sec_face_is_the_maximal_union(self) -> None:
        assert registry.PHASE2_PAYLOAD_KEY_SETS["sec.state_observed"] == (
            SEC_MAXIMAL_FACE
        )


class TestValidatorKeySetFreeze:
    """The validator constants are the frozen per-shape exact key sets."""

    def test_rf_tuner_validator_keys(self) -> None:
        assert registry.RF_TUNER_SNAPSHOT_KEYS == frozenset(RF_TUNER_FACE)

    def test_sec_lnb_validator_keys(self) -> None:
        assert registry.SEC_LNB_SNAPSHOT_KEYS == frozenset(
            {
                "node_id",
                "health",
                "causes",
                "source",
                "confidence",
                "voltage",
                "tone_commanded",
                "tone_actual",
                "tone_composite",
                "band_selected",
                "lo_frequency_khz",
                "polarization_delivered",
                "short_circuit_state",
                "ub_assignments",
            }
        )

    def test_sec_switch_validator_keys(self) -> None:
        assert registry.SEC_SWITCH_SNAPSHOT_KEYS == frozenset(
            {
                "node_id",
                "health",
                "causes",
                "source",
                "confidence",
                "committed_switch_state",
                "uncommitted_switch_state",
                "port_selected",
                "power_pass",
            }
        )

    def test_maximal_sec_face_is_the_shape_union(self) -> None:
        assert set(SEC_MAXIMAL_FACE) == (
            registry.SEC_LNB_SNAPSHOT_KEYS
            | registry.SEC_SWITCH_SNAPSHOT_KEYS
            | registry.SEC_LNB_SAT_SELECTED_KEYS
        )

    def test_tuning_message_stays_out_of_the_phase3_face(self) -> None:
        # Ruling A16: ``tuning_message`` is not part of the Phase 3
        # payload registration (SPEC-303 is authoritative; the SPEC-623
        # §5 key gap is a declared deviation left to the repo audit).
        for face in (RF_TUNER_FACE, SEC_MAXIMAL_FACE):
            assert "tuning_message" not in face


class TestVocabularyDriftLock:
    """The restated vocabularies match the #161 evaluator vocab (A1)."""

    def test_metric_key_sets_match_the_evaluator_vocab(self) -> None:
        assert set(registry._RF_TUNER_METRIC_KEYS) == set(_vocab.TUNER_METRIC_KEYS)
        assert set(registry._SEC_LNB_METRIC_KEYS) == set(_vocab.LNB_METRIC_KEYS)
        assert registry._SEC_LNB_SAT_SELECTED_KEY == (
            _vocab.LNB_SAT_SELECTED_METRIC_KEY
        )
        assert set(registry._SEC_SWITCH_METRIC_KEYS) == set(
            _vocab.SWITCH_METRIC_KEYS
        )

    def test_state_vocabularies_match_the_evaluator_vocab(self) -> None:
        assert registry.STATE_OBSERVED_LOCK_STATES == set(_vocab.LOCK_STATES)
        assert registry.STATE_OBSERVED_BER_STATES == set(_vocab.BER_STATES)
        assert registry.STATE_OBSERVED_VOLTAGES == set(_vocab.VOLTAGES)
        assert registry.STATE_OBSERVED_TONES == set(_vocab.TONES)
        assert registry.STATE_OBSERVED_TONE_COMPOSITES == set(
            _vocab.TONE_COMPOSITES
        )
        assert registry.STATE_OBSERVED_BANDS == set(_vocab.BANDS)
        assert registry.STATE_OBSERVED_POLARIZATIONS_DELIVERED == set(
            _vocab.POLARIZATION_DELIVERED
        )
        assert registry.STATE_OBSERVED_SHORT_CIRCUIT_STATES == set(
            _vocab.SHORT_CIRCUIT_STATES
        )
        assert registry.STATE_OBSERVED_POWER_PASS == set(_vocab.POWER_PASS_VALUES)

    def test_health_vocabulary_matches_the_walk_health(self) -> None:
        from simulation.state.evaluate import Health

        assert registry.STATE_OBSERVED_HEALTHS == {
            health.value for health in Health
        }

    def test_sat_selected_vocabulary(self) -> None:
        # The legacy_cascade satellite labels (SPEC-621 §7 A/B).
        assert registry.STATE_OBSERVED_SAT_SELECTED == frozenset({"A", "B"})
