// Metrics point display rules (SPEC-403 §7.4, AC-403-03): missing ≠ zero is
// the hard discipline — value:null OR quality containing "missing" renders an
// explicit missing state, never 0, never a skipped row. Expected values are
// literals from SPEC-302 §6 / SPEC-206 §6 wording.
import { describe, expect, it } from "vitest";
import { pointDisplay, type FormatPoint } from "./format";

const point = (overrides: Partial<FormatPoint>): FormatPoint => ({
  start_ns: 1_000,
  end_ns: 2_000,
  value: 42,
  quality: ["good"],
  revision: 1,
  is_final: true,
  ...overrides,
});

describe("pointDisplay — missing ≠ zero", () => {
  it("renders value:null as missing (not 0)", () => {
    const display = pointDisplay(point({ value: null }));
    expect(display.kind).toBe("missing");
  });

  it("renders quality containing 'missing' as missing even with a numeric value", () => {
    const display = pointDisplay(point({ quality: ["missing"] }));
    expect(display.kind).toBe("missing");
  });

  it("treats a missing quality array as present-and-good (not missing)", () => {
    const display = pointDisplay(point({ quality: undefined }));
    expect(display.kind).toBe("value");
  });

  it("renders a genuine 0 as the number 0 (zero is data, not absence)", () => {
    const display = pointDisplay(point({ value: 0 }));
    expect(display.kind).toBe("value");
    expect((display as { text: string }).text).toBe("0");
  });

  it("flags non-final points", () => {
    const display = pointDisplay(point({ is_final: false }));
    expect((display as { flags: string[] }).flags).toContain("nonfinal");
  });

  it("flags revisions above 1", () => {
    const display = pointDisplay(point({ revision: 3 }));
    expect((display as { flags: string[] }).flags).toContain("revised");
  });

  it("a missing point still exposes its window start (row is kept, not dropped)", () => {
    const display = pointDisplay(point({ value: null, start_ns: 7_000 }));
    expect(display.kind).toBe("missing");
    expect((display as { start_ns: number }).start_ns).toBe(7_000);
  });

  it("renders non-numeric non-null values as their JSON text (honest, no invention)", () => {
    const display = pointDisplay(point({ value: { p50: 1, p99: 9 } }));
    expect(display.kind).toBe("value");
    expect((display as { text: string }).text).toBe('{"p50":1,"p99":9}');
  });
});
