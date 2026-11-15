// Verify result card (SPEC-403 §4.6, AC-403-05): renders ONLY the server's
// VerificationResultDTO — the three fixture states and the criterion rows.
// The inversion fixture (criteria FAIL / verdict PASS) pins the no-local-
// derivation rule: a local aggregator would flip the verdict; the card must
// render the server string verbatim.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { VerificationResultDTO } from "../types";
import { VERIFY_CRITERION_KINDS, VerifyResultCard } from "./VerifyResultCard";

const result = (overrides: Partial<VerificationResultDTO>): VerificationResultDTO => ({
  session_id: "s-1",
  recovery_run_id: "r-rec",
  baseline_run_id: "r-base",
  scenario: { scenario_id: "sc-1", version: "1.0.0", content_hash: "abc" },
  verdict: "PASS",
  criteria: [
    { criterion_id: "cc-ok", kind: "cc_continuous", mandatory: true, result: "PASS" },
  ],
  evidence_refs: [],
  summary: "全部 mandatory 判据通过",
  verified_at_utc_ms: 1_000,
  ...overrides,
});

describe("VerifyResultCard — three-state verdict rendering", () => {
  for (const verdict of ["PASS", "FAIL", "INCONCLUSIVE"] as const) {
    it(`renders verdict ${verdict} verbatim`, () => {
      render(<VerifyResultCard result={result({ verdict })} />);
      expect(screen.getByTestId("verify-verdict")).toHaveTextContent(verdict);
    });
  }

  it("renders the inversion fixture verbatim (criteria FAIL, verdict PASS → PASS, no local flip)", () => {
    render(
      <VerifyResultCard
        result={result({
          verdict: "PASS",
          criteria: [{ criterion_id: "weird", kind: "cc_continuous", mandatory: true, result: "FAIL" }],
        })}
      />,
    );
    expect(screen.getByTestId("verify-verdict")).toHaveTextContent("PASS");
    expect(screen.getByTestId("verify-verdict")).not.toHaveTextContent("FAIL—verdict");
  });

  it("renders criterion rows with wire fields", () => {
    render(
      <VerifyResultCard
        result={result({
          criteria: [
            { criterion_id: "cc-ok", kind: "cc_continuous", mandatory: true, result: "PASS" },
            { criterion_id: "psi-ok", kind: "psi_pat_valid", mandatory: false, result: "FAIL", reason_code: "PSI_CRC", reason: "CRC 不匹配" },
          ],
        })}
      />,
    );
    expect(screen.getByText("cc-ok")).toBeInTheDocument();
    expect(screen.getByText("cc_continuous")).toBeInTheDocument();
    expect(screen.getByText("psi-ok")).toBeInTheDocument();
    expect(screen.getByText("psi_pat_valid")).toBeInTheDocument();
    expect(screen.getByText("mandatory")).toBeInTheDocument();
    expect(screen.getByText("optional")).toBeInTheDocument();
  });

  it("renders NOT_EVALUATED with its explicit reason (never silent)", () => {
    render(
      <VerifyResultCard
        result={result({
          verdict: "INCONCLUSIVE",
          criteria: [
            {
              criterion_id: "no-cc",
              kind: "no_unexpected_cc_error",
              mandatory: true,
              result: "NOT_EVALUATED",
              reason_code: "SIM_VERIF_EVIDENCE_MISSING",
              reason: "恢复 Run 观测缺失",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("NOT_EVALUATED")).toBeInTheDocument();
    expect(screen.getByText("SIM_VERIF_EVIDENCE_MISSING")).toBeInTheDocument();
    expect(screen.getByTestId("criterion-no-cc")).toHaveTextContent("恢复 Run 观测缺失");
  });

  it("renders summary and run identity fields", () => {
    render(<VerifyResultCard result={result({})} />);
    expect(screen.getByText("全部 mandatory 判据通过")).toBeInTheDocument();
    expect(screen.getByText(/r-base/)).toBeInTheDocument();
    expect(screen.getByText(/r-rec/)).toBeInTheDocument();
    expect(screen.getByText(/sc-1/)).toBeInTheDocument();
  });

  it("renders the context overlay slot (SPEC-406)", () => {
    render(<VerifyResultCard result={result({})} context={<span>SC-02 通关语境</span>} />);
    expect(screen.getByText("SC-02 通关语境")).toBeInTheDocument();
  });
});

describe("VERIFY_CRITERION_KINDS — the six-kind closed set (SPEC-206 §7)", () => {
  it("is exactly the frozen enum, verbatim", () => {
    expect([...VERIFY_CRITERION_KINDS].sort()).toEqual(
      [
        "fault_inactive",
        "psi_pat_valid",
        "psi_pmt_valid",
        "pat_pmt_mapping_valid",
        "cc_continuous",
        "no_unexpected_cc_error",
      ].sort(),
    );
  });
});
