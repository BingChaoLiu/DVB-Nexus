"""Shared REST test stack — composition root for the SPEC-500 §4 routes
(ticket #48; ticket #53 裁定 1b/1d).

The M3 posture, productionized by #53: the port backends (sessions/runs/
artifacts over the #41/#43/#42 backends), the error translation and the
DTO mapping now live in the PRODUCTION composition module
(:mod:`bootstrap.backends`) and are imported from there — the "测试组合根
→ 生产组合根" value (one implementation, two compositions).

Composition scope note: this stack keeps the #48/#54 unbound posture for
§4.4 (diagnosis) and §4.5 (observation) — their mount-point tests pin the
501 freeze answers of the UNBOUND composition. The BOUND behavior of both
planes is covered by the ticket #53/#54 dedicated stacks
(``build_production_app`` + the observation query test stacks).

Fault-filter note (裁定 1b): the identity-filter placeholder is RETIRED —
the default is the real #44 semantic filter
(``faults.factory.build_semantic_filter_factory()``); a test may still
override via ``filter_factory=``.

Bytes discipline (tests/README.md §5): every TS byte comes from the real
SPEC-108 generator via ``tests.unit.simulation._ts_runtime_builders``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

from adapters.storage import db
from adapters.storage.artifact_store import ArtifactStore
from adapters.storage.repositories import SqliteArtifactRepository
from simulation.runtime import SimulationRuntime, SimulationSessionSpec
from simulation.state import TopologyGraph
from simulation.ts_runtime import StoreArtifactSink, TSRuntime

from api.app import create_app
from api.routes import build_spec500_routers
from bootstrap.backends import (
    ArtifactStoreBackend,
    RunIdAllocator,
    SimulationRunsBackend,
    SimulationSessionsBackend,
    default_topology_provider,
    wire_generator_config,
)
from faults.factory import build_semantic_filter_factory
from tests._support.sqlite_support import default_migrations_dir
from tests.unit.simulation._ts_runtime_builders import make_generator_config

__all__ = [
    "ArtifactStoreBackend",
    "RestStack",
    "RunIdAllocator",
    "SimulationRunsBackend",
    "SimulationSessionsBackend",
    "build_rest_stack",
    "default_topology_provider",
    "make_generator_config",
    "wire_generator_config",
]


@dataclasses.dataclass
class RestStack:
    """Everything a REST integration test needs in one handle."""

    app: Any
    sessions_backend: "SimulationSessionsBackend"
    runs_backend: "SimulationRunsBackend"
    artifacts_backend: "ArtifactStoreBackend"
    runtime: SimulationRuntime
    ts_runtime: TSRuntime
    store: ArtifactStore
    repository: SqliteArtifactRepository
    session_specs: dict[str, SimulationSessionSpec]


def build_rest_stack(
    root: Path,
    *,
    topology_provider: Callable[[str, int], TopologyGraph] | None = None,
    filter_factory: Any = None,
) -> RestStack:
    """Compose the SPEC-500 §4 app over the real M3 backends (#48 posture;
    §4.4/§4.5 unbound — see the module docstring)."""
    # check_same_thread=False: the #43 bounded-worker pool writes the tee
    # legs from its worker threads (same posture as the ws_stack journal).
    connection = db.connect(root / "rest-api.sqlite3", check_same_thread=False)
    db.migrate(connection, default_migrations_dir())
    repository = SqliteArtifactRepository(connection)
    store = ArtifactStore(root / "artifacts", index=repository)
    sink = StoreArtifactSink(store, index=repository)

    runtime = SimulationRuntime()
    session_specs: dict[str, SimulationSessionSpec] = {}
    sessions_backend = SimulationSessionsBackend(
        runtime,
        topology_provider or default_topology_provider,
        session_specs,
    )
    allocator = RunIdAllocator(runtime)
    ts_runtime = TSRuntime(
        runtime=allocator,  # structural shim: duck-types the run face
        # 裁定 1b: the production semantic filter is the default — the
        # identity placeholder retired with ticket #53.
        filter_factory=filter_factory or build_semantic_filter_factory(),
    )
    runs_backend = SimulationRunsBackend(
        ts_runtime, runtime, session_specs, sink, allocator
    )
    artifacts_backend = ArtifactStoreBackend(store, repository)

    app = create_app(
        *build_spec500_routers(
            sessions_port=sessions_backend,
            runs_port=runs_backend,
            artifacts_port=artifacts_backend,
        )
    )
    return RestStack(
        app=app,
        sessions_backend=sessions_backend,
        runs_backend=runs_backend,
        artifacts_backend=artifacts_backend,
        runtime=runtime,
        ts_runtime=ts_runtime,
        store=store,
        repository=repository,
        session_specs=session_specs,
    )
