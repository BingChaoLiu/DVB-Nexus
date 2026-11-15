// The SPEC-200 §5 exhaustive lifecycle table as data (SPEC-403 §7.1,
// REQ-UI-403-001): the control bar's disable matrix is DERIVED from these two
// tables — per-button if-chains are banned. The wire vocabulary is the
// lowercase domain enum string values (SessionViewDTO.lifecycle); the
// SPEC-200 §5 row names map 1:1 onto them.
export type LifecycleWire =
  | "created"
  | "validating"
  | "ready"
  | "running"
  | "paused"
  | "stopping"
  | "stopped"
  | "failed"
  | "disposed";

export type LifecycleAction = "validate" | "start" | "pause" | "resume" | "stop" | "dispose";

export const LIFECYCLE_STATES: readonly LifecycleWire[] = [
  "created",
  "validating",
  "ready",
  "running",
  "paused",
  "stopping",
  "stopped",
  "failed",
  "disposed",
];

export const LIFECYCLE_ACTIONS: readonly LifecycleAction[] = [
  "validate",
  "start",
  "pause",
  "resume",
  "stop",
  "dispose",
];

/** SPEC-200 §5 verbatim (unlisted edge = illegal; server answers 409). */
export const LIFECYCLE_TRANSITIONS: Record<LifecycleWire, readonly LifecycleWire[]> = {
  created: ["validating"],
  validating: ["ready", "failed", "stopping"],
  ready: ["running", "failed", "stopping"],
  running: ["paused", "failed", "stopping"],
  paused: ["running", "failed", "stopping"],
  // FAILED is not final: cleanup via STOPPING or straight disposal.
  failed: ["stopping", "disposed"],
  stopping: ["stopped"],
  stopped: ["disposed"],
  // DISPOSED absorbs: no outgoing edge (不可重启).
  disposed: [],
};

/**
 * The enablement matrix: for each action, the states in which the control bar
 * enables it (SPEC-403 §7.1). Derived from LIFECYCLE_TRANSITIONS — an action
 * is enabled iff its target transition is a listed edge from the current
 * state. Notes:
 * - stop targets STOPPING (legal from validating/ready/running/paused/failed).
 *   The server tolerates redundant stop calls on stopping/stopped (idempotent
 *   return-current-view), but the button matrix follows the table: disabled
 *   there. Idempotency is the double-click race safety net, not an enablement.
 * - dispose targets DISPOSED from failed/stopped only; created has no
 *   -> disposed edge (the table rules, no convenience exception).
 * - disposed is absorbing: every action disabled.
 */
export const STATE_ACTIONS: Record<LifecycleAction, readonly LifecycleWire[]> = {
  validate: ["created"],
  start: ["ready"],
  pause: ["running"],
  resume: ["paused"],
  stop: ["validating", "ready", "running", "paused", "failed"],
  dispose: ["failed", "stopped"],
};

export function isActionEnabled(state: LifecycleWire, action: LifecycleAction): boolean {
  return STATE_ACTIONS[action].includes(state);
}
