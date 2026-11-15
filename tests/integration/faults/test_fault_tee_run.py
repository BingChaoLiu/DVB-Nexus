"""End-to-end fault tee run with the PRODUCTION filter (#44 acceptance).

Full chain: SPEC-108 Generator (frozen golden geometry) → TSRuntime tee
double-write → ``faults.factory`` semantic filter → SPEC-503 store
landing.  Because the generator reproduces the registered golden baseline
byte-identically (SPEC-108 §8 determinism), the faulted artifact of a run
with the golden fault plan must equal the registered golden faulted
vector — the strongest oracle form (generator bytes, not parsed vectors).

Covers REQ-SIM-204-002 (determinism incl. mutation log), 003 (faulted
hash differs), 004 (evidence locator), 005/007 (shared packet frame).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from ts.packet import TSPacket

from adapters.storage import db
from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.repositories import SqliteArtifactRepository
from faults.factory import build_semantic_filter_factory
from simulation.ts_runtime import StoreArtifactSink, TSRuntime
from tests._support.sqlite_support import apply_sql_migrations, default_migrations_dir
from tests.unit.faults._fault_builders import (
    GOLDEN_BASELINE_SHA256,
    cc_discontinuity_fault,
    golden_geometry_config,
    pat_missing_fault,
    pmt_invalid_crc_fault,
    pmt_pid_mismatch_fault,
)
from tests.unit.simulation._ts_runtime_builders import make_session_spec

pytestmark = pytest.mark.integration

ORACLE_PAIRS = {
    "pat-missing": pat_missing_fault,
    "pmt-invalid-crc": pmt_invalid_crc_fault,
    "cc-discontinuity": cc_discontinuity_fault,
    "pmt-pid-mismatch": pmt_pid_mismatch_fault,
}


def _store_with_index(tmp_path: Path, dirname: str):
    connection = db.connect(tmp_path / f"{dirname}.sqlite3")
    apply_sql_migrations(connection, default_migrations_dir())
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(tmp_path / dirname, index=repository)
    return store, repository


def _relative_of(repository, sha256: str) -> str:
    rows = repository.find_by_sha256(sha256)
    assert rows, f"no index row for {sha256}"
    return rows[0].relative_path


def _make_runtime(tmp_path: Path, dirname: str):
    store, repository = _store_with_index(tmp_path, dirname)
    sink = StoreArtifactSink(store, index=repository)
    runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
    prepared = runtime.prepare(
        make_session_spec(), golden_geometry_config(), (cc_discontinuity_fault(),)
    )
    return runtime, prepared, sink, store, repository


class TestEndToEndTeeOracle:
    @pytest.mark.parametrize("vector_id", sorted(ORACLE_PAIRS))
    def test_tee_run_reproduces_the_golden_pair(
        self, tmp_path: Path, golden_loader, vector_id: str
    ) -> None:
        """REQ-SIM-204-002/003: the run's baseline leg is byte-identical to
        the registered baseline; the faulted leg is byte-identical to the
        registered faulted vector (generator-driven oracle)."""
        store, repository = _store_with_index(tmp_path, f"tee-{vector_id}")
        sink = StoreArtifactSink(store, index=repository)
        runtime = TSRuntime(filter_factory=build_semantic_filter_factory())
        prepared = runtime.prepare(
            make_session_spec(),
            golden_geometry_config(),
            (ORACLE_PAIRS[vector_id](),),
        )
        result = asyncio.run(runtime.run(prepared, sink))
        assert result.status == "completed"
        assert result.packet_count == 600
        assert result.byte_count == 600 * 188

        kinds = sorted(a.kind for a in result.artifacts)
        assert kinds == ["faulted_ts", "generated_ts", "log"]
        baseline_ref = next(a for a in result.artifacts if a.kind == "generated_ts")
        faulted_ref = next(a for a in result.artifacts if a.kind == "faulted_ts")
        golden_baseline = golden_loader.load(f"{vector_id}-baseline")
        golden_faulted = golden_loader.load(vector_id)
        # REQ-SIM-204-002: baseline reproduces the registered baseline.
        assert baseline_ref.sha256 == golden_baseline.sha256
        assert baseline_ref.sha256 == GOLDEN_BASELINE_SHA256
        # REQ-SIM-204-003: the fault changed the digest to the golden value.
        assert faulted_ref.sha256 == golden_faulted.sha256

        landed_baseline = store.read_bytes(
            _relative_of(repository, baseline_ref.sha256), verify=True
        )
        landed_faulted = store.read_bytes(
            _relative_of(repository, faulted_ref.sha256), verify=True
        )
        assert landed_faulted == golden_faulted.ts_bytes
        assert len(landed_faulted) == len(landed_baseline)

    def test_slot_preserving_invariant_on_landed_streams(
        self, tmp_path: Path
    ) -> None:
        """REQ-SIM-204-005/007: full-stream index-aligned scan of the two
        landed legs — same slot count, 188 alignment, and the declared
        landing slot addresses the same position on both streams."""
        runtime, prepared, sink, store, repository = _make_runtime(
            tmp_path, "tee-invariant"
        )
        result = asyncio.run(runtime.run(prepared, sink))
        baseline_ref = next(a for a in result.artifacts if a.kind == "generated_ts")
        faulted_ref = next(a for a in result.artifacts if a.kind == "faulted_ts")
        baseline_bytes = store.read_bytes(
            _relative_of(repository, baseline_ref.sha256), verify=True
        )
        faulted_bytes = store.read_bytes(
            _relative_of(repository, faulted_ref.sha256), verify=True
        )
        assert len(baseline_bytes) == len(faulted_bytes)
        assert len(faulted_bytes) % 188 == 0
        baseline_packets = [
            TSPacket.from_bytes(baseline_bytes[i : i + 188])
            for i in range(0, len(baseline_bytes), 188)
        ]
        faulted_packets = [
            TSPacket.from_bytes(faulted_bytes[i : i + 188])
            for i in range(0, len(faulted_bytes), 188)
        ]
        for b_packet, f_packet in zip(baseline_packets, faulted_packets):
            assert len(f_packet.to_bytes()) == 188
        # CC golden landing: activation 30 → slot 50 is the first changed
        # slot, and both streams' slot 50 is the same PID-0x0100 payload slot.
        diff = [
            i
            for i, (b, f) in enumerate(zip(baseline_packets, faulted_packets))
            if b.to_bytes() != f.to_bytes()
        ]
        assert diff[0] == 50
        assert baseline_packets[50].pid == faulted_packets[50].pid
        assert faulted_packets[50].continuity_counter == (
            (baseline_packets[50].continuity_counter + 3) & 0x0F
        )


class TestDeterminismIncludingMutationLog:
    """REQ-SIM-204-002: same seed/config/plan → byte-identical artifacts
    AND byte-identical mutation log content (含 mutation log).

    Interpretation note (recorded in the #44 report): each ``run()`` gets a
    fresh uuid4 ``run_id`` (ADR-0006 item 3 — runs are machine entities),
    so the log document's top-level ``run_id`` run binding legitimately
    differs per run; the deterministic content is the fault summaries and
    the per-slot mutation records, compared here byte-exactly.
    """

    def test_two_runs_byte_identical(self, tmp_path: Path) -> None:
        runtime, prepared, sink, store, repository = _make_runtime(
            tmp_path, "determinism-a"
        )
        first = asyncio.run(runtime.run(prepared, sink))
        second = asyncio.run(runtime.run(prepared, sink))

        def landed_bytes(result, kind: str) -> bytes:
            ref = next(a for a in result.artifacts if a.kind == kind)
            return store.read_bytes(_relative_of(repository, ref.sha256), verify=True)

        for kind in ("generated_ts", "faulted_ts"):
            assert hashlib.sha256(landed_bytes(first, kind)).hexdigest() == (
                hashlib.sha256(landed_bytes(second, kind)).hexdigest()
            ), kind

        def log_content(result) -> bytes:
            document = json.loads(landed_bytes(result, "log").decode("utf-8"))
            document.pop("run_id")
            return json.dumps(
                document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")

        assert log_content(first) == log_content(second)
        # the run binding itself is per-run identity and present in both
        first_log = json.loads(landed_bytes(first, "log").decode("utf-8"))
        second_log = json.loads(landed_bytes(second, "log").decode("utf-8"))
        assert first_log["run_id"] == first.run_id
        assert second_log["run_id"] == second.run_id
        assert first_log["run_id"] != second_log["run_id"]


class TestMutationLogEvidenceLocator:
    """REQ-SIM-204-004: every applied fault has lifecycle + locator records
    reachable from the log artifact (AC-204-04)."""

    def test_log_binds_run_and_locates_both_streams(
        self, tmp_path: Path
    ) -> None:
        runtime, prepared, sink, store, repository = _make_runtime(
            tmp_path, "locator"
        )
        result = asyncio.run(runtime.run(prepared, sink))
        log_ref = next(a for a in result.artifacts if a.kind == "log")
        log_bytes = store.read_bytes(
            _relative_of(repository, log_ref.sha256), verify=True
        )
        document = json.loads(log_bytes.decode("utf-8"))
        assert document["run_id"] == result.run_id
        assert document["schema_version"] == 1
        fault_summary = document["faults"][0]
        assert fault_summary["fault_id"] == "fault-cc-discontinuity"
        assert fault_summary["fault_type"] == "CC_DISCONTINUITY"
        assert fault_summary["target"] == {"node_id": "demux-0", "pid": 0x0100}
        lifecycle = fault_summary["lifecycle"]
        assert lifecycle["fault.injected"] is True
        assert lifecycle["fault.activated"] == 30
        assert lifecycle["fault.applied"][0] == 50
        assert lifecycle["fault.cleared"] is True
        # from the log record → the same slot in both landed streams
        record = document["mutations"][0]
        assert record["packet_index"] == 50
        assert record["after"]["continuity_counter"] == (
            record["before"]["continuity_counter"] + 3
        ) % 16
        # the log artifact is registered under the run (SPEC-502 index row)
        rows = repository.find_by_sha256(log_ref.sha256)
        assert rows[0].run_id == result.run_id

    def test_log_records_cover_every_changed_slot(self, tmp_path: Path) -> None:
        runtime, prepared, sink, store, repository = _make_runtime(
            tmp_path, "locator-cover"
        )
        result = asyncio.run(runtime.run(prepared, sink))
        log_ref = next(a for a in result.artifacts if a.kind == "log")
        faulted_ref = next(a for a in result.artifacts if a.kind == "faulted_ts")
        log_document = json.loads(
            store.read_bytes(
                _relative_of(repository, log_ref.sha256), verify=True
            ).decode("utf-8")
        )
        faulted_bytes = store.read_bytes(
            _relative_of(repository, faulted_ref.sha256), verify=True
        )
        import hashlib

        from tests.unit.faults._fault_builders import golden_baseline_packets

        baseline_packets = golden_baseline_packets()
        faulted_packets = [
            TSPacket.from_bytes(faulted_bytes[i : i + 188])
            for i in range(0, len(faulted_bytes), 188)
        ]
        changed = {
            i
            for i, (b, f) in enumerate(zip(baseline_packets, faulted_packets))
            if b.to_bytes() != f.to_bytes()
        }
        logged = {record["packet_index"] for record in log_document["mutations"]}
        assert logged == changed
        for record in log_document["mutations"]:
            assert record["after"]["slot_sha256"] == hashlib.sha256(
                faulted_packets[record["packet_index"]].to_bytes()
            ).hexdigest()
