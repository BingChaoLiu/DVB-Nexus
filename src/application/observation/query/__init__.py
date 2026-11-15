"""Observation query service plane — SPEC-305 (ticket #53).

The read-side service layer of SPEC-300 §7 step 7 (Query API 只暴露已提交
记录) and SPEC-300 §12's ``ObservationQueryService`` required interface.
The durable authorities stay where they are: the SPEC-502 journal
(``adapters.storage``, the only ``journal_seq`` stamp), the #50/#51/#52
service faces and the #52 alert store. This package composes those faces
under the SPEC-305 §4/§5/§6 contract and translates every service-plane
structured error onto the frozen ``application.errors`` categories with
its registry code intact — the REST router then inherits the declarative
SPEC-500 §6 HTTP mapping unchanged.
"""

from application.observation.query.errors import translate_service_error
from application.observation.query.events import EventsPage, EventsQueryRequest
from application.observation.query.exports import (
    ExportTaskRegistry,
    ExportTaskRequest,
    ExportTaskView,
)
from application.observation.query.service import (
    ObservationQueryService,
    SessionObservationSummary,
)

__all__ = [
    "EventsPage",
    "EventsQueryRequest",
    "ExportTaskRegistry",
    "ExportTaskRequest",
    "ExportTaskView",
    "ObservationQueryService",
    "SessionObservationSummary",
    "translate_service_error",
]
