// Region ↔ BissAnnotation wiring (#134 seam composition): the Monitor page
// derives the BISS evidence annotation from the journal cache (biss.* WS
// facts) and hands it to the packet inspector's BissAnnotation (#132 prop).
// The api barrel is mocked ONLY at the structure/meta fetches (the #132
// component posture); every other query fails as in Region.test.tsx (no
// server in jsdom). Asserts the two honest faces: a biss.* journal fact
// renders the annotation verbatim; no biss.* fact renders nothing.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    getArtifactStructure: vi.fn(),
    getArtifactMeta: vi.fn(),
    getArtifactContent: vi.fn(),
  };
});

import { getArtifactStructure } from "../../api";
import type { T2miStructureViewDTO } from "../../api";
import { AppShell } from "../../app/AppShell";
import { appRoutes } from "../../app/routes";
import { qk } from "../../query/keys";
import type { JournalEnvelope } from "../../ws/SessionStream";

const mockedStructure = vi.mocked(getArtifactStructure);

const T2MI_WIRE: T2miStructureViewDTO = {
  view: "t2mi",
  packet_count: 1,
  truncated: false,
  trailing_bytes: 0,
  packets: [
    {
      packet_index: 0,
      packet_type: 0x00,
      packet_counter: 0,
      payload_kind: "bbframe",
      payload_bytes_len: 100,
      crc32_valid: true,
      frame_index: 0,
      plp_id: 0,
    },
  ],
};

const BISS_ENVELOPE: JournalEnvelope = {
  journal_seq: 4,
  event_type: "biss.descramble_failed",
  payload: {
    pid_scope: [256],
    failed_indices_sample: [3],
    self_check_kind: "structure_probe",
    key_fingerprint_ref: "sha256:fingerprint-1",
    mode: "E",
  },
};

function renderAt(path: string, seed?: JournalEnvelope[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed !== undefined) {
    queryClient.setQueryData([...qk.events("s-1", "journal")], seed);
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

describe("MonitorRegion — bissEvidence 透传(#134 journal 面 → #132 BissAnnotation)", () => {
  it("renders the BISS annotation from journal facts (mode/fingerprint verbatim)", async () => {
    mockedStructure.mockResolvedValue(T2MI_WIRE);
    renderAt("/monitor?session=s-1&inspect_artifact=art-1&inspect_pid=0&inspect_packet=0&view=t2mi", [
      BISS_ENVELOPE,
    ]);
    expect(await screen.findByTestId("biss-annotation")).toBeInTheDocument();
    expect(screen.getByTestId("biss-mode")).toHaveTextContent("E");
    expect(screen.getByTestId("biss-fingerprint")).toHaveTextContent("sha256:fingerprint-1");
  });

  it("renders no BISS annotation without a biss.* journal fact (honest absence)", async () => {
    mockedStructure.mockResolvedValue(T2MI_WIRE);
    renderAt("/monitor?session=s-1&inspect_artifact=art-1&inspect_pid=0&inspect_packet=0&view=t2mi", [
      { journal_seq: 1, event_type: "ts.generated" },
    ]);
    expect(await screen.findByTestId("t2mi-structure-view")).toBeInTheDocument();
    expect(screen.queryByTestId("biss-annotation")).not.toBeInTheDocument();
  });
});
