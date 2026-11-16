// Diagnosis presentation components (SPEC-403 §4.5/§6, AC-403-04/06): the
// exported reusable face. Assertions pin wire field names / enum strings /
// ordering semantics — never full-DOM snapshots (tests/README §6).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DiagnosisCandidateDTO, DiagnosisDTO, DiagnosisEvidenceDTO } from "../types";
import { DiagnosisCandidateList, DiagnosisList } from "./DiagnosisList";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";

const diag = (overrides: Partial<DiagnosisDTO>): DiagnosisDTO => ({
  diagnosis_id: "d-1",
  session_id: "s-1",
  run_id: "r-1",
  rule_id: "DIA-CC-DISCONTINUITY",
  rule_version: "1.0.0",
  code: "CC_DISCONTINUITY",
  severity: "warning",
  confidence: "high",
  observation_refs: [{ journal_seq: 12, event_type: "ts.continuity_error" }],
  affected_node_ids: ["mux-0"],
  suggested_actions: ["重新对齐 CC 期望值"],
  state: "raised",
  raised_at: 1_000,
  cleared_at: null,
  ...overrides,
});

const candidate = (overrides: Partial<DiagnosisCandidateDTO>): DiagnosisCandidateDTO => ({
  diagnosis_id: "c-1",
  run_id: "r-2",
  rule_id: "DIA-CC-DISCONTINUITY",
  rule_version: "1.0.0",
  code: "CC_DISCONTINUITY",
  priority: 30,
  severity: "warning",
  confidence: "high",
  title: "连续性计数不连续",
  summary: "PID 0x0100 在包 30 处 delta=3",
  observation_refs: [{ journal_seq: 12, event_type: "ts.continuity_error" }],
  affected_node_ids: ["mux-0"],
  suggested_actions: ["复核故障恢复"],
  evidence: { artifact_id: "art-1", pid: 256, packet_index: 30 },
  ...overrides,
});

describe("DiagnosisList — exported presentation (wire strings verbatim)", () => {
  it("renders code/severity/confidence/state as the wire enum strings", () => {
    render(<DiagnosisList diagnoses={[diag({})]} />);
    expect(screen.getByText("CC_DISCONTINUITY")).toBeInTheDocument();
    expect(screen.getByText("warning")).toBeInTheDocument();
    // confidence is the static rule declaration — plain enum text, never a
    // number/percentage (CONTEXT.md 诊断 ban).
    expect(screen.getByText("confidence: high")).toBeInTheDocument();
    expect(screen.queryByText(/confidence: \d/)).not.toBeInTheDocument();
    expect(screen.getByText("raised")).toBeInTheDocument();
  });

  it("keeps cleared rows visible and weakly marked with cleared_at", () => {
    render(
      <DiagnosisList
        diagnoses={[diag({ state: "cleared", cleared_at: 2_000, diagnosis_id: "d-2" })]}
      />,
    );
    expect(screen.getByText("cleared")).toBeInTheDocument();
    const row = screen.getByTestId("diagnosis-row-d-2");
    expect(row).toBeInTheDocument();
  });

  it("renders observation_refs as static reference chips (journal_seq + event_type)", () => {
    render(<DiagnosisList diagnoses={[diag({})]} />);
    expect(screen.getByText("seq 12 · ts.continuity_error")).toBeInTheDocument();
  });

  it("renders NO locator button on table rows (the wire DiagnosisDTO carries no evidence field)", () => {
    const onSelect = vi.fn();
    render(<DiagnosisList diagnoses={[diag({})]} onEvidenceSelect={onSelect} />);
    expect(screen.queryByRole("button", { name: /evidence|locator|定位/i })).not.toBeInTheDocument();
    // The locator presentation slot lives on the candidate list only —
    // that is where the wire carries {artifact_id, pid, packet_index}.
  });

  it("sorts rows by the SPEC-307 §5 matrix (severity desc, then code — table rows carry no priority)", () => {
    render(
      <DiagnosisList
        diagnoses={[
          diag({ diagnosis_id: "d-low", code: "B_RULE", severity: "info" }),
          diag({ diagnosis_id: "d-mid", code: "Z_RULE", severity: "warning" }),
          diag({ diagnosis_id: "d-top", code: "A_RULE", severity: "critical" }),
        ]}
      />,
    );
    const rows = screen.getAllByTestId(/^diagnosis-row-/);
    expect(rows[0]).toHaveAttribute("data-testid", "diagnosis-row-d-top");
    expect(rows[2]).toHaveAttribute("data-testid", "diagnosis-row-d-low");
  });

  it("renders an explicit empty state when there are no rows", () => {
    render(<DiagnosisList diagnoses={[]} />);
    const c = MONITOR_EMPTY_STATE_COPY.diagnosis;
    expect(screen.getByText(c.what)).toBeInTheDocument();
    expect(screen.getByText(c.why)).toBeInTheDocument();
    expect(screen.getByText(`下一步:${c.next}`)).toBeInTheDocument();
  });

  it("renders the context node (SPEC-406 overlay slot) without touching fact rows", () => {
    render(<DiagnosisList diagnoses={[diag({})]} context={<span>SC-01 语境</span>} />);
    expect(screen.getByText("SC-01 语境")).toBeInTheDocument();
    expect(screen.getByText("CC_DISCONTINUITY")).toBeInTheDocument();
  });
});

describe("DiagnosisCandidateList — report candidates with priority/title/evidence", () => {
  it("renders priority, title, summary and code", () => {
    render(<DiagnosisCandidateList candidates={[candidate({})]} />);
    expect(screen.getByText("priority 30")).toBeInTheDocument();
    expect(screen.getByText("连续性计数不连续")).toBeInTheDocument();
    expect(screen.getByText("CC_DISCONTINUITY")).toBeInTheDocument();
  });

  it("renders the evidence locator verbatim", () => {
    render(<DiagnosisCandidateList candidates={[candidate({})]} />);
    const locator = screen.getByRole("button", { name: /evidence: art-1/ });
    expect(locator).toHaveTextContent("pid 256");
    expect(locator).toHaveTextContent("packet 30");
  });

  it("orders candidates by the SPEC-307 §5 matrix (priority asc)", () => {
    render(
      <DiagnosisCandidateList
        candidates={[candidate({ diagnosis_id: "c-40", priority: 40 }), candidate({ diagnosis_id: "c-10", priority: 10 })]}
      />,
    );
    const rows = screen.getAllByTestId(/^candidate-row-/);
    expect(rows[0]).toHaveAttribute("data-testid", "candidate-row-c-10");
  });

  it("raises onEvidenceSelect with the candidate locator", async () => {
    const onSelect = vi.fn();
    const locator: DiagnosisEvidenceDTO = { artifact_id: "art-2", pid: 256, packet_index: 30 };
    render(<DiagnosisCandidateList candidates={[candidate({ evidence: locator })]} onEvidenceSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: /art-2/ }));
    expect(onSelect).toHaveBeenCalledWith(
      locator,
      expect.objectContaining({ diagnosis_id: "c-1" }),
    );
  });
});
