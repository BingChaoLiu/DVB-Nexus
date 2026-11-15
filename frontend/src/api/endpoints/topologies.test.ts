// Topology face endpoint seam tests (SPEC-401 §6.1). The seam is the HTTP
// call each domain function issues through the real openapi-fetch client
// (fetch/Request stubbed at the global boundary — no internal mocking) plus
// the SPEC-500 §6 envelope error branch.
//
// createClient captures globalThis.fetch/Request at module-load time, so the
// stubs are installed BEFORE the client module chain is imported (dynamic
// import below) and the per-test behavior is driven through a mutable state
// cell instead of swapping the global.
import { afterEach, describe, expect, it, vi } from "vitest";

interface RecordedCall {
  url: string;
  method: string;
  body?: unknown;
}

const calls: RecordedCall[] = [];
const responder = { status: 200, payload: {} as unknown };

// openapi-fetch constructs `new Request(relativeUrl, init)` before calling
// fetch; Node's undici Request rejects relative URLs in the vitest
// environment, so the seam stub provides a pass-through Request whose only
// job is carrying the final URL/method/body to the stubbed fetch.
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

vi.stubGlobal(
  "Request",
  StubRequest as unknown as typeof Request,
);
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

const { ApiError } = await import("../client");
const { createTopology, getTopology, listTopologies, saveTopologyRevision, validateTopology } =
  await import("./topologies");

type ApiErrorInstance = InstanceType<typeof ApiError>;
type TopologyDTO = Awaited<ReturnType<typeof getTopology>>;

function respondWith(status: number, payload: unknown) {
  responder.status = status;
  responder.payload = payload;
}

afterEach(() => {
  calls.length = 0;
  respondWith(200, {});
});

const TOPOLOGY_DTO: TopologyDTO = {
  topology_id: "0d1c9dd1-3d92-4a67-8f30-7092b91c501a",
  revision: 2,
  nodes: [
    {
      node_id: "gen-0",
      node_type: "ts_generator",
      config: {},
      ports: [{ port_id: "ts_out", direction: "output", plane: "MPEG_TS", max_connections: 1 }],
    },
  ],
  connections: [],
};

describe("topologies endpoints — request shapes", () => {
  it("createTopology POSTs the draft body to /api/v1/topologies", async () => {
    respondWith(201, TOPOLOGY_DTO);
    const body = { nodes: TOPOLOGY_DTO.nodes, connections: [] };
    const result = await createTopology(body);
    expect(calls).toEqual([{ url: "/api/v1/topologies", method: "POST", body }]);
    expect(result).toEqual(TOPOLOGY_DTO);
  });

  it("listTopologies GETs the collection, forwarding limit only when given", async () => {
    respondWith(200, [{ topology_id: "t-1", revision: 3 }]);
    await listTopologies();
    await listTopologies(5);
    expect(calls).toEqual([
      { url: "/api/v1/topologies", method: "GET", body: undefined },
      { url: "/api/v1/topologies?limit=5", method: "GET", body: undefined },
    ]);
  });

  it("getTopology GETs by id, appending revision only when pinned", async () => {
    respondWith(200, TOPOLOGY_DTO);
    await getTopology("0d1c9dd1-3d92-4a67-8f30-7092b91c501a");
    await getTopology("0d1c9dd1-3d92-4a67-8f30-7092b91c501a", 2);
    expect(calls).toEqual([
      { url: "/api/v1/topologies/0d1c9dd1-3d92-4a67-8f30-7092b91c501a", method: "GET", body: undefined },
      { url: "/api/v1/topologies/0d1c9dd1-3d92-4a67-8f30-7092b91c501a?revision=2", method: "GET", body: undefined },
    ]);
  });

  it("saveTopologyRevision PUTs the body to the topology resource", async () => {
    respondWith(200, TOPOLOGY_DTO);
    const body = { nodes: TOPOLOGY_DTO.nodes, connections: [] };
    const result = await saveTopologyRevision("0d1c9dd1-3d92-4a67-8f30-7092b91c501a", body);
    expect(calls).toEqual([
      { url: "/api/v1/topologies/0d1c9dd1-3d92-4a67-8f30-7092b91c501a", method: "PUT", body },
    ]);
    expect(result.revision).toBe(2);
  });

  it("validateTopology POSTs to the validate subresource with optional revision query", async () => {
    respondWith(200, { ok: true, violations: [] });
    await validateTopology("0d1c9dd1-3d92-4a67-8f30-7092b91c501a");
    await validateTopology("0d1c9dd1-3d92-4a67-8f30-7092b91c501a", 2);
    expect(calls).toEqual([
      { url: "/api/v1/topologies/0d1c9dd1-3d92-4a67-8f30-7092b91c501a/validate", method: "POST", body: undefined },
      {
        url: "/api/v1/topologies/0d1c9dd1-3d92-4a67-8f30-7092b91c501a/validate?revision=2",
        method: "POST",
        body: undefined,
      },
    ]);
  });
});

describe("topologies endpoints — SPEC-500 §6 envelope error branch", () => {
  it("404 SIM_TOPOLOGY_NOT_FOUND surfaces as ApiError with envelope keys", async () => {
    respondWith(404, {
      error: {
        error_code: "SIM_TOPOLOGY_NOT_FOUND",
        message: "unknown topology",
        retryable: false,
        details: {},
      },
      request_id: "req-topo-1",
    });
    await expect(getTopology("missing")).rejects.toMatchObject({
      status: 404,
      errorCode: "SIM_TOPOLOGY_NOT_FOUND",
      requestId: "req-topo-1",
    });
  });

  it("501 frozen-route errors keep the HTTP_501 family code", async () => {
    respondWith(501, {
      error: { error_code: "HTTP_501", message: "Not Implemented", retryable: false, details: {} },
      request_id: "req-topo-2",
    });
    const error = (await saveTopologyRevision("t", { nodes: [], connections: [] }).catch((e: unknown) => e)) as ApiErrorInstance;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errorCode).toBe("HTTP_501");
  });
});
