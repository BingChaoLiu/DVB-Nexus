"""SPEC-303 §Phase2 — the four encapsulation namespaces in the registry
(ticket #129).

The Phase 2 emitters were reserved by #122~#127 with frozen payload
shapes and wired by #128 behind the unregistered-type guard (ruling
§10-7); #129 lands the authoritative registry entries and the per-type
payload schemas verbatim. These tests pin:

- the four namespace constant sets (exact — the registry is the unique
  legal event type list, REQ-OBS-301-006);
- ``validate_payload`` dispatch per new namespace: strict key sets
  (missing keys refused, extra keys refused — the upstream REPORT key
  sets are the contract), value shapes per key semantics, and NO
  observation axes (the four namespaces are construction/evidence
  faces, not observations — brief §8 #129 card: 勿挂 source/confidence);
- zero regression on the withdrawn face (``observation.*`` stays
  refused) and the delivery-policy faces (coalescable stays
  ``run_progress``-only; delivery protection unchanged).

The happy-path payloads mirror the shapes the layered chain actually
emits (#128 REPORT §1.2 — the collectors in ``ts.t2mi.summary`` /
``ts.t2mi.bbframe_summary`` / ``ts.t2mi.plp`` / ``ts.biss.*`` /
``simulation.layered_pipeline``).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from domain.observation.registry import (
    BBFRAME_EVENT_TYPES,
    BISS_EVENT_TYPES,
    COALESCABLE_EVENT_TYPES,
    DELIVERY_PROTECTED_EVENT_TYPES,
    GEN_EVENT_TYPES,
    REGISTERED_EVENT_TYPES,
    T2MI_EVENT_TYPES,
    WITHDRAWN_EVENT_TYPES,
    is_coalescable,
    is_delivery_protected,
    is_registered,
    validate_payload,
)

T2MI_EVENTS = frozenset({"t2mi.stage_summary", "t2mi.plp_mismatch"})

BBFRAME_EVENTS = frozenset(
    {"bbframe.stage_summary", "bbframe.recovery_failed"}
)

BISS_EVENTS = frozenset(
    {"biss.scramble_applied", "biss.descramble_failed"}
)

GEN_EVENTS = frozenset(
    {
        "gen.stage_started",
        "gen.stage_completed",
        "gen.packet_sampled",
    }
)

#: One valid payload per event type — the #128 REPORT §1.2 frozen key
#: sets, populated with shape-conformant values (asserts shape, not the
#: environment's literal values; tests/README §6).
VALID_PAYLOADS: dict[str, dict] = {
    "t2mi.stage_summary": {
        "packet_count": 3,
        "padding_count": 0,
        "packet_type_distribution": {"bbframe": 3},
        "plp_distribution": {"7": 3},
    },
    "t2mi.plp_mismatch": {
        "expected_plp": 0,
        "actual_plp": None,
        "business_absent_evidence": {
            "plps_seen": [7],
            "bbframe_packet_count": 3,
            "filtered_packet_count": 0,
            "total_packet_count": 4,
        },
    },
    "bbframe.stage_summary": {
        "frame_count": 3,
        "n_ups_distribution": {"1": 2, "3": 1},
        "stuffing_ratio": 0.25,
    },
    "bbframe.recovery_failed": {
        "failure_count": 1,
        "first_failed_frame_index": 4,
    },
    "biss.scramble_applied": {
        "pid_scope": [256],
        "packet_count": 5,
        "key_fingerprint": "sha256:" + "b" * 16,
        "mutation_log_ref": "artifact-1",
        "mode": "1",
    },
    "biss.descramble_failed": {
        "pid_scope": [256],
        "failed_indices_sample": [0, 4],
        "self_check_kind": "tsc_state",
        "key_fingerprint_ref": "sha256:" + "c" * 16,
        "mode": "E",
    },
    "gen.stage_started": {"layer": "TS"},
    "gen.stage_completed": {"layer": "BBFRAME", "item_count": 12},
    "gen.packet_sampled": {
        "layer": "T2MI",
        "packet_index": 3,
        "byte_size": 213,
        "sha256": "a" * 64,
    },
    # Phase 3 state-observation minimal valid payloads (ticket #164): the
    # envelope-layer all-types test consumes this face — the strict per-
    # shape pins live in test_event_registry.py /
    # test_phase3_payload_key_sets.py.
    "rf.state_observed": {
        "node_id": "tuner-a",
        "health": "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "lock_state": "locked",
        "if_frequency_khz": 1_230_000,
        "ber_state": "normal",
        "locked_transponder_id": "tp-1",
        "stale": False,
    },
    "sec.state_observed": {
        "node_id": "lnb-0",
        "health": "ok",
        "causes": [],
        "source": "state_evaluator",
        "confidence": "simulated",
        "voltage": "13V",
        "tone_commanded": "none",
        "tone_actual": "none",
        "tone_composite": "none",
        "band_selected": "low",
        "lo_frequency_khz": 9_750_000,
        "polarization_delivered": "vertical",
        "short_circuit_state": "normal",
        "ub_assignments": [],
    },
}

PHASE2_EVENT_TYPES = (
    T2MI_EVENTS | BBFRAME_EVENTS | BISS_EVENTS | GEN_EVENTS
)


class TestPhase2NamespaceConstants:
    """The four namespace sets are additive registry entries."""

    def test_t2mi_namespace_exact(self):
        assert T2MI_EVENT_TYPES == T2MI_EVENTS

    def test_bbframe_namespace_exact(self):
        assert BBFRAME_EVENT_TYPES == BBFRAME_EVENTS

    def test_biss_namespace_exact(self):
        assert BISS_EVENT_TYPES == BISS_EVENTS

    def test_gen_namespace_exact(self):
        assert GEN_EVENT_TYPES == GEN_EVENTS

    def test_phase2_types_are_registered(self):
        for event_type in PHASE2_EVENT_TYPES:
            assert is_registered(event_type)

    def test_phase2_namespaces_subset_of_registry(self):
        assert PHASE2_EVENT_TYPES <= REGISTERED_EVENT_TYPES

    def test_namespaces_are_disjoint_from_the_existing_families(self):
        # Additive means additive: no pre-existing type moved namespace.
        established = REGISTERED_EVENT_TYPES - PHASE2_EVENT_TYPES
        assert established.isdisjoint(PHASE2_EVENT_TYPES)

    def test_new_namespaces_carry_no_delivery_policy_entries(self):
        # SPEC-303 §Phase2: all discrete event faces — the coalescable
        # face stays run_progress-only and delivery protection is
        # unchanged (brief §2bis: 四新命名空间默认不可 coalesce).
        assert is_coalescable("simulation.run_progress")
        for event_type in PHASE2_EVENT_TYPES:
            assert not is_coalescable(event_type)
            assert not is_delivery_protected(event_type)
        assert COALESCABLE_EVENT_TYPES == frozenset(
            {"simulation.run_progress"}
        )
        assert not any(
            event_type in DELIVERY_PROTECTED_EVENT_TYPES
            for event_type in PHASE2_EVENT_TYPES
        )


class TestPhase2PayloadHappyPaths:
    """Each registered type accepts its frozen shape."""

    @pytest.mark.parametrize(
        "event_type", sorted(PHASE2_EVENT_TYPES), ids=str
    )
    def test_valid_payload_accepted(self, event_type):
        validate_payload(event_type, VALID_PAYLOADS[event_type])

    def test_biss_mode_e_scramble_carries_the_derivation_face(self):
        # The Mode E fault-transform face (#127) adds the redacted
        # derivation-chain reference and the mismatch variants.
        payload = {
            "pid_scope": [256],
            "packet_count": 5,
            "key_fingerprint": "sha256:" + "b" * 16,
            "mutation_log_ref": "artifact-1",
            "mode": "E",
            "derivation_ref": {
                "esw_fingerprint": "sha256:" + "1" * 16,
                "injected_id_fingerprint": "sha256:" + "2" * 16,
                "session_word_fingerprint": "sha256:" + "3" * 16,
                "ciss_key_fingerprint": "sha256:" + "4" * 16,
            },
            "mismatch_variants": ["wrong_esw"],
        }
        validate_payload("biss.scramble_applied", payload)

    def test_biss_mutation_log_ref_may_be_honestly_none(self):
        # The upstream seams emit ``mutation_log_ref=None``; the runtime
        # binds the log artifact at delivery. Both faces are legal.
        payload = {
            **VALID_PAYLOADS["biss.scramble_applied"],
            "mutation_log_ref": None,
        }
        validate_payload("biss.scramble_applied", payload)

    def test_plp_mismatch_actual_plp_ambiguity_is_none(self):
        # Honest ambiguity: ≠1 observed PLP → actual_plp is None, the
        # full observation travels in the evidence object (#124).
        payload = {
            **VALID_PAYLOADS["t2mi.plp_mismatch"],
            "actual_plp": None,
        }
        validate_payload("t2mi.plp_mismatch", payload)
        payload["actual_plp"] = 7
        validate_payload("t2mi.plp_mismatch", payload)

    def test_recovery_failed_first_index_may_be_none(self):
        payload = {
            "failure_count": 0,
            "first_failed_frame_index": None,
        }
        validate_payload("bbframe.recovery_failed", payload)

    def test_empty_stage_distributions_are_legal(self):
        payload = {
            "packet_count": 0,
            "padding_count": 0,
            "packet_type_distribution": {},
            "plp_distribution": {},
        }
        validate_payload("t2mi.stage_summary", payload)
        payload = {
            "frame_count": 0,
            "n_ups_distribution": {},
            "stuffing_ratio": 0.0,
        }
        validate_payload("bbframe.stage_summary", payload)

    @pytest.mark.parametrize(
        "layer", ["TS", "BBFRAME", "T2MI", "BISS"], ids=str
    )
    def test_gen_layer_vocabulary(self, layer):
        for event_type, extra in (
            ("gen.stage_started", {}),
            ("gen.stage_completed", {"item_count": 1}),
            (
                "gen.packet_sampled",
                {"packet_index": 0, "byte_size": 188, "sha256": "a" * 64},
            ),
        ):
            validate_payload(event_type, {"layer": layer, **extra})


class TestPhase2PayloadRefusals:
    """Strict key sets + value shapes (the upstream REPORTs are the
    contract; missing and extra keys are both schema violations)."""

    @pytest.mark.parametrize(
        "event_type", sorted(PHASE2_EVENT_TYPES), ids=str
    )
    def test_empty_payload_refused(self, event_type):
        with pytest.raises(Exception):
            validate_payload(event_type, {})

    @pytest.mark.parametrize(
        "event_type", sorted(PHASE2_EVENT_TYPES), ids=str
    )
    def test_extra_key_refused(self, event_type):
        payload = {
            **VALID_PAYLOADS[event_type],
            "unexpected_key": "no such face",
        }
        with pytest.raises(Exception) as exc:
            validate_payload(event_type, payload)
        assert "unexpected_key" in str(exc.value)

    @pytest.mark.parametrize(
        "event_type", sorted(PHASE2_EVENT_TYPES), ids=str
    )
    def test_missing_key_refused(self, event_type):
        for key in VALID_PAYLOADS[event_type]:
            payload = {
                k: v for k, v in VALID_PAYLOADS[event_type].items() if k != key
            }
            with pytest.raises(Exception):
                validate_payload(event_type, payload)

    def test_gen_layer_outside_vocabulary_refused(self):
        with pytest.raises(Exception):
            validate_payload("gen.stage_started", {"layer": "MPEG_TS"})
        with pytest.raises(Exception):
            validate_payload("gen.stage_started", {"layer": "bbframe"})

    def test_gen_sampled_sha256_must_be_a_digest_shape(self):
        payload = {
            **VALID_PAYLOADS["gen.packet_sampled"],
            "sha256": "not-a-digest",
        }
        with pytest.raises(Exception):
            validate_payload("gen.packet_sampled", payload)

    def test_gen_negative_counts_refused(self):
        with pytest.raises(Exception):
            validate_payload(
                "gen.stage_completed",
                {"layer": "TS", "item_count": -1},
            )
        with pytest.raises(Exception):
            validate_payload(
                "gen.packet_sampled",
                {
                    "layer": "TS",
                    "packet_index": -1,
                    "byte_size": 188,
                    "sha256": "a" * 64,
                },
            )

    def test_t2mi_stage_summary_distribution_key_vocabulary(self):
        payload = {
            **VALID_PAYLOADS["t2mi.stage_summary"],
            "packet_type_distribution": {"mystery": 1},
        }
        with pytest.raises(Exception):
            validate_payload("t2mi.stage_summary", payload)

    def test_t2mi_stage_summary_distribution_values_must_be_ints(self):
        payload = {
            **VALID_PAYLOADS["t2mi.stage_summary"],
            "plp_distribution": {"7": "three"},
        }
        with pytest.raises(Exception):
            validate_payload("t2mi.stage_summary", payload)

    def test_t2mi_plp_mismatch_expected_plp_out_of_range(self):
        payload = {
            **VALID_PAYLOADS["t2mi.plp_mismatch"],
            "expected_plp": 256,
        }
        with pytest.raises(Exception):
            validate_payload("t2mi.plp_mismatch", payload)

    def test_t2mi_plp_mismatch_evidence_key_set_is_strict(self):
        payload = {
            **VALID_PAYLOADS["t2mi.plp_mismatch"],
            "business_absent_evidence": {
                "plps_seen": [7],
                "bbframe_packet_count": 3,
                "filtered_packet_count": 0,
                # total_packet_count missing, an extra key instead:
                "unexpected": 4,
            },
        }
        with pytest.raises(Exception):
            validate_payload("t2mi.plp_mismatch", payload)

    def test_bbframe_stuffing_ratio_must_be_a_ratio(self):
        payload = {
            **VALID_PAYLOADS["bbframe.stage_summary"],
            "stuffing_ratio": 1.5,
        }
        with pytest.raises(Exception):
            validate_payload("bbframe.stage_summary", payload)
        payload = {
            **VALID_PAYLOADS["bbframe.stage_summary"],
            "stuffing_ratio": "a quarter",
        }
        with pytest.raises(Exception):
            validate_payload("bbframe.stage_summary", payload)

    def test_biss_mode_outside_vocabulary_refused(self):
        payload = {**VALID_PAYLOADS["biss.scramble_applied"], "mode": "3"}
        with pytest.raises(Exception):
            validate_payload("biss.scramble_applied", payload)
        payload = {
            **VALID_PAYLOADS["biss.descramble_failed"],
            "mode": "mode-e",
        }
        with pytest.raises(Exception):
            validate_payload("biss.descramble_failed", payload)

    def test_biss_scramble_mode1_face_rejects_derivation_keys(self):
        # derivation_ref / mismatch_variants are the Mode E face's
        # derivation-chain keys (#127); the Mode 1 face has no chain.
        payload = {
            **VALID_PAYLOADS["biss.scramble_applied"],
            "derivation_ref": {"esw_fingerprint": "sha256:" + "1" * 16},
        }
        with pytest.raises(Exception):
            validate_payload("biss.scramble_applied", payload)

    def test_biss_scramble_mode_e_construction_face_is_bare_five_keys(self):
        # The derived-key construction path (``cissa_scramble``, #127
        # composition) emits mode "E" WITHOUT the derivation face — the
        # mismatch lives on the fault transform only.
        payload = {
            "pid_scope": [256],
            "packet_count": 5,
            "key_fingerprint": "sha256:" + "b" * 16,
            "mutation_log_ref": None,
            "mode": "E",
        }
        validate_payload("biss.scramble_applied", payload)

    def test_biss_scramble_half_derivation_face_refused(self):
        # The fault face carries derivation_ref AND mismatch_variants
        # together; either alone is a shape violation.
        base = {
            "pid_scope": [256],
            "packet_count": 5,
            "key_fingerprint": "sha256:" + "b" * 16,
            "mutation_log_ref": None,
            "mode": "E",
        }
        with pytest.raises(Exception):
            validate_payload(
                "biss.scramble_applied",
                {
                    **base,
                    "derivation_ref": {"esw_fingerprint": "sha256:" + "1" * 16},
                },
            )
        with pytest.raises(Exception):
            validate_payload(
                "biss.scramble_applied",
                {**base, "mismatch_variants": ["wrong_esw"]},
            )

    def test_biss_pid_scope_shape(self):
        for bad in ([], [8192], ["256"], [True]):
            payload = {
                **VALID_PAYLOADS["biss.scramble_applied"],
                "pid_scope": bad,
            }
            with pytest.raises(Exception):
                validate_payload("biss.scramble_applied", payload)

    def test_biss_failed_indices_sample_is_bounded(self):
        payload = {
            **VALID_PAYLOADS["biss.descramble_failed"],
            "failed_indices_sample": list(range(17)),
        }
        with pytest.raises(Exception):
            validate_payload("biss.descramble_failed", payload)
        payload = {
            **VALID_PAYLOADS["biss.descramble_failed"],
            "failed_indices_sample": list(range(16)),
        }
        validate_payload("biss.descramble_failed", payload)

    def test_biss_fingerprint_fields_must_be_non_empty_strings(self):
        payload = {
            **VALID_PAYLOADS["biss.scramble_applied"],
            "key_fingerprint": "",
        }
        with pytest.raises(Exception):
            validate_payload("biss.scramble_applied", payload)
        payload = {
            **VALID_PAYLOADS["biss.descramble_failed"],
            "key_fingerprint_ref": None,
        }
        with pytest.raises(Exception):
            validate_payload("biss.descramble_failed", payload)

    def test_phase2_payloads_demand_no_observation_axes(self):
        # The four namespaces are NOT observation faces — the
        # source/confidence axes (SPEC-003 §2.4) must not be demanded
        # (and their absence must not fail): happy paths above already
        # omit them, this pin names the discipline.
        for event_type in PHASE2_EVENT_TYPES:
            assert "source" not in VALID_PAYLOADS[event_type]
            assert "confidence" not in VALID_PAYLOADS[event_type]


class TestWithdrawnAndEstablishedFacesUntouched:
    """Registry additive zero-regression (票面 AC)."""

    def test_observation_namespace_still_refused(self):
        assert is_registered("observation.alert_raised") is False

    def test_withdrawn_set_unchanged(self):
        assert WITHDRAWN_EVENT_TYPES == frozenset(
            {
                "snapshot.updated",
                "lifecycle.changed",
                "verification.completed",
            }
        )

    def test_established_types_still_registered(self):
        for event_type in (
            "simulation.run_started",
            "fault.injected",
            "recovery.verification_completed",
            "diagnosis.raised",
            "ts.continuity_error",
        ):
            assert is_registered(event_type)
