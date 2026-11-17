// SPEC-404 §Phase2 view=bbframe — BBFrameStructureView presentation contract.
// The BBHEADER field rows (MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8) render verbatim
// with their declared units (bits per the #129 wire notes), the UP boundary
// annotation lands (up_count/up_indices), and the SYNCD teaching anchor is
// pinned VERBATIM (SPEC-404 §Phase2 copy discipline — the one sentence the
// tests pin word-for-word).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BBFrameStructureViewDTO } from "../../../api";
import { BBFrameStructureView, SYNCD_TEACHING_ANCHOR } from "./BBFrameStructureView";

const STRUCTURE: BBFrameStructureViewDTO = {
  view: "bbframe",
  frame_count: 2,
  frames: [
    {
      frame_index: 0,
      matype: 0x0000,
      upl: 188 * 8,
      dfl: 0,
      sync: 0x47,
      syncd: 0,
      crc8_valid: true,
      up_count: 3,
      up_indices: [0, 188, 376],
      state: "ok",
    },
    {
      frame_index: 1,
      matype: 0x0100,
      upl: 188 * 8,
      dfl: 42 * 8,
      sync: 0x47,
      syncd: 30,
      crc8_valid: false,
      up_count: 1,
      up_indices: [0],
      state: "crc8_invalid",
    },
  ],
};

describe("BBFrameStructureView — BBHEADER rows (SPEC-404 §Phase2)", () => {
  it("pins the SYNCD teaching anchor VERBATIM", () => {
    render(<BBFrameStructureView structure={STRUCTURE} />);
    // SPEC-404 §Phase2 verbatim sentence — the exact anchor text.
    expect(screen.getByTestId("bbframe-syncd-anchor")).toHaveTextContent(SYNCD_TEACHING_ANCHOR);
    expect(SYNCD_TEACHING_ANCHOR).toBe("SYNCD 是数据字段内首个 UP 的位距离，不是同步字节");
  });

  it("renders the frame rows with the 10-byte field faces verbatim", () => {
    render(<BBFrameStructureView structure={STRUCTURE} />);
    expect(screen.getByTestId("bbframe-summary")).toHaveTextContent("frame_count=2");
    for (const index of [0, 1]) {
      expect(screen.getByTestId(`bbframe-row-${index}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("bbframe-row-0")).toHaveTextContent("matype=0x0000");
    expect(screen.getByTestId("bbframe-row-1")).toHaveTextContent("matype=0x0100");
    // detail rows: units stay as declared (upl/dfl/syncd in bits)
    expect(screen.getByTestId("bbframe-detail-0")).toHaveTextContent("UPL");
    expect(screen.getByTestId("bbframe-detail-0")).toHaveTextContent("bits");
    expect(screen.getByTestId("bbframe-syncd-1")).toHaveTextContent("30");
    expect(screen.getByTestId("bbframe-detail-1")).toHaveTextContent("0x47"); // SYNC verbatim
  });

  it("marks the CRC-8 result explicitly (BAD face stays visible)", () => {
    render(<BBFrameStructureView structure={STRUCTURE} />);
    expect(screen.getByTestId("bbframe-crc8-0")).toHaveTextContent("true");
    expect(screen.getByTestId("bbframe-crc8-1")).toHaveTextContent("false");
    expect(screen.getByTestId("bbframe-row-1")).toHaveTextContent("crc8=BAD");
    expect(screen.getByTestId("bbframe-row-0")).toHaveTextContent("crc8=ok");
    // the wire state string renders verbatim, never rewritten
    expect(screen.getByTestId("bbframe-detail-1")).toHaveTextContent("crc8_invalid");
  });

  it("annotates the UP boundaries (up_count + up_indices byte offsets)", () => {
    render(<BBFrameStructureView structure={STRUCTURE} />);
    expect(screen.getByTestId("bbframe-up-count-0")).toHaveTextContent("3");
    expect(screen.getByTestId("bbframe-up-indices-0")).toHaveTextContent("0,188,376");
    expect(screen.getByTestId("bbframe-up-indices-0")).toHaveTextContent("UP 边界");
  });

  it("renders the honest absent face when the wire omits the frames key", () => {
    const empty: BBFrameStructureViewDTO = { view: "bbframe", frame_count: 0 };
    render(<BBFrameStructureView structure={empty} />);
    expect(screen.getByTestId("bbframe-rows-absent")).toBeInTheDocument();
  });
});
