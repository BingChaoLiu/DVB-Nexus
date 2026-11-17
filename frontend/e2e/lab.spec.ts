// Training Lab E2E (SPEC-406 §11 / AC-406-01..07; SPEC-408 §4.4/§11.3,
// ticket #101): the /lab route region over the REAL backend — the HOME-FOYER
// starting point (§11.3 主干旅程: home → CTA → library), library browse,
// detail render (camelCase island), hints progressive reveal (zero /solution
// requests), the §7.3 THREE-hop opening (auto-baseline declaration note +
// Generate self-lit + the guidance layer), the SC-01 PASS-reachable full
// chain (Inject → Diagnose → Recover → verify PASS → solution reveal 200),
// and the SC-04 honest-INCONCLUSIVE chain (NOT_EVALUATED reasons rendered,
// solution stays locked, and the backend reveal gate answers 403 at the
// request level).
//
// Disciplines pinned here (SPEC-406 §4.7/§12 + SPEC-408 §4.4/§7.5):
// - hidden_reference_solution is NEVER requested before the held verdict is
//   PASS (page.on('request') watch across the whole chain);
// - the verdict renders from the server answer only (no local derivation);
// - INCONCLUSIVE is an honest terminal state (无观测 ≠ 干净), not a failure;
// - the auto-baseline third hop is REAL sandbox data (lab-autorun-note
//   verbatim) and the verify form NEVER auto-guesses run ids — baseline/
//   recovery must be explicitly picked before 提交判定 unlocks.
import { expect, test, type APIRequestContext } from "@playwright/test";

const SC01 = "5c010000-0000-4000-8000-000000000001";
const SC04 = "5c040000-0000-4000-8000-000000000004";

const SOLUTION_URL_SC01 = new RegExp(
  `/api/v1/scenarios/${SC01}/solution\\?session_id=[0-9a-f-]{36}`,
);

test.describe("Training Lab — SC-01 PASS-reachable full chain (home-foyer start)", () => {
  // The home start + guidance assertions widen the chain; the run polls stay
  // the dominant cost, but the headroom is now deliberately larger.
  test.setTimeout(90_000);

  test("home → CTA → library → detail → hints reveal → 开局(auto-baseline) → inject → diagnose → recover → verify PASS → solution reveal", async ({
    page,
    request,
  }) => {
    const solutionRequests: string[] = [];
    const verifyRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes(`/api/v1/scenarios/${SC01}/solution`)) {
        solutionRequests.push(req.url());
      }
      if (req.url().includes("/verify")) {
        verifyRequests.push(req.url());
      }
    });

    // --- Home-foyer start (SPEC-408 §11.3 主干旅程): foyer renders, the bar
    // names the start area, and the CTA leads into the Lab library. (The
    // foyer's frozen copy literals are pinned verbatim in shell.spec.ts;
    // this chain asserts the JOURNEY through them.)
    await page.goto("/");
    await expect(page.getByTestId("home-hero-goal")).toBeVisible();
    await expect(page.getByTestId("home-cta-start")).toBeVisible();
    await expect(page.getByTestId("journey-you-are")).toHaveText("你在：旅程起点");
    await page.getByTestId("home-cta-start").click();
    await expect(page.getByRole("heading", { name: "Lab" })).toBeVisible();
    await expect(page.getByTestId("journey-you-are")).toHaveText("你在：Lab·场景库");

    // --- Library (AC-406-01): the five Lab Pack rows, server registry order.
    for (const title of [
      "认识闭环：PAT 缺失",
      "CRC 防线：PMT 校验和失效",
      "声明失配：PMT PID 重指向",
      "连续性破坏：CC 相对偏移",
      "双故障靶场：组合症状",
    ]) {
      await expect(page.getByText(title)).toBeVisible({ timeout: 15_000 });
    }

    // --- Detail (AC-406-02 + SPEC-408 §4.4 row 单入口): the row's ONLY
    // action is 「查看详情」; objectives + criteria + the camelCase island.
    const sc01Row = page.getByTestId(`lab-scenario-${SC01}`);
    await expect(sc01Row).toBeVisible();
    await expect(sc01Row.getByRole("button", { name: "开始实验" })).toHaveCount(0);
    await sc01Row.getByRole("button", { name: "查看详情" }).click();
    await expect(page.getByTestId("journey-you-are")).toHaveText("你在：Lab·场景详情");
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

    // --- 开局 (AC-406-03 + SPEC-408 §7.3 third hop): two-hop orchestration,
    // then the auto-baseline run is ALREADY in the registry.
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page.getByTestId("lab-step-create")).toContainText("开局完成");
    await expect(page.getByTestId("journey-you-are")).toHaveText("你在：Lab·实验台");

    // --- Guidance layer (SPEC-408 §4.4): the standing auto-baseline note
    // (verbatim) sits ABOVE the Stepper, the action guide BELOW it, and the
    // DOM order is note → stepper → guide (#98/#96 seam contract).
    const note = page.getByTestId("lab-autorun-note");
    await expect(note).toHaveText(
      "开局已自动提交基线 Run——真实沙盘数据，非示例。下一步：注入故障。",
    );
    const domOrder = await page.evaluate(() => {
      const ids = ["lab-autorun-note", "lab-stepper", "lab-action-guide"];
      const els = ids
        .map((id) => document.querySelector(`[data-testid="${id}"]`))
        .filter((el): el is Element => el !== null);
      return els
        .sort((a, b) =>
          a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
        )
        .map((el) => el.getAttribute("data-testid"));
    });
    expect(domOrder).toEqual(["lab-autorun-note", "lab-stepper", "lab-action-guide"]);

    // --- The auto-baseline run self-lights Generate (§7.3): the FIRST row is
    // the auto-submitted baseline (no manual 生成基线 click happened), and
    // once it completes the Generate step is lit WITHOUT any user run click.
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 30_000 });
    const autoBaselineRunId = (await autoRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(autoBaselineRunId).toBeTruthy();
    await expect(page.getByTestId("lab-step-generate")).toContainText("基线完成");
    // Analyze is the declared gap: 不可用, never progress; the pointer SKIPS
    // it and falls on Inject (§7.2) — the inject button is the primary one.
    await expect(page.getByTestId("lab-step-analyze")).toContainText("不可用");
    await expect(page.getByTestId("lab-step-inject")).toHaveClass(/dvb-lab-step-current/);
    await expect(page.getByRole("button", { name: /注入故障/ })).toHaveClass(/dvb-lab-btn-primary/);
    await expect(page.getByTestId("lab-action-guide")).toHaveText(
      "下一步：注入故障 → 点击『注入故障（Inject，场景 fault_plan）』",
    );

    // --- Inject (§4.5): nth(1) — the auto-baseline owns nth(0).
    await page.getByRole("button", { name: /注入故障/ }).click();
    const injectRow = page.getByTestId(/^lab-run-row-/).nth(1);
    await expect(injectRow).toHaveText(/completed/, { timeout: 30_000 });
    await expect(injectRow).toContainText("faulted_ts");
    await expect(page.getByTestId("lab-step-inject")).toContainText("注入完成");
    const injectedRunId = (await injectRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(injectedRunId).not.toBe(autoBaselineRunId);

    // --- Diagnose (SPEC-408 §4.4 主级化跨区块一致): the pointer moves past
    // Inject; the diagnose button in its OWN section is now the primary one,
    // and the guide names it verbatim.
    await expect(page.getByTestId("lab-action-guide")).toHaveText(
      "下一步：诊断注入 Run → 点击『对注入 Run 评估（diagnose）』",
    );
    const diagnoseButton = page.getByRole("button", { name: /对注入 Run 评估/ });
    await expect(diagnoseButton).toHaveClass(/dvb-lab-btn-primary/);
    await diagnoseButton.click();
    // Report SHAPE pins run id + candidates/warnings counts; zero candidates
    // stays the honest answer (no Analyze bridge — M4 裁定 B).
    await expect(
      page.getByText(new RegExp(`report: run ${injectedRunId} · \\d+ candidates · \\d+ warnings`)),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("lab-step-diagnose")).toContainText("已诊断");
    // The pointer now falls on the first UNLIT step in canonical order.
    // Inspect lights ONLY from the page's events answer (fetched once at
    // console mount), so the honest pointer is either Inspect (the mount
    // raced ahead of the auto-baseline's journal events) or Recover (the
    // events answer already saw a run event) — both §7.2-correct; 乱序点亮
    // 不回退 and the pointer never skips an unlit earlier step.
    await expect(page.getByTestId("lab-action-guide")).toHaveText(
      /下一步：(取证（Inspect）|恢复重跑)/,
    );

    // --- Recover (§4.5): nth(2).
    await page.getByRole("button", { name: /恢复重跑/ }).click();
    const recoverRow = page.getByTestId(/^lab-run-row-/).nth(2);
    await expect(recoverRow).toHaveText(/completed/, { timeout: 30_000 });
    await expect(page.getByTestId("lab-step-recover")).toContainText("恢复完成");
    const recoveryRunId = (await recoverRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(recoveryRunId).not.toBe(autoBaselineRunId);
    expect(recoveryRunId).not.toBe(injectedRunId);

    // --- Stepper click = LOCATOR, not check-off (SPEC-408 §4.4): clicking
    // Verify flashes the verify section and NEVER mutates light-up.
    await page.getByTestId("lab-step-verify").click();
    await expect(page.getByTestId("lab-section-verify")).toHaveClass(/dvb-lab-section-flash/);
    await expect(page.getByTestId("lab-step-verify")).not.toHaveClass(/dvb-lab-step-done/);

    // --- Verify (AC-406-05/07 + SPEC-408 §7.5): the EDITABLE PREFILL form.
    // Identity triple prefilled from the REAL scenario detail; run ids NEVER
    // auto-guessed — the submit stays disabled (and zero /verify requests
    // fire) until both run fields hold the user's explicit pick.
    await expect(page.getByLabel("scenario_id")).toHaveValue(SC01);
    await expect(page.getByLabel("version")).toHaveValue("1.0.0");
    await expect(page.getByLabel("content_hash")).toHaveValue(/^[0-9a-f]{64}$/);
    await expect(page.getByLabel("content_hash")).not.toHaveValue("lab-ui-unpinned");
    await expect(page.getByLabel("baseline_run_id")).toHaveValue("");
    await expect(page.getByLabel("recovery_run_id")).toHaveValue("");
    await expect(page.getByRole("button", { name: /提交判定/ })).toBeDisabled();
    // datalist candidates = this console's run registry (auto + inject + recover).
    await expect(page.locator("#lab-verify-run-candidates option")).toHaveCount(3);
    expect(verifyRequests).toEqual([]);
    // The explicit picks (#98 诉求): baseline = the INJECTED run (the fault
    // activation fact the fault_inactive criterion reads), recovery = the
    // clean rerun. The auto-baseline run stays a datalist candidate only.
    await page.getByLabel("baseline_run_id").fill(injectedRunId);
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
    await expect(page.getByRole("button", { name: /提交判定/ })).toBeEnabled();
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/PASS/);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText("fault-cleared");
    await expect(card).toContainText("fault_inactive");
    await expect(page.getByTestId("lab-step-verify")).toContainText("已判定");
    await expect
      .poll(() => verifyRequests.length, { timeout: 5_000 })
      .toBe(1);

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

    // The §7.3 third hop: the auto-baseline is the FIRST registry row — no
    // manual 生成基线 click (the §7.5 run-不自动猜 verify form then picks it
    // explicitly as the baseline candidate).
    await expect(page.getByTestId("lab-autorun-note")).toBeVisible();
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 30_000 });
    const autoBaselineRunId = (await autoRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");

    await page.getByRole("button", { name: /注入故障/ }).click();
    const injectRow = page.getByTestId(/^lab-run-row-/).nth(1);
    await expect(injectRow).toHaveText(/completed/, { timeout: 30_000 });
    const injectedRunId = (await injectRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");

    await page.getByRole("button", { name: /恢复重跑/ }).click();
    const recoverRow = page.getByTestId(/^lab-run-row-/).nth(2);
    await expect(recoverRow).toHaveText(/completed/, { timeout: 30_000 });
    const recoveryRunId = (await recoverRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(recoveryRunId).not.toBe(autoBaselineRunId);
    expect(recoveryRunId).not.toBe(injectedRunId);

    // Observation-class criteria have no evidence face (M4 裁定 B) — the
    // honest verdict is INCONCLUSIVE and the NOT_EVALUATED rows name it.
    // The form's run fields must be EXPLICITLY picked first (run 不自动猜):
    // baseline = the injected run, recovery = the clean rerun (#98 诉求);
    // identity prefills from the SC-04 scenario detail.
    await page.getByLabel("baseline_run_id").fill(injectedRunId);
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
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

// ---------------------------------------------------------------------------
// Lab Pack v2 (ticket #131, SPEC-406 §Phase2): the four Phase 2 scenarios
// landed from docs/spec/.../examples/lab-pack-v2/. Per orchestrator ruling
// §10-22 the E2E scope is:
// - SC-06/07 (real T2MI/BBFRAME primitives): full chain — 开局 (three-level
//   subgraph detail) → inject (layered run) → journal EVIDENCE events +
//   payload-key shapes (ruling §10-18: NOT a diagnose-face candidate
//   assertion — the SPEC-306 §6 anchor gap is #136's evaluation item) →
//   packet-inspector view deep link (§10-20-⑦ layer→view map) → recover →
//   verify PASS;
// - SC-08 (BISS): the CI face is the biss-section validation + 开局/
//   presence; the DLL-driven full injection chain is the LOCAL env-gated
//   enhancement below (DVB_NEXUS_DVBCSA_DLL; skip reason visible with
//   -ra, §5-11) — key MATERIAL is asserted as shape only, never literals;
// - SC-09 (PMT_PID_DRIFT): landing + loader + UI 开局/呈现 assertions only —
//   the TS-layer primitive is an honest skeleton (apply raises, ruling
//   §10-15④), so the faulted run is deliberately NOT exercised here.
// Disciplines unchanged: shapes over literals (UUID [0-9a-f-]{36}), the
// promise-预挂 request watches, and zero regression for the v1 chains above.
// ---------------------------------------------------------------------------

const SC06 = "5c010000-0000-4000-8000-000000000006";
const SC07 = "5c010000-0000-4000-8000-000000000007";
const SC08 = "5c010000-0000-4000-8000-000000000008";
const SC09 = "5c010000-0000-4000-8000-000000000009";

/** The run-status REST face → the artifact id of one kind (the deep-link
 * locator needs the artifact id; the run rows carry only the kind label). */
async function artifactIdOfKind(
  request: APIRequestContext,
  sessionId: string,
  runId: string,
  kind: string,
): Promise<string> {
  const view = await request.get(`/api/v1/sessions/${sessionId}/runs/${runId}`);
  expect(view.status()).toBe(200);
  const json = (await view.json()) as {
    artifacts?: { kind: string; artifact_id: string }[];
  };
  const artifact = json.artifacts?.find((entry) => entry.kind === kind);
  expect(artifact, `run ${runId} must tee a ${kind} artifact`).toBeTruthy();
  expect(artifact!.artifact_id).toMatch(/^[0-9a-f-]{36}$/);
  return artifact!.artifact_id;
}

type EventsAnswer = {
  data: { items: { journal_seq: number; event_type: string; payload: Record<string, unknown> }[] };
};

async function expectEvidenceEvent(
  request: APIRequestContext,
  sessionId: string,
  eventType: string,
): Promise<Record<string, unknown>> {
  const response = await request.get(
    `/api/v1/sessions/${sessionId}/events?limit=300&event_type=${eventType}`,
  );
  expect(response.status()).toBe(200);
  const events = (await response.json()) as EventsAnswer;
  expect(
    events.data.items.length,
    `journal must carry at least one ${eventType}`,
  ).toBeGreaterThanOrEqual(1);
  return events.data.items[0].payload;
}

test.describe("Training Lab — SC-06 T2MI PLP mismatch (Lab Pack v2 full chain)", () => {
  test.setTimeout(150_000);

  test("开局(three-level subgraph) → inject → t2mi.plp_mismatch evidence → view=t2mi deep link → recover → verify PASS", async ({
    page,
    request,
  }) => {
    const solutionRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes(`/api/v1/scenarios/${SC06}/solution`)) {
        solutionRequests.push(req.url());
      }
    });

    // --- Detail: the #110 three-level topology renders in the camelCase
    // island (t2mi_encapsulator / t2mi_demux over the T2MI plane link).
    await page.goto(`/lab?scenario=${SC06}`);
    await expect(page.getByTestId("lab-topology-view")).toBeVisible();
    const topologyView = page.getByTestId("lab-topology-view");
    for (const wire of [
      "nodeType t2mi_encapsulator",
      "nodeType t2mi_demux",
      "portId t2mi_out",
      "portId t2mi_in",
      "plane T2MI",
    ]) {
      await expect(topologyView).toContainText(wire);
    }
    // The single fault_inactive criterion (same SC-01 posture).
    await expect(page.getByText("fault_inactive").first()).toBeVisible();

    // --- 开局: session + auto-baseline (empty plan → the MVP single-layer
    // path; the scenario's T2MI-layer fault only rides the inject run).
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 60_000 });
    const autoBaselineRunId = (await autoRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");

    // --- Inject: the scenario fault plan routes the run onto the layered
    // chain (#128) — the tee leg is the TRANSMITTED T2-MI stream.
    await page.getByRole("button", { name: /注入故障/ }).click();
    const injectRow = page.getByTestId(/^lab-run-row-/).nth(1);
    await expect(injectRow).toHaveText(/completed/, { timeout: 60_000 });
    await expect(injectRow).toContainText("faulted_ts");
    const injectedRunId = (await injectRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(injectedRunId).not.toBe(autoBaselineRunId);

    // --- Journal evidence (ruling §10-18 face): the B1 candidate event
    // with the exact registered payload keys — shapes, never literals.
    const payload = await expectEvidenceEvent(request, sessionId, "t2mi.plp_mismatch");
    for (const key of ["expected_plp", "actual_plp", "business_absent_evidence"]) {
      expect(payload).toHaveProperty(key);
    }
    expect(typeof payload.expected_plp).toBe("number");
    // Honest ambiguity: an unresolvable actual PLP stays null (never a guess).
    if (payload.actual_plp !== null) {
      expect(payload.actual_plp).not.toBe(payload.expected_plp);
    }
    const evidence = payload.business_absent_evidence as Record<string, unknown>;
    for (const key of ["plps_seen", "bbframe_packet_count", "filtered_packet_count", "total_packet_count"]) {
      expect(evidence).toHaveProperty(key);
    }
    expect(Array.isArray(evidence.plps_seen)).toBe(true);

    // The deep-link locator rides the injected run's transmitted T2-MI
    // artifact (run-status REST face; the run rows carry the kind label
    // only).  The deep link itself runs LAST — navigating away and back
    // remounts the console and reorders the run rows (page-memory registry
    // first), which would break nth() indexing for the recover step.
    const faultedArtifactId = await artifactIdOfKind(request, sessionId, injectedRunId, "faulted_ts");

    // --- Recover (empty-plan rerun) then verify PASS.
    await page.getByRole("button", { name: /恢复重跑/ }).click();
    const recoverRow = page.getByTestId(/^lab-run-row-/).nth(2);
    await expect(recoverRow).toHaveText(/completed/, { timeout: 60_000 });
    const recoveryRunId = (await recoverRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(recoveryRunId).not.toBe(injectedRunId);

    await page.getByLabel("baseline_run_id").fill(injectedRunId);
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/PASS/);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText("fault-cleared");
    await expect(card).toContainText("fault_inactive");

    // --- Solution reveal unlocks on PASS (通关前零请求).
    expect(solutionRequests).toEqual([]);
    await page.getByRole("button", { name: "展开参考解" }).click();
    await expect(page.getByTestId("lab-solution-text")).toContainText("恢复路径", { timeout: 15_000 });
    expect(solutionRequests).toHaveLength(1);
    expect(solutionRequests[0]).toContain(`/api/v1/scenarios/${SC06}/solution`);

    // --- Packet inspector deep link (§10-20-⑦: T2MI → view=t2mi) over the
    // injected run's transmitted T2-MI artifact — the chain's last hop.
    await page.goto(
      `/monitor?session=${sessionId}&inspect_artifact=${faultedArtifactId}&inspect_pid=0&inspect_packet=0&view=t2mi`,
    );
    await expect(page.getByTestId("packet-inspector")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view t2mi");
    await expect(page.getByTestId("t2mi-structure-view")).toBeVisible();
  });
});

test.describe("Training Lab — SC-07 BBHEADER sync fault (Lab Pack v2 full chain)", () => {
  test.setTimeout(150_000);

  test("开局 → inject → bbframe.recovery_failed evidence → view=bbframe deep link (SYNCD anchor) → recover → verify PASS", async ({
    page,
    request,
  }) => {
    const solutionRequests: string[] = [];
    page.on("request", (req) => {
      if (req.url().includes(`/api/v1/scenarios/${SC07}/solution`)) {
        solutionRequests.push(req.url());
      }
    });

    await page.goto(`/lab?scenario=${SC07}`);
    await expect(page.getByTestId("lab-topology-view")).toBeVisible();
    await expect(page.getByTestId("lab-topology-view")).toContainText("nodeType t2mi_encapsulator");

    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 60_000 });
    const autoBaselineRunId = (await autoRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");

    await page.getByRole("button", { name: /注入故障/ }).click();
    const injectRow = page.getByTestId(/^lab-run-row-/).nth(1);
    await expect(injectRow).toHaveText(/completed/, { timeout: 60_000 });
    await expect(injectRow).toContainText("faulted_ts");
    const injectedRunId = (await injectRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(injectedRunId).not.toBe(autoBaselineRunId);

    // --- Journal evidence: the B2 recovery face with the registered keys.
    const payload = await expectEvidenceEvent(request, sessionId, "bbframe.recovery_failed");
    for (const key of ["failure_count", "first_failed_frame_index"]) {
      expect(payload).toHaveProperty(key);
    }
    expect(typeof payload.failure_count).toBe("number");
    expect(payload.failure_count as number).toBeGreaterThan(0);

    // The deep-link locator rides the injected run's transmitted T2-MI
    // artifact; the deep link runs LAST (see the SC-06 chain comment).
    const faultedArtifactId = await artifactIdOfKind(request, sessionId, injectedRunId, "faulted_ts");

    // --- Recover then verify PASS.
    await page.getByRole("button", { name: /恢复重跑/ }).click();
    const recoverRow = page.getByTestId(/^lab-run-row-/).nth(2);
    await expect(recoverRow).toHaveText(/completed/, { timeout: 60_000 });
    const recoveryRunId = (await recoverRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(recoveryRunId).not.toBe(injectedRunId);

    await page.getByLabel("baseline_run_id").fill(injectedRunId);
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/PASS/);
    const card = page.locator(".dvb-mon-verify-card");
    await expect(card).toContainText("fault-cleared");

    expect(solutionRequests).toEqual([]);
    await page.getByRole("button", { name: "展开参考解" }).click();
    await expect(page.getByTestId("lab-solution-text")).toContainText("恢复路径", { timeout: 15_000 });
    expect(solutionRequests).toHaveLength(1);
    expect(solutionRequests[0]).toContain(`/api/v1/scenarios/${SC07}/solution`);

    // --- Deep link (§10-20-⑦: BBFRAME → view=bbframe): the BBHEADER face
    // plus the SYNCD teaching anchor, pinned VERBATIM (SPEC-404 §Phase2).
    await page.goto(
      `/monitor?session=${sessionId}&inspect_artifact=${faultedArtifactId}&inspect_pid=0&inspect_packet=0&view=bbframe`,
    );
    await expect(page.getByTestId("packet-inspector")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view bbframe");
    await expect(page.getByTestId("bbframe-structure-view")).toBeVisible();
    await expect(page.getByTestId("bbframe-syncd-anchor")).toHaveText(
      "SYNCD 是数据字段内首个 UP 的位距离，不是同步字节",
    );
  });
});

test.describe("Training Lab — SC-08 BISS key mismatch (Lab Pack v2, CI face)", () => {
  test("biss-section validation + 开局/presence; the DLL injection chain is the env-gated local face below", async ({
    page,
    request,
  }) => {
    // --- REST detail face: the scenario biss construction section survives
    // the loader + detail projection (mode 1; CA_PID 0x1FFF).  Key MATERIAL
    // is asserted as SHAPE only — the session word literal is never pinned
    // (SPEC-610 §9 密钥本体 discipline covers test assertions).
    const detail = await request.get(`/api/v1/scenarios/${SC08}`);
    expect(detail.status()).toBe(200);
    const detailJson = (await detail.json()) as {
      scenario_id: string;
      biss?: { mode: string; session_word?: string; pid_scope: number[]; ca_pid: number };
      fault_plan?: { fault_type: string; expected_observations: string[] }[];
    };
    expect(detailJson.scenario_id).toBe(SC08);
    expect(detailJson.biss?.mode).toBe("1");
    expect(detailJson.biss?.ca_pid).toBe(8191);
    expect(detailJson.biss?.pid_scope).toEqual([256]);
    expect(detailJson.biss?.session_word ?? "").toMatch(/^[0-9A-Fa-f]{12}$/);
    expect(detailJson.fault_plan?.[0]?.fault_type).toBe("BISS_KEY_MISMATCH");
    expect(detailJson.fault_plan?.[0]?.expected_observations).toContain("biss.descramble_failed");

    // --- 开局/presence: the session opens RUNNING and the console mounts.
    // The auto-baseline run (empty plan) still carries the scenario's
    // declared BISS construction face (the composition root resolves the
    // biss section for EVERY run of this session, ADR-0011 §3) — so its
    // terminal state tracks the DLL honestly: absent (CI) → the DLL-absent
    // degradation failure; present (local) → completed.  Both faces are
    // asserted; neither is fabricated.
    await page.goto(`/lab?scenario=${SC08}`);
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(process.env.DVB_NEXUS_DVBCSA_DLL ? /completed/ : /failed/, {
      timeout: 60_000,
    });
  });

  test("LOCAL (DVB_NEXUS_DVBCSA_DLL set): full chain inject → biss.descramble_failed evidence → recover → verify PASS", async ({
    page,
    request,
  }) => {
    // Env-gated local enhancement (ruling §10-22②): the production dlopen
    // adapter needs the SSE2 bitslice DLL (tools/build_dvbcsa_dll.sh — the
    // sandbox artifacts stay read-only outside the repo).  Skip is honest
    // and visible (`-ra`), never a silent pass (§5-11).
    test.skip(
      !process.env.DVB_NEXUS_DVBCSA_DLL,
      "BISS full chain needs the dvbcsa DLL (DVB_NEXUS_DVBCSA_DLL); CI NOT RUN by design (ADR-0011 §5)",
    );
    test.setTimeout(150_000);

    await page.goto(`/lab?scenario=${SC08}`);
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 60_000 });
    const autoBaselineRunId = (await autoRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");

    await page.getByRole("button", { name: /注入故障/ }).click();
    const injectRow = page.getByTestId(/^lab-run-row-/).nth(1);
    await expect(injectRow).toHaveText(/completed/, { timeout: 60_000 });
    const injectedRunId = (await injectRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(injectedRunId).not.toBe(autoBaselineRunId);

    // The C1 evidence face: descramble self-check failure with the
    // registered payload keys (fingerprints only — never key material).
    const payload = await expectEvidenceEvent(request, sessionId, "biss.descramble_failed");
    for (const key of ["pid_scope", "failed_indices_sample", "self_check_kind", "key_fingerprint_ref", "mode"]) {
      expect(payload).toHaveProperty(key);
    }
    expect(Array.isArray(payload.failed_indices_sample)).toBe(true);
    expect(typeof payload.self_check_kind).toBe("string");
    expect(String(payload.key_fingerprint_ref)).not.toMatch(/^[0-9A-Fa-f]{12}$/); // fingerprint, not the SW

    await page.getByRole("button", { name: /恢复重跑/ }).click();
    const recoverRow = page.getByTestId(/^lab-run-row-/).nth(2);
    await expect(recoverRow).toHaveText(/completed/, { timeout: 60_000 });
    const recoveryRunId = (await recoverRow.getAttribute("data-testid"))!.replace("lab-run-row-", "");
    expect(recoveryRunId).not.toBe(injectedRunId);

    await page.getByLabel("baseline_run_id").fill(injectedRunId);
    await page.getByLabel("recovery_run_id").fill(recoveryRunId);
    await page.getByRole("button", { name: /提交判定/ }).click();
    const verdict = page.getByTestId("verify-verdict");
    await expect(verdict).toBeVisible({ timeout: 15_000 });
    await expect(verdict).toHaveText(/PASS/);
  });
});

test.describe("Training Lab — SC-09 PMT PID drift (Lab Pack v2, honest landing face)", () => {
  test("library carries the v2 pack; detail declares the drift fault; 开局 + auto-baseline complete (faulted run NOT exercised)", async ({
    page,
    request,
  }) => {
    // --- Library: the v2 four render in the server registry order (filename
    // ASC after the v1 five) — the SPEC-406 §Phase2 场景库自然承载.  Each
    // title rides its own row anchor.
    await page.goto("/lab");
    const rowTitles: [string, string][] = [
      [SC06, "封装错位：T2MI PLP 映射（业务漂移到非期望 PLP）"],
      [SC07, "封装错位：BBHEADER 同步（SYNCD 位距错配）"],
      [SC08, "加扰错位：BISS 密钥（session word 错配）"],
      [SC09, "时序错位：PMT 版本更新后的 PID 漂移（Demux 过滤未同步）"],
    ];
    for (const [scenarioId, title] of rowTitles) {
      await expect(
        page.getByTestId(`lab-scenario-${scenarioId}`).getByText(title),
      ).toBeVisible({ timeout: 15_000 });
    }

    // --- REST detail face: the drift fault declares the #130/#129 symbol
    // final (ruling §10-16③) and the JSON digit-string-key pid map.
    const detail = await request.get(`/api/v1/scenarios/${SC09}`);
    expect(detail.status()).toBe(200);
    const detailJson = (await detail.json()) as {
      difficulty: string;
      fault_plan?: {
        fault_type: string;
        target_id: string;
        parameters: { new_pid_map: Record<string, number>; pmt_version_bump: boolean };
        expected_observations: string[];
      }[];
    };
    expect(detailJson.difficulty).toBe("advanced");
    const fault = detailJson.fault_plan?.[0];
    expect(fault?.fault_type).toBe("PMT_PID_DRIFT");
    expect(fault?.target_id).toMatch(/^mux-0:pid:0x[0-9a-f]{1,4}$/);
    const pidMap = fault?.parameters.new_pid_map ?? {};
    expect(Object.keys(pidMap).length).toBeGreaterThanOrEqual(1);
    for (const programNumber of Object.keys(pidMap)) {
      expect(programNumber).toMatch(/^\d+$/);
    }
    expect(fault?.parameters.pmt_version_bump).toBe(true);
    expect(fault?.expected_observations).toEqual(
      expect.arrayContaining(["ts.psi_section_observed", "fault.applied"]),
    );

    // --- 开局/呈现: session READY + the auto-baseline (empty plan) completes
    // and the pointer falls on Inject.  The faulted run is DELIBERATELY not
    // exercised: PMT_PID_DRIFT is an honest TS-layer skeleton whose apply
    // raises (ruling §10-15④ — M6 has no implementation ticket; the gap is
    // recorded in the #131 REPORT and the patch ticket is on the #136
    // 收口评估 list).
    await page.goto(`/lab?scenario=${SC09}`);
    await page.getByRole("button", { name: "开始实验" }).click();
    await expect(page.getByTestId("lab-console-session")).toBeVisible({ timeout: 30_000 });
    const sessionId = ((await page.getByTestId("lab-console-session").textContent()) ?? "").trim();
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);
    const autoRow = page.getByTestId(/^lab-run-row-/).first();
    await expect(autoRow).toHaveText(/completed/, { timeout: 60_000 });
    await expect(page.getByTestId("lab-step-generate")).toContainText("基线完成");
    await expect(page.getByTestId("lab-step-inject")).toHaveClass(/dvb-lab-step-current/);
    await expect(page.getByRole("button", { name: /注入故障/ })).toBeEnabled();
  });
});
