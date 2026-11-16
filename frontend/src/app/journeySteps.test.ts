// Journey step table shape tests (SPEC-408 §1 eight-step overview, L23-32 —
// the content authority for the home journey map and the shell mini wayfinding
// bar). Expected values are the spec table's own cells, not recomputed logic.
import { describe, expect, it } from "vitest";
import { ANALYZE_GAP_NOTE, GUIDE_URL, JOURNEY_STEPS } from "./journeySteps";

describe("JOURNEY_STEPS — SPEC-408 §1 eight-step overview table", () => {
  it("has exactly the eight closed-loop steps in canonical order (CONTEXT.md wording)", () => {
    expect(JOURNEY_STEPS.map((step) => step.en)).toEqual([
      "Create",
      "Generate",
      "Inject",
      "Analyze",
      "Diagnose",
      "Inspect",
      "Recover",
      "Verify",
    ]);
    expect(JOURNEY_STEPS.map((step) => step.index)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("carries zh name, one-line description and location per the §1 table", () => {
    const byKey = new Map(JOURNEY_STEPS.map((step) => [step.key, step]));
    expect(byKey.get("create")?.zh).toBe("建会话");
    expect(byKey.get("create")?.what).toBe("选一个场景开局，得到 RUNNING 会话");
    expect(byKey.get("create")?.where).toBe("Lab·场景详情 → 实验台");
    expect(byKey.get("generate")?.what).toBe("空 plan 跑出第一批真实码流（开局自动基线可代跑）");
    expect(byKey.get("inject")?.what).toBe("按场景 fault_plan 注入，产出 faulted artifact");
    expect(byKey.get("analyze")?.what).toBe("深度分析面（MVP REST 冻结 501，诚实呈现，指针跳过）");
    expect(byKey.get("diagnose")?.what).toBe("对注入 Run 出根因候选");
    expect(byKey.get("inspect")?.where).toBe("Monitor/包检查器（Lab 深链进入）");
    expect(byKey.get("recover")?.what).toBe("故障清除后新 Run——通关证据的载体");
    expect(byKey.get("verify")?.what).toBe("服务端三态判定；PASS 只认修复后新 Run 证据");
    expect(byKey.get("verify")?.where).toBe("Lab·实验台（Monitor 同口径可用）");
  });

  it("marks Analyze as the only declared gap", () => {
    expect(JOURNEY_STEPS.filter((step) => step.gap).map((step) => step.key)).toEqual(["analyze"]);
  });

  it("uses the frozen Analyze gap annotation", () => {
    expect(ANALYZE_GAP_NOTE).toBe("不可用（REST 冻结 501），旅程自动跳过");
  });

  it("points the guide link at the repo docs/user-guide", () => {
    expect(GUIDE_URL).toMatch(/docs\/user-guide/);
    expect(GUIDE_URL.startsWith("https://github.com/BingChaoLiu/DVB-Nexus/")).toBe(true);
  });
});
