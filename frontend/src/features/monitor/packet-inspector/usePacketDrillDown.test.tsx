// SPEC-404 §7.3/§8 branch matrix for the drill-down data hook (plan-65.md §4.3).
// Seam = the api barrel (getArtifactMeta/getArtifactContent/packetRange); the
// hook's contract is the state machine, asserted through the public state —
// no internal query-state poking. Every branch must land in an explicit,
// honest phase: no error branch may masquerade as success (SPEC-404 §8).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../api";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    getArtifactMeta: vi.fn(),
    getArtifactContent: vi.fn(),
  };
});

import { getArtifactContent, getArtifactMeta, packetRange } from "../../../api";
import { usePacketDrillDown } from "./usePacketDrillDown";

const mockedMeta = vi.mocked(getArtifactMeta);
const mockedContent = vi.mocked(getArtifactContent);

const LOCATOR = { artifact_id: "art-1", pid: 256, packet_index: 7 };

function makeMeta(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: "art-1",
    run_id: "run-1",
    session_id: "s-1",
    kind: "faulted_ts",
    relative_path: "artifacts/art-1.ts",
    byte_size: 18800,
    sha256: "sha256:x",
    packet_size: 188,
    packet_count: 100,
    created_at_utc_ms: 1,
    ...overrides,
  };
}

function contentResult(status: number, byteCount: number, contentRange: string | null = "bytes 1316-1503/18800") {
  return {
    status,
    bytes: new Uint8Array(byteCount),
    contentRange,
    acceptRanges: "bytes",
  };
}

function renderDrill(locator: typeof LOCATOR | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(({ l }: { l: typeof LOCATOR | null }) => usePacketDrillDown(l), {
    initialProps: { l: locator },
    wrapper,
  });
}

beforeEach(() => {
  mockedMeta.mockReset();
  mockedContent.mockReset();
});

describe("usePacketDrillDown — happy path", () => {
  it("resolves ready with decoded view, hex rows and wire evidence headers", async () => {
    mockedMeta.mockResolvedValue(makeMeta());
    mockedContent.mockResolvedValue(contentResult(206, 188));

    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    if (result.current.phase !== "ready") throw new Error("unreachable");
    expect(result.current.view.header.sync_byte_ok).toBe(false); // zero bytes ≠ 0x47, honestly reported
    expect(result.current.hexRows).toHaveLength(12);
    expect(result.current.byteCount).toBe(188);
    expect(result.current.contentRange).toBe("bytes 1316-1503/18800");
    expect(result.current.acceptRanges).toBe("bytes");
  });

  it("fetches meta first, then content with the single-packet Range from the barrel (188×index)", async () => {
    mockedMeta.mockResolvedValue(makeMeta());
    mockedContent.mockResolvedValue(contentResult(206, 188));
    const order: string[] = [];
    mockedMeta.mockImplementation(async () => {
      order.push("meta");
      return makeMeta();
    });
    mockedContent.mockImplementation(async () => {
      order.push("content");
      return contentResult(206, 188);
    });

    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(order).toEqual(["meta", "content"]); // metadata-first (SPEC-404 §4.3)
    expect(mockedContent).toHaveBeenCalledWith("art-1", { range: packetRange(7) });
    expect(packetRange(7)).toBe("bytes=1316-1503"); // 188×7 .. +187, verbatim barrel formula
  });
});

describe("usePacketDrillDown — geometry gates (client-side pre-branch, §7.3 rows 1-2)", () => {
  it("packet_size ≠ 188 → meta-invalid, content never fetched", async () => {
    mockedMeta.mockResolvedValue(makeMeta({ packet_size: 192 }));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("meta-invalid"));
    if (result.current.phase !== "meta-invalid") throw new Error("unreachable");
    expect(result.current.packetSize).toBe(192);
    expect(mockedContent).not.toHaveBeenCalled();
  });

  it("packet_index ≥ packet_count → out-of-range pre-branch, content never fetched", async () => {
    mockedMeta.mockResolvedValue(makeMeta({ packet_count: 7 }));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("out-of-range"));
    if (result.current.phase !== "out-of-range") throw new Error("unreachable");
    expect(result.current.packetIndex).toBe(7);
    expect(result.current.packetCount).toBe(7);
    expect(mockedContent).not.toHaveBeenCalled();
  });

  it("absent packet_size/packet_count (null) → gates skip, fetch proceeds", async () => {
    mockedMeta.mockResolvedValue(makeMeta({ packet_size: null, packet_count: null }));
    mockedContent.mockResolvedValue(contentResult(206, 188));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(mockedContent).toHaveBeenCalledTimes(1);
  });
});

describe("usePacketDrillDown — wire error branches (§7.3 rows 4-7, §8)", () => {
  it("meta 404 → explicit error branch carrying status + errorCode", async () => {
    mockedMeta.mockRejectedValue(new ApiError({ status: 404, errorCode: "ARTIFACT_NOT_FOUND", message: "no artifact" }));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("error"));
    if (result.current.phase !== "error") throw new Error("unreachable");
    expect(result.current.source).toBe("meta");
    expect(result.current.status).toBe(404);
    expect(result.current.errorCode).toBe("ARTIFACT_NOT_FOUND");
    expect(mockedContent).not.toHaveBeenCalled();
  });

  it("content 416 → explicit error branch (unsatisfiable range)", async () => {
    mockedMeta.mockResolvedValue(makeMeta({ packet_count: null })); // skip pre-check → wire decides
    mockedContent.mockRejectedValue(new ApiError({ status: 416, errorCode: "HTTP_416", message: "range not satisfiable" }));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("error"));
    if (result.current.phase !== "error") throw new Error("unreachable");
    expect(result.current.source).toBe("content");
    expect(result.current.status).toBe(416);
  });

  it("content 400 HTTP_RANGE_MALFORMED → explicit error branch", async () => {
    mockedMeta.mockResolvedValue(makeMeta());
    mockedContent.mockRejectedValue(
      new ApiError({ status: 400, errorCode: "HTTP_RANGE_MALFORMED", message: "malformed range" }),
    );
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("error"));
    if (result.current.phase !== "error") throw new Error("unreachable");
    expect(result.current.errorCode).toBe("HTTP_RANGE_MALFORMED");
  });

  it("content 206 with wrong byte count → truncated branch, never ready", async () => {
    mockedMeta.mockResolvedValue(makeMeta());
    mockedContent.mockResolvedValue(contentResult(206, 96));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("truncated"));
    if (result.current.phase !== "truncated") throw new Error("unreachable");
    expect(result.current.byteCount).toBe(96);
    expect(result.current.contentRange).toBe("bytes 1316-1503/18800");
  });

  it("content unexpected status (200) → explicit error, never ready", async () => {
    mockedMeta.mockResolvedValue(makeMeta());
    mockedContent.mockResolvedValue(contentResult(200, 18800));
    const { result } = renderDrill(LOCATOR);
    await waitFor(() => expect(result.current.phase).toBe("error"));
    if (result.current.phase !== "error") throw new Error("unreachable");
    expect(result.current.status).toBe(200);
    expect(result.current.errorCode).toBe("UNEXPECTED_STATUS");
  });
});

describe("usePacketDrillDown — idle", () => {
  it("null locator → idle, no fetches", () => {
    const { result } = renderDrill(null);
    expect(result.current.phase).toBe("idle");
    expect(mockedMeta).not.toHaveBeenCalled();
    expect(mockedContent).not.toHaveBeenCalled();
  });
});
