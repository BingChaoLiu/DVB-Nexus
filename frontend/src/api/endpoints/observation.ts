// Observation face (SPEC-305 §4/§5/§6). The eight routes' response models are
// NOT in OpenAPI yet (companion ticket wires response_model); bodies are cast
// to the dto-supplement types here — the `as` narrowing is the ONLY cast site
// and shrinks to zero when the generated types cover these routes
// (SPEC-400 §7.1 convergence; scripts/check-dto-supplement.mjs enforces it).
import { client, unwrap } from "../client";
import type {
  AlertsDataDTO,
  EventsDataDTO,
  ExportDataDTO,
  HealthDataDTO,
  MetricsDataDTO,
  ObservationResponseDTO,
  SummaryDataDTO,
  TimelineDataDTO,
} from "../dto-supplement";
import type { components } from "../schema.gen";

export type MetricsQueryBody = components["schemas"]["MetricsQueryBody"];
export type ExportCreateBody = components["schemas"]["ExportCreateBody"];

type PathParams = { session_id: string };

export function querySummary(sessionId: string) {
  return unwrap<ObservationResponseDTO<SummaryDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/observation/summary", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export function queryEvents(
  sessionId: string,
  query: {
    limit?: number;
    cursor?: string | null;
    sort?: string;
    event_type?: string[];
    severity?: string[];
    producer_id?: string[];
    run_id?: string | null;
    clock_domain?: string | null;
    clock_epoch?: number | null;
    start_ns?: string | null;
    end_ns?: string | null;
  } = {},
) {
  return unwrap<ObservationResponseDTO<EventsDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/events", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

export function queryTimeline(
  sessionId: string,
  query: {
    limit?: number;
    cursor?: string | null;
    sort?: string;
    record_kind?: string[];
    event_type?: string[];
    severity?: string[];
    producer_id?: string[];
    pid?: number;
    fault_id?: string | null;
    scenario_id?: string | null;
    tag?: string[];
    lanes?: boolean;
    clock_domain?: string | null;
    clock_epoch?: number | null;
    start_ns?: string | null;
    end_ns?: string | null;
  } = {},
) {
  return unwrap<ObservationResponseDTO<TimelineDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/timeline", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

export function queryMetrics(sessionId: string, body: MetricsQueryBody) {
  return unwrap<ObservationResponseDTO<MetricsDataDTO>>(
    client.POST("/api/v1/sessions/{session_id}/metrics/query", {
      params: { path: { session_id: sessionId } },
      body,
    }),
  );
}

export function queryAlerts(
  sessionId: string,
  query: {
    limit?: number;
    cursor?: string | null;
    rule_id?: string | null;
    state?: string | null;
    severity?: string | null;
    suppressed?: boolean;
  } = {},
) {
  return unwrap<ObservationResponseDTO<AlertsDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/alerts", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

// clock_domain + now_ns are REQUIRED by the wire (missing → 400
// REQUEST_BODY_INVALID); the generated query type is wider, the endpoint
// keeps the downstream discipline strict.
export function queryHealth(
  sessionId: string,
  query: { clock_domain: string; now_ns: number; clock_epoch?: number },
) {
  return unwrap<ObservationResponseDTO<HealthDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/health", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

export function queryExport(sessionId: string, exportId: string) {
  return unwrap<ObservationResponseDTO<ExportDataDTO>>(
    client.GET("/api/v1/sessions/{session_id}/exports/{export_id}", {
      params: { path: { session_id: sessionId, export_id: exportId } satisfies PathParams & { export_id: string } },
    }),
  );
}

export function createExport(
  sessionId: string,
  body: ExportCreateBody = { formats: ["jsonl"], redaction_policy: "none", record_kinds: [] },
) {
  return unwrap<ObservationResponseDTO<ExportDataDTO>>(
    client.POST("/api/v1/sessions/{session_id}/exports", {
      params: { path: { session_id: sessionId } },
      body,
    }),
  );
}
