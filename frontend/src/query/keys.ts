// Canonical query-key vocabulary (SPEC-400 §5): the invalidation bridge and
// every feature ticket speak these prefixes — additive extension only, no
// parallel key systems. Session-scoped observation faces follow the SPEC-305
// §8 hint→REST matrix.
export const qk = {
  session: (sessionId: string) => ["session", sessionId] as const,
  snapshot: (sessionId: string) => ["session", sessionId, "snapshot"] as const,
  summary: (sessionId: string) => ["summary", sessionId] as const,
  events: (sessionId: string, ...rest: readonly unknown[]) => ["events", sessionId, ...rest] as const,
  metrics: (sessionId: string, ...rest: readonly unknown[]) => ["metrics", sessionId, ...rest] as const,
  alerts: (sessionId: string, ...rest: readonly unknown[]) => ["alerts", sessionId, ...rest] as const,
  health: (sessionId: string, ...rest: readonly unknown[]) => ["health", sessionId, ...rest] as const,
  export: (sessionId: string, exportId: string, ...rest: readonly unknown[]) =>
    ["export", sessionId, exportId, ...rest] as const,
  topologies: () => ["topologies"] as const,
  topology: (topologyId: string, revision: number) => ["topology", topologyId, revision] as const,
  scenarios: () => ["scenarios"] as const,
  scenario: (scenarioId: string) => ["scenario", scenarioId] as const,
  // SPEC-408 §6 read faces (ticket #95): additive sessions prefix — the list
  // invalidates as a whole; detail/runs nest under it per session.
  sessions: () => ["sessions"] as const,
  sessionDetail: (sessionId: string) => ["sessions", sessionId, "detail"] as const,
  sessionRuns: (sessionId: string) => ["sessions", sessionId, "runs"] as const,
};
