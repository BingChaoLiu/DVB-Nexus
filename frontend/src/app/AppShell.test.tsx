// Shell seam test (REQ-UI-400-001 / AC-400-01, revised by SPEC-408 §4.1):
// the registry drives nav and routing — four route regions (home foyer +
// three MVP regions) navigable, each region's identity renders, and unknown
// paths land on an explicit unknown-region state instead of a redirect.
// Assertions are on wire-agnostic UI structure (labels/regions/testids),
// never on full-DOM snapshots (tests/README §6 discipline).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";
import { appRoutes } from "./routes";
import { createAppRouter } from "./router";
import { GUIDE_URL, JOURNEY_STEPS } from "./journeySteps";

function renderShellAt(path: string) {
  const queryClient = new QueryClient();
  const router = createMemoryRouter(
    [
      {
        element: <AppShell />,
        children: [
          ...appRoutes.map((route) => ({ path: route.path, element: <route.element /> })),
        ],
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

describe("AppShell — registry-driven four-route shell (AC-400-01 + SPEC-408 §4.1)", () => {
  it("renders one nav link per registered route region", () => {
    renderShellAt("/topologies");
    for (const route of appRoutes) {
      // Prefix match: later slices may append a badge inside the link, which
      // extends the accessible name beyond the bare label.
      expect(screen.getByRole("link", { name: new RegExp(`^${route.label}`) })).toBeInTheDocument();
    }
  });

  it("lands on the Topologies region at /topologies", async () => {
    renderShellAt("/topologies");
    // Regions are lazy-loaded (route registry) — resolve the dynamic import.
    expect(await screen.findByRole("heading", { name: "Topologies" })).toBeInTheDocument();
  });

  it("navigates to Monitor and Lab regions", async () => {
    const user = userEvent.setup();
    renderShellAt("/topologies");
    await screen.findByRole("heading", { name: "Topologies" });
    await user.click(screen.getByRole("link", { name: "Monitor" }));
    expect(await screen.findByRole("heading", { name: "Monitor" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /^Lab/ }));
    expect(await screen.findByRole("heading", { name: "Lab" })).toBeInTheDocument();
  });

  it("registry contains exactly the four route regions, home first (SPEC-408 §4.1)", () => {
    expect(appRoutes.map((route) => route.path)).toEqual(["/", "/topologies", "/monitor", "/lab"]);
    expect(appRoutes[0]?.label).toBe("主页");
  });

  it("renders the home foyer at / instead of a redirect (SPEC-408 §4.2)", async () => {
    renderShellAt("/");
    expect(await screen.findByTestId("home-hero-goal")).toHaveTextContent(
      "目标：不看任何文档，30 分钟内独立走通八步闭环，拿到 PASS。",
    );
    expect(screen.getByTestId("home-cta-start")).toHaveAttribute("href", "/lab");
    expect(screen.getByTestId("home-journey-map")).toBeInTheDocument();
    expect(screen.getByTestId("home-card-lab")).toBeInTheDocument();
    expect(screen.getByTestId("home-card-monitor")).toBeInTheDocument();
    expect(screen.getByTestId("home-card-topologies")).toBeInTheDocument();
  });

  it("renders an explicit unknown-region state for unregistered paths, not a redirect", () => {
    window.history.replaceState({}, "", "/no-such-region");
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={createAppRouter()} />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("unknown-region")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回旅程起点（/）" })).toBeInTheDocument();
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
  });
});

describe("AppShell — nav badges + guide link + journey wayfinding bar (SPEC-408 §4.1)", () => {
  it("badges Lab with 主干 and Topologies with 进阶, no badge on home/Monitor", () => {
    renderShellAt("/");
    expect(screen.getByTestId("nav-badge-lab")).toHaveTextContent("主干");
    expect(screen.getByTestId("nav-badge-topologies")).toHaveTextContent("进阶");
    expect(screen.queryByTestId("nav-badge-home")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-badge-monitor")).not.toBeInTheDocument();
  });

  it("keeps the three module nav entries in registry order around the home entry", () => {
    renderShellAt("/");
    const labels = screen.getAllByRole("link", { name: /^(主页|Topologies|Monitor|Lab)/ });
    expect(labels.map((link) => link.textContent)).toEqual([
      "主页",
      "Topologies进阶",
      "Monitor",
      "Lab主干",
    ]);
  });

  it("links the header guide button to the repo docs/user-guide", () => {
    renderShellAt("/");
    const guide = screen.getByTestId("shell-guide-link");
    expect(guide).toHaveTextContent("查看使用指南 ↗");
    expect(guide).toHaveAttribute("href", GUIDE_URL);
    expect(guide).toHaveAttribute("target", "_blank");
  });

  it("renders the journey bar: eight mini nodes + position + disclaimer, verbatim", () => {
    renderShellAt("/");
    expect(screen.getByTestId("journey-bar")).toBeInTheDocument();
    for (const step of JOURNEY_STEPS) {
      expect(screen.getByTestId(`journey-node-${step.key}`)).toHaveTextContent(step.en);
    }
    expect(screen.getByTestId("journey-you-are")).toHaveTextContent("你在：旅程起点");
    expect(screen.getByTestId("journey-disclaimer")).toHaveTextContent(
      "旅程路标条只指示当前位置，不指示完成进度；通关判定只认修复后新 Run 的服务端三态判定。",
    );
  });

  it.each([
    ["/lab?scenario=SC-01&session=abc", "你在：Lab·实验台"],
    ["/lab?scenario=SC-01", "你在：Lab·场景详情"],
    ["/lab", "你在：Lab·场景库"],
    ["/monitor?session=abc", "你在：Monitor·证据台"],
    ["/monitor", "你在：Monitor·证据台"],
    ["/topologies", "你在：Topologies·进阶"],
  ])("derives the position chip from the URL alone: %s → %s", (path, expected) => {
    renderShellAt(path);
    expect(screen.getByTestId("journey-you-are")).toHaveTextContent(expected);
  });

  it("shows 未知页面 on the position chip for unregistered paths (production router)", () => {
    window.history.replaceState({}, "", "/no-such-region");
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={createAppRouter()} />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("journey-you-are")).toHaveTextContent("你在：未知页面");
    expect(screen.getByTestId("unknown-region")).toBeInTheDocument();
  });

  it("updates the position chip when navigation changes the URL", async () => {
    const user = userEvent.setup();
    renderShellAt("/");
    await screen.findByTestId("home-hero-goal");
    await user.click(screen.getByRole("link", { name: /^Lab/ }));
    expect(await screen.findByTestId("journey-you-are")).toHaveTextContent("你在：Lab·场景库");
  });
});
