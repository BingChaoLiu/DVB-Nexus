// Call detail (SPEC-405 §4.3/§7.3/§7.4, AC-405-02/03): stderr/stdout verbatim
// (zero transformation — GBK display text with CJK and U+FFFD survives the
// render path untouched), the standing content-gate annotation beside the raw
// exit code (exit 0 ≠ valid report), null vs empty text distinguished.
// Shape/contract assertions — never DOM snapshots (tests/README §6).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TSDuckCallDetail } from "./TSDuckCallDetail";
import { GBK_STDERR_FIXTURE, fullCall, nullPathCall, taggedCall } from "./fixtures";

describe("TSDuckCallDetail — GBK verbatim discipline (AC-405-02)", () => {
  it("renders stderr_text byte-for-byte: CJK and U+FFFD survive with zero transformation", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", fullCall)} />);
    expect(screen.getByText(GBK_STDERR_FIXTURE)).toBeInTheDocument();
  });

  it("renders stdout_text verbatim in a monospace block", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", fullCall)} />);
    const block = screen.getByText("analysis report lines...");
    expect(block.tagName).toBe("PRE");
  });

  it("renders argv elements verbatim (no shell join)", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", fullCall)} />);
    expect(screen.getByText("--preserve-package-names")).toBeInTheDocument();
    expect(screen.getByText("input.ts")).toBeInTheDocument();
  });

  it("distinguishes null fields from empty strings (null = explicit absence)", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", nullPathCall)} />);
    // null stderr/stdout render the explicit absence marker, not an empty block
    expect(screen.getAllByText("null（失败路径字段显式缺省）").length).toBeGreaterThanOrEqual(2);
  });
});

describe("TSDuckCallDetail — exit 0 ≠ valid annotation (AC-405-03, #3/#13)", () => {
  it("shows the standing content-gate annotation beside the raw exit code for exit 0", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", fullCall)} />);
    expect(screen.getByText("exit_code")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(
      screen.getByText(/退出码 0 不代表报告有效/),
    ).toBeInTheDocument();
    expect(screen.getByText(/ts\.bytes > 0 && ts\.services\.total >= 1/)).toBeInTheDocument();
    // validity pointer: evidence lives in AnalysisReport / verify, never this page
    expect(screen.getByText(/本页不作有效性判定/)).toBeInTheDocument();
  });

  it("annotation is present (not conditionally hidden) for null exit codes too", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", nullPathCall)} />);
    expect(screen.getByText(/退出码 0 不代表报告有效/)).toBeInTheDocument();
    expect(screen.getByText(/进程未退到可回收码/)).toBeInTheDocument();
  });

  it("never decorates the exit code with success/failure labels (禁单一对号/叉号)", () => {
    render(<TSDuckCallDetail row={taggedCall("tsduck", fullCall)} />);
    expect(screen.queryByText("成功")).not.toBeInTheDocument();
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
    expect(screen.queryByText("✓")).not.toBeInTheDocument();
    expect(screen.queryByText("✗")).not.toBeInTheDocument();
  });
});
