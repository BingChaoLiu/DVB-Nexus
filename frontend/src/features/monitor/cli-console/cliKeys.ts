// Feature-local query-key factory (SPEC-405 §4.2): canonical <prefix,
// sessionId> convention per SPEC-400 §5, same posture as monitorKeys
// (Region.ts header note) — a candidate for the shared keys.ts additive
// landing, deliberately NOT landed from this ticket (shared file NOT-TOUCH).
export const cliKeys = {
  calls: (sessionId: string, runIdFilter: string | null) =>
    ["tsduck-calls", sessionId, runIdFilter] as const,
};
