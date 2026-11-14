"""TSArtifact model tests (SPEC-003 section 2.7).

Seam: public construction/validation surface of ``domain.observation``
(TSArtifact), the ``kind`` closed set and the ``packet_size`` 188|204 literal.
Expected literals come from SPEC-003 section 2.7 text.
"""

import pytest
from pydantic import ValidationError

from domain.observation import ArtifactKind, TSArtifact


def _artifact(**overrides) -> TSArtifact:
    fields = {
        "artifact_id": "aa11bb33-9c2b-4f3e-9c2b-7a1d5e0f3a44",
        "run_id": "3b241101-e2bb-4255-8caf-4136c566a962",
        "kind": "generated_ts",
        "relative_path": "runs/2026/11/14/generated-baseline.ts",
        "byte_size": 1_880_000,
        "sha256": "ab" * 32,
        "created_at_utc_ms": 1_700_000_000_000,
    }
    fields.update(overrides)
    return TSArtifact(**fields)


class TestEnumClosedSets:
    def test_artifact_kind_has_exactly_the_six_spec_kinds(self):
        assert {member.value for member in ArtifactKind} == {
            "input_ts",
            "generated_ts",
            "faulted_ts",
            "report",
            "log",
            "evidence",
        }


class TestTSArtifact:
    def test_valid_construction_required_fields_only(self):
        artifact = _artifact()
        assert artifact.kind is ArtifactKind.GENERATED_TS
        assert artifact.packet_size is None
        assert artifact.packet_count is None
        assert artifact.generator_version is None
        assert artifact.config_hash is None
        assert artifact.fault_profile_ids is None

    def test_valid_construction_full(self):
        artifact = _artifact(
            packet_size=188,
            packet_count=10_000,
            generator_version="ts-core-0.1.0",
            config_hash="cd" * 32,
            fault_profile_ids=["5e0f3a44-1d5e-4c2b-9c2b-7a1d5e0f3a44"],
        )
        assert artifact.packet_size == 188
        assert artifact.packet_count == 10_000
        assert artifact.fault_profile_ids == ["5e0f3a44-1d5e-4c2b-9c2b-7a1d5e0f3a44"]

    def test_round_trip(self):
        artifact = _artifact(packet_size=204, packet_count=7)
        assert TSArtifact.model_validate(artifact.model_dump()) == artifact

    def test_packet_size_accepts_only_188_or_204(self):
        assert _artifact(packet_size=188).packet_size == 188
        assert _artifact(packet_size=204).packet_size == 204

    def test_packet_size_rejects_other_lengths(self):
        with pytest.raises(ValidationError) as excinfo:
            _artifact(packet_size=192)
        assert excinfo.value.errors()[0]["loc"][:1] == ("packet_size",)

    def test_relative_path_is_carried_verbatim_no_filesystem_semantics(self):
        # SPEC-003 section 2.7: relative to the managed artifact root; the
        # model is filesystem-blind (domain must not import pathlib/os —
        # import-linter contract), path safety belongs to SPEC-503 storage.
        artifact = _artifact(relative_path="artifacts/sha/ab/cd/payload.ts")
        assert artifact.relative_path == "artifacts/sha/ab/cd/payload.ts"

    def test_missing_required_field_reports_location(self):
        with pytest.raises(ValidationError) as excinfo:
            TSArtifact(
                artifact_id="aa11bb33-9c2b-4f3e-9c2b-7a1d5e0f3a44",
                run_id="3b241101-e2bb-4255-8caf-4136c566a962",
                kind="report",
                relative_path="reports/r.json",
                byte_size=10,
            )
        error_locs = {error["loc"] for error in excinfo.value.errors()}
        assert ("sha256",) in error_locs
        assert ("created_at_utc_ms",) in error_locs

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            _artifact(absolute_path="C:/tmp/x.ts")
        assert excinfo.value.errors()[0]["loc"] == ("absolute_path",)

    def test_frozen_model_rejects_assignment(self):
        artifact = _artifact()
        with pytest.raises(ValidationError):
            artifact.byte_size = 0
