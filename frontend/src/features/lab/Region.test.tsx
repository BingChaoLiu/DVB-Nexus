// Lab region composition (SPEC-406 §4.1): view-switch smoke over the URL —
// the library guide, the detail scaffold, the console scaffold. Queries
// resolve to error/empty states in jsdom (no server — the Monitor
// Region.test.tsx posture); live composition is the E2E suite's job on the
// real backend.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
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

describe("LabRegion — composition", () => {
  it("renders the scenario library guide without params", async () => {
    renderAt("/lab");
    expect(await screen.findByRole("heading", { name: "场景库" })).toBeInTheDocument();
    expect(screen.getByText(/注册表暂无场景文档|加载中|读取失败/)).toBeInTheDocument();
  });

  it("renders the detail scaffold for ?scenario= (empty/errored queries in jsdom)", async () => {
    renderAt("/lab?scenario=5c010000-0000-4000-8000-000000000001");
    expect(
      await screen.findByRole("heading", { name: /场景详情 5c010000/ }, { timeout: 3_000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回场景库" })).toBeInTheDocument();
  });

  it("renders the console scaffold for ?scenario=&session= with the eight-step stepper", async () => {
    renderAt("/lab?scenario=5c010000-0000-4000-8000-000000000001&session=s-1");
    expect(await screen.findByTestId("lab-stepper", {}, { timeout: 3_000 })).toBeInTheDocument();
    for (const step of ["create", "generate", "inject", "analyze", "diagnose", "inspect", "recover", "verify"]) {
      expect(screen.getByTestId(`lab-step-${step}`)).toBeInTheDocument();
    }
    // The declared-gap Analyze step renders 不可用 — never a pending progress badge.
    expect(screen.getByTestId("lab-step-analyze")).toHaveTextContent("不可用");
    expect(screen.getByTestId("lab-console-session")).toHaveTextContent("s-1");
    // The solution panel is present and locked by default (no verdict held).
    expect(screen.getByTestId("lab-solution-locked")).toBeInTheDocument();
  });
});
