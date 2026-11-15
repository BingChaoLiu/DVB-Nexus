// Control bar (SPEC-403 §4.2/§7.2, AC-403-01): table-driven buttons, wire
// lifecycle badge, busy lock, and the 409 SIM_INVALID_LIFECYCLE_TRANSITION
// resync branch (details.current / details.allowed rendered; no raw stack).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../api/client";
import { ControlBar } from "./ControlBar";

const invalidTransition = (current: string, allowed: string[]) =>
  new ApiError({
    status: 409,
    errorCode: "SIM_INVALID_LIFECYCLE_TRANSITION",
    message: "invalid lifecycle transition",
    details: { current, target: "running", allowed },
  });

describe("ControlBar — table-driven enablement", () => {
  it("renders the wire lifecycle string verbatim as the badge", () => {
    render(<ControlBar lifecycle="running" onAction={vi.fn()} />);
    expect(screen.getByTestId("lifecycle-badge")).toHaveTextContent("running");
  });

  it("enables exactly the STATE_ACTIONS set for the current state (ready)", () => {
    render(<ControlBar lifecycle="ready" onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "start" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "stop" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "validate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "pause" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "resume" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "dispose" })).toBeDisabled();
  });

  it("disables every action while lifecycle is unknown (no guessing)", () => {
    render(<ControlBar lifecycle={null} onAction={vi.fn()} />);
    for (const action of ["validate", "start", "pause", "resume", "stop", "dispose"]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
    expect(screen.getByTestId("lifecycle-badge")).toHaveTextContent(/未知/);
  });

  it("disables everything in the absorbing state disposed", () => {
    render(<ControlBar lifecycle="disposed" onAction={vi.fn()} />);
    for (const action of ["validate", "start", "pause", "resume", "stop", "dispose"]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
  });

  it("locks all buttons while an action is in flight, releases on settle", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onAction = vi.fn(() => gate.then(() => undefined));
    render(<ControlBar lifecycle="ready" onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    expect(onAction).toHaveBeenCalledWith("start");
    for (const action of ["validate", "start", "pause", "resume", "stop", "dispose"]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
    release();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "pause" })).toBeDisabled());
    // after settle the matrix returns (still state ready in this test)
    await userEvent.click(screen.getByRole("button", { name: "stop" }));
    expect(onAction).toHaveBeenLastCalledWith("stop");
  });
});

describe("ControlBar — 409 SIM_INVALID_LIFECYCLE_TRANSITION resync", () => {
  it("renders details.current / details.allowed and calls onResync (stale-UI scenario)", async () => {
    // UI believes ready; the server already moved on (current=running).
    const onAction = vi.fn(() => Promise.reject(invalidTransition("running", ["paused", "failed", "stopping"])));
    const onResync = vi.fn();
    render(<ControlBar lifecycle="ready" onAction={onAction} onResync={onResync} />);
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    const notice = await screen.findByTestId("lifecycle-error");
    expect(notice).toHaveTextContent("running");
    expect(notice).toHaveTextContent("paused, failed, stopping");
    expect(onResync).toHaveBeenCalledWith("running");
  });

  it("non-409 errors render the error code without resync", async () => {
    const onAction = vi.fn(
      () =>
        Promise.reject(
          new ApiError({ status: 503, errorCode: "SIM_BACKEND_UNAVAILABLE", message: "down", retryable: true }),
        ),
    );
    const onResync = vi.fn();
    render(<ControlBar lifecycle="ready" onAction={onAction} onResync={onResync} />);
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    const notice = await screen.findByTestId("lifecycle-error");
    expect(notice).toHaveTextContent("SIM_BACKEND_UNAVAILABLE");
    expect(onResync).not.toHaveBeenCalled();
  });
});
