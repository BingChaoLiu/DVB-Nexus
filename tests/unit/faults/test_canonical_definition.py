"""Canonical SPEC-204 §3 fault models (#44) — shape and substitution tests.

The canonical ``FaultDefinition`` / ``FaultActivation`` live in the
``faults`` package (ADR-0005 D4-4: faults → ts).  SIM-D (#43) had declared
a structural seam in ``simulation.fault_plan`` with identical field sets;
#44 performs the canonicalization, so the seam now re-exports the canonical
classes and #43 consumers keep working unchanged (same duck surface).
"""

from __future__ import annotations

import dataclasses

import pytest

from faults.definition import FaultActivation, FaultDefinition
from simulation import fault_plan
from ts.generator.config import GeneratorConfig, ProgramConfig

pytestmark = pytest.mark.unit


class TestCanonicalShape:
    """SPEC-204 §3 data model: frozen, exact field set, MVP defaults."""

    def test_frozen_dataclasses(self) -> None:
        assert dataclasses.is_dataclass(FaultDefinition)
        assert dataclasses.is_dataclass(FaultActivation)
        with pytest.raises(dataclasses.FrozenInstanceError):
            FaultActivation(kind="session_start").kind = "packet_index"  # type: ignore[misc]
        definition = FaultDefinition(
            fault_id="f-1",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.psi_section_observed",),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            definition.fault_type = "CC_DISCONTINUITY"  # type: ignore[misc]

    def test_exact_field_set_per_spec_section_3(self) -> None:
        definition_fields = {
            field.name for field in dataclasses.fields(FaultDefinition)
        }
        assert definition_fields == {
            "fault_id",
            "fault_type",
            "target_id",
            "parameters",
            "activation",
            "expected_observations",
        }
        activation_fields = {
            field.name for field in dataclasses.fields(FaultActivation)
        }
        assert activation_fields == {"kind", "packet_index"}

    def test_mvp_defaults(self) -> None:
        activation = FaultActivation(kind="session_start")
        assert activation.packet_index is None
        definition = FaultDefinition(
            fault_id="f-1",
            fault_type="PAT_MISSING",
            target_id="demux-0:pid:0x0000",
            expected_observations=("ts.psi_section_observed",),
        )
        assert dict(definition.parameters) == {}
        assert definition.activation == FaultActivation(
            kind="session_start", packet_index=None
        )
        assert definition.expected_observations == (
            "ts.psi_section_observed",
        )


class TestSeamSubstitution:
    """The #43 seam re-exports the canonical classes (structural swap)."""

    def test_simulation_fault_plan_reexports_canonical_classes(self) -> None:
        assert fault_plan.FaultDefinition is FaultDefinition
        assert fault_plan.FaultActivation is FaultActivation

    def test_canonical_classes_satisfy_the_43_fingerprint(self) -> None:
        """#43's prepare fingerprint consumes the canonical shape as-is
        (fault_id excluded, key-sorted canonical serialization)."""
        from simulation.ts_runtime import _canonical_plan

        definition = FaultDefinition(
            fault_id="opaque-uuid-does-not-enter",
            fault_type="CC_DISCONTINUITY",
            target_id="demux-0:pid:0x0100",
            parameters={"delta": 3},
            activation=FaultActivation(kind="packet_index", packet_index=30),
            expected_observations=("ts.continuity_error",),
        )
        document = _canonical_plan((definition,))
        assert document == [
            {
                "fault_type": "CC_DISCONTINUITY",
                "target_id": "demux-0:pid:0x0100",
                "parameters": {"delta": 3},
                "activation": {"kind": "packet_index", "packet_index": 30},
                "expected_observations": ["ts.continuity_error"],
            }
        ]

    def test_fingerprint_ignores_fault_id_identity(self) -> None:
        from simulation.ts_runtime import compute_config_hash

        config = GeneratorConfig(
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
        from simulation.clock import SimulationClockConfig

        def make(fault_id: str) -> FaultDefinition:
            return FaultDefinition(
                fault_id=fault_id,
                fault_type="PAT_MISSING",
                target_id="demux-0:pid:0x0000",
                expected_observations=("ts.psi_section_observed",),
            )

        from simulation.runtime import SimulationSessionSpec
        from simulation.state import TopologyGraph

        session = SimulationSessionSpec(
            session_id="s",
            topology=TopologyGraph(
                topology_id="t", revision=1, nodes=(), connections=()
            ),
            seed=7,
            deterministic=True,
            clock_config=SimulationClockConfig(mode="deterministic"),
        )
        prepared_a = compute_config_hash(
            config,
            clock_config=session.clock_config,
            fault_plan=(make("uuid-a"),),
        )
        prepared_b = compute_config_hash(
            config,
            clock_config=session.clock_config,
            fault_plan=(make("uuid-b"),),
        )
        assert prepared_a == prepared_b
