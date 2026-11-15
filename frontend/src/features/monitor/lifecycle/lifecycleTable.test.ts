// Lifecycle control-bar matrix tests (SPEC-403 §7.1, REQ-UI-403-001 /
// AC-403-01): the exhaustive SPEC-200 §5 table as literal expectations —
// nine states × six actions, one assertion per cell. The wire vocabulary is
// the lowercase domain enum string values (SessionViewDTO.lifecycle).
import { describe, expect, it } from "vitest";
import {
  isActionEnabled,
  LIFECYCLE_ACTIONS,
  LIFECYCLE_STATES,
  LIFECYCLE_TRANSITIONS,
  STATE_ACTIONS,
  type LifecycleAction,
  type LifecycleWire,
} from "./lifecycleTable";

// SPEC-200 §5 verbatim (wire casing lowercase): unlisted transitions are
// illegal — the server answers 409 SIM_INVALID_LIFECYCLE_TRANSITION.
const SPEC_200_TRANSITIONS: Record<LifecycleWire, readonly LifecycleWire[]> = {
  created: ["validating"],
  validating: ["ready", "failed", "stopping"],
  ready: ["running", "failed", "stopping"],
  running: ["paused", "failed", "stopping"],
  paused: ["running", "failed", "stopping"],
  failed: ["stopping", "disposed"],
  stopping: ["stopped"],
  stopped: ["disposed"],
  disposed: [],
};

describe("LIFECYCLE_TRANSITIONS — SPEC-200 §5 exhaustive table", () => {
  it("declares exactly the nine wire states", () => {
    expect([...LIFECYCLE_STATES].sort()).toEqual([...Object.keys(SPEC_200_TRANSITIONS)].sort());
  });

  it("matches the SPEC-200 §5 table row by row", () => {
    for (const [state, targets] of Object.entries(SPEC_200_TRANSITIONS) as [
      LifecycleWire,
      readonly LifecycleWire[],
    ][]) {
      expect(LIFECYCLE_TRANSITIONS[state], `row ${state}`).toEqual(targets);
    }
  });

  it("keeps disposed absorbing and stopped/disposed final (no restart)", () => {
    expect(LIFECYCLE_TRANSITIONS.disposed).toEqual([]);
    expect(LIFECYCLE_TRANSITIONS.stopped).toEqual(["disposed"]);
    expect(LIFECYCLE_TRANSITIONS.created).not.toContain("disposed");
  });
});

// The 48-cell enablement matrix (SPEC-403 §7.1): literal expectations from
// the transition table derivation — an independent truth, not recomputed.
const ENABLED: Partial<Record<LifecycleAction, readonly LifecycleWire[]>> = {
  validate: ["created"],
  start: ["ready"],
  pause: ["running"],
  resume: ["paused"],
  // stop targets STOPPING; stopping/stopped are server-idempotent no-ops but
  // the button matrix follows the table (disabled there).
  stop: ["validating", "ready", "running", "paused", "failed"],
  dispose: ["failed", "stopped"], // created has no -> disposed edge
};

describe("STATE_ACTIONS / isActionEnabled — nine states × six actions", () => {
  it("exposes exactly the six control-bar actions", () => {
    expect([...LIFECYCLE_ACTIONS].sort()).toEqual(
      ["dispose", "pause", "resume", "start", "stop", "validate"].sort(),
    );
  });

  for (const action of ["validate", "start", "pause", "resume", "stop", "dispose"] as const) {
    it(`action ${action} is enabled exactly in ${JSON.stringify(ENABLED[action])}`, () => {
      expect([...STATE_ACTIONS[action]].sort()).toEqual([...ENABLED[action]!].sort());
      for (const state of LIFECYCLE_STATES) {
        expect(isActionEnabled(state, action), `${action}@${state}`).toBe(
          ENABLED[action]!.includes(state),
        );
      }
    });
  }

  it("disables every action in the absorbing state disposed", () => {
    for (const action of LIFECYCLE_ACTIONS) {
      expect(isActionEnabled("disposed", action)).toBe(false);
    }
  });
});
