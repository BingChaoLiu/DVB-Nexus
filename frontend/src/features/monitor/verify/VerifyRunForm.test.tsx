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
