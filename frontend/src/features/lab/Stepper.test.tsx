// Stepper as locator, not punch-card (SPEC-408 §4.4 REQ-UI-408-009). The
// seam is the rendered component: every step except the declared-gap
// Analyze is clickable and reports its key via onStepSelect; clicking is a
// pure navigation affordance — it NEVER mutates light-up (which only
// derives from server facts via deriveStepState), and the
// "stepper 进度 ≠ 通关判定" disclaimer survives verbatim.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { EightStepBooleans } from "./stepperState";
import { Stepper } from "./Stepper";

const LIT: EightStepBooleans = {
  create: true,
  generate: true,
  inject: false,
  analyze: false,
  diagnose: false,
  inspect: false,
  recover: false,
  verify: false,
};

describe("Stepper — clickable locator (定位非打卡)", () => {
  it("renders all eight steps; every step except Analyze is a button", () => {
    render(<Stepper steps={LIT} />);
    for (const key of ["create", "generate", "inject", "diagnose", "inspect", "recover", "verify"]) {
      expect(screen.getByTestId(`lab-step-${key}`).tagName).toBe("BUTTON");
    }
    // Analyze is the declared gap — rendered 不可用, never a click affordance.
    expect(screen.getByTestId("lab-step-analyze").tagName).not.toBe("BUTTON");
    expect(screen.getByTestId("lab-step-analyze")).toHaveTextContent("不可用");
  });

  it("clicking a step reports its key via onStepSelect", async () => {
    const user = userEvent.setup();
    const onStepSelect = vi.fn();
    render(<Stepper steps={LIT} onStepSelect={onStepSelect} />);
    await user.click(screen.getByTestId("lab-step-verify"));
    await user.click(screen.getByTestId("lab-step-generate"));
    expect(onStepSelect).toHaveBeenNthCalledWith(1, "verify");
    expect(onStepSelect).toHaveBeenNthCalledWith(2, "generate");
  });

  it("clicking never changes light-up state (点亮只来自服务端事实)", async () => {
    const user = userEvent.setup();
    render(<Stepper steps={LIT} onStepSelect={vi.fn()} />);
    // Inject is pending before the click.
    expect(screen.getByTestId("lab-step-inject")).toHaveTextContent("待办");
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("基线完成");
    await user.click(screen.getByTestId("lab-step-inject"));
    // ...and stays pending after it: a click is NOT a punch-card stamp.
    expect(screen.getByTestId("lab-step-inject")).toHaveTextContent("待办");
    expect(screen.getByTestId("lab-step-generate")).toHaveTextContent("基线完成");
    expect(screen.getByTestId("lab-step-inject")).not.toHaveTextContent("注入完成");
  });

  it("keeps the disclaimer verbatim (stepper 进度 ≠ 通关判定)", () => {
    render(<Stepper steps={LIT} />);
    expect(
      screen.getByText("stepper 进度 ≠ 通关判定（判定只来自 verify 服务端应答）"),
    ).toBeInTheDocument();
  });

  it("marks the current-action step (指针高亮是渲染层辅助,非打卡)", () => {
    render(<Stepper steps={LIT} />);
    // current action = inject (first not-done); it carries the marker class.
    expect(screen.getByTestId("lab-step-inject").className).toContain("dvb-lab-step-current");
    expect(screen.getByTestId("lab-step-generate").className).not.toContain("dvb-lab-step-current");
  });
});
