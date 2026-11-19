"""Phase 2 encapsulation wire DTOs (ticket #129 — the mirror discipline).

Two mirror obligations, both cross-checked against the LIVE producers:

- structure views (``api.dto.encapsulation``): the key sets are the
  json_map chain's frozen projections — the per-packet T2-MI row (#122
  wire keys + the ``packet_index`` transport locator), ``BBFrame.wire_detail``
  nine keys (#123), ``InnerTsResult.wire_detail`` six keys (#125) and the
  per-view envelopes assembled by ``application.analysis.structure``
  (#128). The Pydantic models must round-trip the real assemblies
  verbatim: a response_model that dropped or renamed a key would change
  the served body (禁手写 mirror = no invented keys, no lost keys).
- biss scenario config (``BissMode1ConfigDTO``/``BissModeEConfigDTO``):
  the scenario document's ``biss`` section wire (SPEC-610 §5 / SPEC-611
  §5, parsed by ``simulation.scenario.schema`` — the §10-6 ruling face).
  The api layer cannot import ``simulation`` (import-linter C6), so the
  shapes are restated here and pinned identical by the field-set test.

Event payload DTOs (``api.dto.observation`` Phase 2 faces) mirror the
registry payload schemas (``domain.observation.registry``, ticket #129):
the registry validators accept what the DTOs accept — both sides pin the
#128 REPORT §1.2 key sets.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from pydantic import ValidationError

from api.dto.encapsulation import (
    BBFrameDTO,
    BissMode1ConfigDTO,
    BissModeEConfigDTO,
    FirstFailureRefDTO,
    InnerTsResultDTO,
    StructureViewDTO,
    T2miPacketDTO,
    T2miStructureViewDTO,
)
from api.dto.observation import (
    BbframeRecoveryFailedPayloadDTO,
    BbframeStageSummaryPayloadDTO,
    BissDescrambleFailedPayloadDTO,
    BissScrambleAppliedPayloadDTO,
    GenPacketSampledPayloadDTO,
    GenStageCompletedPayloadDTO,
    GenStageStartedPayloadDTO,
    T2miPlpMismatchPayloadDTO,
    T2miStageSummaryPayloadDTO,
)
from application.analysis.structure import structure_view

from tests.unit.domain.observation.test_phase2_payload_registry import (
    VALID_PAYLOADS,
)

# --- live fixtures (pure in-memory construction — no I/O) -----------------------


def _t2mi_stream() -> bytes:
    """A minimal real T2-MI stream (one BBFRAME packet), the #122 chain."""
    from ts.t2mi.bbframe import BBFrameBuildConfig, build as build_bbframe
    from ts.t2mi.builder import T2miBuildConfig, build as build_t2mi

    frames = build_bbframe(bytes(range(188)), BBFrameBuildConfig())
    packets = build_t2mi(frames, T2miBuildConfig())
    return b"".join(packet.to_bytes() for packet in packets)


class TestT2miPacketDTOMirror:
    """The per-packet row: #122 wire keys + the packet_index locator."""

    def test_live_structure_row_round_trips(self):
        from ts.t2mi.parser import parse as parse_t2mi

        view = structure_view(_t2mi_stream(), "t2mi")
        assert view["packets"], "fixture stream must hold packets"
        for row in view["packets"]:
            dto = T2miPacketDTO.model_validate(row)
            assert dto.model_dump() == row

    def test_wire_key_set_is_exactly_the_eleven_faces(self):
        # #140 additive: the #122 eight faces + the bytes-2..5 named faces
        # (superframe_index / reserved digest / interleaving_frame_start)
        assert set(T2miPacketDTO.model_fields) == {
            "packet_index",
            "packet_type",
            "packet_counter",
            "superframe_index",
            "reserved",
            "payload_kind",
            "payload_bytes_len",
            "crc32_valid",
            "frame_index",
            "interleaving_frame_start",
            "plp_id",
        }

    def test_payload_kind_is_the_frozen_three_state_vocabulary(self):
        row = {
            "packet_index": 0,
            "packet_type": 0x2A,
            "packet_counter": 1,
            "payload_kind": "mystery",
            "payload_bytes_len": 4,
            "crc32_valid": True,
            "frame_index": None,
            "plp_id": None,
        }
        with pytest.raises(ValidationError):
            T2miPacketDTO.model_validate(row)


class TestBBFrameDTOMirror:
    """The nine frozen ``wire_detail()`` keys (#123), units documented."""

    def test_live_wire_detail_round_trips(self):
        from ts.t2mi.bbframe import BBFrameBuildConfig, build as build_bbframe
        from ts.t2mi.bbframe import parse as parse_bbframe

        frames = build_bbframe(bytes(range(188)), BBFrameBuildConfig())
        frame = parse_bbframe(frames)[0]
        detail = frame.wire_detail()
        dto = BBFrameDTO.model_validate(detail)
        assert dto.model_dump() == detail

    def test_wire_key_set_is_exactly_the_nine_faces(self):
        assert set(BBFrameDTO.model_fields) == {
            "matype",
            "upl",
            "dfl",
            "sync",
            "syncd",
            "crc8_valid",
            "up_count",
            "up_indices",
            "state",
        }


class TestInnerTsResultDTOMirror:
    """The six-key wire projection (#125)."""

    def test_live_wire_detail_round_trips(self):
        from ts.t2mi.inner_ts import InnerTsResult

        result = InnerTsResult(
            artifact_ref="a" * 64,
            packet_count=3,
            up_assembled=3,
            stuffing_bytes=0,
            reconstruction_status="ok",
            first_failure_ref=None,
        )
        dto = InnerTsResultDTO.model_validate(result.wire_detail())
        assert dto.model_dump() == result.wire_detail()

    def test_wire_key_set_is_exactly_the_six_faces(self):
        assert set(InnerTsResultDTO.model_fields) == {
            "artifact_ref",
            "packet_count",
            "up_assembled",
            "stuffing_bytes",
            "reconstruction_status",
            "first_failure_ref",
        }

    def test_reconstruction_status_is_the_closed_three_state_set(self):
        row = {
            "artifact_ref": "a" * 64,
            "packet_count": 0,
            "up_assembled": 0,
            "stuffing_bytes": 0,
            "reconstruction_status": "excellent",
            "first_failure_ref": None,
        }
        with pytest.raises(ValidationError):
            InnerTsResultDTO.model_validate(row)

    def test_first_failure_ref_carries_the_dual_locator(self):
        assert set(FirstFailureRefDTO.model_fields) == {
            "frame_index",
            "reason",
            "packet_position",
        }


class TestStructureViewEnvelopes:
    """The per-view envelopes must round-trip #128's assemblies."""

    def test_t2mi_view_round_trips(self):
        view = structure_view(_t2mi_stream(), "t2mi")
        dto = T2miStructureViewDTO.model_validate(view)
        assert dto.model_dump() == view

    def test_bbframe_view_round_trips(self):
        from api.dto.encapsulation import BBFrameStructureViewDTO

        view = structure_view(_t2mi_stream(), "bbframe")
        dto = BBFrameStructureViewDTO.model_validate(view)
        assert dto.model_dump() == view

    def test_inner_ts_view_round_trips(self):
        from api.dto.encapsulation import InnerTsStructureViewDTO

        view = structure_view(_t2mi_stream(), "ts")
        dto = InnerTsStructureViewDTO.model_validate(view)
        assert dto.model_dump() == view

    def test_union_discriminates_all_three_views(self):
        from api.dto.encapsulation import (
            BBFrameStructureViewDTO,
            InnerTsStructureViewDTO,
        )
        from pydantic import TypeAdapter

        t2mi = T2miStructureViewDTO.model_validate(
            structure_view(_t2mi_stream(), "t2mi")
        )
        assert isinstance(t2mi, T2miStructureViewDTO)
        adapter = TypeAdapter(StructureViewDTO)
        bbframe = adapter.validate_python(
            structure_view(_t2mi_stream(), "bbframe")
        )
        assert isinstance(bbframe, BBFrameStructureViewDTO)
        inner = adapter.validate_python(structure_view(_t2mi_stream(), "ts"))
        assert isinstance(inner, InnerTsStructureViewDTO)


class TestBissConfigDTOMirror:
    """The scenario ``biss`` section wire (SPEC-610 §5 / SPEC-611 §5)."""

    def test_field_sets_match_the_scenario_schema_dataclasses(self):
        from simulation.scenario.schema import (
            BissMode1Config,
            BissModeEConfig,
        )

        assert set(BissMode1ConfigDTO.model_fields) == {
            field.name for field in BissMode1Config.__dataclass_fields__.values()
        }
        assert set(BissModeEConfigDTO.model_fields) == {
            field.name for field in BissModeEConfig.__dataclass_fields__.values()
        }

    def test_mode1_face_validates_the_wire_section(self):
        dto = BissMode1ConfigDTO.model_validate(
            {"mode": "1", "session_word": "A13DBC42908F", "pid_scope": [256]}
        )
        assert dto.ca_pid == 8191  # constant semantics default (Tech 3292)

    def test_mode_e_face_validates_the_wire_section(self):
        dto = BissModeEConfigDTO.model_validate(
            {
                "mode": "E",
                "encrypted_sw": "A13DBC42908F0011",
                "injected_id": "0123456789ABCDEF0123456789ABCDEF",
                "pid_scope": [256],
            }
        )
        assert dto.ca_pid == 8191
        assert dto.ca_system_id == 9730  # 0x2602 constant semantics

    def test_key_shapes_are_the_wire_hex_patterns(self):
        with pytest.raises(ValidationError):
            BissMode1ConfigDTO.model_validate(
                {
                    "mode": "1",
                    "session_word": "not-hex",
                    "pid_scope": [256],
                }
            )
        with pytest.raises(ValidationError):
            BissModeEConfigDTO.model_validate(
                {
                    "mode": "E",
                    "encrypted_sw": "A13DBC42908F",  # 12 hex, not 16
                    "injected_id": "0123456789ABCDEF0123456789ABCDEF",
                    "pid_scope": [256],
                }
            )


class TestEventPayloadDTOMirror:
    """The payload DTOs and the registry validators pin the same shapes."""

    def test_every_registry_phase2_payload_maps_onto_its_dto(self):
        pairs = {
            "t2mi.stage_summary": T2miStageSummaryPayloadDTO,
            "t2mi.plp_mismatch": T2miPlpMismatchPayloadDTO,
            "bbframe.stage_summary": BbframeStageSummaryPayloadDTO,
            "bbframe.recovery_failed": BbframeRecoveryFailedPayloadDTO,
            "biss.scramble_applied": BissScrambleAppliedPayloadDTO,
            "biss.descramble_failed": BissDescrambleFailedPayloadDTO,
            "gen.stage_started": GenStageStartedPayloadDTO,
            "gen.stage_completed": GenStageCompletedPayloadDTO,
            "gen.packet_sampled": GenPacketSampledPayloadDTO,
        }
        from domain.observation.registry import validate_payload

        for event_type, dto_class in pairs.items():
            payload = VALID_PAYLOADS[event_type]
            dto = dto_class.model_validate(payload)
            # exclude_unset: the optional derivation face stays absent
            # exactly when the payload omitted it (the registry key-set
            # rule is the authority; the dump must round-trip verbatim).
            dumped = dto.model_dump(exclude_unset=True)
            assert dumped == payload, event_type
            validate_payload(event_type, dumped)  # must not raise

    def test_mode_e_construction_face_is_the_bare_five_keys(self):
        # The cissa construction path emits mode "E" WITHOUT the
        # derivation face — both faces must validate and round-trip.
        from domain.observation.registry import validate_payload

        payload = {
            "pid_scope": [256],
            "packet_count": 5,
            "key_fingerprint": "sha256:" + "b" * 16,
            "mutation_log_ref": None,
            "mode": "E",
        }
        dto = BissScrambleAppliedPayloadDTO.model_validate(payload)
        dumped = dto.model_dump(exclude_unset=True)
        assert dumped == payload
        validate_payload("biss.scramble_applied", dumped)

    def test_mode_e_scramble_payload_carries_the_derivation_face(self):
        payload = {
            "pid_scope": [256],
            "packet_count": 5,
            "key_fingerprint": "sha256:" + "b" * 16,
            "mutation_log_ref": None,
            "mode": "E",
            "derivation_ref": {
                "esw_fingerprint": "sha256:" + "1" * 16,
                "injected_id_fingerprint": "sha256:" + "2" * 16,
                "session_word_fingerprint": "sha256:" + "3" * 16,
                "ciss_key_fingerprint": "sha256:" + "4" * 16,
            },
            "mismatch_variants": ["wrong_injected_id"],
        }
        dto = BissScrambleAppliedPayloadDTO.model_validate(payload)
        assert dto.model_dump(exclude_unset=True) == payload

    def test_payload_dtos_reject_the_registry_refusals(self):
        with pytest.raises(ValidationError):
            GenStageStartedPayloadDTO.model_validate({"layer": "MPEG_TS"})
        with pytest.raises(ValidationError):
            GenStageCompletedPayloadDTO.model_validate({"layer": "TS"})
        with pytest.raises(ValidationError):
            BissScrambleAppliedPayloadDTO.model_validate(
                {
                    **VALID_PAYLOADS["biss.scramble_applied"],
                    "mode": "3",
                }
            )
