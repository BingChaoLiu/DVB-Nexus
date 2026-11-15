// The api barrel — downstream tickets' single import point (SPEC-400 §4.1
// directory contract; shared face, additive-only per 裁定 C).
export { ApiError, client, errorFromResponse, isApiError, unwrap } from "./client";
import type { components } from "./schema.gen";

// Observation envelopes + error envelope (generated since the #80 response_model
// landing; re-exported here for downstream convenience).
export type AlertsResponseDTO = components["schemas"]["AlertsResponseDTO"];
export type ErrorResponse = components["schemas"]["ErrorResponse"];
export type EventsResponseDTO = components["schemas"]["EventsResponseDTO"];
export type ExportResponseDTO = components["schemas"]["ExportResponseDTO"];
export type HealthResponseDTO = components["schemas"]["HealthResponseDTO"];
export type MetricsResponseDTO = components["schemas"]["MetricsResponseDTO"];
export type ObservationMetaDTO = components["schemas"]["ObservationMetaDTO"];
export type ObservationScopeDTO = components["schemas"]["ObservationScopeDTO"];
export type SummaryResponseDTO = components["schemas"]["SummaryResponseDTO"];
export type TimelineResponseDTO = components["schemas"]["TimelineResponseDTO"];
export * from "./endpoints/artifacts";
export * from "./endpoints/diagnosis";
export * from "./endpoints/observation";
export * from "./endpoints/runs";
export * from "./endpoints/scenarios";
export * from "./endpoints/sessions";
export * from "./endpoints/topologies";
export * from "./endpoints/verification";
export type { components, paths } from "./schema.gen";
