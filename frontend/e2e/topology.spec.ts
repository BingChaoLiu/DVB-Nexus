// SPEC-401 canvas E2E (AC-401-01/03/04): drag → connect → save → new revision
// in a real browser through the same-origin proxy; the backend double layer
// for the single-plane rule surfaces as in-place path-addressed violations.
// Asserts wire shapes (snake_case field names/enum strings) and revision
// numbers — never full-page DOM snapshots (tests/README §6 discipline).
import { expect, test, type Page } from "@playwright/test";

async function dragPaletteItemToCanvas(page: Page, nodeType: string, position: { x: number; y: number }) {
  // The React Flow palette DnD pattern (ADR-0009 decision 1): HTML5 drag
  // carrying the wire node_type, dropped on the canvas wrapper. Distinct
  // positions per node — overlapping nodes cannot be wired.
  await page.dragAndDrop(`[data-node-type="${nodeType}"]`, '[data-testid="dvb-topo-canvas"] .react-flow__pane', {
    targetPosition: position,
  });
}

async function connectHandles(page: Page, sourceTestId: string, targetTestId: string) {
  // React Flow's default click-to-connect (connectOnClick): click the source
  // Handle, click the target Handle — the SAME onConnect path a pointer drag
  // takes, deterministic under Playwright (pointer-drag gestures are
  // viewport-timing sensitive; the wire contract is identical either way).
  await page.getByTestId(sourceTestId).click();
  await page.getByTestId(targetTestId).click();
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
  await page.goto("/topologies");
  await expect(page.getByRole("heading", { name: "Topologies" })).toBeVisible();

  // Fresh unsaved draft (independent of whatever else exists in the store).
  await page.getByRole("button", { name: "新建拓扑" }).click();

  // REQ-UI-401-002/004: drop creates registry nodes with template ports.
  await dragPaletteItemToCanvas(page, "ts_generator", { x: 160, y: 100 });
  await dragPaletteItemToCanvas(page, "ts_monitor", { x: 480, y: 280 });
  await expect(page.getByTestId("dvb-topo-handle-ts_out")).toBeVisible(); // gen-0.ts_out
  await expect(page.getByTestId("dvb-topo-handle-ts_in")).toBeVisible(); // mon-0.ts_in

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
  await connectHandles(page, "dvb-topo-handle-ts_out", "dvb-topo-handle-ts_in");

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
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);
  await expect(page.getByTestId("dvb-topo-handle-ts_out")).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // Immutable append: a second save yields revision 2, the stored row moves on.
  await page.getByRole("button", { name: /TS 复用器/ }).click(); // mark dirty
  await page.getByRole("button", { name: /保存为新 revision/ }).click();
  await expect(page.locator(".dvb-topo-revision")).toContainText("revision 2");
  expect((await savedTopologyWire(page, topologyId)).revision).toBe(2);
});

test("precheck rejects connections beyond max_connections — nothing illegal reaches the wire (ADR-0009 decision 4)", async ({ page }) => {
  await page.goto("/topologies");
  await page.getByRole("button", { name: "新建拓扑" }).click();
  await dragPaletteItemToCanvas(page, "ts_generator", { x: 120, y: 100 });
  await dragPaletteItemToCanvas(page, "ts_mux", { x: 420, y: 80 });
  await dragPaletteItemToCanvas(page, "ts_demux", { x: 420, y: 300 });
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
  await expect(page.getByTestId("dvb-topo-handle-ts_out").first()).toBeVisible();

  // Legal first link: gen-0.ts_out → mux-0.ts_in_1 (distinct handles, but each
  // type carries one ts_out/ts_in-shaped port set — disambiguate via nth).
  const genOut = page.locator('[data-node-id="gen-0"]').getByTestId("dvb-topo-handle-ts_out");
  const muxIn1 = page.locator('[data-node-id="mux-0"]').getByTestId("dvb-topo-handle-ts_in_1");
  const demuxIn = page.locator('[data-node-id="demux-0"]').getByTestId("dvb-topo-handle-ts_in");
  await genOut.click();
  await muxIn1.click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  // Second link from the same ts_out would exceed max_connections=1 — the
  // isValidConnection precheck rejects it and no edge appears.
  await genOut.click();
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
  await page.locator('[aria-label="选择拓扑"]').selectOption(topologyId);

  const violation = page.locator(".dvb-topo-violation", { hasText: "SIM_TOPO_MEDIA_INCOMPATIBLE" });
  await expect(violation).toBeVisible();
  await expect(violation).toContainText("connections[conn-0]");
  // the addressed edge lights up in place too (§7.4: connections[x] → edge)
  await expect(page.locator(".react-flow__edge.dvb-topo-edge-violation")).toHaveCount(1);
});
