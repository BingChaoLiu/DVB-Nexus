"""SPEC-204 Phase 2 revision — ``FaultDefinition.layer`` additive field.

Phase 2 (ticket #121 / SPEC-204 §Phase2 / ADR-0010 §3) adds the pipeline
``layer`` attribute ∈ {TS, BBFRAME, T2MI, BISS} with default ``"TS"`` so
every MVP plan serializes exactly as before (additive compatibility,
SPEC-301 §8: adding an optional field = minor).

Two compatibility guarantees are pinned here:

1. shape — ``layer`` defaults to ``"TS"`` and accepts the four Phase 2
   layer tokens;
2. fingerprint — the prepare fingerprint (``compute_config_hash`` /
   ``_canonical_plan``) is untouched by the new field: plans serialized
   before Phase 2 hash identically after the field lands (ADR-0007 item
   contract continuity: prepare 绑定指纹, MVP 契约全部延续).
"""

from __future__ import annotations

import dataclasses

import pytest

from faults.definition import FaultActivation, FaultDefinition
from ts.generator.config import GeneratorConfig, ProgramConfig

pytestmark = pytest.mark.unit

#: The Phase 2 pipeline layer set (SPEC-204 §Phase2 / ADR-0010 §3).
PHASE2_LAYERS = ("TS", "BBFRAME", "T2MI", "BISS")


def _generator_config() -> GeneratorConfig:
    return GeneratorConfig(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=7,
        initial_media_clock_27mhz=27_000_000,
        target_bitrate_bps=3_008_000,
        output_packet_count=600,
        program=ProgramConfig(
            transport_stream_id=1,
            program_number=1,
            pmt_pid=0x1000,
            pcr_pid=0x0100,
            version_number=0,
            streams=(),
        ),
    )


def _fault(layer: str | None) -> FaultDefinition:
    kwargs: dict = {
        "fault_id": "f-1",
        "fault_type": "PAT_MISSING",
        "target_id": "demux-0:pid:0x0000",
        "expected_observations": ("ts.psi_section_observed",),
    }
    if layer is not None:
        kwargs["layer"] = layer
    return FaultDefinition(**kwargs)


class TestLayerShape:
    def test_layer_field_exists_with_ts_default(self) -> None:
        assert _fault(None).layer == "TS"

    def test_layer_accepts_every_phase2_layer_token(self) -> None:
        for layer in PHASE2_LAYERS:
            assert _fault(layer).layer == layer

    def test_layer_is_the_last_frozen_dataclass_field(self) -> None:
        names = [field.name for field in dataclasses.fields(FaultDefinition)]
        assert names[-1] == "layer"
        assert dataclasses.fields(FaultDefinition)[-1].default == "TS"

    def test_definition_stays_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            _fault(None).layer = "T2MI"  # type: ignore[misc]

    def test_activation_default_untouched(self) -> None:
        assert _fault(None).activation == FaultActivation(
            kind="session_start", packet_index=None
        )


class TestLayerFingerprintCompatibility:
    """ADR-0007 contract continuity: the plan fingerprint must not move."""

    def test_canonical_plan_document_ignores_layer(self) -> None:
        from simulation.ts_runtime import _canonical_plan

        legacy = _fault(None)
        explicit = _fault("TS")
        document = _canonical_plan((explicit,))
        assert document == [
            {
                "fault_type": "PAT_MISSING",
                "target_id": "demux-0:pid:0x0000",
                "parameters": {},
                "activation": {
                    "kind": "session_start",
                    "packet_index": None,
                },
                "expected_observations": ["ts.psi_section_observed"],
            }
        ]
        # Legacy-shaped construction (no layer kwarg) produces the same
        # document — the field never enters the canonical projection.
        assert _canonical_plan((legacy,)) == document

    def test_config_hash_stable_across_layer_field_addition(self) -> None:
        from simulation.clock import SimulationClockConfig
        from simulation.runtime import SimulationSessionSpec
        from simulation.state import TopologyGraph
        from simulation.ts_runtime import compute_config_hash

        session = SimulationSessionSpec(
            session_id="s",
            topology=TopologyGraph(
                topology_id="t", revision=1, nodes=(), connections=()
            ),
            seed=7,
            deterministic=True,
            clock_config=SimulationClockConfig(mode="deterministic"),
        )
        legacy_hash = compute_config_hash(
            _generator_config(),
            clock_config=session.clock_config,
            fault_plan=(_fault(None),),
        )
        explicit_ts_hash = compute_config_hash(
            _generator_config(),
            clock_config=session.clock_config,
            fault_plan=(_fault("TS"),),
        )
        assert legacy_hash == explicit_ts_hash
