// SPEC-401 canvas E2E (AC-401-01/03/04): drag → connect → save → new revision
// in a real browser through the same-origin proxy; the backend double layer
// for the single-plane rule surfaces as in-place path-addressed violations.
// Asserts wire shapes (snake_case field names/enum strings) and revision
// numbers — never full-page DOM snapshots (tests/README §6).
//
// #81 CI incident (e2e-smoke job 132861662996): the :104 precheck test died on
// `genOut.click()` — mux-0's subtree intercepted the pointer on every retry —
// reproducible only in full-suite runs. Root cause (derived from the installed
// @xyflow/react 12.12.1 internals): the `fitView` prop arms a ONE-SHOT queued
// fit (`fitViewQueued`) that fires at the FIRST node-dimension measurement
// (store.updateNodeInternals → resolveFitView) and clamps to maxZoom=2 for
// small bounds (getViewportForBounds on a single ~170×95 node). Every later
// `page.dragAndDrop` maps its screen `targetPosition` through
// screenToFlowPosition — i.e. through the CURRENT zoomed/panned viewport — so
// fixed screen deltas land at flow-gap = screen-gap / zoom, which is narrower
// than a rendered node (~150–170px flow) once zoom ≥ ~1.8. gen/mux/demux then
// overlap in flow space and mux-0 deterministically covers gen-0's ts_out
// click point (the geometry is static, so Playwright retries cannot recover).
// The auto-loaded first-listed topology leaves the same kind of zoomed
// viewport behind after 新建拓扑 (its nodes drain the mount-armed fit at
// zoom ≈ 1.9; `loaded` also REPLACES nodes wholesale, so a late auto-load can
// clobber a fresh draft — the #65 strict-mode/reload face).
//
// Fix layer (test-side; the app's fitView UX stays untouched): (1) settle the
// auto-load network chain before cutting a fresh draft and assert the canvas
// is empty; (2) close-loop normalize the canvas zoom (wheel-out to ≤ 0.9, min
// clamp 0.5) so the visible flow rect can host the column layout; (3) map
// every drop through the live viewport transform to exact flow coordinates —
// flow positions are viewport-invariant, so later fit/zoom cannot move them;
// (4) gate every handle click on an explicit geometric precondition (handle
// center not covered by another node's box — an honest layout-regression
// assertion; no force clicks, no longer retries, no weakened assertions).
// Handle testids are scoped per node (`dvb-topo-handle-<port_id>` is only
// unique within one node — mux/demux carry ts_out-shaped ids too).
import { expect, test, type Locator, type Page } from "@playwright/test";

const CANVAS_TESTID = '[data-testid="dvb-topo-canvas"]';
const PANE_SELECTOR = `${CANVAS_TESTID} .react-flow__pane`;
const VIEWPORT_SELECTOR = `${CANVAS_TESTID} .react-flow__viewport`;
/** Placement clearance for one canvas node when clamping drop points into the
 * visible flow rect: rendered node ≤ ~200×120 (content-driven width bounded by
 * the longest line — the config hint; min-width 150) plus the 4px handle
 * protrusion and click clearance. */
const NODE_CLEARANCE = { margin: 20, width: 220, height: 160 };

interface FlowPoint {
  x: number;
  y: number;
}
interface FlowRect {
  x: number;
  y: number;
  width: number;
  height: number;
}
interface ViewportTransform {
  zoom: number;
  x: number;
  y: number;
}

// --- canvas viewport helpers ---------------------------------------------------

async function renderSettled(page: Page, settleMs = 60): Promise<void> {
  await page.evaluate(
    (wait) =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => window.setTimeout(resolve, wait)));
      }),
    settleMs,
  );
}

/** Live canvas viewport transform: screen = flow * zoom + translate
 * (pane-relative; the viewport's transform-origin is 0 0). Computed style
 * normalizes to matrix(z, 0, 0, z, tx, ty); `none` = untouched identity. */
async function readViewport(page: Page): Promise<ViewportTransform> {
  return page.evaluate((selector) => {
    const el = document.querySelector(selector);
    const matrix = el === null ? "none" : getComputedStyle(el).transform;
    const match = /^matrix\(([^)]+)\)$/.exec(matrix);
    if (match === null) return { zoom: 1, x: 0, y: 0 };
    const [a, b, c, d, e, f] = match[1].split(",").map((value) => Number.parseFloat(value));
    if (b !== 0 || c !== 0 || d !== a) throw new Error(`unexpected canvas transform: ${matrix}`);
    return { zoom: a, x: e, y: f };
  }, VIEWPORT_SELECTOR);
}

/** Wait until the viewport transform stops moving. The one-shot fitView drain
 * fires at the first node's ResizeObserver measurement (a couple of frames
 * after its paint), so transform reads must not straddle that moment. */
async function settleViewport(page: Page): Promise<ViewportTransform> {
  let previous = JSON.stringify(await readViewport(page));
  let stableCount = 0;
  for (let i = 0; i < 40; i += 1) {
    await renderSettled(page);
    const current = JSON.stringify(await readViewport(page));
    stableCount = current === previous ? stableCount + 1 : 0;
    previous = current;
    if (stableCount >= 2) break;
  }
  return JSON.parse(previous) as ViewportTransform;
}

/** Wheel-zoom the canvas out until `targetZoom`. React Flow zooms on a plain
 * wheel (zoomOnScroll default true) and clamps at minZoom 0.5; the loop is
 * closed-loop on the actual transform, so it assumes no wheel-step size. The
 * mount-armed fitView can still re-zoom AFTER the first drop's measurement —
 * callers run this once before the first drop and again right after it. */
async function zoomCanvasOut(page: Page, targetZoom = 0.9): Promise<void> {
  const paneBox = await page.locator(PANE_SELECTOR).boundingBox();
  if (paneBox === null) throw new Error("canvas pane not visible");
  await page.mouse.move(paneBox.x + paneBox.width / 2, paneBox.y + paneBox.height / 2);
  for (let i = 0; i < 20; i += 1) {
    const before = (await settleViewport(page)).zoom;
    if (before <= targetZoom) return;
    await page.mouse.wheel(0, 240);
    await renderSettled(page);
    const after = await readViewport(page);
    if (after.zoom >= before) return; // no progress — clamped at minZoom (0.5 ≤ target)
  }
}

/** The flow-coordinate rectangle currently visible inside the pane. */
async function visibleFlowRect(page: Page): Promise<FlowRect> {
  const viewport = await settleViewport(page);
  const paneBox = await page.locator(PANE_SELECTOR).boundingBox();
  if (paneBox === null) throw new Error("canvas pane not visible");
  return {
    x: -viewport.x / viewport.zoom,
    y: -viewport.y / viewport.zoom,
    width: paneBox.width / viewport.zoom,
    height: paneBox.height / viewport.zoom,
  };
}

/** Clamp a desired flow point into the visible rect minus node clearance, so
 * the drop point and the rendered node's click targets stay on-pane under any
 * zoom in [minZoom 0.5, maxZoom 2]. */
function clampIntoVisibleRect(rect: FlowRect, point: FlowPoint): FlowPoint {
  return {
    x: Math.min(Math.max(point.x, rect.x + NODE_CLEARANCE.margin), rect.x + rect.width - NODE_CLEARANCE.width),
    y: Math.min(Math.max(point.y, rect.y + NODE_CLEARANCE.margin), rect.y + rect.height - NODE_CLEARANCE.height),
  };
}

/** Map flow coordinates to the pane-relative drop point through the LIVE
 * viewport transform — the exact inverse of React Flow's
 * screenToFlowPosition. This removes the incident's coupling: fixed screen
 * deltas shrink to screenGap/zoom in flow space (sub-node-width at zoom ~2),
 * while mapped flow coordinates land exactly where intended regardless of
 * zoom/pan. */
async function flowToPaneTarget(page: Page, flow: FlowPoint): Promise<{ x: number; y: number }> {
  const viewport = await settleViewport(page);
  return { x: flow.x * viewport.zoom + viewport.x, y: flow.y * viewport.zoom + viewport.y };
}

/** Flow-space position (top-left) of a rendered node, via the live transform. */
async function nodeFlowPosition(page: Page, nodeId: string): Promise<FlowPoint> {
  const viewport = await settleViewport(page);
  const nodeBox = await page.locator(`[data-node-id="${nodeId}"]`).boundingBox();
  if (nodeBox === null) throw new Error(`node ${nodeId} not rendered`);
  const paneBox = await page.locator(PANE_SELECTOR).boundingBox();
  if (paneBox === null) throw new Error("canvas pane not visible");
  return {
    x: (nodeBox.x - paneBox.x - viewport.x) / viewport.zoom,
    y: (nodeBox.y - paneBox.y - viewport.y) / viewport.zoom,
  };
}

/** Geometric click precondition (the incident's honesty gate): the handle's
 * center must not sit inside ANY other node's box. A violation means canvas
 * nodes overlap — a layout regression to expose immediately with numbers,
 * never to click through (no force clicks; ADR-0009 decision-4 semantics stay
 * asserted, not skipped). */
async function expectHandleNotCovered(page: Page, handle: Locator, nodeId: string): Promise<void> {
  const viewport = await readViewport(page);
  const handleBox = await handle.boundingBox();
  if (handleBox === null) throw new Error(`handle of ${nodeId} not rendered`);
  const center = { x: handleBox.x + handleBox.width / 2, y: handleBox.y + handleBox.height / 2 };
  const nodes = page.locator(".react-flow__node");
  const nodeCount = await nodes.count();
  for (let i = 0; i < nodeCount; i += 1) {
    const other = nodes.nth(i);
    const otherId = await other.getAttribute("data-id");
    if (otherId === null || otherId === nodeId) continue;
    const otherBox = await other.boundingBox();
    if (otherBox === null) continue;
    const covered =
      center.x >= otherBox.x &&
      center.x <= otherBox.x + otherBox.width &&
      center.y >= otherBox.y &&
      center.y <= otherBox.y + otherBox.height;
    expect(
      covered,
      `canvas layout regression: ${nodeId}'s handle click point (${center.x.toFixed(1)},${center.y.toFixed(1)}) is ` +
        `covered by node ${otherId} box [${otherBox.x.toFixed(1)},${otherBox.y.toFixed(1)} ` +
        `${otherBox.width.toFixed(1)}×${otherBox.height.toFixed(1)}] at viewport zoom ${viewport.zoom.toFixed(2)} ` +
        `— nodes must not overlap (see PR #81 e2e-smoke incident; ADR-0009 decision-4/5)`,
    ).toBe(false);
  }
}

// --- draft lifecycle helpers ---------------------------------------------------

/** Open the editor and settle the first-listed-topology auto-load chain (GET
 * list → GET topology → POST validate) before cutting a fresh draft: a late
 * `loaded` dispatch REPLACES the draft nodes wholesale (#65 race face). Then
 * 新建拓扑 must leave an EMPTY canvas (draft isolation). */
async function openFreshDraft(page: Page): Promise<void> {
  await page.goto("/topologies");
  await expect(page.getByRole("heading", { name: "Topologies" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "新建拓扑" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
}

async function dragPaletteItemToCanvas(page: Page, nodeType: string, nodeId: string, flowPosition: FlowPoint) {
  // The React Flow palette DnD pattern (ADR-0009 decision 1): HTML5 drag
  // carrying the wire node_type, dropped on the canvas wrapper at flow
  // coordinates mapped through the live viewport (see header note).
  const target = await flowToPaneTarget(page, flowPosition);
  await page.dragAndDrop(`[data-node-type="${nodeType}"]`, PANE_SELECTOR, { targetPosition: target });
  // The drop rendered THIS node (also fails fast if something displaced the
  // draft — the deterministic `<prefix>-<n>` ids would be gone).
  await expect(page.locator(`[data-node-id="${nodeId}"]`)).toBeVisible();
  // Absorb the one-shot fitView drain: it fires when THIS node's dimensions
  // are first measured (a couple of frames after paint).
  await settleViewport(page);
}

async function connectHandles(page: Page, sourceNodeId: string, sourcePort: string, targetNodeId: string, targetPort: string) {
  // React Flow's default click-to-connect (connectOnClick): click the source
  // Handle, click the target Handle — the SAME onConnect path a pointer drag
  // takes, deterministic under Playwright (pointer-drag gestures are
  // viewport-timing sensitive; the wire contract is identical either way).
  // Scoped locators: `dvb-topo-handle-<port_id>` is only unique per node
  // (mux/demux carry ts_out-shaped ids too — #65 strict-mode face), and each
  // click is gated on the geometric precondition (no covered click points).
  const source = page.locator(`[data-node-id="${sourceNodeId}"]`).getByTestId(`dvb-topo-handle-${sourcePort}`);
  const target = page.locator(`[data-node-id="${targetNodeId}"]`).getByTestId(`dvb-topo-handle-${targetPort}`);
  await expectHandleNotCovered(page, source, sourceNodeId);
  await source.click();
  await expectHandleNotCovered(page, target, targetNodeId);
  await target.click();
}

async function savedTopologyWire(page: Page, topologyId: string) {
  const response = await page.request.get(`/api/v1/topologies/${topologyId}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as {
    topology_id: string;
    revision: number;
    nodes: { node_id: string; node_type: string; ports: { port_id: string; direction: string; plane: string; max_connections: number }[] }[];
    connections: { connection_id: string; from_node: string; from_port: string; to_node: string; to_port: string; plane: string }[];
  };
}

test("drag → connect → save → new revision walks the full canvas chain (AC-401-01)", async ({ page }) => {
  await openFreshDraft(page);

  // REQ-UI-401-002/004: drop creates registry nodes with template ports.
  // Placement: normalize the zoom, anchor gen-0 inside the visible flow rect,
  // then anchor mon-0 relative to gen-0's ACTUAL flow position after the
  // first-measurement fitView drain — never fixed screen deltas (#81).
  await zoomCanvasOut(page);
  const firstRect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_generator", "gen-0", clampIntoVisibleRect(firstRect, { x: firstRect.x + 60, y: firstRect.y + 40 }));
  await zoomCanvasOut(page); // no-op unless the fitView drain re-zoomed the canvas
  const gen = await nodeFlowPosition(page, "gen-0");
  const rect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_monitor", "mon-0", clampIntoVisibleRect(rect, { x: gen.x + 320, y: gen.y + 180 }));

  await expect(page.locator('[data-node-id="gen-0"]').getByTestId("dvb-topo-handle-ts_out")).toBeVisible(); // gen-0.ts_out
  await expect(page.locator('[data-node-id="mon-0"]').getByTestId("dvb-topo-handle-ts_in")).toBeVisible(); // mon-0.ts_in

  // #63 accommodation (approved AC-402-04): the save entry is gate-gated —
  // select gen-0 and fill a minimal config through the inspector before saving.
  await page.locator(".react-flow__node", { has: page.locator('[data-node-id="gen-0"]') }).click();
  for (const [label, value] of [
    ["seed", "20260101"],
    ["initial_media_clock_27mhz", "0"],
    ["target_bitrate_bps", "3008000"],
    ["output_packet_count", "1000"],
    ["program.transport_stream_id", "1"],
    ["program.program_number", "1"],
    ["program.pmt_pid", "4096"],
    ["program.pcr_pid", "256"],
    ["program.version_number", "0"],
  ] as [string, string][]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "应用到草稿" }).click();

  // REQ-UI-401-003: handle-to-handle connect (Strict mode, four-tuple mapping).
  await connectHandles(page, "gen-0", "ts_out", "mon-0", "ts_in");

  // REQ-UI-401-007: save = PUT/POST → fixed third step validate (§7.4).
  await page.getByRole("button", { name: /保存为新 revision/ }).click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 1");

  // The wire truth: read the server id from the toolbar select, then GET.
  const topologyId = await page.locator('[aria-label="选择拓扑"]').inputValue();
  expect(topologyId).not.toBe("");
  const wire = await savedTopologyWire(page, topologyId);
  expect(wire.revision).toBe(1);
  expect(wire.nodes.map((n) => n.node_type).sort()).toEqual(["ts_generator", "ts_monitor"]);
  expect(wire.nodes.every((n) => n.ports.every((p) => p.plane === "MPEG_TS"))).toBe(true);
  expect(wire.connections).toHaveLength(1);
  expect(wire.connections[0]).toMatchObject({
    from_node: "gen-0",
    from_port: "ts_out",
    to_node: "mon-0",
    to_port: "ts_in",
    plane: "MPEG_TS",
  });

  // Persistence: reload, pick OUR topology back, nodes/edges render again.
  await page.reload();
  await page.waitForLoadState("networkidle"); // settle the post-reload auto-load before re-selecting
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);
  await expect(page.locator('[data-node-id="gen-0"]').getByTestId("dvb-topo-handle-ts_out")).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // Immutable append: a second save yields revision 2, the stored row moves on.
  await page.getByRole("button", { name: /TS 复用器/ }).click(); // mark dirty
  await page.getByRole("button", { name: /保存为新 revision/ }).click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 2");
  expect((await savedTopologyWire(page, topologyId)).revision).toBe(2);
});

test("precheck rejects connections beyond max_connections — nothing illegal reaches the wire (ADR-0009 decision 4)", async ({ page }) => {
  await openFreshDraft(page);

  // Drop gen-0 / mux-0 / demux-0: gen-0 inside the visible flow rect, then
  // mux/demux anchored to gen-0's ACTUAL flow position (post fitView drain) —
  // flow-space column layout with ≥100px gaps under any canvas zoom (#81).
  await zoomCanvasOut(page);
  const firstRect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_generator", "gen-0", clampIntoVisibleRect(firstRect, { x: firstRect.x + 60, y: firstRect.y + 40 }));
  await zoomCanvasOut(page); // no-op unless the fitView drain re-zoomed the canvas
  const gen = await nodeFlowPosition(page, "gen-0");
  const rect = await visibleFlowRect(page);
  await dragPaletteItemToCanvas(page, "ts_mux", "mux-0", clampIntoVisibleRect(rect, { x: gen.x + 320, y: gen.y }));
  await dragPaletteItemToCanvas(page, "ts_demux", "demux-0", clampIntoVisibleRect(rect, { x: gen.x + 320, y: gen.y + 220 }));

  // #63 accommodation (approved AC-402-04): the gate requires the generator
  // config to be filled — select gen-0, fill minimal, apply before saving.
  await page.locator(".react-flow__node", { has: page.locator('[data-node-id="gen-0"]') }).click();
  for (const [label, value] of [
    ["seed", "20260101"],
    ["initial_media_clock_27mhz", "0"],
    ["target_bitrate_bps", "3008000"],
    ["output_packet_count", "1000"],
    ["program.transport_stream_id", "1"],
    ["program.program_number", "1"],
    ["program.pmt_pid", "4096"],
    ["program.pcr_pid", "256"],
    ["program.version_number", "0"],
  ] as [string, string][]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "应用到草稿" }).click();
  await expect(page.locator('[data-node-id="gen-0"]').getByTestId("dvb-topo-handle-ts_out")).toBeVisible();

  // Legal first link: gen-0.ts_out → mux-0.ts_in_1. Handle ids repeat across
  // node types, so every locator is scoped to its node and each click is
  // gated on the not-covered geometric precondition (#81 honesty gate).
  const genOut = page.locator('[data-node-id="gen-0"]').getByTestId("dvb-topo-handle-ts_out");
  const muxIn1 = page.locator('[data-node-id="mux-0"]').getByTestId("dvb-topo-handle-ts_in_1");
  const demuxIn = page.locator('[data-node-id="demux-0"]').getByTestId("dvb-topo-handle-ts_in");
  await expectHandleNotCovered(page, genOut, "gen-0");
  await genOut.click();
  await expectHandleNotCovered(page, muxIn1, "mux-0");
  await muxIn1.click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // Second link from the same ts_out would exceed max_connections=1 — the
  // isValidConnection precheck rejects it and no edge appears.
  await expectHandleNotCovered(page, genOut, "gen-0");
  await genOut.click();
  await expectHandleNotCovered(page, demuxIn, "demux-0");
  await demuxIn.click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // The wire confirms exactly one connection (into the mux).
  // #63 accommodation (approved AC-402-04): a null-schema node marks dirty
  // without tripping the completeness gate (a second generator would).
  await page.getByRole("button", { name: /TS 监测器/ }).click(); // mark dirty (adds mon-0)
  await page.getByRole("button", { name: /保存为新 revision/ }).click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 1");
  const topologyId = await page.locator('[aria-label="选择拓扑"]').inputValue();
  const wire = await savedTopologyWire(page, topologyId);
  expect(wire.connections).toHaveLength(1);
  expect(wire.connections[0]).toMatchObject({ from_node: "gen-0", from_port: "ts_out", to_node: "mux-0", to_port: "ts_in_1", plane: "MPEG_TS" });
});

test("backend double layer: a non-MPEG_TS stored connection surfaces as an in-place violation (AC-401-03/04)", async ({ page }) => {
  // POST a DTO-valid graph whose connection uses a non-enabled plane — the
  // persistence accepts it (no validator on save, SPEC-200 §6 posture), and
  // the canvas' load-time validate must report SIM_TOPO_MEDIA_INCOMPATIBLE
  // addressed to connections[<id>] in place.
  const created = await page.request.post("/api/v1/topologies", {
    data: {
      nodes: [
        {
          node_id: "gen-0",
          node_type: "ts_generator",
          config: {},
          ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
        },
        {
          node_id: "mon-0",
          node_type: "ts_monitor",
          config: {},
          ports: [{ port_id: "ts_in", direction: "input", plane: "MPEG_TS", max_connections: 1 }],
        },
      ],
      connections: [
        { connection_id: "conn-0", from_node: "gen-0", from_port: "ts_out", to_node: "mon-0", to_port: "ts_in", plane: "RF" },
      ],
    },
  });
  expect(created.status()).toBe(201);
  const topologyId = ((await created.json()) as { topology_id: string }).topology_id;

  await page.goto("/topologies");
  await page.waitForLoadState("networkidle"); // settle the auto-load before selecting ours
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);

  const violation = page.locator(".dvb-topo-violation", { hasText: "SIM_TOPO_MEDIA_INCOMPATIBLE" });
  await expect(violation).toBeVisible();
  await expect(violation).toContainText("connections[conn-0]");
  // the addressed edge lights up in place too (§7.4: connections[x] → edge)
  await expect(page.locator(".react-flow__edge.dvb-topo-edge-violation")).toHaveCount(1);
});
