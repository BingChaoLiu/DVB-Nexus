// SPEC-402 node inspector E2E (TV-402-07 / AC-402-04/05): selection → form →
// apply → gate-gated save → reload echo, and the config_schema=null honest
// state — in a real browser through the same-origin proxy. Asserts visible
// disabled states and wire echo (never DOM snapshots; tests/README §6).
import { expect, test, type Page } from "@playwright/test";

async function dragPaletteItemToCanvas(page: Page, nodeType: string, position: { x: number; y: number }) {
  await page.dragAndDrop(`[data-node-type="${nodeType}"]`, '[data-testid="dvb-topo-canvas"] .react-flow__pane', {
    targetPosition: position,
  });
}

async function selectNode(page: Page, nodeId: string) {
  await page.locator(".react-flow__node", { has: page.locator(`[data-node-id="${nodeId}"]`) }).click();
}

/** Fill every required field of a minimal generator config (defaults fill the
 * optional ones) and apply — the 配置待填 → gate-open transition. */
async function fillMinimalGeneratorConfig(page: Page) {
  const required: [string, string][] = [
    ["seed", "20260101"],
    ["initial_media_clock_27mhz", "0"],
    ["target_bitrate_bps", "3008000"],
    ["output_packet_count", "1000"],
    ["program.transport_stream_id", "1"],
    ["program.program_number", "1"],
    ["program.pmt_pid", "4096"],
    ["program.pcr_pid", "256"],
    ["program.version_number", "0"],
  ];
  for (const [label, value] of required) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "应用到草稿" }).click();
}

test("generator gate: empty config keeps save disabled → fill & apply → save → reload echo (AC-402-04/05)", async ({ page }) => {
  await page.goto("/topologies");
  await page.getByRole("button", { name: "新建拓扑" }).click();
  await dragPaletteItemToCanvas(page, "ts_generator", { x: 200, y: 120 });

  // G1 (配置待填): save entry visibly disabled with the incomplete generator.
  const save = page.getByRole("button", { name: /保存为新 revision/ });
  await expect(save).toBeDisabled();

  // Select → the inspector renders the declarative field list.
  await selectNode(page, "gen-0");
  const inspector = page.getByRole("region", { name: "节点属性表单" });
  await expect(inspector.getByText("schema_version")).toBeVisible();
  await expect(inspector.getByText("program.pmt_pid")).toBeVisible();

  // Fill minimal config → apply → the gate opens (still dirty).
  await fillMinimalGeneratorConfig(page);
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 1");

  // The wire truth: stored config echoes the applied values (snake_case).
  const topologyId = await page.locator('[aria-label="选择拓扑"]').inputValue();
  const wire = (await page.request.get(`/api/v1/topologies/${topologyId}`).then((r) => r.json())) as {
    nodes: { node_id: string; config: Record<string, unknown> }[];
  };
  expect(wire.nodes[0]).toMatchObject({
    node_id: "gen-0",
    config: {
      schema_version: 1,
      seed: 20260101,
      target_bitrate_bps: 3008000,
      profile: "analysis_only",
      pat_period_ms: 101,
    },
  });

  // Persistence echo: reload, re-open OUR topology, re-select — the form
  // shows the stored config (seed verbatim); marking dirty with a
  // null-schema node then re-enables save, proving the GATE (not merely
  // dirty=false) is open after the reload.
  await page.reload();
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);
  await expect(page.getByTestId("dvb-topo-handle-ts_out")).toBeVisible();
  await selectNode(page, "gen-0");
  const inspectorAfterReload = page.getByRole("region", { name: "节点属性表单" });
  await expect(inspectorAfterReload.getByLabel("seed", { exact: true })).toHaveValue("20260101");
  await expect(page.getByRole("button", { name: /保存为新 revision/ })).toBeDisabled(); // clean draft
  await page.getByRole("button", { name: /TS 监测器/ }).click(); // dirty, null-schema: gate open
  await expect(page.getByRole("button", { name: /保存为新 revision/ })).toBeEnabled();
});

test("config_schema=null node shows the honest no-fields state (AC-402-01)", async ({ page }) => {
  await page.goto("/topologies");
  await page.getByRole("button", { name: "新建拓扑" }).click();
  await dragPaletteItemToCanvas(page, "ts_monitor", { x: 240, y: 160 });
  await selectNode(page, "mon-0");
  const inspector = page.getByRole("region", { name: "节点属性表单" });
  await expect(inspector.getByText("该类型无配置字段（config 恒 {}）")).toBeVisible();
  await expect(inspector.getByRole("spinbutton")).toHaveCount(0);
  await expect(inspector.getByRole("textbox")).toHaveCount(0);
  // null-schema types are trivially complete — save stays available (dirty).
  await expect(page.getByRole("button", { name: /保存为新 revision/ })).toBeEnabled();
});
