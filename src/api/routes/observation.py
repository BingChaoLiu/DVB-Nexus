"""SPEC-305 observation query routes — the §4.5 frozen table, wired
(ticket #53).

The eight endpoints landed verbatim in M3 (#48) as 501 mount points; this
module now binds them to the observation query plane behind the
``ObservationQueryPort`` (additive-only evolution, SPEC-500 §3: same
paths, same methods, same order as the frozen table). An unbound port
keeps the 501 freeze answers — the composition root decides (the
``diagnosis_port`` posture of ticket #54).

The port is structural (import-linter C6 pins ``api`` to
``application``-only imports); :class:`ServiceObservationQueryPort` wraps
the application query service (``application.observation.query``) and
maps its answers onto the §6 envelope. Application error categories carry
their SPEC-300 §13 registry codes — ``api.errors`` renders the SPEC-305
§7 error envelope on the frozen HTTP rows.

Read-only discipline (REQ-OBS-305-001): every handler is a pure query —
the export POST creates only an Observation export task and never touches
the simulation plane.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from fastapi import APIRouter, Query, Request
from starlette.exceptions import HTTPException

from api.dto.observation import (
    AlertsDataDTO,
    EventsDataDTO,
    ExportCreateBody,
    ExportDataDTO,
    HealthDataDTO,
    MetricsDataDTO,
    MetricsQueryBody,
    ObservationMetaDTO,
    ObservationResponseDTO,
    ObservationScopeDTO,
    SummaryDataDTO,
    TimelineDataDTO,
    alert_record_dto,
    health_result_dto,
    metric_series_dto,
    timeline_record_dto,
)
from application.context import LOCAL_TENANT_ID
from application.errors import REQUEST_BODY_INVALID, BadRequestError

__all__ = [
    "ObservationQueryPort",
    "ServiceObservationQueryPort",
    "build_observation_router",
]

_501_DETAIL = (
    "observation query processing is not bound in this composition (the "
    "route stays mounted per the SPEC-500 §4.5 freeze)"
)


class ObservationQueryPort(Protocol):
    """The §4.5 observation face as seen from the REST layer (structural).

    Implementations return the §6 envelope pieces (scope/data/meta minus
    the per-request id) and raise the application error categories; the
    framework error handlers render the SPEC-305 §7 envelope.
    """

    async def summary(self, session_id: str) -> ObservationResponseDTO: ...

    async def events(self, session_id: str, **params: Any) -> ObservationResponseDTO: ...

    async def timeline(
        self, session_id: str, **params: Any
    ) -> ObservationResponseDTO: ...

    async def metrics_query(
        self, session_id: str, body: MetricsQueryBody
    ) -> ObservationResponseDTO: ...

    async def alerts(self, session_id: str, **params: Any) -> ObservationResponseDTO: ...

    async def health(self, session_id: str, **params: Any) -> ObservationResponseDTO: ...

    async def export(
        self, session_id: str, export_id: str
    ) -> ObservationResponseDTO: ...

    async def create_export(
        self, session_id: str, body: ExportCreateBody
    ) -> ObservationResponseDTO: ...


class ServiceObservationQueryPort:
    """Built-in port adapter over ``application.observation.query`` (the
    #53 query plane). The mapping lives in the api layer (it owns the
    DTOs); the service object stays duck-typed so this adapter never
    imports ``domain`` (C6)."""

    def __init__(self, service: Any, *, tenant_id: str = LOCAL_TENANT_ID) -> None:
        self._service = service
        self._tenant_id = tenant_id

    def _envelope(
        self,
        session_id: str,
        data: Any,
        *,
        next_cursor: Optional[str] = None,
        truncated: bool = False,
        clock_domain: Optional[str] = None,
    ) -> ObservationResponseDTO:
        return ObservationResponseDTO(
            request_id="",  # stamped by the route handler (per-request id)
            scope=ObservationScopeDTO(
                tenant_id=self._tenant_id, session_id=session_id
            ),
            data=data,
            meta=ObservationMetaDTO(
                next_cursor=next_cursor,
                truncated=truncated,
                clock_domain=clock_domain,
            ),
        )

    async def summary(self, session_id: str) -> ObservationResponseDTO:
        result = self._service.get_session_summary(session_id)
        return self._envelope(
            session_id,
            SummaryDataDTO(
                tenant_id=result.tenant_id,
                session_id=result.session_id,
                journal_seq_watermark=result.journal_seq_watermark,
                event_count=result.event_count,
                active_alert_count=result.active_alert_count,
            ),
        )

    async def events(self, session_id: str, **params: Any) -> ObservationResponseDTO:
        page = self._service.query_events(
            session_id=session_id,
            limit=params.get("limit", 100),
            cursor=params.get("cursor"),
            sort=params.get("sort", "journal_asc"),
            event_types=tuple(params.get("event_type") or ()),
            severities=tuple(params.get("severity") or ()),
            producer_ids=tuple(params.get("producer_id") or ()),
            run_id=params.get("run_id"),
            clock_domain=params.get("clock_domain"),
            clock_epoch=params.get("clock_epoch"),
            start_ns=params.get("start_ns"),
            end_ns=params.get("end_ns"),
        )
        return self._envelope(
            session_id,
            EventsDataDTO(sort=page.sort, items=list(page.items)),
            next_cursor=page.next_cursor,
            truncated=page.truncated,
            clock_domain=page.clock_domain,
        )

    async def timeline(self, session_id: str, **params: Any) -> ObservationResponseDTO:
        page = self._service.query_timeline(
            session_id,
            page_size=params.get("limit", 500),
            cursor=params.get("cursor"),
            record_kinds=tuple(params.get("record_kind") or ()),
            scenario_id=params.get("scenario_id"),
            event_types=tuple(params.get("event_type") or ()),
            severities=tuple(params.get("severity") or ()),
            producer_ids=tuple(params.get("producer_id") or ()),
            node_id=params.get("node_id"),
            service_id=params.get("service_id"),
            pid=params.get("pid"),
            fault_id=params.get("fault_id"),
            tags=tuple(params.get("tag") or ()),
            clock_domain=params.get("clock_domain"),
            clock_epoch=params.get("clock_epoch"),
            start_ns=params.get("start_ns"),
            end_ns=params.get("end_ns"),
            lanes=bool(params.get("lanes", False)),
        )
        lanes = None
        if page.lanes:
            lanes = [
                {
                    "clock_domain": lane.clock_domain,
                    "clock_epoch": lane.clock_epoch,
                    "sort_descriptor": lane.sort_descriptor,
                    "records": [timeline_record_dto(r) for r in lane.records],
                }
                for lane in page.lanes
            ]
        data = TimelineDataDTO(
            sort_descriptor=page.sort_descriptor,
            records=[timeline_record_dto(record) for record in page.records],
            lanes=lanes,
        )
        return self._envelope(
            session_id,
            data,
            next_cursor=page.next_cursor,
            truncated=page.truncated,
            clock_domain=params.get("clock_domain"),
        )

    async def metrics_query(
        self, session_id: str, body: MetricsQueryBody
    ) -> ObservationResponseDTO:
        result = self._service.query_metrics(
            session_id,
            metric_names=tuple(body.metric_names),
            start_ns=body.start_ns,
            end_ns=body.end_ns,
            step_ns=body.step_ns,
            clock_domain=body.clock_domain,
            filters=body.filters,
            max_points=body.max_points,
            aggregation_override=body.aggregation_override,
            allow_unknown=body.allow_unknown,
        )
        data = MetricsDataDTO(
            series=[metric_series_dto(view) for view in result.series],
            bucket_convention=result.bucket_convention,
            clock_domain=result.clock_domain,
        )
        return self._envelope(session_id, data, clock_domain=result.clock_domain)

    async def alerts(self, session_id: str, **params: Any) -> ObservationResponseDTO:
        page = self._service.list_alerts(
            session_id,
            rule_id=params.get("rule_id"),
            state=params.get("state"),
            severity=params.get("severity"),
            suppressed=params.get("suppressed"),
            limit=params.get("limit", 100),
            cursor=params.get("cursor"),
        )
        data = AlertsDataDTO(
            items=[alert_record_dto(record) for record in page.items],
            total=page.total,
        )
        return self._envelope(
            session_id,
            data,
            next_cursor=page.next_cursor,
            truncated=page.truncated,
        )

    async def health(self, session_id: str, **params: Any) -> ObservationResponseDTO:
        result = self._service.health(
            session_id,
            clock_domain=params["clock_domain"],
            now_ns=params["now_ns"],
            clock_epoch=params.get("clock_epoch", 0),
        )
        data = health_result_dto(result)
        return self._envelope(session_id, data, clock_domain=result.clock_domain)

    async def export(self, session_id: str, export_id: str) -> ObservationResponseDTO:
        task = self._service.get_export(session_id, export_id)
        data = ExportDataDTO(
            export_id=task.export_id,
            session_id=task.session_id,
            status=task.status,
            manifest=task.manifest,
            file_digests=task.file_digests,
        )
        return self._envelope(
            session_id, data, clock_domain=task.manifest.get("clock_domain")
        )

    async def create_export(
        self, session_id: str, body: ExportCreateBody
    ) -> ObservationResponseDTO:
        task = self._service.create_export(
            session_id=session_id,
            formats=tuple(body.formats),
            redaction_policy=body.redaction_policy,
            record_kinds=tuple(body.record_kinds),
            clock_domain=body.clock_domain,
            clock_epoch=body.clock_epoch,
            start_ns=body.start_ns,
            end_ns=body.end_ns,
        )
        data = ExportDataDTO(
            export_id=task.export_id,
            session_id=task.session_id,
            status=task.status,
            manifest=task.manifest,
            file_digests=task.file_digests,
        )
        return self._envelope(
            session_id, data, clock_domain=task.manifest.get("clock_domain")
        )


def build_observation_router(
    query_port: ObservationQueryPort | None = None,
) -> APIRouter:
    """Build the §4.5 observation router (SPEC-500 §4.5, verbatim paths).

    ``query_port=None`` keeps the eight routes on the 501 freeze answer
    (the unbound composition); binding a port switches the handlers to
    the SPEC-305 query plane in place — the path inventory never changes.
    """
    router = APIRouter()

    # --- §4.5 Observation (SPEC-305 §4, verbatim order) --------------------

    @router.get("/sessions/{session_id}/observation/summary")
    async def observation_summary(session_id: str, request: Request) -> dict:
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        envelope = await query_port.summary(session_id)
        return _stamped(envelope, request)

    @router.get("/sessions/{session_id}/events")
    async def list_events(
        session_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=2000),
        cursor: Optional[str] = Query(default=None),
        sort: str = Query(default="journal_asc"),
        event_type: list[str] = Query(default=()),
        severity: list[str] = Query(default=()),
        producer_id: list[str] = Query(default=()),
        run_id: Optional[str] = Query(default=None),
        clock_domain: Optional[str] = Query(default=None),
        clock_epoch: Optional[int] = Query(default=None, ge=0),
        start_ns: Optional[str] = Query(default=None),
        end_ns: Optional[str] = Query(default=None),
    ) -> dict:
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        envelope = await query_port.events(
            session_id,
            limit=limit,
            cursor=cursor,
            sort=sort,
            event_type=event_type,
            severity=severity,
            producer_id=producer_id,
            run_id=run_id,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            start_ns=start_ns,
            end_ns=end_ns,
        )
        return _stamped(envelope, request)

    @router.get("/sessions/{session_id}/timeline")
    async def get_timeline(
        session_id: str,
        request: Request,
        limit: int = Query(default=500, ge=1, le=2000),
        cursor: Optional[str] = Query(default=None),
        record_kind: list[str] = Query(default=()),
        event_type: list[str] = Query(default=()),
        severity: list[str] = Query(default=()),
        producer_id: list[str] = Query(default=()),
        node_id: Optional[str] = Query(default=None),
        service_id: Optional[str] = Query(default=None),
        pid: Optional[int] = Query(default=None, ge=0, le=8191),
        fault_id: Optional[str] = Query(default=None),
        scenario_id: Optional[str] = Query(default=None),
        tag: list[str] = Query(default=()),
        clock_domain: Optional[str] = Query(default=None),
        clock_epoch: Optional[int] = Query(default=None, ge=0),
        start_ns: Optional[str] = Query(default=None),
        end_ns: Optional[str] = Query(default=None),
        lanes: bool = Query(default=False),
    ) -> dict:
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        envelope = await query_port.timeline(
            session_id,
            limit=limit,
            cursor=cursor,
            record_kind=record_kind,
            event_type=event_type,
            severity=severity,
            producer_id=producer_id,
            node_id=node_id,
            service_id=service_id,
            pid=pid,
            fault_id=fault_id,
            scenario_id=scenario_id,
            tag=tag,
            clock_domain=clock_domain,
            clock_epoch=clock_epoch,
            start_ns=start_ns,
            end_ns=end_ns,
            lanes=lanes,
        )
        return _stamped(envelope, request)

    @router.post("/sessions/{session_id}/metrics/query")
    async def query_metrics(
        session_id: str,
        request: Request,
        body: MetricsQueryBody | None = None,
    ) -> dict:
        # The port check precedes body validation: an UNBOUND composition
        # keeps the frozen 501 answer even for bare requests (the #48
        # mount-point contract).
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        if body is None:
            raise BadRequestError(
                REQUEST_BODY_INVALID, "metrics query requires a JSON body"
            )
        envelope = await query_port.metrics_query(session_id, body)
        return _stamped(envelope, request)

    @router.get("/sessions/{session_id}/alerts")
    async def list_alerts(
        session_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=2000),
        cursor: Optional[str] = Query(default=None),
        rule_id: Optional[str] = Query(default=None),
        state: Optional[str] = Query(default=None),
        severity: Optional[str] = Query(default=None),
        suppressed: Optional[bool] = Query(default=None),
    ) -> dict:
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        envelope = await query_port.alerts(
            session_id,
            limit=limit,
            cursor=cursor,
            rule_id=rule_id,
            state=state,
            severity=severity,
            suppressed=suppressed,
        )
        return _stamped(envelope, request)

    @router.get("/sessions/{session_id}/health")
    async def get_health(
        session_id: str,
        request: Request,
        clock_domain: Optional[str] = Query(default=None),
        now_ns: Optional[int] = Query(default=None),
        clock_epoch: int = Query(default=0, ge=0),
    ) -> dict:
        # The port check precedes param validation (unbound = 501, #48).
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        if not clock_domain or now_ns is None:
            raise BadRequestError(
                REQUEST_BODY_INVALID,
                "health requires clock_domain and now_ns "
                "(SPEC-305 §5: 时钟域显式)",
                details={"param": "clock_domain" if not clock_domain else "now_ns"},
            )
        envelope = await query_port.health(
            session_id,
            clock_domain=clock_domain,
            now_ns=now_ns,
            clock_epoch=clock_epoch,
        )
        return _stamped(envelope, request)

    @router.get("/sessions/{session_id}/exports/{export_id}")
    async def get_export(
        session_id: str, export_id: str, request: Request
    ) -> dict:
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        envelope = await query_port.export(session_id, export_id)
        return _stamped(envelope, request)

    @router.post("/sessions/{session_id}/exports")
    async def create_export(
        session_id: str,
        request: Request,
        body: ExportCreateBody | None = None,
    ) -> dict:
        # Export POST creates only an Observation export task — it never
        # creates or mutates a simulation session (SPEC-305 §4). The port
        # check precedes body validation (unbound = 501, #48).
        if query_port is None:
            raise HTTPException(status_code=501, detail=_501_DETAIL)
        if body is None:
            body = ExportCreateBody()
        envelope = await query_port.create_export(session_id, body)
        return _stamped(envelope, request)

    return router


def _stamped(envelope: ObservationResponseDTO, request: Request) -> dict:
    """Stamp the per-request id into the §6 envelope (the middleware's
    ``request_id`` — the same seam the error envelope uses)."""
    state = request.scope.get("state") or {}
    envelope.request_id = state.get("request_id") or envelope.request_id or ""
    return envelope.model_dump(mode="json")
