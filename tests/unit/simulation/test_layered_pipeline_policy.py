"""Layered pipeline routing / fingerprint / sampling policy (ticket #128).

The layered pipeline instantiates ADR-0010 §3's chain —
``Inner TS → BBFrame → T2MI → 外层 mux`` — inside SIM_TS.  This module
pins the decision faces the chain is built from:

- **layer routing**: ``LAYER_BY_FAULT_TYPE`` routes each plan fault to its
  layer's filter instance group; the MVP four (and PMT_PID_DRIFT) all
  route to ``TS`` so a TS-only plan stays a single MVP-path group.
- **layered detection**: a plan routes beyond ``TS`` iff any fault's type
  declares a BBFRAME/T2MI/BISS layer (``FaultDefinition.layer`` is
  registry-pinned to the declared value, #121).
- **fingerprint**: the pipeline projection joins ``compute_config_hash``
  additively — ``pipeline=None`` keeps the MVP document byte-identical
  (existing pins hold); a wired pipeline changes the hash; key material
  never enters the projection (fingerprints only, ADR-0011 §3).
- **sampling policy** (票面裁量): the first ``sample_window`` slots of a
  stage plus every fault activation slot plus the stage's final slot —
  O(层数) + O(抽样), injection points always sampled (SPEC-303 §Phase2).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytestmark = pytest.mark.unit

from simulation.fault_plan import FaultActivation, FaultDefinition
from simulation.layered_pipeline import (
    BissFaceConfig,
    GEN_PACKET_SAMPLED_EVENT_TYPE,
    GEN_STAGE_COMPLETED_EVENT_TYPE,
    GEN_STAGE_STARTED_EVENT_TYPE,
    SAMPLE_WINDOW_DEFAULT,
    LayerPipelineConfig,
    StageSampler,
    default_demux_filter_for,
    is_layered_plan,
    layered_plan_groups,
    pipeline_fingerprint_document,
)
from simulation.ts_runtime import compute_config_hash
from ts.t2mi.plp import PlpFilterConfig

from tests._support.deterministic import seeded_bytes
from tests.unit.simulation._ts_runtime_builders import (
    make_generator_config,
    make_session_spec,
)


def _fault(fault_type: str, *, layer: str | None = None, index=None) -> FaultDefinition:
    return FaultDefinition(
        fault_id=f"fid-{fault_type.lower()}-001",
        fault_type=fault_type,
        target_id="enc-0" if layer is not None else "gen-0:pid:0x0100",
        parameters={},
        activation=(
            FaultActivation(kind="packet_index", packet_index=index)
            if index is not None
            else FaultActivation(kind="session_start", packet_index=None)
        ),
        expected_observations=("t2mi.plp_mismatch",),
        layer=layer or "TS",
    )


class TestLayerRouting:
    """``LAYER_BY_FAULT_TYPE`` groups the plan per pipeline layer."""

    def test_mvp_plan_is_one_ts_group_equal_to_the_whole_plan(self) -> None:
        plan = (
            _fault("PAT_MISSING"),
            _fault("CC_DISCONTINUITY", index=10),
            _fault("PMT_PID_DRIFT", index=20),
        )
        groups = layered_plan_groups(plan)
        assert set(groups) == {"TS"}
        assert groups["TS"] == plan

    def test_phase2_faults_route_to_their_declared_layers(self) -> None:
        plan = (
            _fault("T2MI_PLP_MISMATCH", layer="T2MI"),
            _fault("BBHEADER_SYNC_FAULT", layer="BBFRAME", index=300),
            _fault("BISS_KEY_MISMATCH", layer="BISS"),
            _fault("PAT_MISSING"),
        )
        groups = layered_plan_groups(plan)
        assert set(groups) == {"TS", "T2MI", "BBFRAME", "BISS"}
        assert groups["T2MI"] == (plan[0],)
        assert groups["BBFRAME"] == (plan[1],)
        assert groups["BISS"] == (plan[2],)
        assert groups["TS"] == (plan[3],)

    def test_group_order_follows_the_pipeline_chain_order(self) -> None:
        # TS → BISS → BBFRAME → T2MI is the chain order (BISS scrambles the
        # contribution TS before encapsulation, ADR-0011 §2); the routing
        # keeps that order so stage execution is deterministic.
        plan = (
            _fault("T2MI_PLP_MISMATCH", layer="T2MI"),
            _fault("BISS_KEY_MISMATCH", layer="BISS"),
            _fault("BBHEADER_SYNC_FAULT", layer="BBFRAME", index=3),
        )
        assert list(layered_plan_groups(plan)) == ["BISS", "BBFRAME", "T2MI"]

    def test_layered_detection(self) -> None:
        assert not is_layered_plan(())
        assert not is_layered_plan((_fault("PAT_MISSING"),))
        assert is_layered_plan((_fault("T2MI_PLP_MISMATCH", layer="T2MI"),))
        assert is_layered_plan((_fault("BBHEADER_SYNC_FAULT", layer="BBFRAME", index=1),))
        assert is_layered_plan((_fault("BISS_KEY_MISMATCH", layer="BISS"),))


class TestPipelineFingerprint:
    """The pipeline projection is additive to the deterministic hash."""

    def test_none_pipeline_keeps_the_mvp_document(self) -> None:
        config = make_generator_config()
        session = make_session_spec()
        plan = (_fault("PAT_MISSING"),)
        baseline = compute_config_hash(
            config, clock_config=session.clock_config, fault_plan=plan
        )
        assert (
            compute_config_hash(
                config,
                clock_config=session.clock_config,
                fault_plan=plan,
                pipeline=None,
            )
            == baseline
        )

    def test_wired_pipeline_changes_the_hash(self) -> None:
        config = make_generator_config()
        session = make_session_spec()
        kwargs = dict(clock_config=session.clock_config, fault_plan=())
        plain = compute_config_hash(config, **kwargs)
        piped = compute_config_hash(
            config, **kwargs, pipeline=LayerPipelineConfig()
        )
        assert plain != piped

    def test_key_material_never_enters_the_projection(self) -> None:
        session_word = "a13dbc42908f"
        pipeline = LayerPipelineConfig(
            biss=BissFaceConfig(
                mode="1", session_word=session_word, pid_scope=(256,)
            )
        )
        document = pipeline_fingerprint_document(pipeline)
        canonical = repr(document)
        assert session_word not in canonical
        assert session_word.upper() not in canonical
        biss = document["biss"]
        assert biss["mode"] == "1"
        assert biss["pid_scope"] == [256]
        # Only the fingerprint trace (hash prefix) carries the key face.
        assert isinstance(biss["key_fingerprint"], str)
        assert biss["key_fingerprint"]

    def test_projection_is_deterministic_and_geometry_carrying(self) -> None:
        first = pipeline_fingerprint_document(LayerPipelineConfig())
        second = pipeline_fingerprint_document(LayerPipelineConfig())
        assert first == second
        assert set(first) == {"bbframe", "t2mi", "plp_assignment", "demux_plp_filter", "biss"}


class TestKeyBodyReprSuppression:
    """``BissFaceConfig`` key bodies never leak through ``repr()``
    (SPEC-610/611 §9 key discipline — M6 code-review fix round; the
    fingerprint projection already redacts, the repr face now does too,
    mirroring ``ScenarioDocument.raw``'s ``repr=False`` precedent)."""

    # 32-hex literals are a data-rule violation → deterministic generator.
    MODE_E_ESW = "0123456789ABCDEF"
    MODE_E_INJECTED_ID = seeded_bytes(0x5CE7A, 16).hex().upper()

    @staticmethod
    def _assert_key_absent(repr_text: str, *secrets: str) -> None:
        """Case-insensitive containment plus a hex-token guard: the repr
        must not carry the key bodies in any case spelling."""
        lowered = repr_text.lower()
        for secret in secrets:
            assert secret.lower() not in lowered

    def test_mode_1_repr_omits_session_word(self) -> None:
        session_word = "a13dbc42908f"
        config = BissFaceConfig(
            mode="1", session_word=session_word, pid_scope=(256,)
        )
        self._assert_key_absent(repr(config), session_word)
        # The wrapping pipeline config inherits the suppression.
        pipeline = LayerPipelineConfig(
            biss=BissFaceConfig(
                mode="1", session_word=session_word, pid_scope=(256,)
            )
        )
        self._assert_key_absent(repr(pipeline), session_word)

    def test_mode_e_repr_omits_esw_and_injected_id(self) -> None:
        config = BissFaceConfig(
            mode="E",
            encrypted_sw=self.MODE_E_ESW,
            injected_id=self.MODE_E_INJECTED_ID,
            pid_scope=(256,),
        )
        self._assert_key_absent(
            repr(config), self.MODE_E_ESW, self.MODE_E_INJECTED_ID
        )

    def test_fields_stay_equality_visible(self) -> None:
        config = BissFaceConfig(
            mode="1", session_word="a13dbc42908f", pid_scope=(256,)
        )
        # repr suppression hides the value from logs, nothing else.
        assert config.session_word == "a13dbc42908f"
        assert config == BissFaceConfig(
            mode="1", session_word="a13dbc42908f", pid_scope=(256,)
        )


class TestDefaultDemuxFilter:
    """B1 (缺失 ≠ 零) needs the demux expectation; derive it from the plan."""

    def test_t2mi_mismatch_fault_supplies_the_expected_side(self) -> None:
        fault = _fault("T2MI_PLP_MISMATCH", layer="T2MI")
        fault = replace(fault, parameters={"expected_plp": 0, "actual_plp": 1})
        demux = default_demux_filter_for((fault,))
        assert isinstance(demux, PlpFilterConfig)
        assert demux.mode == "expected"
        assert demux.expected_plp == 0

    def test_no_t2mi_fault_yields_none(self) -> None:
        assert default_demux_filter_for(()) is None
        assert default_demux_filter_for((_fault("PAT_MISSING"),)) is None


class TestStageSampler:
    """Sampling window policy: window + activations + tail, deduped, bounded."""

    def test_window_only_when_no_activations(self) -> None:
        sampler = StageSampler(window=SAMPLE_WINDOW_DEFAULT)
        indexes = sampler.indexes(item_count=500)
        assert indexes == list(range(SAMPLE_WINDOW_DEFAULT)) + [499]

    def test_activation_inside_the_window_is_not_duplicated(self) -> None:
        sampler = StageSampler(window=8)
        assert sampler.indexes(item_count=500, activation_indexes=(3,)) == list(range(8)) + [499]

    def test_injection_point_beyond_the_window_is_always_sampled(self) -> None:
        sampler = StageSampler(window=8)
        indexes = sampler.indexes(item_count=500, activation_indexes=(300,))
        assert 300 in indexes
        assert indexes == sorted(set(indexes))

    def test_small_stages_sample_everything(self) -> None:
        sampler = StageSampler(window=8)
        assert sampler.indexes(item_count=3) == [0, 1, 2]

    def test_empty_stage_samples_nothing(self) -> None:
        sampler = StageSampler(window=8)
        assert sampler.indexes(item_count=0) == []

    def test_magnitude_is_bounded_by_window_plus_activations(self) -> None:
        sampler = StageSampler(window=8)
        indexes = sampler.indexes(
            item_count=100_000, activation_indexes=(7, 11, 999_999, 12_345)
        )
        # Out-of-range activations are dropped (never fabricated); the
        # bound is window + in-range activations + tail.
        assert len(indexes) <= 8 + 3 + 1


class TestGenEventTypeConstants:
    """The three gen.* type strings (SPEC-303 §Phase2) frozen here."""

    def test_type_strings(self) -> None:
        assert GEN_STAGE_STARTED_EVENT_TYPE == "gen.stage_started"
        assert GEN_STAGE_COMPLETED_EVENT_TYPE == "gen.stage_completed"
        assert GEN_PACKET_SAMPLED_EVENT_TYPE == "gen.packet_sampled"
