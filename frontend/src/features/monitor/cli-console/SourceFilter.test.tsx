// Source filter control (SPEC-405 §4.4/§7.2, AC-405-04): the closed-set
// vocabulary rendered as an accessible single-select control; selection
// raises closed-set values verbatim (snake_case wire literals).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CLI_SOURCE_VALUES, type SourceSelection } from "./sources";
import { SourceFilter } from "./SourceFilter";

describe("SourceFilter — closed-set control (AC-405-04)", () => {
  it("renders 全部 plus exactly the four closed-set values", () => {
    render(<SourceFilter selected="all" onSelectChange={() => {}} />);
    expect(screen.getByRole("button", { name: "全部" })).toBeInTheDocument();
    for (const value of CLI_SOURCE_VALUES) {
      expect(screen.getByRole("button", { name: value })).toBeInTheDocument();
    }
  });

  it("marks the active selection via aria-pressed", () => {
    render(<SourceFilter selected="tsduck" onSelectChange={() => {}} />);
    expect(screen.getByRole("button", { name: "tsduck" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "全部" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "hardware" })).toHaveAttribute("aria-pressed", "false");
  });

  it.each<[SourceSelection]>([["all"], ["generator"], ["internal_parser"], ["tsduck"], ["hardware"]])(
    "raises %s verbatim on selection",
    async (value) => {
      const onSelectChange = vi.fn();
      render(<SourceFilter selected="all" onSelectChange={onSelectChange} />);
      await userEvent.click(screen.getByRole("button", { name: value === "all" ? "全部" : value }));
      expect(onSelectChange).toHaveBeenCalledWith(value);
    },
  );
});
