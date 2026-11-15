// NodePalette seam tests (SPEC-401 REQ-UI-401-001): the palette renders the
// registry declaratively — one entry per MVP_NODE_TYPES, no component-level
// type literals — and the drag payload carries the wire node_type.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MVP_NODE_TYPES } from "./nodeTypes";
import { NodePalette } from "./NodePalette";

describe("NodePalette — declarative registry list (REQ-UI-401-001)", () => {
  it("renders exactly the registry entries with display label and wire node_type", () => {
    render(<NodePalette />);
    for (const spec of MVP_NODE_TYPES) {
      const item = screen.getByRole("button", { name: new RegExp(spec.label) });
      expect(item).toHaveAttribute("data-node-type", spec.node_type);
      expect(item).toHaveAttribute("draggable", "true");
    }
    expect(screen.getAllByRole("button")).toHaveLength(MVP_NODE_TYPES.length);
  });

  it("writes the wire node_type into the drag payload on dragstart", () => {
    render(<NodePalette />);
    const item = screen.getByRole("button", { name: new RegExp("TS 复用器") });
    const setData = vi.fn();
    const dataTransfer = {
      setData,
      effectAllowed: "",
    } as unknown as DataTransfer;
    fireEvent.dragStart(item, { dataTransfer });
    expect(setData).toHaveBeenCalledWith("application/dvb-nexus-node-type", "ts_mux");
  });
});
