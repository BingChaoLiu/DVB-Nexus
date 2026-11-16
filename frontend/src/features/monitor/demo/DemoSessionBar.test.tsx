// DemoSessionBar unit tests (SPEC-408 §4.3 demo session bar + §8 failure
// row, ticket #99): the three landed elements (declaration verbatim, rerun,
// cleanup), the honest per-phase progress rows (进行中/完成/失败), the
// explicit failure hint (「后端未运行？`start.cmd`」) and the kept-session
// manual-cleanup affordance. Wire-agnostic structure assertions only.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { initialDemoPhases, markDemoPhase, type DemoSessionState } from "./demoOrchestrate";
import { DemoSessionBar } from "./DemoSessionBar";

const SESSION = "aa990000-0000-4000-8000-000000009901";

function baseState(overrides: Partial<DemoSessionState> = {}): DemoSessionState {
  return {
    status: "orchestrating",
    phases: initialDemoPhases(),
    sessionId: null,
    scenarioTitle: null,
    inspectLocator: null,
    ...overrides,
  };
}

describe("DemoSessionBar — orchestrating", () => {
  it("renders one honest row per phase with its current state word", () => {
    const phases = markDemoPhase(
      markDemoPhase(initialDemoPhases(), "scenario", "done", "认识闭环：PAT 缺失"),
      "create",
      "active",
    );
    render(<DemoSessionBar demo={baseState({ phases })} rerunBusy={false} cleanupBusy={false} rerunError={null} cleanupError={null} onRerun={() => {}} onCleanup={() => {}} />);

    expect(screen.getByTestId("demo-session-bar")).toHaveAttribute("data-demo-status", "orchestrating");
    expect(screen.getByTestId("demo-phase-row-scenario")).toHaveAttribute("data-phase-state", "done");
    expect(screen.getByTestId("demo-phase-row-scenario").textContent).toContain("完成");
    expect(screen.getByTestId("demo-phase-row-create")).toHaveAttribute("data-phase-state", "active");
    expect(screen.getByTestId("demo-phase-row-create").textContent).toContain("进行中");
    expect(screen.getByTestId("demo-phase-row-inject").textContent).toContain("等待");
  });

  it("no landed action buttons while orchestrating without a session", () => {
    render(<DemoSessionBar demo={baseState()} rerunBusy={false} cleanupBusy={false} rerunError={null} cleanupError={null} onRerun={() => {}} onCleanup={() => {}} />);
    expect(screen.queryByTestId("demo-rerun-run")).not.toBeInTheDocument();
    expect(screen.queryByTestId("demo-cleanup")).not.toBeInTheDocument();
  });
});

describe("DemoSessionBar — landed (three elements, §4.3)", () => {
  it("renders the declaration verbatim + rerun + cleanup for the demo session", async () => {
    const user = userEvent.setup();
    const onRerun = vi.fn();
    const onCleanup = vi.fn();
    const phases = markDemoPhase(initialDemoPhases(), "land", "done", "预锚定 PID 0 · packet 202");
    render(
      <DemoSessionBar
        demo={baseState({
          status: "landed",
          phases,
          sessionId: SESSION,
          scenarioTitle: "认识闭环：PAT 缺失",
          inspectLocator: { artifact_id: "art-1", pid: 0, packet_index: 202 },
        })}
        rerunBusy={false}
        cleanupBusy={false}
        rerunError={null}
        cleanupError={null}
        onRerun={onRerun}
        onCleanup={onCleanup}
      />,
    );

    // Element 1: the frozen declaration (SPEC-408 §4.3 verbatim).
    expect(screen.getByTestId("demo-declaration")).toHaveTextContent("数据 = 沙盘真实生成；与真实会话唯一差别是入口");
    // session identity visible
    expect(screen.getByTestId("demo-session-bar").textContent).toContain(SESSION);

    // Element 2 + 3: rerun + cleanup, both enabled.
    const rerun = screen.getByTestId("demo-rerun-run");
    expect(rerun).toHaveTextContent("再跑一个 Run（看 journal 实时流动）");
    expect(rerun).toBeEnabled();
    const cleanup = screen.getByTestId("demo-cleanup");
    expect(cleanup).toHaveTextContent("结束演示并清理");
    expect(cleanup).toBeEnabled();

    await user.click(rerun);
    await user.click(cleanup);
    expect(onRerun).toHaveBeenCalledTimes(1);
    expect(onCleanup).toHaveBeenCalledTimes(1);
  });

  it("disables rerun/cleanup while their requests are in flight", () => {
    render(
      <DemoSessionBar
        demo={baseState({ status: "landed", phases: initialDemoPhases(), sessionId: SESSION, scenarioTitle: "t", inspectLocator: null })}
        rerunBusy
        cleanupBusy
        rerunError={null}
        cleanupError={null}
        onRerun={() => {}}
        onCleanup={() => {}}
      />,
    );
    expect(screen.getByTestId("demo-rerun-run")).toBeDisabled();
    expect(screen.getByTestId("demo-cleanup")).toBeDisabled();
  });

  it("surfaces rerun/cleanup failures as explicit inline lines (no faking)", () => {
    render(
      <DemoSessionBar
        demo={baseState({ status: "landed", phases: initialDemoPhases(), sessionId: SESSION, scenarioTitle: "t", inspectLocator: null })}
        rerunBusy={false}
        cleanupBusy={false}
        rerunError="SIM_BACKEND_UNAVAILABLE: backend down"
        cleanupError={null}
        onRerun={() => {}}
        onCleanup={() => {}}
      />,
    );
    expect(screen.getByTestId("demo-rerun-error").textContent).toContain("SIM_BACKEND_UNAVAILABLE");
    expect(screen.queryByTestId("demo-cleanup-error")).not.toBeInTheDocument();
  });
});

describe("DemoSessionBar — failed (§8 row 1: explicit reason + start.cmd hint + kept session)", () => {
  it("failed row carries the reason, the start.cmd hint shows, and a kept session stays cleanable", async () => {
    const user = userEvent.setup();
    const onCleanup = vi.fn();
    const phases = markDemoPhase(markDemoPhase(initialDemoPhases(), "inject", "failed", "SIM_RUN_FAILED: inject exploded"), "land", "pending");
    render(
      <DemoSessionBar
        demo={baseState({ status: "failed", phases, sessionId: SESSION, scenarioTitle: null, inspectLocator: null })}
        rerunBusy={false}
        cleanupBusy={false}
        rerunError={null}
        cleanupError={null}
        onRerun={() => {}}
        onCleanup={onCleanup}
      />,
    );

    expect(screen.getByTestId("demo-session-bar")).toHaveAttribute("data-demo-status", "failed");
    const row = screen.getByTestId("demo-phase-row-inject");
    expect(row).toHaveAttribute("data-phase-state", "failed");
    expect(row.textContent).toContain("失败");
    expect(row.textContent).toContain("SIM_RUN_FAILED: inject exploded");

    // The frozen §8 hint (verbatim guidance).
    expect(screen.getByTestId("demo-failure-hint")).toHaveTextContent(/后端未运行？`start.cmd`/);
    // 已建会话保留可手动清理: the kept id is visible and cleanup works.
    expect(screen.getByTestId("demo-session-bar").textContent).toContain(SESSION);
    const cleanup = screen.getByTestId("demo-cleanup");
    expect(cleanup).toBeEnabled();
    await user.click(cleanup);
    expect(onCleanup).toHaveBeenCalledTimes(1);
  });
});
