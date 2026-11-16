// Scenario library single-entry + honest empty states (SPEC-408 §4.4
// REQ-UI-408-012 部分 / §4.6 Lab 组行 1-2 / AC-408-07、AC-408-09):
// - the row's ONLY action is 「查看详情」 (the misleading 「开始实验」 button is
//   removed — it never started anything, both row buttons used to share the
//   open-detail handler; SPEC-406 §4.2「列表行不直接开局、开局前必见详情」);
// - the empty-registry copy is the §4.6 verbatim sentence (the stale
//   「Lab Pack v1 落位后…」 phrasing is replaced);
// - the read-failure copy names the request and offers [重试] (失败 ≠ 空库).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScenarioSummaryDTO } from "../../api";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    listScenarios: vi.fn(),
  };
});

import { listScenarios } from "../../api";
import { ScenarioLibrary } from "./ScenarioLibrary";

const mocked = { listScenarios: vi.mocked(listScenarios) };

const ROWS: ScenarioSummaryDTO[] = [
  { scenario_id: "5c010000-0000-4000-8000-000000000001", version: "1.0.0", title: "认识闭环：PAT 缺失", difficulty: "introductory" },
  { scenario_id: "5c040000-0000-4000-8000-000000000004", version: "1.0.0", title: "连续性破坏：CC 相对偏移", difficulty: "introductory" },
];

function renderLibrary() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ScenarioLibrary onOpenDetail={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocked.listScenarios.mockReset();
});

describe("ScenarioLibrary — row 单入口", () => {
  it("each row has exactly ONE action button 「查看详情」 and no 「开始实验」", async () => {
    mocked.listScenarios.mockResolvedValue(ROWS);
    renderLibrary();
    expect(await screen.findByTestId("lab-scenario-5c010000-0000-4000-8000-000000000001")).toBeInTheDocument();
    const detailButtons = screen.getAllByRole("button", { name: "查看详情" });
    expect(detailButtons).toHaveLength(ROWS.length);
    expect(screen.queryByRole("button", { name: "开始实验" })).not.toBeInTheDocument();
  });

  it("the detail button is the row's only click affordance (opens the detail, never starts)", async () => {
    const user = userEvent.setup();
    const onOpenDetail = vi.fn();
    mocked.listScenarios.mockResolvedValue(ROWS);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ScenarioLibrary onOpenDetail={onOpenDetail} />
      </QueryClientProvider>,
    );
    await user.click((await screen.findAllByRole("button", { name: "查看详情" }))[0] ?? document.body);
    expect(onOpenDetail).toHaveBeenCalledTimes(1);
    expect(onOpenDetail).toHaveBeenCalledWith("5c010000-0000-4000-8000-000000000001");
  });
});

describe("ScenarioLibrary — §4.6 Lab 组 verbatim empty states", () => {
  it("empty registry renders the §4.6 row-1 copy verbatim (stale Lab Pack sentence replaced)", async () => {
    mocked.listScenarios.mockResolvedValue([]);
    renderLibrary();
    expect(await screen.findByText("注册表暂无场景文档")).toBeInTheDocument();
    expect(
      screen.getByText("空库 ≠ 错误：服务端场景注册表为空。下一步：`start.cmd` 一键启动后端并完成场景扫描"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Lab Pack v1 落位后/)).not.toBeInTheDocument();
  });

  it("read failure renders the §4.6 row-2 copy verbatim + a [重试] control that refetches", async () => {
    const user = userEvent.setup();
    mocked.listScenarios.mockRejectedValueOnce(new Error("network down"));
    renderLibrary();
    expect(await screen.findByText("场景注册表读取失败")).toBeInTheDocument();
    expect(screen.getByText("失败 ≠ 空库：GET /scenarios 请求失败。下一步：确认后端已运行")).toBeInTheDocument();
    expect(screen.queryByText("注册表暂无场景文档")).not.toBeInTheDocument();

    mocked.listScenarios.mockResolvedValue(ROWS);
    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByTestId("lab-scenario-5c010000-0000-4000-8000-000000000001")).toBeInTheDocument());
  });
});
