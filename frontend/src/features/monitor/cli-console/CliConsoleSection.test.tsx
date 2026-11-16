// CLI console section composition (SPEC-405 §4.1/§4.4): filter + list +
// detail over one session-scoped query; the run_id filter input passes
// through; state matrix maps honestly. Also pins the Region.tsx tab mount
// (R1): default stream tab unchanged, CLI tab swaps the panel stack.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../app/AppShell";
import { appRoutes } from "../../../app/routes";
import { client } from "../../../api";
import { CliConsoleSection } from "./CliConsoleSection";
import { fullCall } from "./fixtures";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return { ...actual, client: { ...actual.client, GET: vi.fn() } };
});

const mockedGet = vi.mocked(client.GET);

function resolveWith(data: unknown, status = 200) {
  mockedGet.mockResolvedValue({
    data,
    response: new Response(
      status === 200 ? null : JSON.stringify(data),
      { status, headers: { "Content-Type": "application/json" } },
    ),
  } as never);
}

beforeEach(() => {
  mockedGet.mockReset();
});

function renderSection(sessionId = "s-1") {
  // retry:false is a TEST determinism option only — production keeps the
  // default query-cache retry posture (SPEC-405 §8).
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CliConsoleSection sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe("CliConsoleSection — data composition", () => {
  it("lists records with the source badge and opens the detail with the gate annotation", async () => {
    resolveWith([
      { ...fullCall },
      { ...fullCall, started_at_utc_ms: 2_000, run_id: "run-2" },
    ]);
    renderSection();
    await screen.findAllByText("3.40"); // a data cell — rows have arrived (both rows)
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2 records
    await userEvent.click(screen.getByRole("button", { name: /1970-01-01T00:00:01\.000Z/ }));
    expect(screen.getByText(/退出码 0 不代表报告有效/)).toBeInTheDocument();
  });

  it("200 + [] with 全部: honest empty state", async () => {
    resolveWith([]);
    renderSection();
    expect(await screen.findByText(/TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）/)).toBeInTheDocument();
  });

  it("filtering four-value selection over live tsduck rows: non-tsduck selection shows the honest filtered-empty (hardware MVP note)", async () => {
    resolveWith([{ ...fullCall }]); // wire payload = raw TSDuckCallDTO
    renderSection();
    await screen.findByText("3.40");
    await userEvent.click(screen.getByRole("button", { name: "hardware" }));
    expect(await screen.findByText(/MVP 阶段 hardware 来源不产生记录/)).toBeInTheDocument();
    expect(screen.queryByRole("row")).not.toBeInTheDocument();
    // back to 全部 restores the records
    await userEvent.click(screen.getByRole("button", { name: "全部" }));
    await screen.findByText("3.40");
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("run_id filter input passes the value into the §4.8 query", async () => {
    resolveWith([]);
    renderSection();
    await screen.findByText(/TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）/);
    await userEvent.type(screen.getByLabelText("run id 过滤"), "run-9");
    // debounce-free: each keystroke re-queries; the LAST call carries the full value
    await vi.waitFor(() => {
      const last = mockedGet.mock.calls.at(-1) as unknown[] | undefined;
      const init = last?.[1] as { params: { query?: { run_id?: string } } } | undefined;
      expect(init?.params.query?.run_id).toBe("run-9");
    });
  });

  it("404 SIM_SESSION_NOT_FOUND renders the session-absence state, not the empty state", async () => {
    resolveWith(
      {
        error: {
          error_code: "SIM_SESSION_NOT_FOUND",
          message: "no rows and empty journal",
          retryable: false,
          details: {},
        },
        request_id: "req-1",
      },
      404,
    );
    renderSection();
    expect(await screen.findByText(/会话不存在/)).toBeInTheDocument();
    expect(screen.queryByText(/TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）/)).not.toBeInTheDocument();
  });
});

describe("Region tab mount (R1) — minimal additive", () => {
  function renderAt(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter(
      [
        {
          element: <AppShell />,
          children: [...appRoutes.map((route) => ({ path: route.path, element: <route.element /> }))],
        },
      ],
      { initialEntries: [path] },
    );
    return render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  }

  it("defaults to the stream tab (all SPEC-403 headings present); the CLI tab swaps to the CLI console", async () => {
    mockedGet.mockResolvedValue({ data: [], response: new Response(null, { status: 200 }) } as never);
    renderAt("/monitor?session=s-1");
    expect(await screen.findByRole("heading", { name: "运行控制" }, { timeout: 3_000 })).toBeInTheDocument();
    // stream panels visible by default
    expect(screen.getByRole("heading", { name: "诊断" })).toBeInTheDocument();
    // CLI tab swaps the stack
    await userEvent.click(screen.getByRole("tab", { name: "CLI 对照" }));
    expect(await screen.findByText(/TSDuck 调用记录与来源区分（来源标识 ≠ 双解析器 diff）/ , {}, { timeout: 3_000 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "运行控制" })).not.toBeInTheDocument();
    // stream tab restores the SPEC-403 panels
    await userEvent.click(screen.getByRole("tab", { name: "Stream Monitor" }));
    expect(await screen.findByRole("heading", { name: "运行控制" }, { timeout: 3_000 })).toBeInTheDocument();
  });
});
