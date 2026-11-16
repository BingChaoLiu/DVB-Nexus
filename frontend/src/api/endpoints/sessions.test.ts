// Session read-face endpoint seam tests (SPEC-408 §6.1/§6.2/§6.3, ticket #95
// consuming the #94 wire). The seam is the HTTP call each domain function
// issues through the real openapi-fetch client (fetch/Request stubbed at the
// global boundary — no internal mocking) plus the SPEC-500 §6 envelope error
// branch. Mirrors the scenarios.test.ts posture (stub installed before the
// client module chain imports; behavior driven through a mutable responder
// cell).
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

const { getSessionDetail, listSessionRuns, listSessions } = await import("./sessions");

const SESSION_ID = "0f0e0d0c-0b0a-4900-8000-00000000e001";

function respondWith(status: number, payload: unknown) {
  responder.status = status;
  responder.payload = payload;
}

afterEach(() => {
  calls.length = 0;
  respondWith(200, {});
});

describe("sessions read endpoints — request shapes (SPEC-408 §6)", () => {
  it("listSessions GETs the collection with no query when limit is omitted (server default 20)", async () => {
    respondWith(200, [
      {
        session_id: SESSION_ID,
        lifecycle: "running",
        created_at_ms: 1_700_000_000_000,
        scenario_id: null,
        topology_revision: 1,
      },
    ]);
    const result = await listSessions();
    expect(calls).toEqual([{ url: "/api/v1/sessions", method: "GET", body: undefined }]);
    expect(result[0]?.session_id).toBe(SESSION_ID);
    // The wire row passes through verbatim (no frontend reshaping).
    expect(result[0]?.lifecycle).toBe("running");
    expect(result[0]?.created_at_ms).toBe(1_700_000_000_000);
    expect(result[0]?.scenario_id).toBeNull();
  });

  it("listSessions forwards the limit as the query parameter", async () => {
    respondWith(200, []);
    await listSessions(20);
    expect(calls).toEqual([{ url: "/api/v1/sessions?limit=20", method: "GET", body: undefined }]);
  });

  it("getSessionDetail GETs the detail read-back by id (no query string)", async () => {
    respondWith(200, {
      session_id: SESSION_ID,
      revision: 1,
      lifecycle: "running",
      virtual_time_ns: 0,
      topology_revision: 1,
      scenario_id: "5c010000-0000-4000-8000-000000000001",
      created_at_ms: 1_700_000_000_000,
    });
    const result = await getSessionDetail(SESSION_ID);
    expect(calls).toEqual([{ url: `/api/v1/sessions/${SESSION_ID}`, method: "GET", body: undefined }]);
    // The provenance pair is the additive face the verify prefill consumes.
    expect(result.scenario_id).toBe("5c010000-0000-4000-8000-000000000001");
    expect(result.created_at_ms).toBe(1_700_000_000_000);
  });

  it("listSessionRuns GETs the run list by session id (no query string)", async () => {
    respondWith(200, [
      {
        run_id: "r-1",
        status: "completed",
        submitted_at_ms: 1_700_000_000_000,
        fault_plan_present: false,
        packet_count: 600,
      },
    ]);
    const result = await listSessionRuns(SESSION_ID);
    expect(calls).toEqual([
      { url: `/api/v1/sessions/${SESSION_ID}/runs`, method: "GET", body: undefined },
    ]);
    expect(result[0]?.run_id).toBe("r-1");
    expect(result[0]?.status).toBe("completed");
    expect(result[0]?.submitted_at_ms).toBe(1_700_000_000_000);
    expect(result[0]?.fault_plan_present).toBe(false);
    expect(result[0]?.packet_count).toBe(600);
  });
});

describe("sessions read endpoints — SPEC-500 §6 envelope error branch", () => {
  it("404 SIM_SESSION_NOT_FOUND surfaces as ApiError with envelope keys", async () => {
    respondWith(404, {
      error: {
        error_code: "SIM_SESSION_NOT_FOUND",
        message: "unknown session",
        retryable: false,
        details: {},
      },
      request_id: "req-sess-1",
    });
    await expect(getSessionDetail("missing")).rejects.toMatchObject({
      status: 404,
      errorCode: "SIM_SESSION_NOT_FOUND",
      requestId: "req-sess-1",
    });
    await expect(listSessionRuns("missing")).rejects.toMatchObject({
      status: 404,
      errorCode: "SIM_SESSION_NOT_FOUND",
    });
  });

  it("400 REQUEST_BODY_INVALID (limit out of range) keeps the envelope family code", async () => {
    respondWith(400, {
      error: {
        error_code: "REQUEST_BODY_INVALID",
        message: "limit out of range",
        retryable: false,
        details: {},
      },
      request_id: "req-sess-2",
    });
    await expect(listSessions(101)).rejects.toMatchObject({
      status: 400,
      errorCode: "REQUEST_BODY_INVALID",
    });
  });
});
