// Current-action pointer — the §7.2 single-pointer layer over
// deriveStepState (SPEC-408 REQ-UI-408-008 / AC-408-05). The seam is the
// pure function `deriveCurrentAction`: canonical order
// [Create, Generate, Inject, Diagnose, Inspect, Recover, Verify], first
// NOT-done step = pointer; out-of-order completions light their step but
// never drag the pointer past an incomplete earlier step; all lit → Verify;
// Analyze (the declared gap) is NEVER a candidate. Input = the §7.3
// deriveStepState output — this file adds no fact inference of its own.
import { describe, expect, it } from "vitest";
import { deriveStepState, type LabFacts } from "./stepperState";
import { CURRENT_ACTION_ORDER, currentActionGuide, deriveCurrentAction } from "./currentAction";

function run(
  runId: string,
  status: LabFacts["runs"][number]["status"],
  kinds: string[],
): LabFacts["runs"][number] {
  return { runId, status, artifacts: kinds.map((kind) => ({ kind })) };
}

function steps(overrides: Partial<Record<keyof LabFacts, unknown>>) {
  // Base = loop not yet begun except Create (session running), via the §7.3
  // mapping — the pointer layer is only ever fed deriveStepState output.
  const facts: LabFacts = {
    sessionLifecycle: "running",
    runs: [],
    reportFetched: false,
    eventsSeen: 0,
    verdictFetched: false,
    ...overrides,
  } as LabFacts;
  return deriveStepState(facts);
}

describe("deriveCurrentAction — the §7.2 pointer table", () => {
  it("canonical order has exactly seven candidates, Analyze excluded", () => {
    expect([...CURRENT_ACTION_ORDER]).toEqual([
      "create",
      "generate",
      "inject",
      "diagnose",
      "inspect",
      "recover",
      "verify",
    ]);
    expect(CURRENT_ACTION_ORDER).not.toContain("analyze");
  });

  it("nothing done → pointer Create", () => {
    expect(deriveCurrentAction(steps({ sessionLifecycle: null }))).toBe("create");
  });

  it("in-order prefix done → pointer at the first not-done step", () => {
    const clean = run("r-base", "completed", ["generated_ts", "log"]);
    const faulted = run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]);
    // [facts override, expected pointer] — Create is done via base lifecycle.
    const table: Array<[Partial<LabFacts>, string]> = [
      [{ runs: [] }, "generate"],
      [{ runs: [clean] }, "inject"],
      [{ runs: [clean, faulted] }, "diagnose"],
      [{ runs: [clean, faulted], reportFetched: true }, "inspect"],
      [{ runs: [clean, faulted], reportFetched: true, eventsSeen: 1 }, "recover"],
      [
        {
          runs: [clean, faulted, run("r-recover", "completed", ["generated_ts", "log"])],
          reportFetched: true,
          eventsSeen: 1,
        },
        "verify",
      ],
    ];
    for (const [overrides, want] of table) {
      expect(deriveCurrentAction(steps(overrides))).toBe(want);
    }
  });

  it("out-of-order completion does NOT drag the pointer forward (乱序不回退)", () => {
    // Recover's fact (two clean runs) holds while Inject is still missing:
    // pointer stays at Inject — the fact lights Recover but cannot advance
    // the pointer past an incomplete earlier step.
    const outOfOrder = steps({
      runs: [
        run("r-clean-1", "completed", ["generated_ts", "log"]),
        run("r-clean-2", "completed", ["generated_ts", "log"]),
      ],
    });
    expect(deriveCurrentAction(outOfOrder)).toBe("inject");
    // verify fact held while generate missing → pointer generate.
    expect(deriveCurrentAction(steps({ verdictFetched: true }))).toBe("generate");
    // diagnose fact held while generate missing → pointer generate (not diagnose).
    expect(deriveCurrentAction(steps({ reportFetched: true }))).toBe("generate");
    // diagnose fact held while inject missing → pointer inject (not diagnose).
    const clean = run("r-clean", "completed", ["generated_ts", "log"]);
    expect(deriveCurrentAction(steps({ runs: [clean], reportFetched: true }))).toBe("inject");
  });

  it("pointer only moves forward as facts accumulate", () => {
    const a = steps({ runs: [run("r-base", "completed", ["generated_ts", "log"])] });
    expect(deriveCurrentAction(a)).toBe("inject");
    const b = steps({
      runs: [
        run("r-base", "completed", ["generated_ts", "log"]),
        run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
      ],
    });
    expect(deriveCurrentAction(b)).toBe("diagnose");
  });

  it("every step lit → pointer lands on Verify (or 闭环完成 face)", () => {
    const facts: LabFacts = {
      sessionLifecycle: "running",
      runs: [
        run("r-base", "completed", ["generated_ts", "log"]),
        run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
        run("r-recover", "completed", ["generated_ts", "log"]),
      ],
      reportFetched: true,
      eventsSeen: 3,
      verdictFetched: true,
    };
    const all = deriveStepState(facts);
    expect(deriveCurrentAction(all)).toBe("verify");
  });

  it("Analyze is never the pointer, even if a hypothetically true boolean arrives", () => {
    const allButCreateFalse = {
      create: false,
      generate: false,
      inject: false,
      analyze: true, // impossible from deriveStepState — pointer must still skip it
      diagnose: false,
      inspect: false,
      recover: false,
      verify: false,
    };
    expect(deriveCurrentAction(allButCreateFalse)).toBe("create");
  });

  it("first guide follows an automatic baseline: generate done, inject not → 注入故障", () => {
    // Auto-baseline (its own wiring is #98's seam) would leave exactly this
    // fact shape: one completed clean run, no faulted run yet.
    const afterBaseline = deriveStepState({
      sessionLifecycle: "running",
      runs: [run("r-auto-base", "completed", ["generated_ts", "log"])],
      reportFetched: false,
      eventsSeen: 0,
      verdictFetched: false,
    });
    expect(deriveCurrentAction(afterBaseline)).toBe("inject");
    expect(currentActionGuide(afterBaseline)).toBe(
      "下一步：注入故障 → 点击『注入故障（Inject，场景 fault_plan）』",
    );
  });

  it("guide copy is verbatim to the console button texts", () => {
    expect(currentActionGuide(steps({ sessionLifecycle: null }))).toBe(
      "下一步：开局（Create） → 等待会话 lifecycle 进入 running（未就绪时点「返回场景库」重新开局）",
    );
    expect(currentActionGuide(steps({}))).toBe(
      "下一步：生成基线 → 点击『生成基线（Generate，空 plan）』",
    );
    expect(
      currentActionGuide(
        steps({
          runs: [
            run("r-base", "completed", ["generated_ts", "log"]),
            run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
          ],
        }),
      ),
    ).toBe("下一步：诊断注入 Run → 点击『对注入 Run 评估（diagnose）』");
    expect(
      currentActionGuide(
        steps({
          runs: [
            run("r-base", "completed", ["generated_ts", "log"]),
            run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
          ],
          reportFetched: true,
        }),
      ),
    ).toBe("下一步：取证（Inspect） → 触发一个 Run 后在「证据 / 事件（Inspect）」区块查看 journal 事件");
    expect(
      currentActionGuide(
        steps({
          runs: [
            run("r-base", "completed", ["generated_ts", "log"]),
            run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
          ],
          reportFetched: true,
          eventsSeen: 2,
        }),
      ),
    ).toBe("下一步：恢复重跑 → 点击『恢复重跑（Recover，空 plan）』");
    expect(
      currentActionGuide(
        steps({
          runs: [
            run("r-base", "completed", ["generated_ts", "log"]),
            run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
            run("r-recover", "completed", ["generated_ts", "log"]),
          ],
          reportFetched: true,
          eventsSeen: 2,
        }),
      ),
    ).toBe("下一步：提交判定 → 点击『提交判定（verify）』");
  });

  it("all lit → the guide declares loop completion (not a fake next action)", () => {
    const facts: LabFacts = {
      sessionLifecycle: "running",
      runs: [
        run("r-base", "completed", ["generated_ts", "log"]),
        run("r-inject", "completed", ["generated_ts", "faulted_ts", "log"]),
        run("r-recover", "completed", ["generated_ts", "log"]),
      ],
      reportFetched: true,
      eventsSeen: 3,
      verdictFetched: true,
    };
    expect(currentActionGuide(deriveStepState(facts))).toBe(
      "下一步：闭环已完成（判定以 verify 服务端应答为准）",
    );
  });
});
