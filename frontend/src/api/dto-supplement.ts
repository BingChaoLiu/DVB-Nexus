// DTO supplement — models NOT reachable from the current OpenAPI dump
// (SPEC-400 §5). SHRINK-ONLY: when the backend wires a model into OpenAPI
// (M5 companion-ticket scope: observation routes gain response_model), the
// entry MUST be deleted here and the generated type used instead —
// scripts/check-dto-supplement.mjs fails CI with the exact names to delete
// (npm run dto:check).
//
// Each entry's shape authority is named in its leading comment (the Pydantic
// DTO file is the wire truth; SPEC-305 is the spec anchor). Field names are
// snake_case verbatim — never rename for style (SPEC-400 §10 rendering
// discipline).

// --- error envelope (SPEC-305 §7; src/api/dto/errors.py ErrorDetail/ErrorResponse) ---

export type ErrorDetail = {
  error_code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
};

export type ErrorResponse = {
  error: ErrorDetail;
  request_id: string;
};

// --- observation envelope (SPEC-305 §6; src/api/dto/observation.py) -----------------

export type ObservationScopeDTO = {
  tenant_id: string;
  session_id: string;
};

export type ObservationMetaDTO = {
  schema_version: string;
  next_cursor: string | null;
  truncated: boolean;
  clock_domain: string | null;
};

// Pydantic `data: Any` — typed generically per endpoint at the call sites.
export type ObservationResponseDTO<TData = unknown> = {
  request_id: string;
  scope: ObservationScopeDTO;
  data: TData;
  meta: ObservationMetaDTO;
};

// --- data bodies (SPEC-305 §4/§6; src/api/dto/observation.py) -----------------------

export type SummaryDataDTO = {
  tenant_id: string;
  session_id: string;
  journal_seq_watermark: number;
  event_count: number;
  active_alert_count: number;
  schema_version: string;
};

// items are journal envelopes verbatim (SPEC-301; unknown fields tolerated
// per ADR-0006 decision 4).
export type EventsDataDTO = {
  sort: string;
  items: Record<string, unknown>[];
};

export type TimelineLaneDTO = {
  clock_domain: string;
  clock_epoch: number;
  sort_descriptor: string;
  records: Record<string, unknown>[];
};

export type TimelineDataDTO = {
  sort_descriptor: string;
  records: Record<string, unknown>[];
  lanes: TimelineLaneDTO[] | null;
};

export type MetricPointDTO = {
  start_ns: number;
  end_ns: number;
  value: number | Record<string, unknown> | null;
  quality: string[];
  revision: number;
  is_final: boolean;
};

export type MetricSeriesDTO = {
  metric_name: string;
  unit: string;
  value_type: string;
  aggregation: string;
  clock_domain: string;
  dimensions: Record<string, unknown>;
  points: MetricPointDTO[];
  provenance: Record<string, unknown>;
};

export type MetricsDataDTO = {
  series: MetricSeriesDTO[];
  bucket_convention: string;
  clock_domain: string;
};

export type AlertRecordDTO = {
  alert_id: string;
  fingerprint: string;
  rule_id: string;
  rule_version: string;
  state: string;
  severity: string;
  scope: ObservationScopeDTO;
  time: Record<string, unknown>;
  summary: string | null;
  evidence_refs: string[];
  suppression: Record<string, unknown> | null;
  suppressed: boolean;
};

export type AlertsDataDTO = {
  items: AlertRecordDTO[];
  total: number;
};

export type HealthDimensionDTO = {
  dimension: string;
  status: string;
  contributing_rule_ids: string[];
  evidence_refs: string[];
  reason_codes: string[];
};

export type HealthDataDTO = {
  session_id: string;
  clock_domain: string;
  evaluated_at: Record<string, unknown>;
  rule_set_id: string;
  rule_set_version: string;
  profile: string;
  overall: string;
  dimensions: HealthDimensionDTO[];
};

export type ExportDataDTO = {
  export_id: string;
  session_id: string;
  status: string;
  manifest: Record<string, unknown>;
  file_digests: Record<string, string>;
};
