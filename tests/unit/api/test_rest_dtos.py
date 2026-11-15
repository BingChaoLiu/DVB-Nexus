"""REST DTO contracts, unit layer (SPEC-500 §5/§7, ticket #48).

SPEC-108 §4 mapping-table cross-checks (JSON ↔ the frozen
``ts.generator.config`` shapes) and Pydantic DTO JSON round-trips for the
ticket #48 route DTOs. Pure models only — no I/O, no wall clock (unit
layer discipline, SPEC-505 §3/§8).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.dto.artifacts import ArtifactMetaDTO
from api.dto.faults import FaultActivationDTO, FaultDefinitionDTO
from api.dto.generator import GeneratorConfigDTO
from api.dto.runs import (
    RunAcceptedDTO,
    RunArtifactDTO,
    RunStatusDTO,
    RunSubmitRequest,
)
from api.dto.sessions import (
    ClockConfigDTO,
    CreateSessionRequest,
    SessionValidationDTO,
    SessionViewDTO,
    SnapshotDTO,
)
from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)
from tests.unit.simulation._ts_runtime_builders import make_generator_config

pytestmark = pytest.mark.unit


def _roundtrip(model, payload: dict):
    """SPEC-500 §7 discipline: payload → model → JSON boundary → model."""
    instance = model.model_validate(payload)
    through_json = instance.model_dump(mode="json")
    reloaded = model.model_validate(through_json)
    assert reloaded == instance
    return instance


class TestGeneratorConfigDTOAlignsWithSpec108Section4:
    """Every SPEC-108 §4 mapping-table row has its DTO counterpart."""

    def test_wire_payload_roundtrips_and_matches_domain_field_set(self):
        config = make_generator_config()
        wire = {
            "schema_version": config.schema_version,
            "profile": config.profile,
            "deterministic": config.deterministic,
            "seed": config.seed,
            "initial_media_clock_27mhz": config.initial_media_clock_27mhz,
            "target_bitrate_bps": config.target_bitrate_bps,
            "output_packet_count": config.output_packet_count,
            "program": {
                "transport_stream_id": config.program.transport_stream_id,
                "program_number": config.program.program_number,
                "pmt_pid": config.program.pmt_pid,
                "pcr_pid": config.program.pcr_pid,
                "version_number": config.program.version_number,
                "streams": [
                    {
                        "pid": stream.pid,
                        "stream_type": stream.stream_type,
                        "stream_id": stream.stream_id,
                        "bitrate_bps": stream.bitrate_bps,
                        "payload_profile": stream.payload_profile,
                        "payload_seed_offset": stream.payload_seed_offset,
                    }
                    for stream in config.program.streams
                ],
                "program_descriptors": config.program.program_descriptors.hex(),
            },
            "pat_period_ms": config.pat_period_ms,
            "pmt_period_ms": config.pmt_period_ms,
            "pcr_interval_ms": config.pcr_interval_ms,
            "pcr_insertion_policy": config.pcr_insertion_policy,
        }
        dto = _roundtrip(GeneratorConfigDTO, wire)
        assert dto.model_dump() == wire  # lossless §4 mapping

    def test_defaults_match_the_ruling_72_out_of_phase_periods(self):
        dto = GeneratorConfigDTO(
            schema_version=1,
            seed=1,
            initial_media_clock_27mhz=0,
            target_bitrate_bps=1,
            output_packet_count=1,
            program={
                "transport_stream_id": 1,
                "program_number": 1,
                "pmt_pid": 0x1000,
                "pcr_pid": 0x100,
                "version_number": 0,
                "streams": [],
            },
        )
        domain_defaults = GeneratorConfig(
            schema_version=1,
            profile="analysis_only",
            deterministic=True,
            seed=1,
            initial_media_clock_27mhz=0,
            target_bitrate_bps=1,
            output_packet_count=1,
            program=ProgramConfig(
                transport_stream_id=1,
                program_number=1,
                pmt_pid=0x1000,
                pcr_pid=0x100,
                version_number=0,
                streams=(),
            ),
        )
        # JSON default and code default can never drift (SPEC-500 §5).
        assert (dto.pat_period_ms, dto.pmt_period_ms, dto.pcr_interval_ms) == (
            domain_defaults.pat_period_ms,
            domain_defaults.pmt_period_ms,
            domain_defaults.pcr_interval_ms,
        )
        assert dto.pcr_insertion_policy == domain_defaults.pcr_insertion_policy
        assert dto.profile == domain_defaults.profile
        assert dto.deterministic is True

    def test_bytes_field_is_hex_encoded(self):
        # SPEC-500 §5: bytes → hex on the wire.
        payload = {
            "schema_version": 1,
            "seed": 1,
            "initial_media_clock_27mhz": 0,
            "target_bitrate_bps": 1,
            "output_packet_count": 1,
            "program": {
                "transport_stream_id": 1,
                "program_number": 1,
                "pmt_pid": 0x1000,
                "pcr_pid": 0x100,
                "version_number": 0,
                "streams": [],
                "program_descriptors": "deadbeef",
            },
        }
        dto = GeneratorConfigDTO.model_validate(payload)
        assert bytes.fromhex(dto.program.program_descriptors) == b"\xde\xad\xbe\xef"

    def test_unknown_fields_are_schema_violations(self):
        payload = {"schema_version": 1, "seed": 1, "unexpected": True}
        with pytest.raises(ValidationError):
            GeneratorConfigDTO.model_validate(
                {
                    "schema_version": 1,
                    "seed": 1,
                    "initial_media_clock_27mhz": 0,
                    "target_bitrate_bps": 1,
                    "output_packet_count": 1,
                    "program": {
                        "transport_stream_id": 1,
                        "program_number": 1,
                        "pmt_pid": 1,
                        "pcr_pid": 1,
                        "version_number": 0,
                        "streams": [],
                    },
                    **{"unexpected": True},
                }
            )


class TestFaultPlanDTOAlignsWithSpec204Section3:
    def test_fault_definition_roundtrips(self):
        payload = {
            "fault_id": "fault-1",
            "fault_type": "CC_DISCONTINUITY",
            "target_id": "demux-0:pid:0x0100",
            "parameters": {"delta": 3},
            "activation": {"kind": "packet_index", "packet_index": 10},
            "expected_observations": ["ts.continuity_error"],
        }
        dto = _roundtrip(FaultDefinitionDTO, payload)
        assert dto.activation.kind == "packet_index"
        assert dto.activation.packet_index == 10

    def test_activation_defaults_to_session_start(self):
        dto = FaultActivationDTO()
        assert dto.kind == "session_start"
        assert dto.packet_index is None

    def test_activation_kind_is_enum_pinned(self):
        with pytest.raises(ValidationError):
            FaultActivationDTO.model_validate({"kind": "wall_clock"})


class TestRunDTOs:
    def test_run_submit_request_roundtrips(self):
        payload = {
            "config": {
                "schema_version": 1,
                "seed": 1,
                "initial_media_clock_27mhz": 0,
                "target_bitrate_bps": 1,
                "output_packet_count": 1,
                "program": {
                    "transport_stream_id": 1,
                    "program_number": 1,
                    "pmt_pid": 1,
                    "pcr_pid": 1,
                    "version_number": 0,
                    "streams": [],
                },
            },
            "fault_plan": [
                {
                    "fault_type": "PAT_MISSING",
                    "target_id": "demux-0",
                    "expected_observations": ["ts.pat_missing"],
                }
            ],
        }
        dto = _roundtrip(RunSubmitRequest, payload)
        assert dto.fault_plan[0].fault_type == "PAT_MISSING"

    def test_empty_fault_plan_is_the_default(self):
        request = RunSubmitRequest.model_validate(
            {"config": _minimal_config_payload()}
        )
        assert request.fault_plan == []

    def test_run_accepted_is_the_202_shape(self):
        dto = _roundtrip(
            RunAcceptedDTO,
            {"run_id": "r-1", "config_hash": "abc", "status": "running"},
        )
        assert dto.status == "running"

    def test_run_status_terminal_shape_roundtrips(self):
        payload = {
            "run_id": "r-1",
            "status": "completed",
            "config_hash": "abc",
            "generator_version": "1.0.0",
            "packet_count": 500,
            "byte_count": 500 * 188,
            "virtual_duration_ns": 10_000_000,
            "artifacts": [
                {
                    "artifact_id": "a-1",
                    "kind": "generated_ts",
                    "sha256": "ff" * 32,
                    "byte_size": 500 * 188,
                    "packet_count": 500,
                    "partial": False,
                },
                {
                    "artifact_id": "a-2",
                    "kind": "log",
                    "sha256": "ee" * 32,
                    "byte_size": 42,
                    "packet_count": None,
                    "partial": False,
                },
            ],
            "warnings": [],
        }
        dto = _roundtrip(RunStatusDTO, payload)
        assert dto.artifacts[0].kind == "generated_ts"

    def test_run_status_running_shape_has_null_result_fields(self):
        dto = RunStatusDTO.model_validate({"run_id": "r-1", "status": "running"})
        assert dto.config_hash is None
        assert dto.artifacts == []

    def test_run_artifact_kind_is_pinned_to_the_tee_kinds(self):
        with pytest.raises(ValidationError):
            RunArtifactDTO.model_validate(
                {
                    "artifact_id": "a-1",
                    "kind": "snapshot",
                    "sha256": "ff" * 32,
                    "byte_size": 1,
                    "partial": False,
                }
            )


class TestSessionDTOs:
    def test_create_session_request_roundtrips_with_defaults(self):
        payload = {"topology_id": "topo-1", "seed": 7}
        dto = _roundtrip(CreateSessionRequest, payload)
        assert dto.topology_revision == 1
        assert dto.clock_config.mode == "deterministic"
        assert dto.scenario_id is None

    def test_seed_is_uint64_bounded(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest.model_validate(
                {"topology_id": "topo-1", "seed": -1}
            )

    def test_clock_config_mirrors_spec_201_section4(self):
        dto = _roundtrip(
            ClockConfigDTO,
            {
                "mode": "deterministic",
                "start_time_ns": 5,
                "speed_num": 1,
                "speed_den": 1,
                "tick_quantum_ns": 1_000_000,
            },
        )
        assert dto.tick_quantum_ns == 1_000_000

    def test_session_view_lifecycle_vocabulary_is_the_spec200_table(self):
        dto = SessionViewDTO.model_validate(
            {
                "session_id": "s-1",
                "revision": 0,
                "lifecycle": "created",
                "virtual_time_ns": 0,
                "topology_revision": 1,
            }
        )
        assert dto.node_states == {}
        # lifecycle is a string mirror of the nine-state vocabulary; the
        # value set is pinned by the enum in simulation.lifecycle (wire
        # values identical), asserted here for the created/running pair.
        assert SessionViewDTO.model_validate(
            {
                "session_id": "s-1",
                "revision": 0,
                "lifecycle": "running",
                "virtual_time_ns": 0,
                "topology_revision": 1,
            }
        ).lifecycle == "running"

    def test_snapshot_echoes_cursor_and_connections(self):
        payload = {
            "session_id": "s-1",
            "revision": 0,
            "lifecycle": "created",
            "virtual_time_ns": 0,
            "topology_revision": 1,
            "connection_states": [
                {
                    "connection_id": "c-1",
                    "from_node": "a",
                    "from_port": "out-0",
                    "to_node": "b",
                    "to_port": "in-0",
                }
            ],
            "journal_seq_cursor": 41,
        }
        dto = _roundtrip(SnapshotDTO, payload)
        assert dto.journal_seq_cursor == 41

    def test_validation_report_shape(self):
        dto = _roundtrip(
            SessionValidationDTO,
            {
                "ok": False,
                "violations": [
                    {"code": "SIM_TOPO_CYCLE", "path": "topology", "message": "cycle"}
                ],
            },
        )
        assert dto.ok is False
        assert dto.violations[0].code == "SIM_TOPO_CYCLE"


class TestArtifactMetaDTO:
    def test_metadata_roundtrips(self):
        payload = {
            "artifact_id": "a-1",
            "run_id": "r-1",
            "session_id": "s-1",
            "kind": "generated_ts",
            "relative_path": "artifacts/ab/abcdef.ts",
            "byte_size": 94000,
            "sha256": "ff" * 32,
            "packet_size": 188,
            "packet_count": 500,
            "generator_version": "1.0.0",
            "config_hash": "abc",
            "fault_profile_ids": [],
            "created_at_utc_ms": 1,
        }
        dto = _roundtrip(ArtifactMetaDTO, payload)
        # SPEC-003 §2.7: relative_path travels verbatim, never absolute.
        assert dto.relative_path == "artifacts/ab/abcdef.ts"


def _minimal_config_payload() -> dict:
    return {
        "schema_version": 1,
        "seed": 1,
        "initial_media_clock_27mhz": 0,
        "target_bitrate_bps": 1,
        "output_packet_count": 1,
        "program": {
            "transport_stream_id": 1,
            "program_number": 1,
            "pmt_pid": 1,
            "pcr_pid": 1,
            "version_number": 0,
            "streams": [],
        },
    }
