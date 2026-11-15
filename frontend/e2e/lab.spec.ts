// Training Lab E2E (SPEC-406 §11 / AC-406-01..07): the /lab route region
// over the REAL backend — library browse, detail render (camelCase island),
// hints progressive reveal (zero /solution requests), 开局 two-hop chain,
// the SC-01 PASS-reachable full chain (Generate → Inject → Recover → verify
// PASS → solution reveal 200), and the SC-04 honest-INCONCLUSIVE chain
// (NOT_EVALUATED reasons rendered, solution stays locked, and the backend
// reveal gate answers 403 at the request level).
//
// Disciplines pinned here (SPEC-406 §4.7/§12):
// - hidden_reference_solution is NEVER requested before the held verdict is
//   PASS (page.on('request') watch across the whole chain);
// - the verdict renders from the server answer only (no local derivation);
// - INCONCLUSIVE is an honest terminal state (无观测 ≠ 干净), not a failure.
import { expect, test } from "@playwright/test";

const SC01 = "5c010000-0000-4000-8000-000000000001";
const SC04 = "5c040000-0000-4000-8000-000000000004";

const SOLUTION_URL_SC01 = new RegExp(
  `/api/v1/scenarios/${SC01}/solution\\?session_id=[0-9a-f-]{36}`,
);

test.describe("Training Lab — SC-01 PASS-reachable full chain", () => {
  test("library → detail → hints reveal → 开局 → three runs → verify PASS → solution reveal", async ({
    page,
    request,
  }) => {
    const solutionRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes(`/api/v1/scenarios/${SC01}/solution`)) {
        solutionRequests.push(req.url());
      }
    });

    // --- Library (AC-406-01): the five Lab Pack rows, server registry order.
    await page.goto("/lab");
    for (const title of [
      "认识闭环：PAT 缺失",
      "CRC 防线：PMT 校验和失效",
      "声明失配：PMT PID 重指向",
      "连续性破坏：CC 相对偏移",
      "双故障靶场：组合症状",
    ]) {
      await expect(page.getByText(title)).toBeVisible({ timeout: 15_000 });
    }

    // --- Detail (AC-406-02): objectives + criteria + the camelCase island.
    await page.goto(`/lab?scenario=${SC01}`);
    await expect(page.getByText("观察基线流的 PSI 重复事实（PAT 在 PID 0 的周期性出现）")).toBeVisible();
    await expect(page.getByText("fault-cleared")).toBeVisible();
    await expect(page.getByText("fault_inactive").first()).toBeVisible();
    const topologyView = page.getByTestId("lab-topology-view");
    await expect(topologyView).toBeVisible();
    for (const wire of [
      "nodeId gen-0",
      "nodeType ts_generator",
      "nodeType ts_mux",
      "nodeType ts_monitor",
      "portId ts_out",
      "maxConnections 1",
    ]) {
      await expect(topologyView).toContainText(wire);
    }

    // --- Hints progressive reveal (AC-406-04): one layer per click, ZERO
    // /solution requests fire during reveals (the watch records the whole
    // page lifetime; it must stay empty until the PASS-gated reveal later).
    await expect(page.getByTestId("lab-hints-remaining")).toHaveText(/3/);
    await page.getByRole("button", { name: /揭示下一条提示/ }).click();
    await expect(page.getByText("PAT 位于 PID 0。先在基线 Run 的 artifact 上确认 PSI 重复节奏，再观察注入后同一 PID 的变化。")).toBeVisible();
    await page.getByRole("button", { name: /揭示下一条提示/ }).click();
    await expect(page.getByTestId("lab-hints-remaining")).toHaveText(/1/);
    expect(solutionRequests).toEqual([]);

    // --- 开局 (AC-406-03): the §4.3 two-hop orchestration.
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page.getByTestId("lab-step-create")).toContainText("开局完成");
    // (the create request BODY shape is asserted by the labBodies unit tests;
    //  the console mounting over a RUNNING scenario session IS the two-hop
    //  proof here)

    // --- The three Lab runs (§4.5): Generate → Inject → Recover.
    await page.getByRole("button", { name: /生成基线/ }).click();
    const baseRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(baseRow).toHaveText(/completed/, { timeout: 30_000 });
    await expect(page.getByTestId("lab-step-generate")).toContainText("基线完成");

    await page.getByRole("button", { name: /注入故障/ }).click();
    await expect(page.getByTestId(/^lab-run-row-/).nth(1)).toHaveText(/completed/, { timeout: 30_000 });
    await expect(page.getByTestId(/^lab-run-row-/).nth(1)).toContainText("faulted_ts");
    await expect(page.getByTestId("lab-step-inject")).toContainText("注入完成");

    await page.getByRole("button", { name: /恢复重跑/ }).click();
    await expect(page.getByTestId(/^lab-run-row-/).nth(2)).toHaveText(/completed/, { timeout: 30_000 });
    await expect(page.getByTestId("lab-step-recover")).toContainText("恢复完成");

    // Analyze is the declared gap: 不可用, never progress.
    await expect(page.getByTestId("lab-step-analyze")).toContainText("不可用");

    // --- Verify (AC-406-05/07): the server's three-state answer — PASS here.
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/PASS/);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText("fault-cleared");
    await expect(card).toContainText("fault_inactive");
    await expect(page.getByTestId("lab-step-verify")).toContainText("已判定");

    // --- Solution reveal (AC-406-07): unlocked ONLY NOW; before this point
    // the watch list must still be empty (通关前零请求).
    expect(solutionRequests).toEqual([]);
    await page.getByRole("button", { name: "展开参考解" }).click();
    await expect(page.getByTestId("lab-solution-text")).toContainText("恢复路径", { timeout: 15_000 });
    // The gated reveal actually consulted the backend gate with the session.
    await expect
      .poll(() => solutionRequests.length, { timeout: 5_000 })
      .toBe(1);
    expect(solutionRequests[0]).toMatch(SOLUTION_URL_SC01);

    // --- The session's evidence chain answer (Inspect fact): events exist.
    const events = await request.get(`/api/v1/sessions/${sessionId}/events?limit=10`);
    expect(events.status()).toBe(200);
    const eventsJson = (await events.json()) as { data: { items: unknown[] } };
    expect(eventsJson.data.items.length).toBeGreaterThanOrEqual(1);
  });
});

test.describe("Training Lab — SC-04 honest INCONCLUSIVE chain", () => {
  test("full chain renders INCONCLUSIVE + NOT_EVALUATED reasons; solution stays locked; the backend gate answers 403", async ({
    page,
    request,
  }) => {
    const solutionRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes(`/api/v1/scenarios/${SC04}/solution`)) {
        solutionRequests.push(req.url());
      }
    });

    await page.goto(`/lab?scenario=${SC04}`);
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();

    await page.getByRole("button", { name: /生成基线/ }).click();
    await expect(page.getByTestId(/^lab-run-row-/).first()).toHaveText(/completed/, { timeout: 30_000 });
    await page.getByRole("button", { name: /注入故障/ }).click();
    await expect(page.getByTestId(/^lab-run-row-/).nth(1)).toHaveText(/completed/, { timeout: 30_000 });
    await page.getByRole("button", { name: /恢复重跑/ }).click();
    await expect(page.getByTestId(/^lab-run-row-/).nth(2)).toHaveText(/completed/, { timeout: 30_000 });

    // Observation-class criteria have no evidence face (M4 裁定 B) — the
    // honest verdict is INCONCLUSIVE and the NOT_EVALUATED rows name it.
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/INCONCLUSIVE/);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText("NOT_EVALUATED");
    await expect(card).toContainText("SIM_VERIF_EVIDENCE_MISSING");

    // The solution NEVER unlocks: the button stays disabled and the panel
    // states the lock — and not a single /solution request was sent.
    await expect(page.getByRole("button", { name: "展开参考解" })).toBeDisabled();
    await expect(page.getByTestId("lab-solution-locked")).toContainText("参考解保持锁定");
    expect(solutionRequests).toEqual([]);

    // Request-level 通关前不泄露 proof: the backend reveal gate refuses a
    // PASS-less session with the SPEC-205 §7 row 6 code.
    const reveal = await request.get(`/api/v1/scenarios/${SC04}/solution?session_id=${sessionId}`);
    expect(reveal.status()).toBe(403);
    const revealJson = (await reveal.json()) as { error: { error_code: string } };
    expect(revealJson.error.error_code).toBe("SIM_SCENARIO_SOLUTION_LEAK");
  });
});
