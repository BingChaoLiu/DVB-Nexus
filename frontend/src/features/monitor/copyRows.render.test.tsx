// §4.6 Monitor 组「渲染级」补钉(AC-408-09;#101 新增文件,零既有测试改动)。
// 常量级逐字钉扎在 copy.test.ts(独立规格提取物);行 0/1/2/3/4/6/9/10 的
// 渲染断言已分布在 Region.guidance.test.tsx 与各面板组件测试;本文件补齐
// 缺渲染断言的三行——row 5 告警(AlertsPanel)/ row 7 包检查
// (PacketInspectorSection)/ row 8 verify(MonitorRegion 判定空态面)——并附
// VerifyResultCard 判据空诚实面(§4.6 Lab 组行 7 后半,#88 定案维持现状,
// 此前无渲染断言)。期望值一律经 copy.ts 导出取用(其与规格表逐字一致性由
// copy.test.ts 钉扎),本文件钉的是「文案真的渲染到了面板」。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getSnapshot: vi.fn(),
    querySummary: vi.fn(),
    queryAlerts: vi.fn(),
    listDiagnoses: vi.fn(),
    getSessionDetail: vi.fn(),
    getScenario: vi.fn(),
    listSessionRuns: vi.fn(),
    listSessions: vi.fn(),
  };
});

vi.mock("./stream/useSessionStream", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./stream/useSessionStream")>();
  return {
    ...actual,
    useSessionStream: vi.fn(),
  };
});

import {
  getSnapshot,
  getSessionDetail,
  listDiagnoses,
  listSessionRuns,
  queryAlerts,
  querySummary,
} from "../../api";
import { useSessionStream } from "./stream/useSessionStream";
import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";
import { DemoContext, type DemoController } from "./demo/DemoSessionContext";
import { AlertsPanel } from "./alerts/AlertsPanel";
import { PacketInspectorSection } from "./packet-inspector/PacketInspectorSection";
import { VerifyResultCard } from "./verify/VerifyResultCard";
import { MONITOR_EMPTY_STATE_COPY, type ThreeQuestionCopy } from "./copy";
import type { SnapshotDTO, SessionDetailDTO, VerificationResultDTO } from "../../api";

const SESSION = "0bb0b0b0-0b0b-4b00-8000-00000000b001";

/** §4.6 三问句式的渲染级断言(这是什么 · 为什么空 · 下一步:{next})。 */
function expectThreeQuestionsRendered(copy: ThreeQuestionCopy): void {
  expect(screen.getByText(copy.what)).toBeInTheDocument();
  expect(screen.getByText(copy.why)).toBeInTheDocument();
  expect(screen.getByText(`下一步:${copy.next}`)).toBeInTheDocument();
}

describe("§4.6 Monitor 组渲染级补钉(#101)", () => {
  it("row 5 告警:空记录渲染三问逐字(无告警记录 ≠ 干净 承载句在 why 上)", () => {
    render(<AlertsPanel alerts={[]} total={0} />);
    expectThreeQuestionsRendered(MONITOR_EMPTY_STATE_COPY.alerts);
  });

  it("row 7 包检查:未进入下钻(locator null)渲染三问逐字,不渲染面板本体", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <PacketInspectorSection locator={null} onClose={() => {}} />
      </QueryClientProvider>,
    );
    expectThreeQuestionsRendered(MONITOR_EMPTY_STATE_COPY.packetInspector);
    expect(screen.queryByTestId("packet-inspector")).not.toBeInTheDocument();
  });

  it("row 8 verify:无判定结果时 Region 渲染三问逐字", async () => {
    const snapshot: SnapshotDTO = {
      session_id: SESSION,
      revision: 1,
      lifecycle: "running",
      virtual_time_ns: 0,
      topology_revision: 1,
    };
    const detail: SessionDetailDTO = {
      session_id: SESSION,
      revision: 1,
      lifecycle: "running",
      virtual_time_ns: 0,
      topology_revision: 1,
      scenario_id: null,
      created_at_ms: 1_700_000_000_000,
    };
    vi.mocked(getSnapshot).mockResolvedValue(snapshot);
    vi.mocked(querySummary).mockResolvedValue({
      data: { tenant_id: "t", session_id: SESSION, journal_seq_watermark: 0, event_count: 0, active_alert_count: 0, schema_version: "1" },
    } as never);
    vi.mocked(queryAlerts).mockResolvedValue({ data: { items: [], total: 0 } } as never);
    vi.mocked(listDiagnoses).mockResolvedValue([]);
    vi.mocked(getSessionDetail).mockResolvedValue(detail);
    vi.mocked(listSessionRuns).mockResolvedValue([]);

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const demoController: DemoController = { startDemo: () => {}, demoBusy: false };
    const router = createMemoryRouter(
      [
        {
          element: (
            <QueryClientProvider client={queryClient}>
              <DemoContext.Provider value={demoController}>
                <AppShell />
              </DemoContext.Provider>
            </QueryClientProvider>
          ),
          children: [...appRoutes.map((route) => ({ path: route.path, element: <route.element /> }))],
        },
      ],
      { initialEntries: [`/monitor?session=${SESSION}`] },
    );
    render(<RouterProvider router={router} />);

    expect(await screen.findByText(MONITOR_EMPTY_STATE_COPY.verify.what)).toBeInTheDocument();
    expectThreeQuestionsRendered(MONITOR_EMPTY_STATE_COPY.verify);
  });
});

describe("VerifyResultCard 判据空诚实面(§4.6 Lab 组行 7 后半;#88 定案维持现状)", () => {
  it("criteria 为空渲染显式无判据明细面,不伪造判据行", () => {
    const result: VerificationResultDTO = {
      session_id: SESSION,
      recovery_run_id: "rrrrrrrr-0000-4000-8000-000000000001",
      baseline_run_id: "bbbbbbbb-0000-4000-8000-000000000001",
      scenario: {
        scenario_id: "5c010000-0000-4000-8000-000000000001",
        version: "1.0.0",
        content_hash: "aa".repeat(32),
      },
      verdict: "INCONCLUSIVE",
      criteria: [],
      summary: "服务端应答",
      verified_at_utc_ms: 1_700_000_000_000,
    };
    render(<VerifyResultCard result={result} />);
    expect(screen.getByText("无判据明细")).toBeInTheDocument();
    expect(screen.getByText("服务端返回 criteria 为空（原样呈现）。")).toBeInTheDocument();
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useSessionStream).mockReturnValue({ status: "idle", closeCode: null });
});
