// Alerts panel (SPEC-403 §4.7): alerts merged into the monitor page — no
// standalone alert center. The empty state must say "no records", never
// "clean" (CONTEXT.md ban: 无告警 ≠ 干净).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AlertRecordDTO } from "../types";
import { AlertsPanel } from "./AlertsPanel";

const alert = (overrides: Partial<AlertRecordDTO>): AlertRecordDTO => ({
  alert_id: "a-1",
  fingerprint: "fp-cc-256",
  rule_id: "ALT-CC-RATE",
  rule_version: "1.0.0",
  state: "active",
  severity: "warning",
  scope: {
    tenant_id: "local",
    session_id: "s-1",
  },
  time: {},
  summary: "CC 错误率超阈值",
  evidence_refs: [],
  suppression: null,
  suppressed: false,
  ...overrides,
});

describe("AlertsPanel — records rendering", () => {
  it("renders rule_id/state/severity/summary with wire strings", () => {
    render(<AlertsPanel alerts={[alert({})]} total={1} />);
    expect(screen.getByText("ALT-CC-RATE")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("warning")).toBeInTheDocument();
    expect(screen.getByText("CC 错误率超阈值")).toBeInTheDocument();
  });

  it("marks suppressed records explicitly without hiding them", () => {
    render(<AlertsPanel alerts={[alert({ suppressed: true, alert_id: "a-s" })]} total={1} />);
    expect(screen.getByText(/suppressed/)).toBeInTheDocument();
    expect(screen.getByText("ALT-CC-RATE")).toBeInTheDocument();
  });

  it("empty state says no records — never clean (无告警 ≠ 干净)", () => {
    render(<AlertsPanel alerts={[]} total={0} />);
    expect(screen.getByText(/无告警记录/)).toBeInTheDocument();
    expect(screen.getByText(/≠ 干净/)).toBeInTheDocument();
    expect(screen.queryByText(/干净。/)).not.toBeInTheDocument();
  });
});
