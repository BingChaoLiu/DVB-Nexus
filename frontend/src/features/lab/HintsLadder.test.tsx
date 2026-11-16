// HintsLadder (SPEC-406 §4.4, REQ-UI-406-004 / AC-406-04): the progressive
// reveal ladder is PURE frontend — array order is the reveal order, `level`
// renders verbatim as a badge (never a sort key), and a reveal click issues
// ZERO network requests (the fetch seam is spied to pin that).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { HintsLadder, type LabHintWire } from "./HintsLadder";

const hints: LabHintWire[] = [
  {
    hint_id: "h-1",
    trigger: "experiment opened",
    level: "nudge",
    content: "第一层提示内容",
    requirement_ids: ["REQ-SIM-204-001"],
    standard_ref: null,
  },
  {
    hint_id: "h-2",
    trigger: "after Inject",
    level: "direction",
    content: "第二层提示内容",
    requirement_ids: [],
    standard_ref: null,
  },
  {
    hint_id: "h-3",
    trigger: "before Verify",
    level: "walkthrough",
    content: "第三层提示内容",
    requirement_ids: ["REQ-SIM-204-003"],
    standard_ref: "ETS 300 468" // non-null renders verbatim; Lab Pack ships null
  },
];

const fetchSpy = vi.fn();
vi.stubGlobal("fetch", fetchSpy);

afterEach(() => fetchSpy.mockClear());

describe("HintsLadder — progressive reveal (pure frontend, zero network)", () => {
  it("initially reveals none; locked cards show the reveal count, not content", () => {
    render(<HintsLadder hints={hints} revealedCount={0} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByTestId("lab-hints-remaining")).toHaveTextContent("3");
    expect(screen.queryByText("第一层提示内容")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /揭示下一条提示/ })).toBeEnabled();
  });

  it("click reveals the NEXT hint in document array order (one per click)", async () => {
    const onRevealNext = vi.fn();
    const user = userEvent.setup();
    render(<HintsLadder hints={hints} revealedCount={1} onRevealNext={onRevealNext} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByText("第一层提示内容")).toBeInTheDocument();
    expect(screen.queryByText("第二层提示内容")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /揭示下一条提示/ }));
    expect(onRevealNext).toHaveBeenCalledTimes(1);
    // Zero network: the reveal never touches the api seam.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("revealed card renders level badge, trigger, requirement chips and standard_ref verbatim", () => {
    render(<HintsLadder hints={hints} revealedCount={3} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByText("第三层提示内容")).toBeInTheDocument();
    expect(screen.getByText("walkthrough")).toBeInTheDocument();
    expect(screen.getByText("before Verify")).toBeInTheDocument();
    expect(screen.getByText("REQ-SIM-204-003")).toBeInTheDocument();
    expect(screen.getByText("ETS 300 468", { exact: false })).toBeInTheDocument();
  });

  it("null standard_ref renders the explicit 无 marker (not silence)", () => {
    render(<HintsLadder hints={hints} revealedCount={1} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    const refValue = screen.getByText("standard_ref:", { exact: false }).querySelector(".dvb-lab-hint-ref-value");
    expect(refValue).toHaveTextContent("无");
  });

  it("fully revealed ladder disables the button with the honest note", () => {
    render(<HintsLadder hints={hints} revealedCount={3} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    const button = screen.getByRole("button", { name: /本场景提示已全部揭示/ });
    expect(button).toBeDisabled();
  });

  it("empty hints render the honest empty note and no button", () => {
    render(<HintsLadder hints={[]} revealedCount={0} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByText("本场景未声明提示")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("HintsLadder — persistence disclosure + reset (SPEC-408 §4.4 REQ-UI-408-011)", () => {
  it("renders the verbatim 已揭示 N/M（本地记录，非服务端事实） disclosure line", () => {
    render(<HintsLadder hints={hints} revealedCount={1} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 1/3（本地记录，非服务端事实）");
  });

  it("reset control emits onResetHints (重置提示 — 重做场景可清空)", async () => {
    const onResetHints = vi.fn();
    const user = userEvent.setup();
    render(<HintsLadder hints={hints} revealedCount={2} onRevealNext={() => {}} onResetHints={onResetHints} storageAvailable />);
    await user.click(screen.getByTestId("lab-hints-reset"));
    expect(onResetHints).toHaveBeenCalledTimes(1);
    // The reset click never touches the api seam either.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("storage unavailable: 已揭示 N/M stays, but the 本地记录 claim is replaced by the honest degradation note", () => {
    render(
      <HintsLadder hints={hints} revealedCount={1} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable={false} />,
    );
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 1/3");
    expect(screen.getByTestId("lab-hints-status")).not.toHaveTextContent("本地记录，非服务端事实");
    expect(screen.getByTestId("lab-hints-storage-unavailable")).toHaveTextContent("本地记录不可用，刷新将复位");
  });

  it("over-large stored count clamps the displayed N to M (revealed ≤ declared)", () => {
    render(<HintsLadder hints={hints} revealedCount={9} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByTestId("lab-hints-status")).toHaveTextContent("已揭示 3/3");
  });

  it("empty hints keep the untouched empty note (no disclosure line, no reset)", () => {
    render(<HintsLadder hints={[]} revealedCount={0} onRevealNext={() => {}} onResetHints={() => {}} storageAvailable />);
    expect(screen.getByText("本场景未声明提示")).toBeInTheDocument();
    expect(screen.queryByTestId("lab-hints-status")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lab-hints-reset")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lab-hints-storage-unavailable")).not.toBeInTheDocument();
  });
});
