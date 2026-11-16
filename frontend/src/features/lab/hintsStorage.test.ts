// hintsStorage seam (SPEC-408 §5 L188, REQ-UI-408-011 / AC-408-06): the
// ONLY localStorage key family in the whole spec — `dvb-lab-hints:{scenario_id}`
// holding the revealed-hint count. The seam reports availability honestly
// (privacy mode / quota throws → available:false) so the UI can degrade to
// page memory instead of faking persistence (SPEC-408 §8 降级行). Reveal
// state NEVER feeds any verify/evidence path — data flow is strictly
// storage → UI display.
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearRevealedHintCount,
  hintsStorageKey,
  readRevealedHintCount,
  writeRevealedHintCount,
} from "./hintsStorage";

const SID = "5c010000-0000-4000-8000-000000000001";

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("hintsStorage — key contract (SPEC-408 §5)", () => {
  it("builds the verbatim per-scenario key dvb-lab-hints:{scenario_id}", () => {
    expect(hintsStorageKey("SC-01")).toBe("dvb-lab-hints:SC-01");
    expect(hintsStorageKey(SID)).toBe(`dvb-lab-hints:${SID}`);
  });
});

describe("hintsStorage — read/write/clear roundtrip", () => {
  it("writes the count and reads it back (刷新不丢 contract)", () => {
    expect(writeRevealedHintCount(SID, 2)).toBe(true);
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBe("2");
    expect(readRevealedHintCount(SID)).toEqual({ available: true, stored: 2 });
  });

  it("absent key reads as stored:null with storage available", () => {
    expect(readRevealedHintCount(SID)).toEqual({ available: true, stored: null });
  });

  it("unparseable stored value reads as stored:null (honest ignore, not a crash)", () => {
    window.localStorage.setItem(hintsStorageKey(SID), "not-a-count");
    expect(readRevealedHintCount(SID)).toEqual({ available: true, stored: null });
  });

  it("negative stored value reads as stored:null (corrupted record ignored)", () => {
    window.localStorage.setItem(hintsStorageKey(SID), "-3");
    expect(readRevealedHintCount(SID)).toEqual({ available: true, stored: null });
  });

  it("clear removes the scenario key only (重做场景可清空)", () => {
    writeRevealedHintCount(SID, 1);
    const other = hintsStorageKey("other-scenario");
    window.localStorage.setItem(other, "7");
    expect(clearRevealedHintCount(SID)).toBe(true);
    expect(readRevealedHintCount(SID).stored).toBeNull();
    expect(window.localStorage.getItem(other)).toBe("7");
  });

  it("refuses to write non-integer or negative counts (key stays untouched)", () => {
    expect(writeRevealedHintCount(SID, -1)).toBe(false);
    expect(writeRevealedHintCount(SID, 1.5)).toBe(false);
    expect(window.localStorage.getItem(hintsStorageKey(SID))).toBeNull();
  });
});

describe("hintsStorage — availability degradation (SPEC-408 §8)", () => {
  it("getItem throwing (privacy mode) reads as available:false", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readRevealedHintCount(SID)).toEqual({ available: false, stored: null });
  });

  it("setItem throwing (quota/denied) write reports false", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(writeRevealedHintCount(SID, 1)).toBe(false);
  });

  it("removeItem throwing clear reports false (best-effort)", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(clearRevealedHintCount(SID)).toBe(false);
  });

  it("localStorage property access itself throwing degrades to available:false", () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
    expect(descriptor).not.toBeUndefined();
    Object.defineProperty(window, "localStorage", {
      ...descriptor,
      configurable: true,
      get() {
        throw new DOMException("denied", "SecurityError");
      },
    });
    try {
      expect(readRevealedHintCount(SID)).toEqual({ available: false, stored: null });
    } finally {
      if (descriptor) Object.defineProperty(window, "localStorage", descriptor);
    }
  });
});
