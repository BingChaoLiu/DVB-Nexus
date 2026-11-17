// Canvas driving helpers shared by the SPEC-401 canvas E2E specs. The
// viewport/drag discipline below is the #81 e2e-smoke incident fix (see
// e2e/topology.spec.ts header for the full root-cause analysis): normalize
// zoom, anchor drops at flow coordinates mapped through the LIVE viewport
// transform, and gate every handle click on the not-covered geometric
// precondition. Extracted for topology-t2mi.spec.ts (#135) — topology.spec.ts
// keeps its local copies untouched (additive-only seam).
import { expect, type Locator, type Page } from "@playwright/test";

export const CANVAS_TESTID = '[data-testid="dvb-topo-canvas"]';
export const PANE_SELECTOR = `${CANVAS_TESTID} .react-flow__pane`;
export const VIEWPORT_SELECTOR = `${CANVAS_TESTID} .react-flow__viewport`;
/** Placement clearance for one canvas node when clamping drop points into the
 * visible flow rect: rendered node ≤ ~220×160 plus click clearance. */
export const NODE_CLEARANCE = { margin: 20, width: 220, height: 160 };

export interface FlowPoint {
  x: number;
  y: number;
}
export interface FlowRect {
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
 * (pane-relative; transform-origin 0 0). */
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

/** Wait until the viewport transform stops moving (the one-shot fitView drain). */
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

/** Wheel-zoom the canvas out until `targetZoom` (closed-loop on the actual
 * transform; React Flow clamps at minZoom 0.5). */
export async function zoomCanvasOut(page: Page, targetZoom = 0.9): Promise<void> {
  const paneBox = await page.locator(PANE_SELECTOR).boundingBox();
  if (paneBox === null) throw new Error("canvas pane not visible");
  await page.mouse.move(paneBox.x + paneBox.width / 2, paneBox.y + paneBox.height / 2);
  for (let i = 0; i < 20; i += 1) {
    const before = (await settleViewport(page)).zoom;
    if (before <= targetZoom) return;
    await page.mouse.wheel(0, 240);
    await renderSettled(page);
    const after = await readViewport(page);
    if (after.zoom >= before) return; // no progress — clamped at minZoom
  }
}

/** The flow-coordinate rectangle currently visible inside the pane. */
export async function visibleFlowRect(page: Page): Promise<FlowRect> {
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

/** Clamp a desired flow point into the visible rect minus node clearance. */
export function clampIntoVisibleRect(rect: FlowRect, point: FlowPoint): FlowPoint {
  return {
    x: Math.min(Math.max(point.x, rect.x + NODE_CLEARANCE.margin), rect.x + rect.width - NODE_CLEARANCE.width),
    y: Math.min(Math.max(point.y, rect.y + NODE_CLEARANCE.margin), rect.y + rect.height - NODE_CLEARANCE.height),
  };
}

/** Map flow coordinates to the pane-relative drop point through the LIVE
 * viewport transform (the exact inverse of screenToFlowPosition). */
async function flowToPaneTarget(page: Page, flow: FlowPoint): Promise<{ x: number; y: number }> {
  const viewport = await settleViewport(page);
  return { x: flow.x * viewport.zoom + viewport.x, y: flow.y * viewport.zoom + viewport.y };
}

/** Flow-space position (top-left) of a rendered node, via the live transform. */
export async function nodeFlowPosition(page: Page, nodeId: string): Promise<FlowPoint> {
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

/** Geometric click precondition: the handle's center must not sit inside ANY
 * other node's box (an honest layout-regression assertion — no force clicks). */
export async function expectHandleNotCovered(page: Page, handle: Locator, nodeId: string): Promise<void> {
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

/** Open the editor and settle the first-listed-topology auto-load chain before
 * cutting a fresh draft (a late `loaded` dispatch REPLACES the draft nodes
 * wholesale — #65 race face); 新建拓扑 must leave an EMPTY canvas. */
export async function openFreshDraft(page: Page): Promise<void> {
  await page.goto("/topologies");
  await expect(page.getByRole("heading", { name: "Topologies" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "新建拓扑" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
}

/** The React Flow palette DnD pattern: HTML5 drag carrying the wire
 * node_type, dropped at flow coordinates mapped through the live viewport. */
export async function dragPaletteItemToCanvas(
  page: Page,
  nodeType: string,
  nodeId: string,
  flowPosition: FlowPoint,
): Promise<void> {
  const target = await flowToPaneTarget(page, flowPosition);
  await page.dragAndDrop(`[data-node-type="${nodeType}"]`, PANE_SELECTOR, { targetPosition: target });
  await expect(page.locator(`[data-node-id="${nodeId}"]`)).toBeVisible();
  await settleViewport(page);
}

/** React Flow's default click-to-connect (connectOnClick) — the SAME onConnect
 * path a pointer drag takes, deterministic under Playwright. Handle ids repeat
 * across node types, so every locator is node-scoped and gated on the
 * not-covered geometric precondition (#81 honesty gate). */
export async function connectHandles(
  page: Page,
  sourceNodeId: string,
  sourcePort: string,
  targetNodeId: string,
  targetPort: string,
): Promise<void> {
  const source = page.locator(`[data-node-id="${sourceNodeId}"]`).getByTestId(`dvb-topo-handle-${sourcePort}`);
  const target = page.locator(`[data-node-id="${targetNodeId}"]`).getByTestId(`dvb-topo-handle-${targetPort}`);
  await expectHandleNotCovered(page, source, sourceNodeId);
  await source.click();
  await expectHandleNotCovered(page, target, targetNodeId);
  await target.click();
}

/** GET the stored topology wire body (the wire truth after a save). */
export async function savedTopologyWire(page: Page, topologyId: string) {
  const response = await page.request.get(`/api/v1/topologies/${topologyId}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as {
    topology_id: string;
    revision: number;
    nodes: { node_id: string; node_type: string; ports: { port_id: string; direction: string; plane: string; max_connections: number }[] }[];
    connections: { connection_id: string; from_node: string; from_port: string; to_node: string; to_port: string; plane: string }[];
  };
}
