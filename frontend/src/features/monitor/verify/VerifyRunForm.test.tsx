// Verify request form (SPEC-403 §4.6): builds the VerifyRunRequest wire body.
// The kind dropdown is locked to the six-kind closed set; zero criterion rows
// disable submission (min 1). ui_state is never emitted.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VerifyRunForm } from "./VerifyRunForm";

async function fillAndSubmit() {
  const onSubmit = vi.fn();
  render(
    <VerifyRunForm
      runCandidates={["r-base", "r-rec", "r-inj"]}
      onSubmit={onSubmit}
    />,
  );
  // run inputs are datalist-backed (browser-native suggestions); in jsdom we
  // type into them directly.
  await userEvent.type(screen.getByLabelText("recovery_run_id"), "r-rec");
  await userEvent.type(screen.getByLabelText("baseline_run_id"), "r-base");
  await userEvent.type(screen.getByLabelText("scenario_id"), "cc-discontinuity-lab");
  await userEvent.type(screen.getByLabelText("version"), "1.0.0");
  await userEvent.type(screen.getByLabelText("content_hash"), "e2e-smoke");
  await userEvent.type(screen.getByLabelText("criterion_id"), "cc-ok");
  await userEvent.selectOptions(screen.getByLabelText("kind"), "cc_continuous");
  await userEvent.type(screen.getByLabelText("fault_id"), "fd000000-0000-4000-8000-00000000f103");
  await userEvent.click(screen.getByRole("button", { name: "verify" }));
  return onSubmit;
}

describe("VerifyRunForm — request face", () => {
  it("offers exactly the six-kind closed set in the kind dropdown", () => {
    render(<VerifyRunForm runCandidates={[]} onSubmit={vi.fn()} />);
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options.sort()).toEqual(
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

  it("emits the wire-shaped request body with the chosen runs", async () => {
    const onSubmit = await fillAndSubmit();
    expect(onSubmit).toHaveBeenCalledOnce();
    const payload = onSubmit.mock.calls[0][0] as {
      recoveryRunId: string;
      body: {
        baseline_run_id: string;
        scenario: { scenario_id: string; version: string; content_hash: string };
        pass_criteria: { criterion_id: string; kind: string; mandatory: boolean; fault_id?: string }[];
        ui_state?: unknown;
      };
    };
    expect(payload.recoveryRunId).toBe("r-rec");
    expect(payload.body.baseline_run_id).toBe("r-base");
    expect(payload.body.scenario).toEqual({
      scenario_id: "cc-discontinuity-lab",
      version: "1.0.0",
      content_hash: "e2e-smoke",
    });
    expect(payload.body.pass_criteria).toEqual([
      {
        criterion_id: "cc-ok",
        kind: "cc_continuous",
        mandatory: true,
        fault_id: "fd000000-0000-4000-8000-00000000f103",
      },
    ]);
    // ui_state is accepted-and-ignored by the engine — the form never emits it.
    expect("ui_state" in payload.body).toBe(false);
  });

  it("disables submission while any required field is empty (min 1 criterion enforced)", async () => {
    const onSubmit = vi.fn();
    render(<VerifyRunForm runCandidates={["r-base"]} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("recovery_run_id"), "r-base");
    await userEvent.click(screen.getByRole("button", { name: "verify" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("can remove the criterion row, which disables submission", async () => {
    const onSubmit = vi.fn();
    render(<VerifyRunForm runCandidates={["r-base"]} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /移除判据/ }));
    await userEvent.click(screen.getByRole("button", { name: "verify" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// SPEC-408 §7.5 verify prefill (ticket #95): three-source editable prefill.
// scenario_id ← session detail; version/content_hash ← scenario detail;
// baseline/recovery candidates ← the run list datalist. Everything stays
// editable, and runs are NEVER auto-guessed: with no explicit user run
// choice there is no submission (zero verify requests).
describe("VerifyRunForm — editable prefill (SPEC-408 §7.5)", () => {
  const PREFILL = {
    scenarioId: "5c010000-0000-4000-8000-000000000001",
    version: "1.0.0",
    contentHash: "a".repeat(64),
  };

  it("renders the three-source prefill into the identity fields (still editable inputs)", () => {
    render(<VerifyRunForm runCandidates={["r-1", "r-2"]} prefill={PREFILL} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("scenario_id")).toHaveValue(PREFILL.scenarioId);
    expect(screen.getByLabelText("version")).toHaveValue(PREFILL.version);
    expect(screen.getByLabelText("content_hash")).toHaveValue(PREFILL.contentHash);
    // run fields stay EMPTY — candidates are suggestions, never values.
    expect(screen.getByLabelText("recovery_run_id")).toHaveValue("");
    expect(screen.getByLabelText("baseline_run_id")).toHaveValue("");
    // datalist carries the run candidates for explicit user selection.
    const datalist = document.getElementById("verify-run-candidates");
    expect(datalist?.querySelectorAll("option")).toHaveLength(2);
  });

  it("prefill arriving late (async detail read-back) still lands, and user edits win over prefill", async () => {
    const { rerender } = render(<VerifyRunForm runCandidates={["r-1"]} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("scenario_id")).toHaveValue("");

    rerender(<VerifyRunForm runCandidates={["r-1"]} prefill={PREFILL} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("scenario_id")).toHaveValue(PREFILL.scenarioId);

    // user edit overrides the prefill and survives further prefill re-renders
    await userEvent.clear(screen.getByLabelText("content_hash"));
    await userEvent.type(screen.getByLabelText("content_hash"), "user-picked-hash");
    rerender(<VerifyRunForm runCandidates={["r-1", "r-2"]} prefill={PREFILL} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("content_hash")).toHaveValue("user-picked-hash");
  });

  it("never auto-guesses runs: prefill + candidates but no user run choice → no submission (zero requests)", async () => {
    const onSubmit = vi.fn();
    render(<VerifyRunForm runCandidates={["r-base", "r-rec"]} prefill={PREFILL} onSubmit={onSubmit} />);
    // identity fields are prefilled, candidates are on offer — but the run
    // inputs are untouched, so the complete gate keeps submission disabled.
    expect(screen.getByLabelText("recovery_run_id")).toHaveValue("");
    expect(screen.getByLabelText("baseline_run_id")).toHaveValue("");
    expect(screen.getByRole("button", { name: "verify" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "verify" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("an explicit user run selection completes the prefilled form and emits the body", async () => {
    const onSubmit = vi.fn();
    render(<VerifyRunForm runCandidates={["r-base", "r-rec"]} prefill={PREFILL} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("recovery_run_id"), "r-rec");
    await userEvent.type(screen.getByLabelText("baseline_run_id"), "r-base");
    await userEvent.type(screen.getByLabelText("criterion_id"), "fault-cleared");
    await userEvent.selectOptions(screen.getByLabelText("kind"), "fault_inactive");
    await userEvent.type(screen.getByLabelText("fault_id"), "fd000000-0000-4000-8000-00000000f1a1");
    await userEvent.click(screen.getByRole("button", { name: "verify" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      recoveryRunId: "r-rec",
      body: {
        baseline_run_id: "r-base",
        scenario: { scenario_id: PREFILL.scenarioId, version: PREFILL.version, content_hash: PREFILL.contentHash },
        pass_criteria: [
          { criterion_id: "fault-cleared", kind: "fault_inactive", mandatory: true, fault_id: "fd000000-0000-4000-8000-00000000f1a1" },
        ],
      },
    });
  });
});
