// Api client core seam tests (SPEC-400 §8; the unified error envelope is the
// SPEC-305 §7 shape via SPEC-500 §3). These pin the wire contract the whole
// frontend depends on: every non-2xx becomes an ApiError carrying the
// envelope's exact keys.
import { describe, expect, it, vi } from "vitest";
import { ApiError, errorFromResponse, isApiError, unwrap } from "./client";

const ENVELOPE = {
  error: {
    error_code: "OBS_QUERY_RANGE_TOO_LARGE",
    message: "Requested range exceeds configured maximum",
    retryable: false,
    details: { max_range_ns: 3600000000000 },
  },
  request_id: "req-001",
};

describe("errorFromResponse — parses the unified envelope into ApiError", () => {
  it("carries error_code/message/retryable/details/request_id verbatim", async () => {
    const response = new Response(JSON.stringify(ENVELOPE), { status: 400 });
    const error = await errorFromResponse(response);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
    expect(error.errorCode).toBe("OBS_QUERY_RANGE_TOO_LARGE");
    expect(error.message).toBe("Requested range exceeds configured maximum");
    expect(error.retryable).toBe(false);
    expect(error.details).toEqual({ max_range_ns: 3600000000000 });
    expect(error.requestId).toBe("req-001");
  });

  it("keeps 501 frozen-route errors as HTTP_<status> family codes", async () => {
    const response = new Response(JSON.stringify({ error: { error_code: "HTTP_501", message: "Not Implemented", retryable: false, details: {} }, request_id: "r2" }), { status: 501 });
    const error = await errorFromResponse(response);
    expect(error.status).toBe(501);
    expect(error.errorCode).toBe("HTTP_501");
    expect(isApiError(error)).toBe(true);
  });

  it("falls back to HTTP_<status> when the body is not an envelope", async () => {
    const response = new Response("<html>proxy error</html>", { status: 502 });
    const error = await errorFromResponse(response);
    expect(error.errorCode).toBe("HTTP_502");
    expect(error.requestId).toBeNull();
  });
});

describe("unwrap — openapi-fetch result → data or ApiError", () => {
  it("returns parsed data on ok responses", async () => {
    const response = new Response(JSON.stringify({ ok: true }), { status: 200 });
    const data = await unwrap<{ ok: boolean }>(Promise.resolve({ data: { ok: true }, response }));
    expect(data).toEqual({ ok: true });
  });

  it("returns undefined for 204 no-content responses (DELETE idempotent stop)", async () => {
    const response = new Response(null, { status: 204 });
    const data = await unwrap<void>(Promise.resolve({ data: undefined, response }));
    expect(data).toBeUndefined();
  });

  it("throws ApiError with the envelope's error_code on error responses", async () => {
    const response = new Response(JSON.stringify(ENVELOPE), { status: 400 });
    const promise = Promise.resolve({ data: undefined, response });
    await expect(unwrap(promise)).rejects.toMatchObject({
      errorCode: "OBS_QUERY_RANGE_TOO_LARGE",
      requestId: "req-001",
    });
  });
});

// Real-flow regression (ticket #62, ruling I on #15): openapi-fetch consumes
// the body of non-ok responses itself, so unwrap must surface the parsed
// payload instead of re-reading the used-up response body. The client is
// constructed fresh with scoped fetch/Request stubs (createClient options) —
// the static-import module instance already captured the real globals.
import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";

describe("unwrap through the real openapi-fetch flow", () => {
  it("surfaces the envelope keys (error_code/details/request_id) from a consumed body", async () => {
    const fetchStub = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          error: {
            error_code: "SIM_TS_PLAN_INVALID",
            message: "fault plan rejected at prepare",
            retryable: false,
            details: { errors: ["fault_plan[0]: bogus_key is not a v1 parameter"] },
          },
          request_id: "req-flow-1",
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      );
    });
    const requestStub = class {
      url: string;
      method: string;
      constructor(input: string | URL, init?: { method?: string }) {
        this.url = String(input);
        this.method = (init?.method ?? "GET").toUpperCase();
      }
    } as unknown as typeof Request;
    const scoped = createClient<paths>({ fetch: fetchStub as unknown as typeof fetch, Request: requestStub });
    const error = await unwrap(
      // body never reaches the wire — the fetch stub answers 422 before that;
      // it is only present to satisfy the generated path types.
      scoped.POST("/api/v1/sessions/{session_id}/runs", { params: { path: { session_id: "s" } }, body: {} as never }),
    ).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).errorCode).toBe("SIM_TS_PLAN_INVALID");
    expect((error as ApiError).details).toEqual({ errors: ["fault_plan[0]: bogus_key is not a v1 parameter"] });
    expect((error as ApiError).requestId).toBe("req-flow-1");
  });
});
