// Shell seam test (REQ-UI-400-001 / AC-400-01): the registry drives nav and
// routing — three MVP regions navigable, each region's identity renders.
// Assertions are on wire-agnostic UI structure (labels/regions), never on
// full-DOM snapshots (tests/README §6 discipline).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";
import { appRoutes } from "./routes";

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

describe("AppShell — registry-driven three-route shell (AC-400-01)", () => {
  it("renders one nav link per registered route region", () => {
    renderShellAt("/topologies");
    for (const route of appRoutes) {
      expect(screen.getByRole("link", { name: route.label })).toBeInTheDocument();
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
    await user.click(screen.getByRole("link", { name: "Lab" }));
    expect(await screen.findByRole("heading", { name: "Lab" })).toBeInTheDocument();
  });

  it("registry contains exactly the three MVP regions (Topologies/Monitor/Lab)", () => {
    expect(appRoutes.map((route) => route.path)).toEqual(["/topologies", "/monitor", "/lab"]);
  });
});
