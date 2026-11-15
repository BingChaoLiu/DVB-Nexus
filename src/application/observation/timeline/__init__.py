"""Observation timeline package — SPEC-303 Timeline Recorder (ticket #51).

Owns the timeline plane of SPEC-300 §7 step 5: the six-kind record store
fed by the gateway commit fan-out (:mod:`.recorder`), the §4/§6 query face
with lanes and opaque-cursor pagination (:mod:`.service`, :mod:`.cursor`)
and the JSONL/CSV/ZIP export pipeline with manifest + redaction
(:mod:`.export`). The durable event authority remains the SPEC-502 journal
in ``adapters.storage``; checkpoints are observation behavior and never
touch the simulation (SPEC-303 §5, Must-not OBS-D).
"""

from application.observation.timeline.errors import (
    OBS_CURSOR_EXPIRED,
    OBS_QUERY_RANGE_TOO_LARGE,
    TimelineError,
)
from application.observation.timeline.export import (
    TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION,
    ExportRequest,
    ExportResult,
    build_export,
    secret_scan_violations,
    write_export,
)
from application.observation.timeline.recorder import RECORDER_SOURCE_ID, TimelineRecorder
from application.observation.timeline.service import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_HARD_CAP,
    TimelineFilter,
    TimelineLane,
    TimelinePage,
    TimelineService,
    TimelineServiceConfig,
)

__all__ = [
    "OBS_CURSOR_EXPIRED",
    "OBS_QUERY_RANGE_TOO_LARGE",
    "PAGE_SIZE_DEFAULT",
    "PAGE_SIZE_HARD_CAP",
    "RECORDER_SOURCE_ID",
    "TIMELINE_EXPORT_MANIFEST_SCHEMA_VERSION",
    "ExportRequest",
    "ExportResult",
    "TimelineError",
    "TimelineFilter",
    "TimelineLane",
    "TimelinePage",
    "TimelineRecorder",
    "TimelineService",
    "TimelineServiceConfig",
    "build_export",
    "secret_scan_violations",
    "write_export",
]
