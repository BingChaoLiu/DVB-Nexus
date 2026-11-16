// Unknown-session predicate (SPEC-408 §4.3 未知会话态): the two signal
// routes — a session-scoped REST read answering HTTP 404
// (SIM_SESSION_NOT_FOUND) and the WS permanent close 4404
// (CLOSE_SESSION_UNKNOWN, SPEC-501 §5) — plus the honest negatives: no
// signal yet, transient network-class closes, and other statuses.
import { describe, expect, it } from "vitest";
import { CLOSE_ABNORMAL, CLOSE_SESSION_UNKNOWN, CLOSE_SLOW_CONSUMER } from "../../ws/closeCodes";
import { isUnknownSessionState } from "./unknownSession";

describe("isUnknownSessionState — two signal routes", () => {
  it("session detail/snapshot REST 404 alone triggers the unknown state", () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: true, wsCloseCode: null })).toBe(true);
  });

  it(`WS ${CLOSE_SESSION_UNKNOWN} (4404) alone triggers the unknown state`, () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: false, wsCloseCode: CLOSE_SESSION_UNKNOWN })).toBe(true);
  });

  it("either route suffices (disjunction)", () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: true, wsCloseCode: CLOSE_SESSION_UNKNOWN })).toBe(true);
  });
});

describe("isUnknownSessionState — honest negatives", () => {
  it("no signals yet → not unknown (page still loading)", () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: false, wsCloseCode: null })).toBe(false);
  });

  it("transient WS closes (reconnectable) never imply unknown", () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: false, wsCloseCode: CLOSE_ABNORMAL })).toBe(false);
    expect(isUnknownSessionState({ sessionHttpNotFound: false, wsCloseCode: CLOSE_SLOW_CONSUMER })).toBe(false);
  });

  it("a WS close that is not 4404 does not trigger the state", () => {
    expect(isUnknownSessionState({ sessionHttpNotFound: false, wsCloseCode: 4400 })).toBe(false);
  });
});
