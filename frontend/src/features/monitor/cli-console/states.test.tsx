// Non-data states (SPEC-405 §4.2/§7.5, AC-405-05): empty / filtered-empty /
// session-not-found / not-bound / request-failure are mutually distinguishable,
// and every empty copy explicitly refuses the "clean" implication
// (CONTEXT.md: 无告警 ≠ 干净 extends to 空态). Context ban tests included.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CallStates } from "./states";
import { MONITOR_EMPTY_STATE_COPY } from "../copy";

describe("CallStates — honest empty states (AC-405-04/05)", () => {
  it("200 + []: honest empty copy that names the MVP zero-real-calls posture and refuses the clean implication", () => {
    render(<CallStates state={{ kind: "empty" }} />);
    const c = MONITOR_EMPTY_STATE_COPY.cli;
    expect(screen.getByText(c.what)).toBeInTheDocument();
    expect(screen.getByText(c.why)).toBeInTheDocument();
    expect(screen.getByText(`下一步:${c.next}`)).toBeInTheDocument();
  });

  it("filtered-empty (hardware): MVP note present + 无记录 ≠ 干净", () => {
    render(<CallStates state={{ kind: "filtered-empty", selected: "hardware" }} />);
    expect(screen.getAllByText(/hardware/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/MVP 阶段 hardware 来源不产生记录/)).toBeInTheDocument();
    expect(screen.getByText(/无记录 ≠ 干净/)).toBeInTheDocument();
  });

  it("filtered-empty (generator/internal_parser): honest copy without the hardware-specific note", () => {
    render(<CallStates state={{ kind: "filtered-empty", selected: "generator" }} />);
    expect(screen.getByText(/所选来源（generator）在本会话暂无记录/)).toBeInTheDocument();
    expect(screen.getByText(/无记录 ≠ 干净/)).toBeInTheDocument();
    expect(screen.queryByText(/MVP 阶段 hardware 来源不产生记录/)).not.toBeInTheDocument();
  });
});

describe("CallStates — error states (AC-405-05)", () => {
  it("404 SIM_SESSION_NOT_FOUND: distinct session-absence copy with requestId", () => {
    render(
      <CallStates
        state={{ kind: "error", errorCode: "SIM_SESSION_NOT_FOUND", message: "session missing", requestId: "req-9", retryable: false }}
      />,
    );
    expect(screen.getByText(/会话不存在/)).toBeInTheDocument();
    expect(screen.getByText(/SIM_SESSION_NOT_FOUND/)).toBeInTheDocument();
    expect(screen.getByText(/req-9/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument();
  });

  it("501 not-bound: storage-face copy, distinct from empty", () => {
    render(
      <CallStates
        state={{ kind: "error", errorCode: "HTTP_501", message: "not bound", requestId: null, retryable: false, notBound: true }}
      />,
    );
    expect(screen.getByText(/存储面.*未绑定|调用记录存储面在当前组合未绑定/)).toBeInTheDocument();
    expect(screen.queryByText(/暂无 TSDuck 调用记录/)).not.toBeInTheDocument();
  });

  it("retryable failure: error envelope fields verbatim + retry affordance", () => {
    const onRetry = vi.fn();
    render(
      <CallStates
        state={{ kind: "error", errorCode: "HTTP_503", message: "storage unavailable", requestId: "req-3", retryable: true, onRetry }}
      />,
    );
    expect(screen.getByText(/HTTP_503/)).toBeInTheDocument();
    expect(screen.getByText(/storage unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/req-3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  });
});
