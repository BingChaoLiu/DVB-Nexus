// Monitor region composition (SPEC-403 §4.1): section assembly smoke.
// No-session renders the guide state only. A tracked-session render mounts
// every section; queries resolve to error/empty states in jsdom (no server)
// and the WS loop is torn down on unmount. Live composition is covered by
// the E2E suite on the real backend.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";

function renderAt(path: string) {
  const queryClient = new QueryClient();
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

describe("MonitorRegion — composition", () => {
  it("renders the guide state without a tracked session (no sections, no queries)", async () => {
    renderAt("/monitor");
    expect(await screen.findByText(/输入 session id/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "运行控制" })).not.toBeInTheDocument();
  });

  it("mounts every section heading for a tracked session", async () => {
    renderAt("/monitor?session=s-1");
    for (const heading of ["运行控制", "概览", "Run 触发", "PID/指标", "告警", "诊断", "Verify", "journal 尾窗"]) {
      expect(await screen.findByRole("heading", { name: heading }, { timeout: 3_000 })).toBeInTheDocument();
    }
  });

  it("session tracking from the guide navigates to the scoped page", async () => {
    const user = (await import("@testing-library/user-event")).default;
    renderAt("/monitor");
    await user.setup().type(screen.getByLabelText("session id"), "s-9");
    await user.setup().click(screen.getByRole("button", { name: "跟踪" }));
    expect(await screen.findByRole("heading", { name: "运行控制" }, { timeout: 3_000 })).toBeInTheDocument();
    expect(screen.getByText("session: s-9")).toBeInTheDocument();
  });
});
