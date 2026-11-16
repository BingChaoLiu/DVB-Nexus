// Demo controller context (SPEC-408 §4.3, ticket #99): the ONE seam between
// the shell-owned demo state (AppShell React state — zero new dependencies,
// zero global state library) and the two entry buttons (Monitor guide seat +
// home Monitor card). React built-in context only; the default fallback is a
// no-op so standalone consumers (unit tests, isolated renders) stay enabled
// without a provider — the real app always mounts AppShell's provider.
import { createContext, useContext } from "react";

export interface DemoController {
  /** Kick off the one-click demo orchestration (idempotent while one is
   * in flight — the shell guards re-entry). */
  startDemo: () => void;
  /** True while an orchestration is in flight: entry buttons disable so a
   * second click can never start a parallel demo. */
  demoBusy: boolean;
}

const NOOP_CONTROLLER: DemoController = { startDemo: () => {}, demoBusy: false };

export const DemoContext = createContext<DemoController>(NOOP_CONTROLLER);

export function useDemoController(): DemoController {
  return useContext(DemoContext);
}
