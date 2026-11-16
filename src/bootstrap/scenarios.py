"""Scenario composition adapters (ticket #80, SPEC-205 × SPEC-500 §4.7/
§4.2) — the registry, the solution-reveal gate and the scenario error
translation.

- :class:`ScenarioRegistry` — the composition-time directory scan (裁定 F
  fallback: repo-top-level ``scenarios/``; ``SC-01~05`` file bodies are
  ticket #67's创作义务). Every ``*.json`` file is parsed through the
  production loader face (:func:`load_scenario_file` — schema gate,
  path-addressed rejections); the registry indexes
  ``{scenario_id: document}``. A **missing directory is an empty
  registry** (the pre-#67 posture — nothing to serve, list answers 200
  ``[]``); a **malformed file fails fast at composition** (SPEC-502 §7
  迁移失败 posture: a broken deployment artifact is a startup error, not a
  per-request surprise). The registry order is filename-ASC (deterministic
  list answers).
- :class:`RegistryScenarioPort` — the api ``ScenarioPort`` backend: list
  projection / export-face detail (hidden solution stripped by
  construction) / the reveal gate.
- :class:`RegistrySolutionGate` — 裁定 F: the session+scenario pair must
  carry a verdict=PASS SPEC-206 row (read from the SPEC-502
  ``verification_verdicts`` table) before
  :func:`reveal_hidden_solution` grants access; everything else is 403
  ``SIM_SCENARIO_SOLUTION_LEAK`` (SPEC-205 §7 row 6, refuse AND audit).
  A PASS on a scenario that declares no hidden field yields ``None`` (200
  ``hidden_reference_solution: null``, orchestrator OQ-3).
- :func:`translate_scenario_error` — the simulation scenario error family
  → application categories (the composition-root concern, the
  ``_translate_simulation_error`` neighbor in ``backends.py``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from simulation.scenario.loader import load_scenario_file
from simulation.scenario.schema import (
    SIM_SCENARIO_SOLUTION_LEAK,
    ScenarioDocument,
    ScenarioSolutionLeakError,
    ScenarioVersionConflictError,
    export_scenario_document,
)
from simulation.errors import SimulationIOError

from api.dto.scenarios import (
    ScenarioDetailDTO,
    ScenarioSolutionDTO,
    ScenarioSummaryDTO,
)
from application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    SemanticValidationError,
    ServiceUnavailableError,
)
from application.observation.errors import OBS_STORAGE_UNAVAILABLE

from adapters.storage.repositories import (
    SqliteVerificationRepository,
    VerdictRecord,
)

__all__ = [
    "RegistryScenarioPort",
    "RegistrySolutionGate",
    "ScenarioRegistry",
    "translate_scenario_error",
]

_LOG = logging.getLogger(__name__)


class ScenarioRegistry:
    """The composition-time scenario registry (read-only, SPEC-205)."""

    def __init__(self, scenario_dir: Path) -> None:
        self.scenario_dir = Path(scenario_dir)
        self._documents: dict[str, ScenarioDocument] = {}
        self._scan()

    def _scan(self) -> None:
        if not self.scenario_dir.is_dir():
            # Missing directory = empty registry (pre-#67 posture).
            _LOG.info(
                "scenario registry: %s does not exist — empty registry",
                self.scenario_dir,
            )
            return
        for path in sorted(self.scenario_dir.glob("*.json")):
            document = load_scenario_file(path)  # fail-fast on malformed
            self._documents[document.scenario_id] = document
        _LOG.info(
            "scenario registry: %d document(s) from %s",
            len(self._documents),
            self.scenario_dir,
        )

    def require(self, scenario_id: str) -> ScenarioDocument:
        document = self._documents.get(scenario_id)
        if document is None:
            raise NotFoundError(
                "SIM_SCENARIO_NOT_FOUND",
                f"unknown scenario {scenario_id!r}: not in the registry"
                f" (scan root {self.scenario_dir.name!r}; SPEC-500 §6 row 404)",
            )
        return document

    def ordered(self) -> list[ScenarioDocument]:
        """Filename-ASC determinism (the scan insertion order)."""
        return list(self._documents.values())


class RegistrySolutionGate:
    """裁定 F: the backend reveal gate over ``verification_verdicts``."""

    def __init__(self, registry: ScenarioRegistry, verdicts: SqliteVerificationRepository) -> None:
        self._registry = registry
        self._verdicts = verdicts

    def reveal(self, scenario_id: str, session_id: str) -> ScenarioSolutionDTO:
        document = self._registry.require(scenario_id)
        if not self._has_pass(session_id, scenario_id):
            raise ForbiddenError(
                SIM_SCENARIO_SOLUTION_LEAK,
                "hidden reference solution reveal refused: no PASS verdict"
                f" for session {session_id!r} on scenario {scenario_id!r}"
                " (SPEC-205 §7 row 6; the refusal is audited)",
            )
        solution = document.hidden_reference_solution
        if solution is None:
            # PASS granted but the scenario declares no hidden field —
            # 200 with explicit null (orchestrator OQ-3; no fabricated text).
            return ScenarioSolutionDTO(
                scenario_id=scenario_id, hidden_reference_solution=None
            )
        return ScenarioSolutionDTO(
            scenario_id=scenario_id, hidden_reference_solution=solution
        )

    def _has_pass(self, session_id: str, scenario_id: str) -> bool:
        verdicts: list[VerdictRecord] = self._verdicts.query(session_id)
        return any(
            verdict.verdict == "PASS" and verdict.scenario_id == scenario_id
            for verdict in verdicts
        )


class RegistryScenarioPort:
    """The api ``ScenarioPort`` backend over the registry + gate."""

    def __init__(
        self,
        registry: ScenarioRegistry,
        solution_gate: RegistrySolutionGate,
    ) -> None:
        self._registry = registry
        self._gate = solution_gate

    def list_scenarios(self) -> list[ScenarioSummaryDTO]:
        return [
            ScenarioSummaryDTO(
                scenario_id=document.scenario_id,
                version=document.version,
                title=document.title,
                difficulty=document.difficulty,
            )
            for document in self._registry.ordered()
        ]

    def get(self, scenario_id: str) -> ScenarioDetailDTO:
        document = self._registry.require(scenario_id)
        # export_scenario_document: hidden solution stripped by default +
        # the executable-content defense-in-depth scan (REQ-SIM-205-003).
        exported = export_scenario_document(document)
        # SPEC-408 §6.4 (ticket #94): the loader's pinned SHA-256 (the
        # SPEC-205 §5 version-pinning identity) rides the detail answer;
        # the export face itself does not carry it, so it is injected here
        # from the document.
        return ScenarioDetailDTO(content_hash=document.content_hash, **exported)

    def reveal(self, scenario_id: str, session_id: str) -> ScenarioSolutionDTO:
        return self._gate.reveal(scenario_id, session_id)


def translate_scenario_error(exc: Exception) -> Optional[Exception]:
    """Simulation scenario error family → application categories by code
    (the composition-root translation; ``api.errors`` renders the §6
    rows). ``None`` = not a scenario-family error (caller re-raises)."""
    code = getattr(exc, "code", None)
    if code == SIM_SCENARIO_SOLUTION_LEAK or isinstance(
        exc, ScenarioSolutionLeakError
    ):
        return ForbiddenError(SIM_SCENARIO_SOLUTION_LEAK, str(exc))
    if isinstance(exc, ScenarioVersionConflictError):
        return ConflictError("SIM_SCENARIO_VERSION_CONFLICT", str(exc))
    if isinstance(exc, SimulationIOError):
        return ServiceUnavailableError(OBS_STORAGE_UNAVAILABLE, str(exc))
    if code is not None and str(code).startswith("SIM_SCENARIO_"):
        # Schema/criterion/fault-plan rejections — the 422 semantic row.
        return SemanticValidationError(str(code), str(exc))
    return None
