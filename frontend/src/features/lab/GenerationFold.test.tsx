// GenerationFold component seam (SPEC-406 §Phase2 只读折叠区): a <details>
// static-wayfinding block inside the console's Inspect section — stage
// progress rows + sampled packet cards + the inspector jump with the view
// parameter. Tests drive the public interface (props in, rendered faces +
// onJump out) through the mocked api seam; no router (navigation is the
// console's wiring, covered in ExperimentConsole.genfold.test.tsx).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    queryEvents: vi.fn(),
    getRun: vi.fn(),
  };
});

import { getRun, queryEvents } from "../../api";
import type { GenRunFace } from "./genEvents";
import { GenerationFold } from "./GenerationFold";

const mocked = { queryEvents: vi.mocked(queryEvents), getRun: vi.mocked(getRun) };

const SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2";

function envelope(eventType: string, payload: Record<string, unknown>, seq: number, runId?: string) {
  return {
    journal_seq: seq,
    event_type: eventType,
    severity: "info",
    payload,
    scope: { session_id: "s-1", run_id: runId ?? null },
  };
}

/** The synthetic layered-run gen.* stream (key sets per #128/#129). */
const LAYERED_STREAM = [
  envelope("gen.stage_started", { layer: "TS" }, 1),
  envelope("gen.packet_sampled", { layer: "TS", packet_index: 0, byte_size: 188, sha256: SHA }, 2, "run-1"),
  envelope("gen.stage_completed", { layer: "TS", item_count: 188 }, 3),
  envelope("gen.stage_started", { layer: "BBFRAME" }, 4),
  envelope("gen.stage_completed", { layer: "BBFRAME", item_count: 12 }, 5),
  envelope("gen.stage_started", { layer: "T2MI" }, 6),
  envelope(
    "gen.packet_sampled",
    { layer: "T2MI", packet_index: 7, byte_size: 194, sha256: SHA.replace("a1b2", "f1e2") },
    8,
    "run-1",
  ),
];

const RUNS: GenRunFace[] = [
  {
    runId: "run-1",
    artifacts: [
      { artifact_id: "art-log-1", kind: "log" },
      { artifact_id: "art-faulted-1", kind: "faulted_ts" },
    ],
  },
];

function renderFold(overrides?: { runs?: GenRunFace[]; active?: boolean }) {
  // retryDelay 0: the component's retry:1 stays, but the retry backoff
  // defaults to a 1s exponential delay — the error-face walk must not race
  // that timer (deterministic, not a timing assertion).
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  const onJump = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <GenerationFold
        sessionId="s-1"
        runs={overrides?.runs ?? RUNS}
        active={overrides?.active ?? false}
        onJump={onJump}
      />
    </QueryClientProvider>,
  );
  return { onJump };
}

async function openFold() {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("lab-gen-summary"));
  return user;
}

beforeEach(() => {
  mocked.queryEvents.mockReset();
});

describe("GenerationFold — the static-wayfinding signpost", () => {
  it("renders the folded summary line (closed by default — no separate page, no animation)", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: [] } } as never);
    renderFold();
    const summary = await screen.findByTestId("lab-gen-summary");
    expect(summary).toHaveTextContent("生成过程");
    expect(summary).toHaveTextContent("分层流水线只读折叠区");
    // Folded by default: the faces only exist once the reader opens it.
    expect(screen.queryByTestId("lab-gen-body")).not.toBeInTheDocument();
    await openFold();
    expect(screen.getByTestId("lab-gen-body")).toBeInTheDocument();
  });

  it("states the honest empty face for zero gen.* events (v1/MVP runs never emit them)", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: [] } } as never);
    renderFold();
    await openFold();
    const empty = await screen.findByTestId("lab-gen-empty");
    expect(empty).toHaveTextContent("尚无分层生成事件");
    // 无记录 ≠ 干净 honesty anchor (SPEC-406 空态纪律).
    expect(empty).toHaveTextContent("无记录 ≠ 干净");
    // The v1 face names the honest scope: only layered runs emit gen.*.
    expect(empty).toHaveTextContent("分层 Run");
  });

  it("renders stage progress rows with verbatim wire layer values and item counts", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: LAYERED_STREAM } } as never);
    renderFold();
    await openFold();
    const stages = await screen.findByTestId("lab-gen-stages");
    // Wire enums verbatim — no aliasing, no case folding.
    expect(screen.getByTestId("lab-gen-stage-TS")).toHaveTextContent("TS");
    expect(screen.getByTestId("lab-gen-stage-TS")).toHaveTextContent("已完成 188 项");
    expect(screen.getByTestId("lab-gen-stage-BBFRAME")).toHaveTextContent("BBFRAME");
    expect(screen.getByTestId("lab-gen-stage-BBFRAME")).toHaveTextContent("已完成 12 项");
    expect(screen.getByTestId("lab-gen-stage-T2MI")).toHaveTextContent("T2MI");
    expect(screen.getByTestId("lab-gen-stage-T2MI")).toHaveTextContent("进行中");
    // Chain order TS → BBFRAME → T2MI.
    const layers = Array.from(stages.querySelectorAll("[data-testid^='lab-gen-stage-']")).map(
      (node) => node.getAttribute("data-testid"),
    );
    expect(layers).toEqual(["lab-gen-stage-TS", "lab-gen-stage-BBFRAME", "lab-gen-stage-T2MI"]);
    void stages;
  });

  it("renders sampled packet cards with layer badge, packet_index, byte_size and the sha256 verbatim", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: LAYERED_STREAM } } as never);
    renderFold();
    await openFold();
    const card = await screen.findByTestId("lab-gen-sample-2");
    expect(card).toHaveTextContent("TS");
    expect(card).toHaveTextContent("packet_index 0");
    expect(card).toHaveTextContent("byte_size 188");
    expect(card).toHaveTextContent(SHA);
    const outer = await screen.findByTestId("lab-gen-sample-8");
    expect(outer).toHaveTextContent("T2MI");
    expect(outer).toHaveTextContent("packet_index 7");
    expect(outer).toHaveTextContent("byte_size 194");
  });

  it("jump click resolves the run's layered transmission artifact and hands the console the view target", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: LAYERED_STREAM } } as never);
    const { onJump } = renderFold();
    await openFold();
    await userEvent.click(await screen.findByTestId("lab-gen-jump-8"));
    await waitFor(() =>
      expect(onJump).toHaveBeenCalledWith({
        artifactId: "art-faulted-1",
        pid: 0,
        packetIndex: 7,
        view: "t2mi",
      }),
    );
  });

  it("renders no jump action when the sample's run is absent everywhere (no fabricated locator)", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: LAYERED_STREAM } } as never);
    mocked.getRun.mockRejectedValue(new Error("404 run unknown"));
    renderFold({ runs: [{ runId: "run-other", artifacts: [] }] });
    await openFold();
    await screen.findByTestId("lab-gen-sample-8");
    expect(screen.queryByTestId("lab-gen-jump-8")).not.toBeInTheDocument();
  });

  it("lazily reads the run face for samples the registry face cannot resolve (refresh/deep-link walks), then the jump appears", async () => {
    mocked.queryEvents.mockResolvedValue({ data: { sort: "journal_asc", items: LAYERED_STREAM } } as never);
    // The registry face carries NO artifacts for run-1 (the §6.3 derived-row
    // posture, review-fix F1) — the fold fills the jump from one read-only
    // getRun (terminal run faces are immutable).
    mocked.getRun.mockResolvedValue({
      run_id: "run-1",
      status: "completed",
      artifacts: [
        { artifact_id: "art-faulted-lazy", kind: "faulted_ts", sha256: "ab", byte_size: 10, partial: false },
      ],
    } as never);
    const { onJump } = renderFold({ runs: [{ runId: "run-1", artifacts: [] }] });
    await openFold();
    const jump = await screen.findByTestId("lab-gen-jump-8", {}, { timeout: 3_000 });
    expect(mocked.getRun).toHaveBeenCalledWith("s-1", "run-1");
    await userEvent.click(jump);
    await waitFor(() =>
      expect(onJump).toHaveBeenCalledWith({
        artifactId: "art-faulted-lazy",
        pid: 0,
        packetIndex: 7,
        view: "t2mi",
      }),
    );
  });

  it("speaks the 失败 ≠ 空库 error face when the gen.* read fails", async () => {
    mocked.queryEvents.mockRejectedValue(new Error("backend refused"));
    renderFold();
    await openFold();
    const error = await screen.findByTestId("lab-gen-error");
    expect(error).toHaveTextContent("失败 ≠ 空库");
    expect(error).toHaveTextContent("backend refused");
  });
});
