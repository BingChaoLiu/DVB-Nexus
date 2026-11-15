"""Frozen-table routes whose backing use-cases arrive with M4 (SPEC-500
§4.4/§4.7, tickets #48/#54/#56).

Route-table freeze discipline (REQ-API-500-001): the §4 inventory is the
authority, so these routes are **mounted now** and answer **501 Not
Implemented** through the unified envelope until their backends land:

- §4.4 Diagnosis/Recovery: ticket #54 wires the TWO diagnosis endpoints
  (``GET .../diagnoses`` list, ``POST .../runs/{run_id}/diagnose``
  idempotent re-evaluation) behind the optional ``diagnosis_port``;
  ticket #56 wires ``POST .../verify`` (SPEC-206 three-state verdict)
  behind the optional ``verification_port``. An unbound port (composition
  root has no service yet) keeps the 501 freeze answer.

(The §4.1 topology ×5 and §4.7 scenario ×2 stubs lived here until ticket
#80 moved them behind ``api.routes.topology`` / ``api.routes.scenarios``
port modules — same paths, same unbound 501 envelopes.)

Each stub documents exactly which spec owns the future semantics so the
additive-only evolution (SPEC-500 §3) can replace the handler in place
without touching the path inventory.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from fastapi import APIRouter
from starlette.exceptions import HTTPException

from api.dto.diagnosis import (
    DiagnosisDTO,
    DiagnosisReportDTO,
    diagnosis_dto_from_record,
    diagnosis_report_dto_from_report,
)
from api.dto.verification import (
    VerifyRunRequest,
    VerificationResultDTO,
    verification_result_dto_from_result,
)
from application.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    SemanticValidationError,
    ServiceUnavailableError,
)
from application.observation.errors import OBS_STORAGE_UNAVAILABLE

__all__ = [
    "DiagnosisPort",
    "ServiceDiagnosisPort",
    "ServiceVerificationPort",
    "VerificationPort",
    "build_pending_router",
]

_501 = 501

_DIAGNOSIS_DETAIL = (
    "diagnosis evaluation (SPEC-306) / verification (SPEC-206) lands with "
    "the M4 diagnosis chain; the route is mounted per the SPEC-500 §4.4 "
    "freeze"
)
_VERIFY_DETAIL = (
    "recovery verification (SPEC-206 three-state) is wired through the "
    "optional verification_port (ticket #56); an unbound port keeps the "
    "SPEC-500 §4.4 freeze answer"
)


class DiagnosisPort(Protocol):
    """The §4.4 diagnosis face as seen from the REST layer (structural —
    import-linter C6 pins the api layer to ``application``-only imports).
    Implementations return the api-owned DTOs and raise the application
    error categories; ``api.errors`` renders the SPEC-500 §6 rows
    (404 unknown session/run, 503 storage unavailable)."""

    async def list_diagnoses(self, session_id: str) -> Sequence[DiagnosisDTO]: ...

    async def diagnose(self, session_id: str, run_id: str) -> DiagnosisReportDTO: ...


class ServiceDiagnosisPort:
    """Built-in port adapter: wraps an application diagnosis service into
    :class:`DiagnosisPort`. The mapping lives in the api layer (it owns
    the DTOs); the service object stays duck-typed so the adapter never
    imports ``domain`` (C6)."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def list_diagnoses(self, session_id: str) -> list[DiagnosisDTO]:
        return [
            diagnosis_dto_from_record(record)
            for record in self._service.list_diagnoses(session_id)
        ]

    async def diagnose(self, session_id: str, run_id: str) -> DiagnosisReportDTO:
        return diagnosis_report_dto_from_report(
            self._service.evaluate(session_id, run_id)
        )


class VerificationPort(Protocol):
    """The §4.4 recovery-verification face as seen from the REST layer
    (structural — import-linter C6 pins the api layer to
    ``application``-only imports). Implementations return the api-owned
    DTOs and raise the application error categories; ``api.errors`` renders
    the SPEC-500 §6 rows (400 body invalid, 404 unknown session, 409 run
    mismatch, 422 criterion invalid, 503 storage unavailable)."""

    async def verify_run(
        self, session_id: str, run_id: str, request: VerifyRunRequest
    ) -> VerificationResultDTO: ...


#: Simulation error codes → application categories + the registry code the
#: rendered envelope carries (the api layer owns the HTTP mapping, SPEC-500
#: §6; the verification service raises the simulation family — this
#: declarative table is the translation seam; storage rows keep the
#: OBS_STORAGE_UNAVAILABLE registry code per SPEC-300 §13).
_VERIFICATION_ERROR_TRANSLATION: tuple[tuple[str, Any, str], ...] = (
    ("SIM_SESSION_NOT_FOUND", NotFoundError, "SIM_SESSION_NOT_FOUND"),
    ("SIM_VERIF_RUN_MISMATCH", ConflictError, "SIM_VERIF_RUN_MISMATCH"),
    (
        "SIM_VERIF_CRITERION_INVALID",
        SemanticValidationError,
        "SIM_VERIF_CRITERION_INVALID",
    ),
    (
        "SIM_IO_ERROR",
        ServiceUnavailableError,
        OBS_STORAGE_UNAVAILABLE,
    ),
)


class ServiceVerificationPort:
    """Built-in port adapter over the SPEC-206 verification service.

    The service object stays duck-typed (never imported here — C6); its
    simulation-family errors are translated by ``code`` onto the
    application categories, and storage failures map to the 503 row (the
    diagnosis-service adapter posture).
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    async def verify_run(
        self, session_id: str, run_id: str, request: VerifyRunRequest
    ) -> VerificationResultDTO:
        try:
            result = self._service.verify(
                session_id,
                run_id,
                baseline_run_id=request.baseline_run_id,
                scenario_id=request.scenario.scenario_id,
                scenario_version=request.scenario.version,
                scenario_content_hash=request.scenario.content_hash,
                pass_criteria=[
                    {
                        "criterion_id": entry.criterion_id,
                        "kind": entry.kind,
                        "mandatory": entry.mandatory,
                        "fault_id": entry.fault_id,
                    }
                    for entry in request.pass_criteria
                ],
                ui_state=request.ui_state,
            )
        except Exception as exc:  # noqa: BLE001 — translated below by code
            # Application-category errors (no ``.code`` attribute) pass
            # through unchanged; simulation-family codes map onto the
            # SPEC-500 §6 rows via the declarative table.
            translated = _translate_verification_error(exc)
            if translated is not None:
                raise translated from exc
            raise
        return verification_result_dto_from_result(result)


def _translate_verification_error(exc: Exception) -> Exception | None:
    """Map a simulation-family error onto an application category by code."""
    code = getattr(exc, "code", None)
    for known_code, category, envelope_code in _VERIFICATION_ERROR_TRANSLATION:
        if code == known_code:
            return category(envelope_code, str(exc))
    return None


def build_pending_router(
    *,
    diagnosis_port: DiagnosisPort | None = None,
    verification_port: VerificationPort | None = None,
) -> APIRouter:
    """Build the §4.4/§4.7 router (frozen table presence).

    ``diagnosis_port=None`` keeps the §4.4 diagnosis endpoints on the 501
    freeze answer; binding a port switches exactly those two handlers to
    the SPEC-306 service (additive wiring — the paths/methods never
    change, SPEC-500 §3). ``verification_port=None`` keeps ``POST
    .../verify`` on the 501 freeze answer; binding it switches the handler
    to the SPEC-206 three-state verdict (ticket #56).
    """
    router = APIRouter()

    # --- §4.4 Diagnosis / Recovery ------------------------------------------

    @router.get("/sessions/{session_id}/diagnoses")
    async def list_diagnoses(session_id: str) -> list[DiagnosisDTO]:
        if diagnosis_port is None:
            raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)
        return list(await diagnosis_port.list_diagnoses(session_id))

    @router.post("/sessions/{session_id}/runs/{run_id}/diagnose")
    async def diagnose_run(session_id: str, run_id: str) -> DiagnosisReportDTO:
        # Idempotent re-evaluation (SPEC-306 §5 evaluate).
        if diagnosis_port is None:
            raise HTTPException(status_code=_501, detail=_DIAGNOSIS_DETAIL)
        return await diagnosis_port.diagnose(session_id, run_id)

    @router.post("/sessions/{session_id}/runs/{run_id}/verify")
    async def verify_run(
        session_id: str,
        run_id: str,
        request: VerifyRunRequest | None = None,
    ) -> VerificationResultDTO:
        # Three-state PASS/FAIL/INCONCLUSIVE (SPEC-206, ticket #56). The
        # body stays optional so an unbound port keeps the exact freeze
        # answer for any POST shape; a bound port requires the body.
        if verification_port is None:
            raise HTTPException(status_code=_501, detail=_VERIFY_DETAIL)
        if request is None:
            raise BadRequestError(
                "REQUEST_BODY_INVALID",
                "verify requires a JSON body (baseline_run_id, scenario,"
                " pass_criteria; SPEC-206)",
            )
        return await verification_port.verify_run(session_id, run_id, request)

    return router
