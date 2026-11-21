// SimStateEmptyState seam tests (SPEC-404 §Phase3 空态三问, ticket #169): the
// state-domain Run face — SIM_STATE runs produce no TS artifacts, so the
// packet inspector renders the three-question empty state (这是什么 · 为什么空
// ——状态域 Run 不产码流，空 ≠ 干净 · 下一步去哪——按钮跳节点详情面板) instead
// of a fake packet face. The copy lives in THIS folder (packet-inspector/ is
// the #169 monitor-side footprint; copy.ts is the SPEC-408 §4.6 Monitor-row
// authority and is not touched).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { SIM_STATE_EMPTY_COPY, SimStateEmptyState } from "./SimStateEmptyState";

function renderEmpty(sessionId: string) {
  return render(
    <MemoryRouter initialEntries={[`/monitor?session=${sessionId}`]}>
      <SimStateEmptyState sessionId={sessionId} />
    </MemoryRouter>,
  );
}

describe("SimStateEmptyState — SIM_STATE Run 空态三问", () => {
  it("renders the three-question copy with the 状态域 honesty phrase verbatim (空 ≠ 干净)", () => {
    renderEmpty("s-9");
    const empty = screen.getByTestId("dvb-pi-simstate-empty");
    expect(empty).toHaveTextContent(SIM_STATE_EMPTY_COPY.what);
    expect(empty).toHaveTextContent("状态域 Run 不产码流");
    expect(empty).toHaveTextContent("空 ≠ 干净");
    expect(empty).toHaveTextContent("下一步:");
    expect(empty).toHaveTextContent("节点详情面板");
  });

  it("the jump button targets the topology canvas with the tracked session (?session deep link)", () => {
    renderEmpty("s-9");
    const jump = screen.getByTestId("dvb-pi-simstate-jump");
    expect(jump).toHaveTextContent("前往节点详情面板");
    expect(jump).toHaveAttribute("href", "/topologies?session=s-9");
  });
});
