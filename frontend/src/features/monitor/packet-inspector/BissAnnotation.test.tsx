// SPEC-404 §Phase2 — BissAnnotation presentation contract: the fingerprint
// reference renders verbatim (sha256: prefix preserved; key material NEVER
// crosses this face), the mode wire value renders verbatim ("1"/"E"/"2"),
// and the mutation-log summary faces (loading/ready/error) are explicit.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    getArtifactContent: vi.fn(),
  };
});

import { getArtifactContent } from "../../../api";
import { BissAnnotation } from "./BissAnnotation";

const mockedContent = vi.mocked(getArtifactContent);

function renderAnnotation(evidence: Parameters<typeof BissAnnotation>[0]["evidence"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<BissAnnotation evidence={evidence} />, { wrapper });
}

beforeEach(() => {
  mockedContent.mockReset();
});

describe("BissAnnotation — reference faces only (SPEC-404 §Phase2)", () => {
  it("renders mode and fingerprint verbatim (sha256: prefix preserved)", () => {
    renderAnnotation({ mode: "E", key_fingerprint_ref: "sha256:1a2b3c4d5e6f7081" });
    expect(screen.getByTestId("biss-mode")).toHaveTextContent("E");
    // wire enum verbatim — "E" is never rewritten to "Mode E" or lowercased
    expect(screen.getByTestId("biss-fingerprint")).toHaveTextContent("sha256:1a2b3c4d5e6f7081");
    expect(screen.getByTestId("biss-evidence-link")).toHaveTextContent("biss.descramble_failed");
    // the leak-safety sentence is on the face
    expect(screen.getByTestId("biss-fingerprint")).toHaveTextContent("密钥本体永不渲染");
  });

  it("summarizes the mutation log artifact (layered wrapper face)", async () => {
    const document = {
      schema_version: 1,
      log_kind: "layered_pipeline_mutation_log",
      run_id: "run-1",
      layers: ["TS", "BBFRAME"],
      layer_logs: {
        TS: { mutations: [{}, {}, {}] },
        BBFRAME: { mutations: [{}] },
      },
    };
    mockedContent.mockResolvedValue({
      status: 200,
      bytes: new TextEncoder().encode(JSON.stringify(document)),
      contentRange: null,
      acceptRanges: null,
    });
    renderAnnotation({ key_fingerprint_ref: "sha256:aabb", mutation_log_ref: "log-artifact-1" });
    expect(await screen.findByTestId("biss-mutation-log")).toBeInTheDocument();
    expect(screen.getByTestId("biss-mutation-log")).toHaveTextContent("log-artifact-1");
    expect(screen.getByTestId("biss-mutation-log")).toHaveTextContent("layered_pipeline_mutation_log");
    expect(screen.getByTestId("biss-mutation-log")).toHaveTextContent("run-1");
    // per-layer record counts (summary — no record payload rendering)
    expect(screen.getByTestId("biss-mutation-log")).toHaveTextContent("TS");
    expect(screen.getByTestId("biss-mutation-log")).toHaveTextContent("BBFRAME");
  });

  it("renders an explicit error face when the log artifact cannot be read", async () => {
    const { ApiError } = await import("../../../api");
    mockedContent.mockRejectedValue(new ApiError({ status: 404, errorCode: "ARTIFACT_NOT_FOUND", message: "missing" }));
    renderAnnotation({ key_fingerprint_ref: "sha256:aabb", mutation_log_ref: "log-gone" });
    const error = await screen.findByTestId("biss-mutation-log-error");
    expect(error).toHaveTextContent("404");
    expect(error).toHaveTextContent("ARTIFACT_NOT_FOUND");
  });

  it("renders the explicit unparseable face when the bytes are not a JSON document", async () => {
    mockedContent.mockResolvedValue({
      status: 200,
      bytes: new TextEncoder().encode("not json at all"),
      contentRange: null,
      acceptRanges: null,
    });
    renderAnnotation({ key_fingerprint_ref: "sha256:aabb", mutation_log_ref: "log-bad" });
    const error = await screen.findByTestId("biss-mutation-log-error");
    expect(error).toHaveTextContent("MUTATION_LOG_UNPARSEABLE");
  });
});
