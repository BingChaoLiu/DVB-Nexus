// SPEC-404 §Phase2 view=t2mi — T2miStructureView presentation contract.
// Shape assertions over the structure-JSON wire (#129 T2miStructureViewDTO):
// the 8-key rows render verbatim (wire enums never rewritten), CRC-32 result
// and the BBFrame payload pointer land explicitly, the locator's
// packet_index selects a row and unmatched locators stay honest.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { T2miStructureViewDTO } from "../../../api";
import { T2miStructureView } from "./T2miStructureView";

const LOCATOR = { artifact_id: "art-t2mi", pid: 0, packet_index: 1 };

const STRUCTURE: T2miStructureViewDTO = {
  view: "t2mi",
  packet_count: 3,
  truncated: false,
  trailing_bytes: 0,
  packets: [
    {
      packet_index: 0,
      packet_type: 0x00,
      packet_counter: 7,
      payload_kind: "bbframe",
      payload_bytes_len: 100,
      crc32_valid: true,
      frame_index: 0,
      plp_id: 0,
    },
    {
      packet_index: 1,
      packet_type: 0x01,
      packet_counter: 8,
      payload_kind: "padding",
      payload_bytes_len: 96,
      crc32_valid: true,
      frame_index: null,
      plp_id: null,
    },
    {
      packet_index: 2,
      packet_type: 0xff,
      packet_counter: 9,
      payload_kind: "unknown",
      payload_bytes_len: 4,
      crc32_valid: false,
      frame_index: null,
      plp_id: null,
    },
  ],
};

describe("T2miStructureView — wire rows (SPEC-404 §Phase2)", () => {
  it("renders every packet row verbatim, including the wire payload_kind enums", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={null} />);
    expect(screen.getByTestId("t2mi-structure-view")).toBeInTheDocument();
    expect(screen.getByTestId("t2mi-summary")).toHaveTextContent("packet_count=3");
    // wire enums verbatim — bbframe/padding/unknown (no aliasing/rewriting)
    expect(screen.getByTestId("t2mi-row-0")).toHaveTextContent("bbframe");
    expect(screen.getByTestId("t2mi-row-1")).toHaveTextContent("padding");
    expect(screen.getByTestId("t2mi-row-2")).toHaveTextContent("unknown");
    for (const index of [0, 1, 2]) {
      expect(screen.getByTestId(`t2mi-row-${index}`)).toBeInTheDocument();
    }
    // header bytes 0/1 verbatim (hex/dec presentation of the raw values)
    expect(screen.getByTestId("t2mi-row-0")).toHaveTextContent("type=0x00");
    expect(screen.getByTestId("t2mi-row-0")).toHaveTextContent("counter=7");
  });

  it("renders the CRC-32 result face, BAD marked explicitly", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={null} />);
    expect(screen.getByTestId("t2mi-row-2")).toHaveTextContent("crc32=BAD");
    expect(screen.getByTestId("t2mi-row-0")).toHaveTextContent("crc32=ok");
  });

  it("expands the selected packet's field detail (CRC-32 + BBFrame payload pointer)", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={{ ...LOCATOR, packet_index: 0 }} />);
    expect(screen.getByTestId("t2mi-detail-0")).toBeInTheDocument();
    expect(screen.getByTestId("t2mi-crc32-0")).toHaveTextContent("true");
    expect(screen.getByTestId("t2mi-payload-kind-0")).toHaveTextContent("bbframe");
    // the BBFrame 载荷指针 face: frame_index + plp_id rows
    expect(screen.getByTestId("t2mi-frame-pointer-0")).toHaveTextContent("0");
    expect(screen.getByTestId("t2mi-frame-pointer-0")).toHaveTextContent("BBFrame 载荷指针");
    expect(screen.getByTestId("t2mi-plp-0")).toHaveTextContent("0");
  });

  it("keeps non-BBFRAME payloads honest (null pointer rows, no fabricated faces)", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={{ ...LOCATOR, packet_index: 1 }} />);
    expect(screen.getByTestId("t2mi-detail-1")).toBeInTheDocument();
    expect(screen.queryByTestId("t2mi-frame-pointer-1")).not.toBeInTheDocument();
    expect(screen.getByText("非 BBFRAME 载荷——诚实三态，不伪造指针")).toBeInTheDocument();
    expect(screen.getByText("传输前缀未声明（非 BBFRAME 包）")).toBeInTheDocument();
    expect(screen.getByTestId("t2mi-crc32-1")).toHaveTextContent("true");
  });

  it("selects the locator's packet row and expands its field detail", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={LOCATOR} />);
    const row = screen.getByTestId("t2mi-row-1");
    expect(row.className).toContain("dvb-pi-row-selected");
    expect(screen.getByTestId(`t2mi-detail-${LOCATOR.packet_index}`)).toBeInTheDocument();
  });

  it("keeps an unmatched locator honest (rows render, no fabricated selection)", () => {
    render(<T2miStructureView structure={STRUCTURE} locator={{ ...LOCATOR, packet_index: 99 }} />);
    expect(screen.getByTestId("t2mi-locator-unmatched")).toHaveTextContent("packet 99");
    expect(screen.queryByTestId("t2mi-detail-99")).not.toBeInTheDocument();
  });

  it("renders the truncated tail face when the wire declares it", () => {
    const truncated: T2miStructureViewDTO = { ...STRUCTURE, truncated: true, trailing_bytes: 5 };
    render(<T2miStructureView structure={truncated} locator={null} />);
    expect(screen.getByTestId("t2mi-truncated")).toHaveTextContent("5 字节");
  });

  it("renders the honest absent face when the wire omits the rows key", () => {
    const empty: T2miStructureViewDTO = { view: "t2mi", packet_count: 0, truncated: false, trailing_bytes: 0 };
    render(<T2miStructureView structure={empty} locator={null} />);
    expect(screen.getByTestId("t2mi-rows-absent")).toBeInTheDocument();
  });
});
