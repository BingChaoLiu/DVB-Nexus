// SPEC-404 §Phase2 — PacketInspectorSection view-driven branches (#132).
// The default `ts` face keeps the MVP branch machine (zero regression — the
// existing PacketInspectorSection.test.tsx asserts stay untouched); the
// t2mi/bbframe views render the structure-JSON wire, and every non-ready
// structure branch is explicit (400 SIM_STRUCTURE_NOT_T2MI etc. — SPEC-404
// §8: no branch masquerades as success).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    getArtifactStructure: vi.fn(),
    getArtifactMeta: vi.fn(),
    getArtifactContent: vi.fn(),
  };
});

import { getArtifactStructure, getArtifactMeta } from "../../../api";
import type { BBFrameStructureViewDTO, T2miStructureViewDTO } from "../../../api";
import { PacketInspectorSection } from "./PacketInspectorSection";

const mockedStructure = vi.mocked(getArtifactStructure);
const mockedMeta = vi.mocked(getArtifactMeta);

const LOCATOR = { artifact_id: "art-layered", pid: 0, packet_index: 1 };

const T2MI_WIRE: T2miStructureViewDTO = {
  view: "t2mi",
  packet_count: 2,
  truncated: false,
  trailing_bytes: 0,
  packets: [
    {
      packet_index: 0,
      packet_type: 0x00,
      packet_counter: 0,
      payload_kind: "bbframe",
      payload_bytes_len: 100,
      crc32_valid: true,
      frame_index: 0,
      plp_id: 0,
    },
    {
      packet_index: 1,
      packet_type: 0x00,
      packet_counter: 1,
      payload_kind: "bbframe",
      payload_bytes_len: 100,
      crc32_valid: true,
      frame_index: 1,
      plp_id: 1,
    },
  ],
};

const BBFRAME_WIRE: BBFrameStructureViewDTO = {
  view: "bbframe",
  frame_count: 1,
  frames: [
    {
      frame_index: 0,
      matype: 0x0000,
      upl: 1504,
      dfl: 0,
      sync: 0x47,
      syncd: 0,
      crc8_valid: true,
      up_count: 3,
      up_indices: [0, 188, 376],
      state: "ok",
    },
  ],
};

function renderSection(props: Partial<Parameters<typeof PacketInspectorSection>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<PacketInspectorSection locator={LOCATOR} onClose={() => {}} {...props} />, { wrapper });
}

beforeEach(() => {
  mockedStructure.mockReset();
  mockedMeta.mockReset();
});

describe("PacketInspectorSection — view=t2mi (SPEC-404 §Phase2)", () => {
  it("renders the layered structure rows and the view label", async () => {
    mockedStructure.mockResolvedValue(T2MI_WIRE);
    renderSection({ view: "t2mi" });
    expect(await screen.findByTestId("t2mi-structure-view")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-view")).toHaveTextContent("view t2mi");
    // locator packet_index 1 selects row 1 (the t2mi-view locator face)
    expect(screen.getByTestId("t2mi-row-1").className).toContain("dvb-pi-row-selected");
    // MVP meta/Range faces never fire on layered views
    expect(mockedMeta).not.toHaveBeenCalled();
  });

  it("renders an explicit error branch on 400 SIM_STRUCTURE_NOT_T2MI (plain TS artifact)", async () => {
    const { ApiError } = await import("../../../api");
    mockedStructure.mockRejectedValue(
      new ApiError({ status: 400, errorCode: "SIM_STRUCTURE_NOT_T2MI", message: "plain MPEG-TS stream" }),
    );
    renderSection({ view: "t2mi" });
    const error = await screen.findByTestId("inspect-structure-error");
    expect(error).toHaveTextContent("view=t2mi");
    expect(error).toHaveTextContent("400");
    expect(error).toHaveTextContent("SIM_STRUCTURE_NOT_T2MI");
    // no structure view may masquerade as success
    expect(screen.queryByTestId("t2mi-structure-view")).not.toBeInTheDocument();
  });
});

describe("PacketInspectorSection — view=bbframe (SPEC-404 §Phase2)", () => {
  it("renders the BBHEADER rows with the verbatim SYNCD anchor", async () => {
    mockedStructure.mockResolvedValue(BBFRAME_WIRE);
    renderSection({ view: "bbframe" });
    expect(await screen.findByTestId("bbframe-structure-view")).toBeInTheDocument();
    expect(screen.getByTestId("inspect-view")).toHaveTextContent("view bbframe");
    expect(screen.getByTestId("bbframe-syncd-anchor")).toHaveTextContent(
      "SYNCD 是数据字段内首个 UP 的位距离，不是同步字节",
    );
  });
});

describe("PacketInspectorSection — default view=ts (MVP zero-regression face)", () => {
  it("does NOT fetch the structure endpoint and renders the MVP ready face", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-layered", run_id: "r", session_id: "s", kind: "generated_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    const { getArtifactContent } = await import("../../../api");
    vi.mocked(getArtifactContent).mockResolvedValue({
      status: 206,
      // 188 zero bytes: sync warning face — enough for the shape assertion.
      bytes: new Uint8Array(188),
      contentRange: "bytes 0-187/18800",
      acceptRanges: "bytes",
    });
    renderSection();
    expect(await screen.findByTestId("inspect-content-range")).toHaveTextContent("bytes 0-187/18800");
    expect(screen.getByTestId("inspect-view")).toHaveTextContent("view ts");
    expect(mockedStructure).not.toHaveBeenCalled();
    expect(screen.queryByTestId("t2mi-structure-view")).not.toBeInTheDocument();
    // the payload-layer scrambling annotation face (wire-derived; 00 = clear)
    expect(screen.getByTestId("inspect-biss-state")).toHaveTextContent("clear");
  });

  it("annotates scrambled when the wire scrambling bits are non-zero", async () => {
    mockedMeta.mockResolvedValue({
      artifact_id: "art-layered", run_id: "r", session_id: "s", kind: "faulted_ts",
      relative_path: "x", byte_size: 18800, sha256: "sha", packet_size: 188,
      packet_count: 100, created_at_utc_ms: 1,
    } as never);
    const { getArtifactContent } = await import("../../../api");
    const scrambled = new Uint8Array(188);
    scrambled[3] = 0b10_000000; // AFC=00, scrambling=10 (even key face)
    vi.mocked(getArtifactContent).mockResolvedValue({
      status: 206,
      bytes: scrambled,
      contentRange: "bytes 188-375/18800",
      acceptRanges: "bytes",
    });
    renderSection({ bissEvidence: { mode: "1", key_fingerprint_ref: "sha256:abc", mutation_log_ref: null } });
    expect(await screen.findByTestId("inspect-biss-state")).toHaveTextContent("scrambled");
    // the BISS annotation block renders from the optional prop
    expect(screen.getByTestId("biss-annotation")).toBeInTheDocument();
    expect(screen.getByTestId("biss-fingerprint")).toHaveTextContent("sha256:abc");
  });
});
