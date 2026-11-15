// Feature-local DTO type aliases (SPEC-403 §5): every consumed wire type in
// one place, aliased from the generated authority (schema.gen.ts — read-only
// import; the file itself is NEVER modified). Where the api barrel already
// re-exports a type, both paths resolve to the identical generated type.
import type { components } from "../../api/schema.gen";

type Schemas = components["schemas"];

export type AlertRecordDTO = Schemas["AlertRecordDTO"];
export type AlertsDataDTO = Schemas["AlertsDataDTO"];
export type CriterionResultDTO = Schemas["CriterionResultDTO"];
export type DiagnosisCandidateDTO = Schemas["DiagnosisCandidateDTO"];
export type DiagnosisDTO = Schemas["DiagnosisDTO"];
export type DiagnosisEvidenceDTO = Schemas["DiagnosisEvidenceDTO"];
export type DiagnosisObservationRefDTO = Schemas["DiagnosisObservationRefDTO"];
export type DiagnosisReportDTO = Schemas["DiagnosisReportDTO"];
export type MetricsResponseDTO = Schemas["MetricsResponseDTO"];
export type PassCriterionDTO = Schemas["PassCriterionDTO"];
export type RunStatusDTO = Schemas["RunStatusDTO"];
export type SnapshotDTO = Schemas["SnapshotDTO"];
export type SummaryDataDTO = Schemas["SummaryDataDTO"];
export type VerificationResultDTO = Schemas["VerificationResultDTO"];
export type VerifyRunRequest = Schemas["VerifyRunRequest"];
