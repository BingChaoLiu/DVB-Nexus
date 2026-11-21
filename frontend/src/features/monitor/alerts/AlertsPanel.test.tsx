// Alerts panel (SPEC-403 §4.7): alerts merged into the monitor page — no
// standalone alert center. The empty state must say "no records", never
// "clean" (CONTEXT.md ban: 无告警 ≠ 干净). The #170 Phase 3 face: the two
// SPEC-304 §Phase3 rule registrations (TUNER_UNLOCKED warning / BER_SEVERE
// error) enter registry-driven — rule_id renders verbatim and the copy map
// adds the wire-faithful line; unmapped rules keep the bare face.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ALERT_RULE_COPY } from "../copy";
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

  // --- #170: SPEC-304 §Phase3 两条告警注册的呈现面 --------------------------
  it("renders the TUNER_UNLOCKED copy line (warning 告警呈现, rule_id verbatim)", () => {
    render(
      <AlertsPanel
        alerts={[alert({ rule_id: "TUNER_UNLOCKED", severity: "warning", alert_id: "a-tu" })]}
        total={1}
      />,
    );
    expect(screen.getByText("TUNER_UNLOCKED")).toBeInTheDocument();
    expect(screen.getByText("warning")).toBeInTheDocument();
    expect(screen.getByTestId("alert-copy-a-tu")).toHaveTextContent(ALERT_RULE_COPY["TUNER_UNLOCKED"]!);
  });

  it("renders the BER_SEVERE copy line (error 告警呈现 + elevated 档不告警纪律)", () => {
    render(
      <AlertsPanel
        alerts={[alert({ rule_id: "BER_SEVERE", severity: "error", alert_id: "a-bs" })]}
        total={1}
      />,
    );
    expect(screen.getByText("BER_SEVERE")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
    const copy = screen.getByTestId("alert-copy-a-bs");
    expect(copy).toHaveTextContent(ALERT_RULE_COPY["BER_SEVERE"]!);
    // the SPEC-304 §Phase3 discipline: elevated 告两轴不混 — the line carries it.
    expect(copy).toHaveTextContent("elevated");
  });

  it("keeps unmapped rule_ids on the bare wire face (no invented copy — zero side effects)", () => {
    render(<AlertsPanel alerts={[alert({})]} total={1} />);
    expect(screen.getByText("ALT-CC-RATE")).toBeInTheDocument();
    expect(screen.queryByTestId("alert-copy-a-1")).not.toBeInTheDocument();
  });
});
