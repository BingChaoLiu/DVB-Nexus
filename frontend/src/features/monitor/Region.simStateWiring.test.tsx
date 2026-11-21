// Region ↔ PacketInspectorSection simStateRun wiring (SPEC-404 §Phase3, ticket
// #169 prop + #172 接线): the Monitor page derives the tracked-run fidelity
// face (any tracked run with fidelity SIM_STATE and honestly empty artifacts —
// the #165 trigger condition) and hands { sessionId } to the packet
// inspector, which renders the 空态三问 instead of the generic faces. The api
// barrel is untouched (no artifact fetch on this path); every query fails as
// in Region.test.tsx (no server in jsdom); the run list rides the seeded
// query cache.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { type ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";
import { qk } from "../../query/keys";
import type { RunListItemDTO } from "../../api";

const SIM_STATE_ROW: RunListItemDTO = {
  run_id: "run-state-1",
  status: "completed",
  submitted_at_ms: 1,
  fault_plan_present: true,
  fidelity: "SIM_STATE",
  graph_health: "error",
};

const SIM_TS_ROW: RunListItemDTO = {
  run_id: "run-ts-1",
  status: "completed",
  submitted_at_ms: 1,
  fault_plan_present: false,
  fidelity: "SIM_TS",
  packet_count: 600,
};

function renderAt(path: string, seed?: RunListItemDTO[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed !== undefined) {
    queryClient.setQueryData([...qk.sessionRuns("s-1")], seed);
  }
  const router = createMemoryRouter(
    [
      {
        element: <AppShell />,
        children: [...appRoutes.map((route) => ({ path: route.path, element: <route.element /> }))],
      },
    ],
    { initialEntries: [path] },
  );
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(<RouterProvider router={router} />, { wrapper });
}

describe("MonitorRegion — simStateRun 接线(#169 prop × #172 Region 推导)", () => {
  it("a tracked SIM_STATE run renders the 空态三问 with the jump button", async () => {
    renderAt("/monitor?session=s-1", [SIM_STATE_ROW]);
    expect(
      await screen.findByTestId("dvb-pi-simstate-empty", {}, { timeout: 3_000 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("dvb-pi-simstate-jump")).toHaveAttribute(
      "href",
      "/topologies?session=s-1",
    );
  });

  it("SIM_TS-only runs keep the pre-#169 faces (no sim-state takeover)", async () => {
    renderAt("/monitor?session=s-1", [SIM_TS_ROW]);
    // The generic packet-inspector empty face (locator-null 指路面,
    // MONITOR_EMPTY_STATE_COPY.packetInspector) renders; the SIM_STATE
    // empty state never appears.
    expect(await screen.findByText("尚未从诊断候选点「定位」进入", {}, { timeout: 3_000 })).toBeInTheDocument();
    expect(screen.queryByTestId("dvb-pi-simstate-empty")).not.toBeInTheDocument();
  });

  it("no tracked run rows keep the pre-#169 faces too", async () => {
    renderAt("/monitor?session=s-1", []);
    expect(await screen.findByRole("heading", { name: "诊断" }, { timeout: 3_000 })).toBeInTheDocument();
    expect(screen.queryByTestId("dvb-pi-simstate-empty")).not.toBeInTheDocument();
  });
});
