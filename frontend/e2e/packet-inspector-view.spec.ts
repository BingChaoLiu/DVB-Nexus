// Packet inspector view deep-link E2E (SPEC-404 §Phase2, ticket #132): the
// `view=t2mi|bbframe|ts` param over the REAL backend. A layered run is driven
// REST-first (BBHEADER_SYNC_FAULT routes the run onto the layered chain —
// #128 plan-driven layering, no scenario needed), the faulted tee leg is the
// transmitted T2-MI stream (packet_size honestly null), and the browser
// opens the /monitor deep link with the locator triple + view. The default
// (no view param) face is pinned on a plain TS run's artifact — the MVP
// zero-regression chain.
//
// Disciplines (SPEC-404 §Phase2 + brief §5-10): URL params assert SHAPE
// ([0-9a-f-]{36} UUIDs, never pinned values); wire enums assert verbatim;
// the SYNCD teaching anchor is pinned VERBATIM; lab.spec.ts is #131's
// additive face and is deliberately not touched by this file.
//
// The BISS annotation face is NOT exercised here: a production BISS run
// needs the CSA DLL (CI honestly NOT RUN, §5-11) — its contract is pinned at
// the component layer (BissAnnotation.test.tsx).
import { expect, test } from "@playwright/test";
import { createStartedSession, submitAndAwaitRun } from "./helpers/backend";

const UUID_SHAPE = /^[0-9a-f-]{36}$/;

/** The B2 injection as the run-request wire body (the proven #129 e2e shape:
 * no `layer` field on the wire — the backend derives it from the registry). */
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

test.describe("packet inspector view deep link (SPEC-404 §Phase2)", () => {
  test("layered run artifact: structure REST shape + view=t2mi / view=bbframe deep links", async ({ page, request }) => {
    const sessionId = await createStartedSession(request);
    expect(sessionId).toMatch(UUID_SHAPE);

    // Layered run: the fault plan routes beyond the TS layer → the tee legs
    // carry the TRANSMITTED T2-MI stream (#128 posture).
    const run = await submitAndAwaitRun(request, sessionId, BBHEADER_SYNC_FAULT_PLAN);
    const faulted = run.artifacts.find((artifact) => artifact.kind === "faulted_ts");
    expect(faulted, "layered run must tee a faulted_ts (T2-MI) leg").toBeTruthy();
    const artifactId = faulted!.artifact_id;
    expect(artifactId).toMatch(UUID_SHAPE);

    // REST shape sanity: the view-discriminated structure union (#129).
    const t2miResponse = await request.get(`/api/v1/artifacts/${artifactId}/structure?view=t2mi`);
    expect(t2miResponse.status()).toBe(200);
    const t2mi = (await t2miResponse.json()) as {
      view: string;
      packet_count: number;
      packets?: { packet_index: number; payload_kind: string; crc32_valid: boolean; frame_index?: number | null }[];
    };
    expect(t2mi.view).toBe("t2mi");
    expect(t2mi.packet_count).toBeGreaterThan(0);
    expect(t2mi.packets?.length).toBeGreaterThan(0);
    for (const key of ["packet_index", "packet_type", "packet_counter", "payload_kind", "payload_bytes_len", "crc32_valid"]) {
      expect(t2mi.packets![0]).toHaveProperty(key);
    }

    const bbframeResponse = await request.get(`/api/v1/artifacts/${artifactId}/structure?view=bbframe`);
    expect(bbframeResponse.status()).toBe(200);
    const bbframe = (await bbframeResponse.json()) as {
      view: string;
      frame_count: number;
      frames?: Record<string, unknown>[];
    };
    expect(bbframe.view).toBe("bbframe");
    expect(bbframe.frame_count).toBeGreaterThan(0);
    for (const key of ["matype", "upl", "dfl", "sync", "syncd", "crc8_valid", "up_count", "state", "frame_index"]) {
      expect(bbframe.frames![0]).toHaveProperty(key);
    }

    // Deep link view=t2mi: the panel renders the T2-MI packet face over the
    // real structure JSON; the locator packet 0 selects row 0.
    await page.goto(
      `/monitor?session=${sessionId}&inspect_artifact=${artifactId}&inspect_pid=0&inspect_packet=0&view=t2mi`,
    );
    await expect(page.getByTestId("packet-inspector")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view t2mi");
    await expect(page.getByTestId("t2mi-structure-view")).toBeVisible();
    await expect(page.getByTestId("t2mi-row-0")).toBeVisible();
    await expect(page.getByTestId("t2mi-row-0").getAttribute("class")).toBeTruthy();
    // CRC-32 wire face renders verbatim (ok/BAD annotations from the boolean)
    await expect(page.getByTestId("t2mi-rows")).toContainText("crc32=");

    // Deep link view=bbframe: BBHEADER face + the SYNCD teaching anchor,
    // pinned VERBATIM (SPEC-404 §Phase2).
    await page.goto(
      `/monitor?session=${sessionId}&inspect_artifact=${artifactId}&inspect_pid=0&inspect_packet=0&view=bbframe`,
    );
    await expect(page.getByTestId("bbframe-structure-view")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view bbframe");
    await expect(page.getByTestId("bbframe-syncd-anchor")).toHaveText(
      "SYNCD 是数据字段内首个 UP 的位距离，不是同步字节",
    );
    await expect(page.getByTestId("bbframe-row-0")).toContainText("crc8=");
  });

  test("default (no view param) keeps the MVP single-packet face on a plain TS artifact", async ({ page, request }) => {
    const sessionId = await createStartedSession(request);
    // Empty plan → the MVP single-layer path → a real 188-geometry TS artifact.
    const run = await submitAndAwaitRun(request, sessionId, []);
    const generated = run.artifacts.find((artifact) => artifact.kind === "generated_ts");
    expect(generated).toBeTruthy();
    const artifactId = generated!.artifact_id;
    expect(artifactId).toMatch(UUID_SHAPE);

    // Zero-regression: absent view behaves exactly like the pre-Phase2 panel
    // (meta gate → Range → hex + SPEC-100 header fields).
    await page.goto(`/monitor?session=${sessionId}&inspect_artifact=${artifactId}&inspect_pid=0&inspect_packet=0`);
    await expect(page.getByTestId("packet-inspector")).toBeVisible();
    await expect(page.getByTestId("inspect-view")).toHaveText("view ts");
    await expect(page.getByTestId("inspect-content-range")).toContainText("206");
    await expect(page.getByTestId("inspect-hex-row-0")).toBeVisible();
    await expect(page.getByTestId("inspect-field-sync")).toContainText("0x47");
    // no structure face may leak into the default view
    await expect(page.getByTestId("t2mi-structure-view")).toHaveCount(0);
    await expect(page.getByTestId("bbframe-structure-view")).toHaveCount(0);
    // the payload-layer scrambling annotation (wire-derived): clear on MVP streams
    await expect(page.getByTestId("inspect-biss-state")).toContainText("clear");
  });

  test("structure view honestly refuses a plain TS artifact (400 SIM_STRUCTURE_NOT_T2MI)", async ({ request }) => {
    const sessionId = await createStartedSession(request);
    const run = await submitAndAwaitRun(request, sessionId, []);
    const generated = run.artifacts.find((artifact) => artifact.kind === "generated_ts");
    expect(generated).toBeTruthy();
    const response = await request.get(`/api/v1/artifacts/${generated!.artifact_id}/structure?view=t2mi`);
    expect(response.status()).toBe(400);
    const body = (await response.json()) as { error?: { error_code?: string } };
    expect(body.error?.error_code).toBe("SIM_STRUCTURE_NOT_T2MI");
  });
});
