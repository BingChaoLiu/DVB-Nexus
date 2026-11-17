// Guidance components tests (SPEC-408 §4.5, five faces). Expected strings are
// the spec's 定稿 literals copied byte-exact from §4.5 L134-140 (fullwidth
// punctuation; the two vocabulary-discipline terms 「已保存拓扑」/「场景初始
// 拓扑」 are asserted in their spec surface forms) — never recomputed from the
// components. Assertions pin wire-independent UI structure (role/label/testid)
// and shape, no DOM snapshots (SPEC-408 §11.2).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasEmptyOverlay, ConnectionHint, SaveGateNote, SaveSuccessNote, TopologyGuidanceBanner } from "./guidance";
import { CONNECTION_HINT_VISIBLE_MS } from "./connectionFeedback";
import type { GateReason } from "./inspector/inspectorGate";

function withRouter(ui: React.ReactNode) {
  return <MemoryRouter initialEntries={["/topologies"]}>{ui}</MemoryRouter>;
}

describe("TopologyGuidanceBanner — §4.5 item 1 (页内常驻说明条)", () => {
  it("renders the 定稿 copy verbatim with the 进阶 marker and the two links", () => {
    render(withRouter(<TopologyGuidanceBanner />));
    // vocabulary discipline: 场景初始拓扑 term in its spec surface form, and
    // the 已保存拓扑 side ("这里保存的拓扑") in the same sentence.
    expect(screen.getByText("进阶工具")).toBeInTheDocument();
    expect(screen.getByText("场景自带的初始拓扑")).toBeInTheDocument();
    expect(
      screen.getByText(
        "这里用于手工搭建和校验 MPEG-TS 拓扑（节点 + 连线）。主干旅程（Lab 八步闭环）使用",
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/不会读取这里保存的拓扑/)).toBeInTheDocument();
    expect(screen.getByText(/拿到第一次 PASS 之后再回来探索不迟/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "[去 Lab →]" })).toHaveAttribute("href", "/lab");
    expect(screen.getByRole("link", { name: "[回主页 →]" })).toHaveAttribute("href", "/");
  });
});

describe("CanvasEmptyOverlay — §4.5 item 2 (画布空态三问)", () => {
  it("renders the three questions verbatim with the skip-to-Lab link", () => {
    render(withRouter(<CanvasEmptyOverlay />));
    expect(screen.getByText("这是什么")).toBeInTheDocument();
    expect(screen.getByText("为什么是空的")).toBeInTheDocument();
    expect(screen.getByText("下一步")).toBeInTheDocument();
    expect(screen.getByText(/拓扑画布——搭建 MPEG-TS 链路结构的进阶工具/)).toBeInTheDocument();
    expect(screen.getByText(/你刚新建了草稿（或拓扑库还是空的），画布上还没有节点/)).toBeInTheDocument();
    expect(screen.getByText(/从左侧『节点类型』面板拖一个『TS 生成器』进画布开始搭建/)).toBeInTheDocument();
    expect(screen.getByText(/或在上方『拓扑』下拉打开已有拓扑/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "[去 Lab 开始主干旅程 →]" })).toHaveAttribute("href", "/lab");
  });
});

describe("SaveGateNote — §4.5 item 3 (gate 说明区三态 + 可保存零噪音)", () => {
  const configReason: GateReason = { kind: "config_incomplete", nodeIds: ["gen-0", "gen-1"] };
  const violationReason: GateReason = { kind: "structural_violations" };
  const fieldReason: GateReason = { kind: "field_errors" };

  it("gate state: 暂不能保存：{N} 处待处理 with per-kind lines (N = honest pending count)", () => {
    render(
      <SaveGateNote
        saving={false}
        dirty
        pendingCount={4}
        reasons={[configReason, violationReason]}
      />,
    );
    expect(screen.getByText("暂不能保存：4 处待处理")).toBeInTheDocument();
    expect(screen.getByText("配置待填 → 右侧「节点属性」补全")).toBeInTheDocument();
    expect(screen.getByText("校验违规 → 见下方「校验」面板")).toBeInTheDocument();
    expect(screen.queryByText("表单字段有误")).toBeNull(); // not present → no line (honest)
  });

  it("field_errors line renders for the 口径 A/B channel", () => {
    render(<SaveGateNote saving={false} dirty pendingCount={2} reasons={[fieldReason]} />);
    expect(screen.getByText("暂不能保存：2 处待处理")).toBeInTheDocument();
    expect(screen.getByText("表单字段有误")).toBeInTheDocument();
  });

  it("无修改 state: 没有待保存的修改 — wins over any gate reasons (save is not even offered)", () => {
    render(
      <SaveGateNote saving={false} dirty={false} pendingCount={3} reasons={[configReason]} />,
    );
    expect(screen.getByText("没有待保存的修改")).toBeInTheDocument();
    expect(screen.queryByText(/暂不能保存/)).toBeNull();
  });

  it("saving state: 正在保存…", () => {
    render(<SaveGateNote saving dirty pendingCount={1} reasons={[configReason]} />);
    expect(screen.getByText("正在保存…")).toBeInTheDocument();
    expect(screen.queryByText(/暂不能保存/)).toBeNull();
    expect(screen.queryByText("没有待保存的修改")).toBeNull();
  });

  it("saveable state renders NOTHING (零噪音)", () => {
    const { container } = render(<SaveGateNote saving={false} dirty pendingCount={0} reasons={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ConnectionHint — §4.5 item 4 display (一行原因, 约 4 秒消失)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders the reason inline with a status role, then auto-dismisses at 4 s", () => {
    const { rerender } = render(<ConnectionHint rejection="“ts_out”连接数已满（上限 1）" />);
    const hint = screen.getByRole("status");
    expect(hint).toHaveTextContent("“ts_out”连接数已满（上限 1）");
    act(() => {
      vi.advanceTimersByTime(CONNECTION_HINT_VISIBLE_MS - 1);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByRole("status")).toBeNull();
    rerender(<ConnectionHint rejection={null} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("a NEW rejection restarts the window (key remount at the page seam)", () => {
    const { rerender } = render(<ConnectionHint key="1" rejection="方向不符（需 输出/双向 → 输入/双向）" />);
    act(() => {
      vi.advanceTimersByTime(CONNECTION_HINT_VISIBLE_MS - 500);
    });
    rerender(<ConnectionHint key="2" rejection="平面不符（当前支持 MPEG_TS / T2MI）" />);
    expect(screen.getByRole("status")).toHaveTextContent("平面不符（当前支持 MPEG_TS / T2MI）");
    act(() => {
      vi.advanceTimersByTime(CONNECTION_HINT_VISIBLE_MS - 100);
    });
    expect(screen.getByRole("status")).toBeInTheDocument(); // fresh window, not the old one
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("SaveSuccessNote — §4.5 item 5 (保存成功声明, 每次显示一行)", () => {
  it("renders the 定稿 sentence with the revision number and the two vocabulary terms", () => {
    render(<SaveSuccessNote revision={3} />);
    const note = screen.getByRole("status");
    expect(note).toHaveTextContent("已保存为 revision 3。");
    // 场景初始拓扑 term + 已保存拓扑 side, verbatim from §4.5 L140.
    expect(note).toHaveTextContent("此处保存的拓扑仅供本模块载入与校验；Lab 场景使用场景自带初始拓扑，不会自动使用它。");
  });
});
