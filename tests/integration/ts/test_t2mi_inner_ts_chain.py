"""SPEC-603 §6 / SPEC-100 — the full demux chain, in-process (ticket #125).

AC-603-02/03 本票范围: the three-level demux chain verified end-to-end on
the research pair (``tests/data/t2mi/inner_ts_roundtrip_input.bin`` →
registered golden ``inner-ts-roundtrip``), the SPEC-503 artifact landing
with ``kind=inner_ts`` (content-addressed, index row via the SPEC-502
repository), and the analyze/inspect consumption faces (SPEC-100 /
application.analysis) consuming the reconstructed stream.  The cross-ticket
runtime wiring (layered pipeline emission, tee double-write) lands with
#128.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from adapters.storage import db
from adapters.storage.artifact_store import ArtifactStore, SinkCommit
from adapters.storage.repositories import SqliteArtifactRepository
from application.analysis.parser import analyze_transport_stream
from domain.observation.artifact import ArtifactKind
from tests._support.paths import REPO_ROOT
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)
from ts.packet import TSPacket
from ts.t2mi.inner_ts import (
    INNER_TS_ARTIFACT_KIND,
    reconstruct,
    verify_against_tsduck,
)
from ts.t2mi.parser import parse
from ts.t2mi.plp import PlpFilterConfig

pytestmark = pytest.mark.integration

INPUT_PATH = REPO_ROOT / "tests" / "data" / "t2mi" / "inner_ts_roundtrip_input.bin"
GOLDEN_ROOT = REPO_ROOT / "docs" / "test-vectors" / "golden" / "inner-ts-roundtrip"

_TS_PACKET_BYTES = 188

_FIXED_CLOCK_MS = 1_700_000_000_000


def _clock() -> int:
    return _FIXED_CLOCK_MS


def _reconstruct_expected_plp_zero() -> "object":
    """The demux chain face: parse → filter(expected PLP 0) → reconstruct."""
    packets = parse(INPUT_PATH.read_bytes())
    assert not packets.truncated
    return reconstruct(packets, PlpFilterConfig(mode="expected", expected_plp=0))


def _golden_bytes() -> bytes:
    return (GOLDEN_ROOT / "inner-ts-roundtrip.ts").read_bytes()


def _research_program_config() -> GeneratorConfig:
    """The research inner stream's signalization (PAT/PMT walk targets)."""
    program = ProgramConfig(
        transport_stream_id=1,
        program_number=1,
        pmt_pid=0x0100,
        pcr_pid=0x0100,
        version_number=0,
        streams=(
            ElementaryStreamConfig(
                pid=0x0101,
                stream_type=0x1B,
                stream_id=1,
                bitrate_bps=1_000_000,
            ),
        ),
        program_descriptors=b"",
    )
    return GeneratorConfig(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=0,
        initial_media_clock_27mhz=0,
        target_bitrate_bps=1_000_000,
        output_packet_count=6,
        program=program,
    )


def _store_with_index(root: Path) -> ArtifactStore:
    conn = db.connect(root / "index.sqlite3")
    apply_sql_migrations(conn, default_migrations_dir())
    return ArtifactStore(root=root / "store", index=SqliteArtifactRepository(conn), clock=_clock)


class TestDemuxChainRoundTrip:
    """parse → filter → reconstruct equals the registered expected side."""

    def test_chain_output_is_byte_identical_to_the_golden(self) -> None:
        result = _reconstruct_expected_plp_zero()
        assert result.reconstruction_status == "ok"
        assert result.inner_ts == _golden_bytes()
        assert result.anomalies == ()
        assert result.first_failure_ref is None

    def test_artifact_ref_is_the_content_address_of_the_output(self) -> None:
        result = _reconstruct_expected_plp_zero()
        assert result.artifact_ref == hashlib.sha256(result.inner_ts).hexdigest()

    def test_wire_face_carries_the_frozen_six_keys(self) -> None:
        result = _reconstruct_expected_plp_zero()
        assert set(result.wire_detail()) == {
            "artifact_ref",
            "packet_count",
            "up_assembled",
            "stuffing_bytes",
            "reconstruction_status",
            "first_failure_ref",
        }

    def test_ts_side_and_domain_kind_strings_agree(self) -> None:
        # The one-way mirror face: ts purity keeps the import direction
        # ts ← nothing, so the domain enum mirrors the ts-side constant.
        assert ArtifactKind(INNER_TS_ARTIFACT_KIND).value == INNER_TS_ARTIFACT_KIND
        assert ArtifactKind.INNER_TS.value == "inner_ts"


class TestInspectConsumptionFace:
    """SPEC-603 §2.1: the output enters the SPEC-100 packet face."""

    def test_strict_packet_parse_consumes_every_reconstructed_byte(self) -> None:
        inner = _reconstruct_expected_plp_zero().inner_ts
        packets = [
            TSPacket.from_bytes(inner[offset : offset + _TS_PACKET_BYTES])
            for offset in range(0, len(inner), _TS_PACKET_BYTES)
        ]
        assert len(packets) == len(inner) // _TS_PACKET_BYTES
        assert all(packet.parse_issues == () for packet in packets)

    def test_packet_pid_population_matches_the_expected_side(self) -> None:
        inner = _reconstruct_expected_plp_zero().inner_ts
        pids = {
            TSPacket.from_bytes(inner[offset : offset + _TS_PACKET_BYTES]).pid
            for offset in range(0, len(inner), _TS_PACKET_BYTES)
        }
        assert pids == {0x0000, 0x0100, 0x1FFF}  # PAT / PMT / null


class TestAnalyzeConsumptionFace:
    """SPEC-603 §2.1: the output enters the application analysis face."""

    def test_analyze_transport_stream_yields_pat_facts(self) -> None:
        result = _reconstruct_expected_plp_zero()
        facts = analyze_transport_stream(result.inner_ts, _research_program_config())
        assert facts, "the analyze face must consume the reconstructed stream"
        fact_types = {type(fact).__name__ for fact in facts}
        assert any(name.startswith("Pat") for name in fact_types)

    def test_analyze_face_sees_both_pat_instances(self) -> None:
        result = _reconstruct_expected_plp_zero()
        facts = analyze_transport_stream(result.inner_ts, _research_program_config())
        pat_packet_indexes = [
            fact.packet_index
            for fact in facts
            if type(fact).__name__ == "PatSectionFact"
        ]
        assert pat_packet_indexes == [0, 3]  # [PAT, PMT, null] × 2


class TestArtifactLandingInnerTs:
    """SPEC-603 §5: content-addressed landing + kind=inner_ts index row."""

    def test_store_lands_at_the_reconstruction_content_address(self, tmp_path: Path) -> None:
        result = _reconstruct_expected_plp_zero()
        store = ArtifactStore(root=tmp_path / "store", clock=_clock)
        ref = store.store_bytes(result.inner_ts, ext="ts")
        assert ref.sha256 == result.artifact_ref
        assert ref.relative_path.startswith(
            f"artifacts/{result.artifact_ref[:2]}/{result.artifact_ref}.ts"
        )
        assert store.read_bytes(ref.relative_path) == result.inner_ts

    def test_index_registration_carries_the_inner_ts_kind(self, tmp_path: Path) -> None:
        result = _reconstruct_expected_plp_zero()
        store = _store_with_index(tmp_path)
        ref = store.store_bytes(result.inner_ts, ext="ts")
        artifact_id = store.register(
            SinkCommit(ref.sha256, ref.byte_size, ref.relative_path),
            run_id="run-inner-ts-1",
            session_id="session-1",
            kind=ArtifactKind.INNER_TS.value,
        )
        row = store.index.get(artifact_id)
        assert row is not None
        assert row.kind == ArtifactKind.INNER_TS.value
        assert row.kind == "inner_ts"
        assert row.sha256 == result.artifact_ref
        assert store.read_by_artifact(artifact_id) == result.inner_ts

    def test_identical_content_dedups_to_one_file(self, tmp_path: Path) -> None:
        result = _reconstruct_expected_plp_zero()
        store = _store_with_index(tmp_path)
        first = store.store_bytes(result.inner_ts, ext="ts")
        second = store.store_bytes(result.inner_ts, ext="ts")
        assert first.sha256 == second.sha256
        assert second.deduplicated is True


class TestTsduckCrossProtocolShape:
    """The pure L2 record on the real pair (the live tsp run is conformance)."""

    def test_record_on_the_chain_pair_is_not_trusted(self) -> None:
        result = _reconstruct_expected_plp_zero()
        record = verify_against_tsduck(result.inner_ts, _golden_bytes())
        assert record["match"] is True
        assert record["trusted"] is False
        assert record["trust_annotation"] == "NOT TRUSTED"
        assert record["not_trusted_reason"]

    def test_unattested_version_is_honest_evidence(self) -> None:
        record = verify_against_tsduck(_golden_bytes(), _golden_bytes()[:-188])
        assert record["match"] is False
        assert record["first_diff_offset"] == len(_golden_bytes()) - _TS_PACKET_BYTES
        assert record["trust_annotation"] == "NOT TRUSTED"
