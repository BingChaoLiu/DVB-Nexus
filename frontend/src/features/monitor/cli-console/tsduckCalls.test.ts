// Data face (SPEC-405 §7.1, REQ-UI-405-003 core + §4.2): the channel→source
// assignment happens HERE (every §4.8 row is source=tsduck), run_id passes
// through as the query param, and errors surface as ApiError envelopes.
// The api barrel (shared face) is mocked at its transport method only —
// unwrap/errorFromResponse/ApiError stay REAL (importOriginal), so the
// envelope contract below is exercised through the actual client semantics.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError } from "../../../api";
import { fullCall } from "./fixtures";
import { listTSDuckCalls } from "./tsduckCalls";
import { client } from "../../../api";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return { ...actual, client: { ...actual.client, GET: vi.fn() } };
});

const mockedGet = vi.mocked(client.GET);

beforeEach(() => {
  mockedGet.mockReset();
});

describe("listTSDuckCalls — channel→source assignment (§7.1)", () => {
  it("tags every §4.8 record with source=tsduck at the data-face boundary", async () => {
    mockedGet.mockResolvedValue({
      data: [fullCall],
      response: new Response(null, { status: 200 }),
    } as never);
    const rows = await listTSDuckCalls("s-1");
    expect(rows).toHaveLength(1);
    expect(rows[0]?.source).toBe("tsduck");
    expect(rows[0]?.call.started_at_utc_ms).toBe(1_000);
    expect(rows[0]?.call.argv).toEqual(fullCall.argv);
  });

  it("returns an empty tagged list for 200 + [] (empty stays the empty state's job)", async () => {
    mockedGet.mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as never);
    const rows = await listTSDuckCalls("s-1");
    expect(rows).toEqual([]);
  });
});

describe("listTSDuckCalls — SPEC-500 §4.8 request shape", () => {
  it("GETs the session-scoped tsduck/calls path", async () => {
    mockedGet.mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as never);
    await listTSDuckCalls("s-1");
    expect(mockedGet).toHaveBeenCalledTimes(1);
    const [path, init] = mockedGet.mock.calls[0] as [string, { params: { path: { session_id: string }; query?: { run_id?: string } } }];
    expect(path).toBe("/api/v1/sessions/{session_id}/tsduck/calls");
    expect(init.params.path.session_id).toBe("s-1");
    expect(init.params.query).toBeUndefined();
  });

  it("passes run_id through as the query param verbatim", async () => {
    mockedGet.mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as never);
    await listTSDuckCalls("s-1", "run-7");
    const [, init] = mockedGet.mock.calls[0] as [string, { params: { query?: { run_id?: string } } }];
    expect(init.params.query?.run_id).toBe("run-7");
  });
});

describe("listTSDuckCalls — error envelope (AC-405-05, real unwrap path)", () => {
  it("raises ApiError with the 404 SIM_SESSION_NOT_FOUND envelope keys", async () => {
    mockedGet.mockResolvedValue({
      data: undefined,
      response: new Response(
        JSON.stringify({
          error: {
            error_code: "SIM_SESSION_NOT_FOUND",
            message: "no rows and empty journal",
            retryable: false,
            details: {},
          },
          request_id: "req-404",
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      ),
    } as never);
    const error = await listTSDuckCalls("s-1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(404);
    expect(apiError.errorCode).toBe("SIM_SESSION_NOT_FOUND");
    expect(apiError.requestId).toBe("req-404");
  });

  it("raises ApiError for the 501 unbound composition", async () => {
    mockedGet.mockResolvedValue({
      data: undefined,
      response: new Response(
        JSON.stringify({
          error: { error_code: "HTTP_501", message: "not bound", retryable: false, details: {} },
          request_id: null,
        }),
        { status: 501, headers: { "Content-Type": "application/json" } },
      ),
    } as never);
    const error = await listTSDuckCalls("s-1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(501);
  });
});
