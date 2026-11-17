// SPEC-404 §Phase2 viewTypes — the view vocabulary contract (ruling §10-5:
// this file owns the type; monitor/types.ts is #134's). Shape assertions
// only: the wire enum is never aliased or case-folded, the absent/invalid
// param falls back to the MVP default.
import { describe, expect, it } from "vitest";
import {
  DEFAULT_PACKET_INSPECTOR_VIEW,
  PACKET_INSPECTOR_VIEWS,
  isPacketInspectorView,
  parsePacketInspectorView,
} from "./viewTypes";

describe("viewTypes — SPEC-404 §Phase2 view vocabulary", () => {
  it("carries exactly the wire vocabulary t2mi|bbframe|ts", () => {
    expect([...PACKET_INSPECTOR_VIEWS]).toEqual(["t2mi", "bbframe", "ts"]);
  });

  it("defaults to ts (MVP zero-regression face)", () => {
    expect(DEFAULT_PACKET_INSPECTOR_VIEW).toBe("ts");
    expect(parsePacketInspectorView(null)).toBe("ts");
    expect(parsePacketInspectorView("")).toBe("ts");
  });

  it("accepts every wire value verbatim", () => {
    for (const view of PACKET_INSPECTOR_VIEWS) {
      expect(parsePacketInspectorView(view)).toBe(view);
      expect(isPacketInspectorView(view)).toBe(true);
    }
  });

  it("falls back to the default on unknown values (no fabricated view)", () => {
    expect(parsePacketInspectorView("T2MI")).toBe("ts"); // no case folding
    expect(parsePacketInspectorView("bbframes")).toBe("ts");
    expect(parsePacketInspectorView("mpegtypes")).toBe("ts");
    expect(isPacketInspectorView("T2MI")).toBe(false);
  });
});
