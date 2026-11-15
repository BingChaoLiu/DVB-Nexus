// The api barrel — downstream tickets' single import point (SPEC-400 §4.1
// directory contract; shared face, additive-only per 裁定 C).
export { ApiError, client, errorFromResponse, isApiError, unwrap } from "./client";
export type {
  AlertsDataDTO,
  ErrorDetail,
  ErrorResponse,
  EventsDataDTO,
  ExportDataDTO,
  HealthDataDTO,
  HealthDimensionDTO,
  MetricPointDTO,
  MetricSeriesDTO,
  MetricsDataDTO,
  ObservationMetaDTO,
  ObservationResponseDTO,
  ObservationScopeDTO,
  SummaryDataDTO,
  TimelineDataDTO,
  TimelineLaneDTO,
} from "./dto-supplement";
export * from "./endpoints/artifacts";
export * from "./endpoints/diagnosis";
export * from "./endpoints/observation";
export * from "./endpoints/runs";
export * from "./endpoints/sessions";
export * from "./endpoints/verification";
export type { components, paths } from "./schema.gen";
