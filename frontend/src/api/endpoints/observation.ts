// Observation face (SPEC-305 §4/§5/§6). Since the M5 companion ticket wired
// response_model onto the eight routes, every response envelope is generated
// (`*ResponseDTO` in schema.gen.ts) — the supplement-era casts are gone.
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type MetricsQueryBody = components["schemas"]["MetricsQueryBody"];
export type ExportCreateBody = components["schemas"]["ExportCreateBody"];
export type SummaryResponseDTO = components["schemas"]["SummaryResponseDTO"];
export type EventsResponseDTO = components["schemas"]["EventsResponseDTO"];
export type TimelineResponseDTO = components["schemas"]["TimelineResponseDTO"];
export type MetricsResponseDTO = components["schemas"]["MetricsResponseDTO"];
export type AlertsResponseDTO = components["schemas"]["AlertsResponseDTO"];
export type HealthResponseDTO = components["schemas"]["HealthResponseDTO"];
export type ExportResponseDTO = components["schemas"]["ExportResponseDTO"];

export function querySummary(sessionId: string) {
  return unwrap(
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
  return unwrap(
    client.GET("/api/v1/sessions/{session_id}/events", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

// #169 (SPEC-305 §Phase3 / SPEC-404 §Phase3): the state_observed snapshot read
// path — a DISTINCT export beside queryEvents (A19 parallel discipline: two
// tickets each add their own functions to this shared file; the existing
// exports stay untouched). The endpoint's flat scalar repeated parameters
// namespace/node_type ride the generated query type (schema.gen.ts, #167
// sync); node_id narrowing is CLIENT-side (the §5 whitelist does not grow).
export function queryStateObservedEvents(
  sessionId: string,
  query: {
    namespace?: string[];
    node_type?: string[];
    limit?: number;
    cursor?: string | null;
    sort?: string;
    run_id?: string | null;
  } = {},
) {
  return unwrap(
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
  return unwrap(
    client.GET("/api/v1/sessions/{session_id}/timeline", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

export function queryMetrics(sessionId: string, body: MetricsQueryBody) {
  return unwrap(
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
  return unwrap(
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
  return unwrap(
    client.GET("/api/v1/sessions/{session_id}/health", {
      params: { path: { session_id: sessionId }, query },
    }),
  );
}

export function queryExport(sessionId: string, exportId: string) {
  return unwrap(
    client.GET("/api/v1/sessions/{session_id}/exports/{export_id}", {
      params: { path: { session_id: sessionId, export_id: exportId } },
    }),
  );
}

export function createExport(
  sessionId: string,
  body: ExportCreateBody = { formats: ["jsonl"], redaction_policy: "none", record_kinds: [] },
) {
  return unwrap(
    client.POST("/api/v1/sessions/{session_id}/exports", {
      params: { path: { session_id: sessionId } },
      body,
    }),
  );
}
