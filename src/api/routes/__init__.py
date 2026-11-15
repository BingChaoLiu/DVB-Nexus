"""Route assembly for the SPEC-500 §4 inventory (ticket #48).

The composition-root helper: builds the full frozen-table router set from
the three M3-wired ports (sessions / runs / artifacts) plus the 501
mount-point routers (observation §4.5, topology §4.1, diagnosis §4.4,
scenario §4.7). Routers carry no prefix themselves — ``api.app.create_app``
mounts everything under the frozen ``/api/v1`` prefix (single mount point,
additive-only policy, SPEC-500 §3).

The port interfaces are structural Protocols owned by the route modules;
the api layer never imports ``simulation`` / ``ts`` / ``adapters``
(import-linter C6) — the composition root binds the real #41/#43/#42
backends. See ``src/api/README.md`` for the layer posture.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.artifacts import ArtifactsPort, build_artifacts_router
from api.routes.observation import (
    ObservationQueryPort,
    build_observation_router,
)
from api.routes.pending import (
    DiagnosisPort,
    VerificationPort,
    build_pending_router,
)
from api.routes.runs import RunsPort, build_runs_router
from api.routes.sessions import SessionsPort, build_sessions_router

__all__ = [
    "ArtifactsPort",
    "DiagnosisPort",
    "ObservationQueryPort",
    "RunsPort",
    "SessionsPort",
    "VerificationPort",
    "build_spec500_routers",
]


def build_spec500_routers(
    *,
    sessions_port: SessionsPort,
    runs_port: RunsPort,
    artifacts_port: ArtifactsPort,
    diagnosis_port: DiagnosisPort | None = None,
    observation_port: ObservationQueryPort | None = None,
    verification_port: VerificationPort | None = None,
) -> list[APIRouter]:
    """Assemble the complete SPEC-500 §4 router set.

    Args:
        sessions_port: the SPEC-200 lifecycle backend (§4.2, wired).
        runs_port: the run async-job backend (§4.3, wired).
        artifacts_port: the #42 artifact read boundary (§4.6, wired).
        diagnosis_port: optional SPEC-306 backend for the §4.4 diagnosis
          endpoints (ticket #54; ``None`` keeps their 501 freeze answers —
          the composition root binds ``ServiceDiagnosisPort`` when the
          diagnosis service is in the stack).
        observation_port: optional SPEC-305 backend for the §4.5
          observation endpoints (ticket #53; ``None`` keeps their 501
          freeze answers — the composition root binds
          ``ServiceObservationQueryPort`` when the query plane is in the
          stack).
        verification_port: optional SPEC-206 backend for the §4.4 verify
          endpoint (ticket #56; ``None`` keeps the 501 freeze answer —
          the composition root binds ``ServiceVerificationPort`` when the
          verification service is in the stack).
    """
    return [
        build_sessions_router(sessions_port),
        build_runs_router(runs_port),
        build_artifacts_router(artifacts_port),
        build_observation_router(query_port=observation_port),
        build_pending_router(
            diagnosis_port=diagnosis_port,
            verification_port=verification_port,
        ),
    ]
