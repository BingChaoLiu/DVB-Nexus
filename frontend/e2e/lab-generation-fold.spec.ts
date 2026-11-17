// Lab 生成过程折叠区 E2E (SPEC-406 §Phase2, ticket #133): the read-only
// generation fold over the REAL backend. Two chains:
//
// 1. v1 SC-01 开局链 stand-in (SC-06 is #131's landing — the dispatch rules
//    the v1 chain proves journey compatibility): the UI opening walk lands
//    in the console with the fold mounted; v1 runs emit no gen.* events
//    (gen.* 仅分层 run 发射, ruling §10-15④) → the fold answers the honest
//    empty face and nothing about the journey moves.
//
// 2. Layered-run protocol compat: a BBHEADER_SYNC_FAULT plan routes the run
//    onto the layered chain (#128 plan-driven layering); the REAL gen.*
//    journal payloads are pulled through the SAME REST face the fold
//    consumes (payload key sets per #128/#129 — shapes asserted, values
//    never pinned), the fold renders the real stage rows + sampled packet
//    cards, and a packet-card jump lands on the #132 Monitor deep link with
//    view=t2mi over the transmitted T2-MI artifact.
//
// Disciplines (brief §5-9/§5-10): wire enums verbatim; UUID/64-hex asserted
// as SHAPES; lab.spec.ts is #131's additive face — untouched by this file.
import { expect, test } from "@playwright/test";
import { createStartedSession, submitAndAwaitRun } from "./helpers/backend";

const SC01 = "5c010000-0000-4000-8000-000000000001";
const UUID_SHAPE = /^[0-9a-f-]{36}$/;
const SHA256_SHAPE = /^[0-9a-f]{64}$/;

/** The B2 injection as the run-request wire body (no `layer` field on the
 * wire — the backend derives it; the proven #129/#132 e2e shape). */
const BBHEADER_SYNC_FAULT_PLAN = [
  {
    fault_id: "fd000000-0000-4000-8000-00000000b2099",
    fault_type: "BBHEADER_SYNC_FAULT",
    target_id: "mux-0",
    parameters: { field: "SYNCD", mode: "corrupt" },
    activation: { kind: "packet_index", packet_index: 3 },
    expected_observations: ["bbframe.recovery_failed"],
  },
];

test.describe("Lab 生成过程折叠区 (SPEC-406 §Phase2)", () => {
  test("v1 SC-01 开局链 stand-in: the journey keeps working with the fold mounted; zero gen.* events answer the honest empty face", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto(`/lab?scenario=${SC01}`);
    await page.getByRole("button", { name: "开始实验" }).click();
    const sessionChip = page.getByTestId("lab-console-session");
    await expect(sessionChip).toBeVisible({ timeout: 15_000 });
    expect(await sessionChip.textContent()).toMatch(UUID_SHAPE);

    // The fold's signpost is present inside the Inspect section; the eight
    // locator sections are untouched (八步闭环结构零改动).
    await expect(page.getByTestId("lab-gen-summary")).toBeVisible();
    await expect(page.getByTestId("lab-section-run")).toBeVisible();
    await expect(page.getByTestId("lab-section-verify")).toBeVisible();

    // v1 face: SC-01's runs (auto-baseline empty plan + TS-layer fault plan)
    // never route the layered chain — the fold opens on the honest empty
    // face, not a fabricated pipeline (无记录 ≠ 干净).
    await page.getByTestId("lab-gen-summary").click();
    const empty = page.getByTestId("lab-gen-empty");
    await expect(empty).toBeVisible();
    await expect(empty).toContainText("尚无分层生成事件");
    await expect(empty).toContainText("无记录 ≠ 干净");

    // The journey still moves: the auto-baseline run row shows up and the
    // run triggers stay reachable.
    await expect(page.getByTestId(/^lab-run-row-/).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "生成基线（Generate，空 plan）" })).toBeEnabled({ timeout: 15_000 });
  });

  test("layered-run protocol compat: real gen.* payloads drive the stage rows and packet cards; a jump lands on the view deep link", async ({ page, request }) => {
    test.setTimeout(90_000);
    const sessionId = await createStartedSession(request);
    expect(sessionId).toMatch(UUID_SHAPE);
    const run = await submitAndAwaitRun(request, sessionId, BBHEADER_SYNC_FAULT_PLAN);
    const faulted = run.artifacts.find((artifact) => artifact.kind === "faulted_ts");
    expect(faulted, "layered run must tee a faulted_ts (T2-MI) leg").toBeTruthy();

    // REST protocol compat: the fold's exact query face (the three gen.*
    // wire types) over the REAL journal.
    const eventsResponse = await request.get(
      `/api/v1/sessions/${sessionId}/events?limit=200&event_type=gen.stage_started&event_type=gen.stage_completed&event_type=gen.packet_sampled`,
    );
    expect(eventsResponse.status()).toBe(200);
    const events = (await eventsResponse.json()) as {
      data: { items: { journal_seq: number; event_type: string; payload: Record<string, unknown> }[] };
    };
    const types = new Set(events.data.items.map((item) => item.event_type));
    for (const wire of ["gen.stage_started", "gen.stage_completed", "gen.packet_sampled"]) {
      expect(types.has(wire), `journal must carry ${wire}`).toBe(true);
    }
    for (const item of events.data.items) {
      const layer = item.payload.layer;
      expect(["TS", "BISS", "BBFRAME", "T2MI"]).toContain(layer);
      if (item.event_type === "gen.stage_completed") {
        expect(typeof item.payload.item_count).toBe("number");
        expect(item.payload.item_count as number).toBeGreaterThan(0);
      }
      if (item.event_type === "gen.packet_sampled") {
        expect(typeof item.payload.packet_index).toBe("number");
        expect(item.payload.packet_index as number).toBeGreaterThanOrEqual(0);
        expect(typeof item.payload.byte_size).toBe("number");
        expect(String(item.payload.sha256)).toMatch(SHA256_SHAPE);
      }
    }

    // The console over this session (the fold's data face is session-scoped).
    await page.goto(`/lab?scenario=${SC01}&session=${sessionId}`);
    await page.getByTestId("lab-gen-summary").click();

    // Real stage rows, wire layers verbatim, chain order TS → BBFRAME → T2MI
    // (no BISS stage: the plan carries no BISS-layer fault and the scenario
    // declares no BISS construction face).
    await expect(page.getByTestId("lab-gen-stage-TS")).toContainText("已完成");
    await expect(page.getByTestId("lab-gen-stage-BBFRAME")).toContainText("已完成");
    await expect(page.getByTestId("lab-gen-stage-T2MI")).toContainText("已完成");
    const stageLayers = await page.getByTestId(/^lab-gen-stage-/).all();
    const stageTestIds = await Promise.all(stageLayers.map((node) => node.getAttribute("data-testid")));
    expect(stageTestIds).toEqual([
      "lab-gen-stage-TS",
      "lab-gen-stage-BBFRAME",
      "lab-gen-stage-T2MI",
    ]);

    // Real sampled packet cards: sha256 renders verbatim in 64-hex shape.
    const t2miCard = page.locator("[data-testid^='lab-gen-sample-']").filter({ hasText: "T2MI" }).first();
    await expect(t2miCard).toBeVisible();
    const sha = await t2miCard.locator(".dvb-lab-gen-sha").textContent();
    expect(sha).toMatch(SHA256_SHAPE);
    await expect(t2miCard).toContainText(/packet_index \d+/);
    await expect(t2miCard).toContainText(/byte_size \d+/);

    // The jump lands on the #132 Monitor deep link with the mapped view —
    // the T2MI sample maps to view=t2mi over the transmitted T2-MI artifact.
    await t2miCard.getByTestId(/lab-gen-jump-/).click();
    await page.waitForURL(/view=t2mi/);
    const url = new URL(page.url());
    expect(url.pathname).toBe("/monitor");
    expect(url.searchParams.get("session")).toMatch(UUID_SHAPE);
    expect(url.searchParams.get("inspect_artifact")).toMatch(UUID_SHAPE);
    expect(url.searchParams.get("inspect_pid")).toBe("0");
    expect(url.searchParams.get("inspect_packet")).toMatch(/^\d+$/);
    await expect(page.getByTestId("packet-inspector")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view t2mi");
    await expect(page.getByTestId("t2mi-structure-view")).toBeVisible();
  });
});
