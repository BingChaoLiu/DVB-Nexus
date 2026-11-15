"""Export task registry — SPEC-305 §4 export rows (ticket #53).

``POST .../exports`` creates ONLY an Observation export task (the read-only
discipline: it never creates or mutates a simulation session, SPEC-305 §4);
``GET .../exports/{export_id}`` reads the task's status/manifest. The build
itself is the #51 pure export pipeline (``build_export`` — bytes in memory,
manifest with per-file SHA-256, redaction + secret scan); this registry
adds the SPEC-305 §9 service posture around it:

- **限流**: a bounded per-session task budget — over-limit creates are the
  429 row (``RateLimitedError``, retryable);
- **scope**: task ids are global but reads are session-scoped — a foreign
  session's id is the 403 row (``OBS_SCOPE_FORBIDDEN``); an unknown id is
  the 404 row (``PLT_ARTIFACT_NOT_FOUND`` — the export manifest is the
  metadata record of the produced export files, the Platform record family);
- **hints**: every completed task emits one ``observation.export_progress``
  hint through the injected publisher (SPEC-305 §8; best-effort — publisher
  failures never break the task).

MVP tasks complete synchronously (the timeline record store is in-memory
and bounded) and are retained for the process lifetime; file bytes are NOT
retained after the manifest is built — the manifest's per-file digests are
the durable answer (a re-run of the same interval + options reproduces the
same digests, SPEC-303 §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from application.errors import ForbiddenError, NotFoundError, RateLimitedError

from application.observation.query.errors import OBS_SCOPE_FORBIDDEN
from application.observation.timeline.export import (
    EXPORT_FORMAT_JSONL,
    ExportRequest,
    build_export,
)
from domain.observation import TimelineTimepoint

#: The SPEC-305 §8 hint topic for export progress.
EXPORT_PROGRESS_TOPIC = "observation.export_progress"

#: The Platform 404 code (registered by #53 in SPEC-300 §13): the export
#: manifest is a Platform record-metadata family (per-file digests).
PLT_ARTIFACT_NOT_FOUND = "PLT_ARTIFACT_NOT_FOUND"

#: The registered HTTP_<status> fallback-convention code for the 429 row
#: (SPEC-300 §13 defines no dedicated rate-limit code).
HTTP_429 = "HTTP_429"

#: Default per-session task budget (SPEC-305 §9 限流, 默认保守).
DEFAULT_MAX_EXPORTS_PER_SESSION = 32

VALID_EXPORT_FORMATS = ("jsonl", "csv", "zip")
VALID_REDACTION_POLICIES = ("none", "strip_payloads")


@dataclass(frozen=True)
class ExportTaskRequest:
    """One export task request (SPEC-303 §7 options, session-scoped)."""

    session_id: str
    formats: tuple[str, ...] = (EXPORT_FORMAT_JSONL,)
    redaction_policy: str = "none"
    record_kinds: tuple[str, ...] = ()
    clock_domain: Optional[str] = None
    clock_epoch: Optional[int] = None
    start_ns: Optional[int] = None
    end_ns: Optional[int] = None


@dataclass(frozen=True)
class ExportTaskView:
    """One task's REST answer: identity, status, manifest, file digests."""

    export_id: str
    session_id: str
    status: str
    manifest: dict = field(default_factory=dict)
    file_digests: dict[str, str] = field(default_factory=dict)
    schema_version: str = "1.0"


class ExportTaskRegistry:
    """Bounded, session-scoped export task store (read-side only)."""

    def __init__(
        self,
        *,
        records_provider: Callable[..., Any],
        export_id_factory: Callable[[], str],
        created_at_factory: Callable[[], TimelineTimepoint],
        hint_publisher: Optional[Any] = None,
        tenant_id: str = "local",
        max_exports_per_session: int = DEFAULT_MAX_EXPORTS_PER_SESSION,
    ) -> None:
        self._records_provider = records_provider
        self._export_id_factory = export_id_factory
        self._created_at_factory = created_at_factory
        self._hints = hint_publisher
        self._tenant_id = tenant_id
        self._max_per_session = max_exports_per_session
        self._tasks: dict[str, ExportTaskView] = {}
        self._by_session: dict[str, list[str]] = {}

    # --- POST .../exports ---------------------------------------------------

    def create(self, request: ExportTaskRequest) -> ExportTaskView:
        """Create (and, MVP-synchronously, complete) one export task."""
        _validate_export_request(request)
        held = self._by_session.get(request.session_id, [])
        if len(held) >= self._max_per_session:
            raise RateLimitedError(
                HTTP_429,
                f"session {request.session_id!r} holds {len(held)} export "
                f"tasks; the limit is {self._max_per_session} (SPEC-305 §9 "
                "导出任务限流)",
                details={"limit": self._max_per_session, "held": len(held)},
            )
        export_id = self._export_id_factory()
        records = self._records_provider(
            request.session_id,
            clock_domain=request.clock_domain,
            clock_epoch=request.clock_epoch,
            start_ns=request.start_ns,
            end_ns=request.end_ns,
            record_kinds=request.record_kinds,
        )
        result = build_export(
            records,
            ExportRequest(
                export_id=export_id,
                created_at=self._created_at_factory(),
                session_id=request.session_id,
                tenant_id=self._tenant_id,
                formats=request.formats,
                redaction_policy=request.redaction_policy,
                clock_domain=request.clock_domain,
                start_ns=request.start_ns,
                end_ns=request.end_ns,
                record_kinds=request.record_kinds,
            ),
        )
        view = ExportTaskView(
            export_id=export_id,
            session_id=request.session_id,
            status="completed",
            manifest=result.manifest,
            file_digests=dict(result.file_digests),
        )
        self._tasks[export_id] = view
        self._by_session.setdefault(request.session_id, []).append(export_id)
        self._publish_progress(view)
        return view

    # --- GET .../exports/{export_id} ------------------------------------------

    def get(self, session_id: str, export_id: str) -> ExportTaskView:
        """Read one task (scope-forced). Unknown → 404 row; a task belonging
        to another session → 403 row."""
        task = self._tasks.get(export_id)
        if task is None:
            raise NotFoundError(
                PLT_ARTIFACT_NOT_FOUND,
                f"unknown export {export_id!r} in session {session_id!r} "
                "(SPEC-305 §7 row 404)",
            )
        if task.session_id != session_id:
            raise ForbiddenError(
                OBS_SCOPE_FORBIDDEN,
                f"export {export_id!r} belongs to session {task.session_id!r}; "
                f"the request scope is {session_id!r} (SPEC-305 §7 row 403)",
                details={"export_session": task.session_id},
            )
        return task

    # --- internals ---------------------------------------------------------------

    def _publish_progress(self, task: ExportTaskView) -> None:
        if self._hints is None:
            return
        try:
            self._hints.publish(
                task.session_id,
                EXPORT_PROGRESS_TOPIC,
                {
                    "export_id": task.export_id,
                    "status": task.status,
                    "total_records": task.manifest.get("total_records"),
                },
            )
        except Exception:
            # Hints are best-effort (SPEC-305 §8) — a publisher failure must
            # never break the task itself.
            pass


def _validate_export_request(request: ExportTaskRequest) -> None:
    from application.errors import BadRequestError, REQUEST_BODY_INVALID

    for fmt in request.formats:
        if fmt not in VALID_EXPORT_FORMATS:
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                f"export format {fmt!r} is not one of {VALID_EXPORT_FORMATS}",
                details={"param": "formats"},
            )
    if request.redaction_policy not in VALID_REDACTION_POLICIES:
        raise BadRequestError(
            REQUEST_BODY_INVALID,
            f"redaction_policy {request.redaction_policy!r} is not one of "
            f"{VALID_REDACTION_POLICIES}",
            details={"param": "redaction_policy"},
        )
    if (
        request.start_ns is not None
        and request.end_ns is not None
        and request.start_ns >= request.end_ns
    ):
        from application.errors import SemanticValidationError

        raise SemanticValidationError(
            "OBS_QUERY_RANGE_TOO_LARGE",
            "start_ns must be < end_ns (SPEC-305 §5)",
            details={"start_ns": request.start_ns, "end_ns": request.end_ns},
        )


__all__ = [
    "DEFAULT_MAX_EXPORTS_PER_SESSION",
    "EXPORT_PROGRESS_TOPIC",
    "HTTP_429",
    "ExportTaskRegistry",
    "ExportTaskRequest",
    "ExportTaskView",
    "PLT_ARTIFACT_NOT_FOUND",
    "VALID_EXPORT_FORMATS",
    "VALID_REDACTION_POLICIES",
]
