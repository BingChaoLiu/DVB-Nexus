// Source vocabulary + filter predicate (SPEC-405 §4.4/§7.2, AC-405-04).
// Assertions pin the four-value closed set and ASC-order-preserving
// filtering — never DOM (tests/README §6).
import { describe, expect, it } from "vitest";
import { CLI_SOURCE_VALUES, CLI_SOURCE_ALL, filterCalls } from "./sources";
import { fourSourceRows } from "./fixtures";

describe("CLI_SOURCE_VALUES — the four-value closed set (ObservationSource CLI face)", () => {
  it("exposes exactly generator/internal_parser/tsduck/hardware in canonical order", () => {
    expect([...CLI_SOURCE_VALUES]).toEqual(["generator", "internal_parser", "tsduck", "hardware"]);
  });
});

describe("filterCalls — predicate matrix over the closed set (AC-405-04)", () => {
  it('"all" keeps every row in the original ASC order', () => {
    const rows = fourSourceRows();
    const out = filterCalls(rows, CLI_SOURCE_ALL);
    expect(out).toHaveLength(4);
    expect(out.map((r) => r.call.started_at_utc_ms)).toEqual([100, 200, 300, 400]);
  });

  it("each of the four values selects only its own rows, order preserved", () => {
    const rows = fourSourceRows();
    for (const value of CLI_SOURCE_VALUES) {
      const out = filterCalls(rows, value);
      expect(out).toHaveLength(1);
      expect(out[0]?.source).toBe(value);
    }
  });

  it("returns the same array instance semantics: no re-sorting, no mutation", () => {
    const rows = fourSourceRows();
    const snapshot = rows.map((r) => r.call.started_at_utc_ms);
    filterCalls(rows, "tsduck");
    expect(rows.map((r) => r.call.started_at_utc_ms)).toEqual(snapshot);
  });
});
