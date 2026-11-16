// Home foyer tests (SPEC-408 §4.2, AC-408-01): the frozen copy renders
// VERBATIM (§4.2 L97-102; expected values below are the spec's own sentences,
// checked against the spec file). Assertions target wire-agnostic UI
// structure (role/label/testid) — never full-DOM snapshots (§11.2 discipline).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import HomePage from "./HomePage";

function renderHome() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HomePage — foyer (SPEC-408 §4.2 / AC-408-01)", () => {
  it("renders the hero goal sentence verbatim", () => {
    renderHome();
    expect(screen.getByTestId("home-hero-goal")).toHaveTextContent(
      "目标：不看任何文档，30 分钟内独立走通八步闭环，拿到 PASS。",
    );
  });

  it("renders the big CTA verbatim, pointing at the Lab library", () => {
    renderHome();
    const cta = screen.getByTestId("home-cta-start");
    expect(cta).toHaveTextContent("从这里开始：选一个场景");
    expect(cta).toHaveAttribute("href", "/lab");
  });

  it("renders the eight-step journey map with index/en/zh/what/where per §1", () => {
    renderHome();
    const map = screen.getByTestId("home-journey-map");
    expect(within(map).getByText("八步闭环旅程地图")).toBeInTheDocument();

    const create = within(screen.getByTestId("home-journey-step-create"));
    expect(create.getByText("Create")).toBeInTheDocument();
    expect(create.getByText("建会话")).toBeInTheDocument();
    expect(create.getByText("选一个场景开局，得到 RUNNING 会话")).toBeInTheDocument();
    expect(create.getByText("发生在哪：Lab·场景详情 → 实验台")).toBeInTheDocument();

    const inspect = within(screen.getByTestId("home-journey-step-inspect"));
    expect(inspect.getByText("检查证据")).toBeInTheDocument();
    expect(inspect.getByText("发生在哪：Monitor/包检查器（Lab 深链进入）")).toBeInTheDocument();
  });

  it("annotates the Analyze row as the declared gap, verbatim", () => {
    renderHome();
    const analyze = within(screen.getByTestId("home-journey-step-analyze"));
    expect(analyze.getByText("分析")).toBeInTheDocument();
    expect(screen.getByTestId("home-journey-step-analyze-gap")).toHaveTextContent(
      "不可用（REST 冻结 501），旅程自动跳过",
    );
  });

  it("renders the three module cards with the §4.2 frozen copy, verbatim", () => {
    renderHome();

    const lab = within(screen.getByTestId("home-card-lab"));
    expect(lab.getByText("Lab（主干）")).toBeInTheDocument();
    expect(lab.getByText("这是主干旅程所在：场景库列出五个场景，实验台走完八步。")).toBeInTheDocument();
    expect(lab.getByText("下一步 = 点击上方 CTA 选一个场景。")).toBeInTheDocument();

    const monitor = within(screen.getByTestId("home-card-monitor"));
    expect(monitor.getByText("Monitor（证据台）")).toBeInTheDocument();
    expect(
      monitor.getByText("这是自由观测台（free observation deck），按 session 展示真实运行证据。"),
    ).toBeInTheDocument();
    expect(monitor.getByText("需先有 session 才有内容：从 Lab 进入，或粘贴 UUID，或一键演示。")).toBeInTheDocument();
    expect(monitor.getByText("下一步按钮 = 「一键演示」（演示门，§4.3）。")).toBeInTheDocument();

    const topologies = within(screen.getByTestId("home-card-topologies"));
    expect(topologies.getByText("Topologies（进阶）")).toBeInTheDocument();
    expect(
      topologies.getByText("这是进阶工具：手工搭建与校验 MPEG-TS 拓扑。主干旅程使用场景自带初始拓扑，不读这里保存的拓扑。"),
    ).toBeInTheDocument();
    expect(topologies.getByText("下一步 = 拿到第一次 PASS 之后再回来探索。")).toBeInTheDocument();
  });

  it("renders the Monitor card demo button as a disabled placeholder (wiring is #99)", () => {
    renderHome();
    const demo = screen.getByTestId("home-monitor-demo-start");
    expect(demo).toBeDisabled();
    expect(demo).toHaveTextContent("一键演示");
  });
});
