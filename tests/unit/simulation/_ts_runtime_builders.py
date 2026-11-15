"""Programmatic builders for the SPEC-203 TS-runtime test slices (#43).

Byte discipline (tests/README.md section 5): every TS byte in these tests
comes from the real SPEC-108 generator chain driven by a fixed-seed
:class:`ts.generator.config.GeneratorConfig` — nothing is hand-assembled.
The fault-filter fake is a slot-preserving in-place rewrite (ADR-0007
item 4) built from the public ``ts.packet.TSPacket`` model.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Mapping

from simulation.clock import SimulationClockConfig
from simulation.runtime import SimulationSessionSpec
from simulation.state import TopologyGraph
from ts.generator.config import (
    ElementaryStreamConfig,
    GeneratorConfig,
    ProgramConfig,
)
from ts.packet import TSPacket


def make_generator_config(**overrides: Any) -> GeneratorConfig:
    """A minimal §5-valid analysis_only GeneratorConfig (fixed seed).

    One video ES carrying PCR on its own PID (the allowed PCR-on-ES reuse),
    PMT on 0x1000, 10 Mbps target, 500 packets — comfortably inside the
    SPEC-107 deadline window and the §5 rate-fit estimate.
    """
    fields: dict[str, Any] = dict(
        schema_version=1,
        profile="analysis_only",
        deterministic=True,
        seed=20260101,
        initial_media_clock_27mhz=27_000_000,
        target_bitrate_bps=10_000_000,
        output_packet_count=500,
        program=ProgramConfig(
            transport_stream_id=1,
            program_number=1,
            pmt_pid=0x1000,
            pcr_pid=0x0100,
            version_number=0,
            streams=(
                ElementaryStreamConfig(
                    pid=0x0100,
                    stream_type=0x1B,
                    stream_id=0xE0,
                    bitrate_bps=2_000_000,
                ),
            ),
        ),
    )
    fields.update(overrides)
    return GeneratorConfig(**fields)


def make_session_spec(
    session_id: str = "session-ts-runtime",
    clock_config: SimulationClockConfig | None = None,
) -> SimulationSessionSpec:
    """A minimal frozen session spec carrying the fingerprint inputs."""
    return SimulationSessionSpec(
        session_id=session_id,
        topology=TopologyGraph(topology_id="topo-1", revision=1, nodes=(), connections=()),
        seed=20260101,
        deterministic=True,
        clock_config=clock_config or SimulationClockConfig(mode="deterministic"),
    )


class RecordingSinkLeg:
    """In-memory sink leg (unit layer: no filesystem IO).

    Mirrors the :class:`adapters.storage.artifact_store.ArtifactWriteSink`
    protocol surface the runtime consumes: incremental write, commit,
    abort.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.chunks: list[bytes] = []
        self.committed = False
        self.aborted = False

    def write(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    @property
    def data(self) -> bytes:
        return b"".join(self.chunks)

    def commit(self) -> dict[str, Any]:
        self.committed = True
        import hashlib

        return {
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "byte_size": len(self.data),
            "relative_path": f"mem://{self.name}",
        }

    def abort(self) -> None:
        self.aborted = True
        self.chunks = []


class FakeArtifactSink:
    """Structural ArtifactSink fake: three legs, dict-backed registry.

    ``find_reusable_baseline`` consults only records this fake registered
    itself (complete baselines), so the dedup decision can be asserted
    without a storage adapter (unit layer discipline).
    """

    def __init__(self) -> None:
        self.legs: dict[str, RecordingSinkLeg] = {}
        self.registrations: list[dict[str, Any]] = []
        self.records: list[dict[str, Any]] = []
        self._reusable: dict[tuple, str] = {}

    def open_legs(self, *, tee: bool, run_id: str, session_id: str) -> Any:
        legs = {"baseline": RecordingSinkLeg("baseline")}
        if tee:
            legs["faulted"] = RecordingSinkLeg("faulted")
            legs["log"] = RecordingSinkLeg("log")
        self.legs = legs
        self.run_id = run_id
        self.session_id = session_id
        self.tee = tee

        class _TeeLegs:
            pass

        holder = _TeeLegs()
        holder.baseline = legs["baseline"]
        holder.faulted = legs.get("faulted")
        holder.log = legs.get("log")
        return holder

    def register(
        self,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        commit: Mapping[str, Any],
        packet_count: int | None,
        config_hash: str,
        generator_version: str,
        partial: bool,
    ) -> str:
        artifact_id = f"artifact-{len(self.records) + 1}"
        record = {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "session_id": session_id,
            "kind": kind,
            "sha256": commit["sha256"],
            "byte_size": commit["byte_size"],
            "relative_path": commit["relative_path"],
            "packet_count": packet_count,
            "config_hash": config_hash,
            "generator_version": generator_version,
            "partial": partial,
        }
        self.records.append(record)
        self.registrations.append(dict(record))
        if kind == "generated_ts" and not partial:
            # Reuse key = full fingerprint triple (sha + config_hash +
            # packet_count) — mirrors the store-backed registry's guard.
            self._reusable.setdefault(
                (commit["sha256"], config_hash, packet_count), artifact_id
            )
        return artifact_id

    def find_reusable_baseline(
        self, sha256: str, config_hash: str, packet_count: int
    ) -> str | None:
        return self._reusable.get((sha256, config_hash, packet_count))


class CCShiftFilter:
    """Slot-preserving fake fault filter (ADR-0007 item 4 shape).

    Rewrites the continuity counter of every packet after the activation
    index by a fixed delta (in-place, equal-slot — no insertion/removal),
    and accumulates a JSON mutation log with the shared packet index.
    """

    def __init__(self, plan: tuple[Any, ...], delta: int = 3) -> None:
        self._delta = delta
        self._entries: list[dict[str, Any]] = []

    def apply(self, index: int, packet: TSPacket) -> TSPacket:
        shifted = (packet.continuity_counter + self._delta) % 16
        self._entries.append(
            {"index": index, "pid": packet.pid, "cc_after": shifted}
        )
        return replace(packet, continuity_counter=shifted)

    def mutation_log(self) -> bytes:
        return json.dumps(
            {"mutations": self._entries}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
