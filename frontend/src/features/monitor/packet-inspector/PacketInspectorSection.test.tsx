// SPEC-404 §4.4/§4.5 — PacketInspectorSection presentation contract.
// Seam = the component's rendered shape (data-testid/role assertions; no DOM
// snapshots per SPEC-400 test discipline). Data comes from the hook, whose
// wire face is mocked at the api barrel; decode fidelity is golden-proven in
// decode.test.ts — here we assert the VIEW of the facts, honestly branched.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    getArtifactMeta: vi.fn(),
    getArtifactContent: vi.fn(),
  };
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { getArtifactContent, getArtifactMeta } from "../../../api";
import { PacketInspectorSection } from "./PacketInspectorSection";

const mockedMeta = vi.mocked(getArtifactMeta);
const mockedContent = vi.mocked(getArtifactContent);

const REPO_ROOT = resolve(import.meta.dirname, "../../../../..");
const GOLDEN = resolve(REPO_ROOT, "docs/test-vectors/golden/packet-header-set/packet-header-set.ts");

/** packet 0 of the golden header set: 47 40 00 10 10 (afc=1 → payload at 4). */
// Snapshot copy (NOT a live view over the read buffer): readFileSync may hand
// back a pooled Buffer, and a Uint8Array built on buffer.buffer aliases the
// shared 8KB pool — pool reuse during the run corrupted the bytes (#169: the
// added modules perturbed transform timing and exposed this latent bug).
const GOLDEN_PACKET_0 = new Uint8Array(readFileSync(GOLDEN).subarray(0, 188));

const LOCATOR = { artifact_id: "art-g", pid: 16, packet_index: 3 };

function renderSection(locator: typeof LOCATOR | null, onClose: () => void = () => {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<PacketInspectorSection locator={locator} onClose={onClose} />, { wrapper });
}

beforeEach(() => {
  mockedMeta.mockReset();
  mockedContent.mockReset();
});

describe("PacketInspectorSection — idle", () => {
  it("renders nothing when no locator is selected (honest empty state)", () => {
    renderSection(null);
    expect(screen.queryByTestId("packet-inspector")).not.toBeInTheDocument();
  });
});

describe("PacketInspectorSection — ready (golden packet 0 bytes)", () => {
  it("renders wire evidence line, 12 hex rows and SPEC-100 header fields", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    mockedContent.mockResolvedValue({
      status: 206,
      bytes: GOLDEN_PACKET_0,
      contentRange: "bytes 564-751/18800",
      acceptRanges: "bytes",
    });

    renderSection(LOCATOR);
    // wire evidence verbatim (SPEC-404 §4.3) — findBy waits through meta+content loads
    expect(await screen.findByTestId("inspect-content-range")).toHaveTextContent("bytes 564-751/18800");
    expect(screen.getByTestId("inspect-content-range")).toHaveTextContent("Accept-Ranges: bytes");
    console.log("DEBUG hex row 0:", screen.getByTestId("inspect-hex-row-0").textContent);

    // hex: 12 rows, row 0 starts with offset 0 and the golden header bytes
    for (let r = 0; r < 12; r++) {
      expect(screen.getByTestId(`inspect-hex-row-${r}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("inspect-hex-row-0")).toHaveTextContent("47400010");

    // SPEC-100 §3 field view: packet 0 = pid 0, pusi=1, afc=1, cc=0
    expect(screen.getByTestId("inspect-field-pid")).toHaveTextContent("0x0000");
    expect(screen.getByTestId("inspect-field-sync")).toHaveTextContent("0x47");
    expect(screen.getByTestId("inspect-field-cc")).toHaveTextContent("0");
    expect(screen.getByTestId("inspect-field-pusi")).toHaveTextContent("1");
    // locator pid (16) vs packet header pid (0) — both shown, never merged
    expect(screen.getByTestId("inspect-locator-pid")).toHaveTextContent("16");
    expect(screen.getByTestId("inspect-field-pid")).not.toHaveTextContent("16");
  });

  it("renders the AF face when present and the close action calls onClose", async () => {
    // packet-header-set packet 6 (index 6): afc=3 with PCR base 12345.
    const golden6 = new Uint8Array(readFileSync(GOLDEN).subarray(188 * 6, 188 * 6 + 188));
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    mockedContent.mockResolvedValue({ status: 206, bytes: golden6, contentRange: "bytes 1128-1315/18800", acceptRanges: "bytes" });

    const onClose = vi.fn();
    const user = userEvent.setup();
    renderSection({ ...LOCATOR, packet_index: 6 }, onClose);
    expect(await screen.findByTestId("inspect-field-afc")).toHaveTextContent("11");
    expect(screen.getByTestId("inspect-af")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-af-length")).toHaveTextContent(/\d+/);
    expect(screen.getByTestId("inspect-pcr")).toHaveTextContent("12345");
    expect(screen.getByTestId("inspect-pcr")).toHaveTextContent("3703500"); // combined ticks
    await user.click(screen.getByRole("button", { name: /关闭/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("PacketInspectorSection — explicit non-success branches (§8)", () => {
  async function expectBranch(phase: "meta" | "wire") {
    if (phase === "meta") {
      mockedMeta.mockRejectedValue(
        new (await import("../../../api")).ApiError({ status: 404, errorCode: "ARTIFACT_NOT_FOUND", message: "missing" }),
      );
    } else {
      mockedMeta.mockResolvedValue({
        artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
        relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
        packet_count: 100, created_at_utc_ms: 1,
      } as never);
      mockedContent.mockRejectedValue(
        new (await import("../../../api")).ApiError({ status: 416, errorCode: "HTTP_416", message: "range not satisfiable" }),
      );
    }
    renderSection(LOCATOR);
    expect(await screen.findByTestId("inspect-error")).toBeInTheDocument();
    return screen.getByTestId("inspect-error");
  }

  it("meta error carries status + errorCode verbatim", async () => {
    const el = await expectBranch("meta");
    expect(el).toHaveTextContent("404");
    expect(el).toHaveTextContent("ARTIFACT_NOT_FOUND");
  });

  it("content 416 carries status verbatim", async () => {
    const el = await expectBranch("wire");
    expect(el).toHaveTextContent("416");
  });

  it("meta-invalid gate states the non-188 geometry", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "other",
      relative_path: "x", byte_size: 5, sha256: "sha", packet_size: 204,
      packet_count: null, created_at_utc_ms: 1,
    } as never);
    renderSection(LOCATOR);
    expect(await screen.findByTestId("inspect-meta-invalid")).toHaveTextContent("204");
  });

  it("out-of-range gate states index and packet_count", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 1316, sha256: "sha", packet_size: 188,
      packet_count: 3, created_at_utc_ms: 1,
    } as never);
    renderSection(LOCATOR);
    expect(await screen.findByTestId("inspect-out-of-range")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-out-of-range")).toHaveTextContent("packet 3");
    expect(screen.getByTestId("inspect-out-of-range")).toHaveTextContent("共 3 包");
  });

  it("truncated wire states the arrived byte count", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    mockedContent.mockResolvedValue({ status: 206, bytes: new Uint8Array(96), contentRange: "bytes 564-659/18800", acceptRanges: "bytes" });
    renderSection(LOCATOR);
    expect(await screen.findByTestId("inspect-truncated")).toHaveTextContent("96");
  });

  it("sync_byte ≠ 0x47 renders the warning line without hiding the fields", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-g", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    mockedContent.mockResolvedValue({ status: 206, bytes: new Uint8Array(188), contentRange: "bytes 564-751/18800", acceptRanges: "bytes" });
    renderSection(LOCATOR);
    expect(await screen.findByTestId("inspect-sync-warning")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-field-pid")).toBeInTheDocument();
  });
});

// SPEC-404 §Phase3 (ticket #169): the SIM_STATE Run face — view param NOT
// extended; a state-domain run (artifacts == []) renders the 空态三问 with the
// jump button to the node detail panel, taking precedence over both the
// generic locator-null row and any stale locator.
describe("PacketInspectorSection — SIM_STATE Run 空态三问 (view 不扩)", () => {
  function renderSimState(locator: typeof LOCATOR | null) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/monitor"]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    return render(<PacketInspectorSection locator={locator} onClose={() => {}} simStateRun={{ sessionId: "s-9" }} />, { wrapper });
  }

  it("renders the SIM_STATE three-question face (not the generic locator-null row)", () => {
    renderSimState(null);
    expect(screen.getByTestId("dvb-pi-simstate-empty")).toHaveTextContent("空 ≠ 干净");
    expect(screen.queryByText("尚未从诊断候选点")).toBeNull();
    expect(screen.queryByTestId("packet-inspector")).toBeNull();
  });

  it("takes precedence over a stale locator (SIM_STATE runs have no artifacts to drill)", () => {
    renderSimState(LOCATOR);
    expect(screen.getByTestId("dvb-pi-simstate-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("packet-inspector")).toBeNull();
  });

  it("the jump button deep-links the tracked session onto the topology canvas", () => {
    renderSimState(null);
    expect(screen.getByTestId("dvb-pi-simstate-jump")).toHaveAttribute("href", "/topologies?session=s-9");
  });

  it("without the simStateRun prop the pre-#169 face is byte-identical (generic empty row)", () => {
    renderSection(null);
    expect(screen.getByText(/尚未从诊断候选点/)).toBeInTheDocument();
    expect(screen.queryByTestId("dvb-pi-simstate-empty")).toBeNull();
  });
});
