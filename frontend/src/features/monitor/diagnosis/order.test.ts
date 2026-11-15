// SPEC-307 §5 ordering matrix tests (SPEC-403 §7.3, AC-403-04): priority
// ascending -> severity descending (critical first) -> code lexicographic.
// Expected values are literal worked examples, not recomputations.
import { describe, expect, it } from "vitest";
import { SEVERITY_RANK, orderDiagnoses } from "./order";

interface Row {
  code: string;
  severity: string;
  priority?: number;
  label: string;
}

const row = (label: string, code: string, severity: string, priority?: number): Row => ({
  label,
  code,
  severity,
  priority,
});

describe("SEVERITY_RANK — four-tier severity vocabulary", () => {
  it("ranks critical highest and info lowest (descending sort puts critical first)", () => {
    expect(SEVERITY_RANK.critical).toBeGreaterThan(SEVERITY_RANK.error);
    expect(SEVERITY_RANK.error).toBeGreaterThan(SEVERITY_RANK.warning);
    expect(SEVERITY_RANK.warning).toBeGreaterThan(SEVERITY_RANK.info);
  });
});

describe("orderDiagnoses — SPEC-307 §5 matrix", () => {
  it("orders by priority ascending", () => {
    const input = [row("b", "X", "info", 20), row("a", "X", "info", 10)];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["a", "b"]);
  });

  it("breaks priority ties by severity descending (critical before warning)", () => {
    const input = [row("warn", "X", "warning", 10), row("crit", "X", "critical", 10)];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["crit", "warn"]);
  });

  it("breaks priority+severity ties by code lexicographic", () => {
    const input = [row("zeta", "ZZ", "error", 10), row("alpha", "AA", "error", 10)];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["alpha", "zeta"]);
  });

  it("sorts rows without priority after all prioritized rows (+infinity)", () => {
    const input = [
      row("bare", "X", "critical"), // no priority
      row("p99", "X", "info", 99),
      row("p1", "X", "info", 1),
    ];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["p1", "p99", "bare"]);
  });

  it("bare-vs-bare falls through to severity then code", () => {
    const input = [row("second", "BB", "error"), row("first", "AA", "critical")];
    // severity first: critical > error despite code order
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["first", "second"]);
  });

  it("is stable for fully equal keys (input order preserved)", () => {
    const input = [row("one", "X", "error", 5), row("two", "X", "error", 5)];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["one", "two"]);
  });

  it("is idempotent on already-sorted input (server-order pass-through)", () => {
    const sorted = [row("a", "A", "critical", 1), row("b", "B", "error", 2)];
    const once = orderDiagnoses(sorted);
    expect(orderDiagnoses(once).map((r) => r.label)).toEqual(once.map((r) => r.label));
  });

  it("does not mutate the input array", () => {
    const input = [row("b", "X", "info", 2), row("a", "X", "info", 1)];
    orderDiagnoses(input);
    expect(input.map((r) => r.label)).toEqual(["b", "a"]);
  });

  it("handles the full SPEC-307 §6 rule table order (worked example)", () => {
    // DIA-PAT-MISSING p10 error, DIA-PMT-CRC-BAD p20 error,
    // DIA-CC-DISCONTINUITY p30 warning, DIA-PMT-PID-MISMATCH p40 error.
    const input = [
      row("cc", "DIA-CC-DISCONTINUITY", "warning", 30),
      row("pat", "DIA-PAT-MISSING", "error", 10),
      row("pmt-pid", "DIA-PMT-PID-MISMATCH", "error", 40),
      row("pmt-crc", "DIA-PMT-CRC-BAD", "error", 20),
    ];
    expect(orderDiagnoses(input).map((r) => r.label)).toEqual(["pat", "pmt-crc", "cc", "pmt-pid"]);
  });
});
