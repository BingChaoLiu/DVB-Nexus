// Scenario face endpoint seam tests (SPEC-500 §4.7; SPEC-406 §6). The seam
// is the HTTP call each domain function issues through the real
// openapi-fetch client (fetch/Request stubbed at the global boundary — no
// internal mocking) plus the SPEC-500 §6 envelope error branch. Mirrors the
// topologies.test.ts posture (stub installed before the client module chain
// imports; behavior driven through a mutable responder cell).
import { afterEach, describe, expect, it, vi } from "vitest";

interface RecordedCall {
  url: string;
  method: string;
  body?: unknown;
}

const calls: RecordedCall[] = [];
const responder = { status: 200, payload: {} as unknown };

class StubRequest {
  url: string;
  method: string;
  body?: unknown;
  constructor(input: string | URL, init?: { method?: string; body?: string }) {
    this.url = String(input);
    this.method = (init?.method ?? "GET").toUpperCase();
    this.body = init?.body === undefined ? undefined : JSON.parse(init.body);
  }
}

vi.stubGlobal("Request", StubRequest as unknown as typeof Request);
vi.stubGlobal(
  "fetch",
  vi.fn(async (input: RequestInfo | URL) => {
    const req = input instanceof StubRequest ? input : undefined;
    calls.push({
      url: req ? req.url : String(input),
      method: (req ? req.method : "GET").toUpperCase(),
      body: req ? req.body : undefined,
    });
    return new Response(JSON.stringify(responder.payload), {
      status: responder.status,
      headers: { "Content-Type": "application/json" },
    });
  }),
);

const { getScenario, listScenarios, revealScenarioSolution } = await import("./scenarios");

const SCENARIO_ID = "5c010000-0000-4000-8000-000000000001";

function respondWith(status: number, payload: unknown) {
  responder.status = status;
  responder.payload = payload;
}

afterEach(() => {
  calls.length = 0;
  respondWith(200, {});
});

describe("scenarios endpoints — request shapes", () => {
  it("listScenarios GETs the collection without parameters", async () => {
    respondWith(200, [
      { scenario_id: SCENARIO_ID, version: "1.0.0", title: "认识闭环：PAT 缺失", difficulty: "introductory" },
    ]);
    const result = await listScenarios();
    expect(calls).toEqual([{ url: "/api/v1/scenarios", method: "GET", body: undefined }]);
    expect(result[0].scenario_id).toBe(SCENARIO_ID);
  });

  it("getScenario GETs the exported detail by id (no query string)", async () => {
    respondWith(200, { scenario_id: SCENARIO_ID, version: "1.0.0", title: "t", difficulty: "d" });
    const result = await getScenario(SCENARIO_ID);
    expect(calls).toEqual([
      { url: `/api/v1/scenarios/${SCENARIO_ID}`, method: "GET", body: undefined },
    ]);
    expect(result.scenario_id).toBe(SCENARIO_ID);
  });

  it("revealScenarioSolution GETs the gated reveal with session_id as query", async () => {
    respondWith(200, { scenario_id: SCENARIO_ID, hidden_reference_solution: "恢复路径…" });
    const result = await revealScenarioSolution(SCENARIO_ID, "sess-1");
    expect(calls).toEqual([
      { url: `/api/v1/scenarios/${SCENARIO_ID}/solution?session_id=sess-1`, method: "GET", body: undefined },
    ]);
    expect(result.hidden_reference_solution).toBe("恢复路径…");
  });
});

describe("scenarios endpoints — SPEC-500 §6 envelope error branch", () => {
  it("403 SIM_SCENARIO_SOLUTION_LEAK surfaces as ApiError with envelope keys", async () => {
    respondWith(403, {
      error: {
        error_code: "SIM_SCENARIO_SOLUTION_LEAK",
        message: "hidden reference solution reveal refused",
        retryable: false,
        details: {},
      },
      request_id: "req-sol-1",
    });
    await expect(revealScenarioSolution(SCENARIO_ID, "sess-2")).rejects.toMatchObject({
      status: 403,
      errorCode: "SIM_SCENARIO_SOLUTION_LEAK",
      requestId: "req-sol-1",
    });
  });

  it("404 SIM_SCENARIO_NOT_FOUND keeps the envelope family code", async () => {
    respondWith(404, {
      error: {
        error_code: "SIM_SCENARIO_NOT_FOUND",
        message: "unknown scenario",
        retryable: false,
        details: {},
      },
      request_id: "req-scn-1",
    });
    await expect(getScenario("missing")).rejects.toMatchObject({
      status: 404,
      errorCode: "SIM_SCENARIO_NOT_FOUND",
    });
  });
});
