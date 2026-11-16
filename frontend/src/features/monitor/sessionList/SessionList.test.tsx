// SessionList component tests (SPEC-408 §4.3 会话列表区, ticket #95). The
// seam is the rendered guide surface: rows keyed by session id (created time
// / lifecycle wire badge verbatim / scenario annotation or 无场景 / track
// action), the failure face (错误态 + 重试, 兜底可用), and the honest empty
// face. API is mocked at the barrel boundary (jsdom has no backend); the
// live list is the E2E suite's job on the real backend.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionListItemDTO } from "../../../api";

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return {
    ...actual,
    listSessions: vi.fn(),
  };
});

import { listSessions } from "../../../api";
import { formatCreatedAt, SessionList } from "./SessionList";

const listSessionsMock = vi.mocked(listSessions);

const ROW_A: SessionListItemDTO = {
  session_id: "0aa0a0a0-0a0a-4a00-8000-00000000a001",
  lifecycle: "running",
  created_at_ms: 1_700_000_000_000,
  scenario_id: "5c010000-0000-4000-8000-000000000001",
  topology_revision: 1,
};
const ROW_B: SessionListItemDTO = {
  session_id: "0bb0b0b0-0b0b-4b00-8000-00000000b002",
  lifecycle: "created",
  created_at_ms: 1_700_008_800_000,
  scenario_id: null,
  topology_revision: 3,
};

function renderList() {
  const onTrack = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SessionList onTrack={onTrack} />
    </QueryClientProvider>,
  );
  return { onTrack };
}

beforeEach(() => {
  listSessionsMock.mockReset();
});

describe("SessionList — the recent-session rows", () => {
  it("renders one row per session: created time, lifecycle wire badge verbatim, scenario annotation or 无场景", async () => {
    listSessionsMock.mockResolvedValue([ROW_A, ROW_B]);
    const { onTrack } = renderList();

    expect(await screen.findByTestId(`monitor-session-row-${ROW_A.session_id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`monitor-session-row-${ROW_B.session_id}`)).toBeInTheDocument();

    // lifecycle: wire string verbatim (SPEC-200 nine-state mirror)
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("created")).toBeInTheDocument();

    // created time: deterministic local-format shape
    expect(screen.getByText(formatCreatedAt(ROW_A.created_at_ms))).toBeInTheDocument();

    // scenario annotation or the explicit 无场景 marker
    expect(screen.getByText("场景: 5c010000-0000-4000-8000-000000000001")).toBeInTheDocument();
    expect(screen.getByText("无场景")).toBeInTheDocument();

    // limit 20 is the entry-list contract (server default; explicit here)
    expect(listSessionsMock).toHaveBeenCalledWith(20);

    // track action routes the row's session id
    await userEvent.click(screen.getByTestId(`monitor-track-${ROW_B.session_id}`));
    expect(onTrack).toHaveBeenCalledExactlyOnceWith(ROW_B.session_id);
  });

  it("asks with the server default face and shows the honest empty list", async () => {
    listSessionsMock.mockResolvedValue([]);
    renderList();
    expect(await screen.findByTestId("session-list-empty")).toBeInTheDocument();
    // 空 ≠ 错误:an empty list is a fact, not a failure.
    expect(screen.getByText(/暂无会话记录/)).toBeInTheDocument();
  });
});

describe("SessionList — failure face (错误态 + 重试, 兜底仍可用)", () => {
  it("renders the explicit error face with retry and the fallback note, then recovers on retry", async () => {
    listSessionsMock.mockRejectedValueOnce(new Error("network down"));
    listSessionsMock.mockResolvedValueOnce([ROW_A]);
    renderList();

    const errorFace = await screen.findByTestId("session-list-error");
    expect(errorFace).toBeInTheDocument();
    expect(errorFace.textContent).toContain("最近会话读取失败");
    // 失败 ≠ 空库:the failure face never masquerades as an empty list.
    expect(screen.queryByTestId("session-list-empty")).not.toBeInTheDocument();
    // The manual-UUID fallback stays usable during the failure.
    expect(errorFace.textContent).toContain("手输 UUID");

    await userEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => {
      expect(screen.getByTestId(`monitor-session-row-${ROW_A.session_id}`)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("session-list-error")).not.toBeInTheDocument();
  });

  it("shows the loading face while the list request is in flight", async () => {
    listSessionsMock.mockReturnValue(new Promise(() => {}));
    renderList();
    expect(screen.getByTestId("session-list-loading")).toBeInTheDocument();
  });
});
