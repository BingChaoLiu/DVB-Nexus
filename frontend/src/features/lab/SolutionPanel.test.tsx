// SolutionPanel (SPEC-406 §4.7, REQ-UI-406-007 / AC-406-07): the hidden
// reference solution stays LOCKED unless the page-held verdict is exactly
// "PASS" — the SAME verdict field the result card renders (no local
// derivation). The fetch is delegated to the parent (the panel never calls
// the api itself — fetch seam spied to pin it); a 403 server-gate refusal
// renders the server message and stays locked (the backend gate is the
// authority; the client unlock condition is only a precondition).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import { SolutionPanel } from "./SolutionPanel";

const fetchSpy = vi.fn();
vi.stubGlobal("fetch", fetchSpy);

beforeEach(() => fetchSpy.mockClear());
afterEach(() => fetchSpy.mockClear());

const base = {
  scenarioId: "5c010000-0000-4000-8000-000000000001",
  sessionId: "sess-1",
  solution: null,
  error: null,
  onRequest: vi.fn(),
};

describe("SolutionPanel — the PASS gate", () => {
  it("no verdict / FAIL / INCONCLUSIVE stay locked: button disabled, onRequest unreachable", async () => {
    const user = userEvent.setup();
    for (const verdict of [null, "FAIL", "INCONCLUSIVE"]) {
      const onRequest = vi.fn();
      const { unmount } = render(<SolutionPanel {...base} verdict={verdict} onRequest={onRequest} />);
      const button = screen.getByRole("button", { name: "展开参考解" });
      expect(button).toBeDisabled();
      expect(screen.getByTestId("lab-solution-locked")).toHaveTextContent("参考解保持锁定");
      await user.click(button).catch(() => {}); // disabled: no-op
      expect(onRequest).not.toHaveBeenCalled();
      expect(fetchSpy).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("verdict PASS unlocks; click delegates exactly once to onRequest (no direct fetch)", async () => {
    const user = userEvent.setup();
    const onRequest = vi.fn();
    render(<SolutionPanel {...base} verdict="PASS" onRequest={onRequest} />);
    const button = screen.getByRole("button", { name: "展开参考解" });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onRequest).toHaveBeenCalledTimes(1);
    expect(onRequest).toHaveBeenCalledWith("5c010000-0000-4000-8000-000000000001", "sess-1");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("fetched solution text renders verbatim; explicit null renders the 未声明 note", () => {
    const { rerender } = render(
      <SolutionPanel {...base} verdict="PASS" solution={{ text: "恢复路径：以空 fault_plan 重跑…" }} />,
    );
    expect(screen.getByTestId("lab-solution-text")).toHaveTextContent("恢复路径：以空 fault_plan 重跑…");

    rerender(<SolutionPanel {...base} verdict="PASS" solution={{ text: null }} />);
    expect(screen.getByText("本场景未声明参考解")).toBeInTheDocument();
  });

  it("a server-gate 403 renders the refusal and stays locked", () => {
    render(
      <SolutionPanel
        {...base}
        verdict="PASS"
        error={{ errorCode: "SIM_SCENARIO_SOLUTION_LEAK", message: "reveal refused: no PASS verdict" }}
      />,
    );
    expect(screen.getByTestId("lab-solution-error")).toHaveTextContent("SIM_SCENARIO_SOLUTION_LEAK");
    expect(screen.getByTestId("lab-solution-error")).toHaveTextContent("reveal refused: no PASS verdict");
    expect(screen.getByTestId("lab-solution-locked")).toBeInTheDocument();
  });

  it("locked-note context line names the backend gate (POST-gate reveal posture)", () => {
    render(<SolutionPanel {...base} verdict={null} />);
    expect(screen.getByTestId("lab-solution-locked")).toHaveTextContent("后端 reveal 门核验");
  });
});
