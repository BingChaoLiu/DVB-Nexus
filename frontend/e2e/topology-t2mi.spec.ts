// SPEC-401 §Phase2 canvas E2E (#135): the three-level encapsulation subgraph
// (三级封装 gen → enc → dmx → mon) end to end in a real browser — palette
// entries with the CONTEXT.md「Phase 2 封装层」labels, registry default ports
// (inner_in/t2mi_out, t2mi_in/inner_out), the #63 per-schema config forms
// (T2miEncapsulatorConfigDTO / T2miDemuxConfigDTO field lists) satisfying the
// G1 gate, the T2MI links admitted by the MVP_ENABLED_PLANES mirror
// (readonly ["MPEG_TS","T2MI"], the #121 domain frozenset), and the stored
// wire truth (connection planes MPEG_TS / T2MI / MPEG_TS).
// Canvas-driving discipline: the #81 incident fix, extracted into
// e2e/helpers/canvas.ts (zoom normalize + live-viewport flow coordinates +
// not-covered click preconditions). Wire shapes are the only exact-match
// targets; copy is asserted at CONTEXT.md anchor level (tests/README §6).
import { expect, test } from "@playwright/test";

import {
  clampIntoVisibleRect,
  connectHandles,
  dragPaletteItemToCanvas,
  nodeFlowPosition,
  openFreshDraft,
  savedTopologyWire,
  visibleFlowRect,
  zoomCanvasOut,
} from "./helpers/canvas";
import { fillMinimalGeneratorConfig } from "./helpers/inspector";

test("三级封装子图: drag → fill Phase 2 configs → connect T2MI links → save → wire truth", async ({ page }) => {
  await openFreshDraft(page);

  // Palette carries the two Phase 2 entries with the CONTEXT.md 词条 labels
  // (BBFrame stays a node-internal layer — never named as a plane).
  const palette = page.getByLabel("节点面板");
  await expect(palette.locator('[data-node-type="t2mi_encapsulator"]')).toContainText("T2-MI 封装器");
  await expect(palette.locator('[data-node-type="t2mi_demux"]')).toContainText("T2-MI 解封装器");

  // Drop the four-node chain, spaced in flow coordinates (the #81 fix).
  await zoomCanvasOut(page);
  const firstRect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_generator", "gen-0", clampIntoVisibleRect(firstRect, { x: firstRect.x + 60, y: firstRect.y + 40 }));
  await zoomCanvasOut(page); // no-op unless the fitView drain re-zoomed the canvas
  const gen = await nodeFlowPosition(page, "gen-0");
  const rect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "t2mi_encapsulator", "enc-0", clampIntoVisibleRect(rect, { x: gen.x + 320, y: gen.y }));
  await dragPaletteItemToCanvas(page, "t2mi_demux", "dmx-0", clampIntoVisibleRect(rect, { x: gen.x + 640, y: gen.y }));
  await dragPaletteItemToCanvas(page, "ts_monitor", "mon-0", clampIntoVisibleRect(rect, { x: gen.x + 960, y: gen.y + 200 }));

  // Registry default ports per the SPEC-401 §Phase2 table.
  await expect(page.locator('[data-node-id="enc-0"]').getByTestId("dvb-topo-handle-inner_in")).toBeVisible();
  await expect(page.locator('[data-node-id="enc-0"]').getByTestId("dvb-topo-handle-t2mi_out")).toBeVisible();
  await expect(page.locator('[data-node-id="dmx-0"]').getByTestId("dvb-topo-handle-t2mi_in")).toBeVisible();
  await expect(page.locator('[data-node-id="dmx-0"]').getByTestId("dvb-topo-handle-inner_out")).toBeVisible();

  // G1 gate: the three typed-config nodes are 配置待填 subjects (mon is
  // trivially complete — config_schema null).
  const note = page.getByTestId("dvb-topo-gate-note");
  await expect(note).toContainText("暂不能保存：3 处待处理");
  await expect(note).toContainText("配置待填 → 右侧「节点属性」补全");

  // gen-0: the shared minimal generator fill (helpers/inspector.ts seam).
  await page.locator(".react-flow__node", { has: page.locator('[data-node-id="gen-0"]') }).click();
  await fillMinimalGeneratorConfig(page);

  // enc-0: T2miEncapsulatorConfigDTO form — one assignment row + the five
  // bbframe_params keys (npd_enabled free checkbox left false).
  await page.locator(".react-flow__node", { has: page.locator('[data-node-id="enc-0"]') }).click();
  await page.getByRole("button", { name: "增行" }).click();
  await page.getByLabel("plp_assignment.entries[].plp_id", { exact: true }).fill("0");
  await page.getByLabel("plp_assignment.entries[].source_tag", { exact: true }).fill("inner");
  await page.getByLabel("bbframe_params.matype_value", { exact: true }).fill("0");
  await page.getByLabel("bbframe_params.upl", { exact: true }).fill("1504");
  await page.getByLabel("bbframe_params.n_ups", { exact: true }).fill("1");
  await page.getByLabel("bbframe_params.issy_mode", { exact: true }).fill("simple");
  await page.getByRole("button", { name: "应用到草稿" }).click();

  // dmx-0: T2miDemuxConfigDTO form — expected-PLP filter (strict_crc rides its
  // wire default true). The select is targeted through its data-field hook
  // (the wrapping-label accessible name carries extra text for selects).
  await page.locator(".react-flow__node", { has: page.locator('[data-node-id="dmx-0"]') }).click();
  await page.locator('[data-field="plp_filter.mode"] select').selectOption("expected");
  await page.getByLabel("plp_filter.expected_plp", { exact: true }).fill("0");
  await page.getByRole("button", { name: "应用到草稿" }).click();

  // The gate opens → zero noise (all typed configs complete).
  await expect(note).toHaveCount(0);

  // REQ-UI-401-003: handle-to-handle connect — the T2MI link is admitted by
  // the mirrored plane set with NO precheck-code change.
  await connectHandles(page, "gen-0", "ts_out", "enc-0", "inner_in");
  await connectHandles(page, "enc-0", "t2mi_out", "dmx-0", "t2mi_in");
  await connectHandles(page, "dmx-0", "inner_out", "mon-0", "ts_in");
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);

  // REQ-UI-401-007: save → revision 1, then the wire truth.
  await page.getByRole("button", { name: /保存为新 revision/ }).click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 1");
  const topologyId = await page.locator('[aria-label="选择拓扑"]').inputValue();
  expect(topologyId).not.toBe("");
  const wire = await savedTopologyWire(page, topologyId);
  expect(wire.revision).toBe(1);
  expect(wire.nodes.map((n) => n.node_type).sort()).toEqual([
    "t2mi_demux",
    "t2mi_encapsulator",
    "ts_generator",
    "ts_monitor",
  ]);
  const enc = wire.nodes.find((n) => n.node_id === "enc-0")!;
  expect(enc.node_type).toBe("t2mi_encapsulator");
  expect(enc.ports).toEqual([
    { port_id: "inner_in", direction: "input", plane: "MPEG_TS", max_connections: 1 },
    { port_id: "t2mi_out", direction: "output", plane: "T2MI", max_connections: 1 },
  ]);
  const dmx = wire.nodes.find((n) => n.node_id === "dmx-0")!;
  expect(dmx.ports).toEqual([
    { port_id: "t2mi_in", direction: "input", plane: "T2MI", max_connections: 1 },
    { port_id: "inner_out", direction: "output", plane: "MPEG_TS", max_connections: 1 },
  ]);
  // connection planes: 外层 MPEG_TS → T2MI → Inner TS MPEG_TS (三级封装;
  // BBFrame is the encapsulator's internal layer — it never appears as a plane).
  expect(wire.connections.map((c) => [c.from_node, c.from_port, c.to_node, c.to_port, c.plane])).toEqual([
    ["gen-0", "ts_out", "enc-0", "inner_in", "MPEG_TS"],
    ["enc-0", "t2mi_out", "dmx-0", "t2mi_in", "T2MI"],
    ["dmx-0", "inner_out", "mon-0", "ts_in", "MPEG_TS"],
  ]);

  // Persistence: reload, pick OUR topology back, the chain renders again.
  await page.reload();
  await page.waitForLoadState("networkidle");
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);
  await expect(page.locator('[data-node-id="enc-0"]').getByTestId("dvb-topo-handle-t2mi_out")).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
});

test("§Phase2 plane precheck: a T2MI↔MPEG_TS mix rejects with the updated reason line and never reaches the wire", async ({ page }) => {
  await openFreshDraft(page);

  await zoomCanvasOut(page);
  const firstRect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "t2mi_encapsulator", "enc-0", clampIntoVisibleRect(firstRect, { x: firstRect.x + 60, y: firstRect.y + 40 }));
  await zoomCanvasOut(page);
  const enc = await nodeFlowPosition(page, "enc-0");
  const rect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_monitor", "mon-0", clampIntoVisibleRect(rect, { x: enc.x + 320, y: enc.y }));

  // enc.t2mi_out (output, T2MI) → mon.ts_in (input, MPEG_TS): direction and
  // cardinality pass, the plane precheck rejects — the §Phase2 reason line
  // surfaces inline for ~4 s and no edge is created (ADR-0009 decision 4).
  const t2miOut = page.locator('[data-node-id="enc-0"]').getByTestId("dvb-topo-handle-t2mi_out");
  const monIn = page.locator('[data-node-id="mon-0"]').getByTestId("dvb-topo-handle-ts_in");
  await t2miOut.click();
  await monIn.click();
  await expect(page.getByTestId("dvb-topo-connection-hint")).toHaveText("平面不符（当前支持 MPEG_TS / T2MI）");
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);
  await expect(page.getByTestId("dvb-topo-canvas")).not.toHaveAttribute("data-connecting", /.+/);
});
