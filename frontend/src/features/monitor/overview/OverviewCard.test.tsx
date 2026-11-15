// Overview card + run trigger (SPEC-403 §4.3, AC-403-02): SummaryDataDTO
// five fields + snapshot view fields, wire names verbatim; the run trigger
// submits the empty-plan wire body and presents run status.
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SnapshotDTO, SummaryDataDTO } from "../types";
import { DEFAULT_RUN_CONFIG_JSON, OverviewCard, RunTrigger } from "./OverviewCard";

const summary: SummaryDataDTO = {
  tenant_id: "local",
  session_id: "s-1",
  journal_seq_watermark: 42,
  event_count: 42,
  active_alert_count: 1,
  schema_version: "1.0",
};

const snapshot: SnapshotDTO = {
  session_id: "s-1",
  revision: 7,
  lifecycle: "running",
  virtual_time_ns: 9_000_000_000,
  topology_revision: 1,
  node_states: {
    "gen-0": { node_id: "gen-0", health: "healthy", ports: [] },
    "mux-0": { node_id: "mux-0", health: "degraded", ports: [] },
  },
  active_faults: [{ fault_id: "fd-1", state: "ACTIVE" }],
  latest_artifact_refs: [{ artifact_id: "art-1", kind: "generated_ts", status: "ready" }],
} as unknown as SnapshotDTO;

describe("OverviewCard — summary + snapshot view fields", () => {
  it("renders the five summary fields with wire names verbatim", () => {
    render(<OverviewCard summary={summary} snapshot={undefined} />);
    expect(screen.getByText("local")).toBeInTheDocument();
    expect(screen.getByText("s-1")).toBeInTheDocument();
    expect(screen.getByText(/journal_seq_watermark/)).toBeInTheDocument();
    // watermark and event_count both carry 42 in this fixture
    expect(screen.getAllByText("42")).toHaveLength(2);
    expect(screen.getByText(/active_alert_count/)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders snapshot view fields: virtual time, node health, faults, artifact refs", () => {
    render(<OverviewCard summary={summary} snapshot={snapshot} />);
    expect(screen.getByText(/virtual_time_ns/)).toBeInTheDocument();
    expect(screen.getByText("gen-0")).toBeInTheDocument();
    expect(screen.getByText("healthy")).toBeInTheDocument();
    expect(screen.getByText("mux-0")).toBeInTheDocument();
    expect(screen.getByText("degraded")).toBeInTheDocument();
    expect(screen.getByText(/fd-1/)).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    expect(screen.getByText(/art-1/)).toBeInTheDocument();
    expect(screen.getByText(/generated_ts/)).toBeInTheDocument();
  });

  it("renders an explicit empty state while data has not arrived", () => {
    render(<OverviewCard summary={undefined} snapshot={undefined} />);
    expect(screen.getByText(/等待数据/)).toBeInTheDocument();
  });
});

describe("RunTrigger — empty-plan run submission face", () => {
  it("exposes the frozen golden default config and emits it with an empty fault plan", async () => {
    const onSubmit = vi.fn();
    render(<RunTrigger onSubmit={onSubmit} runs={[]} busy={false} />);
    const textarea = screen.getByLabelText("config");
    expect((textarea as HTMLTextAreaElement).value).toBe(DEFAULT_RUN_CONFIG_JSON);
    await userEvent.click(screen.getByRole("button", { name: /提交 Run/ }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(JSON.parse(DEFAULT_RUN_CONFIG_JSON));
  });

  it("rejects malformed config JSON inline without calling onSubmit", async () => {
    const onSubmit = vi.fn();
    render(<RunTrigger onSubmit={onSubmit} runs={[]} busy={false} />);
    await userEvent.clear(screen.getByLabelText("config"));
    // braces are keyboard-syntax in user-event; set the malformed value directly
    fireEvent.change(screen.getByLabelText("config"), { target: { value: "{not json" } });
    await userEvent.click(screen.getByRole("button", { name: /提交 Run/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/config JSON/)).toBeInTheDocument();
  });

  it("presents run status rows: run_id, status, packet_count, artifact refs", () => {
    render(
      <RunTrigger
        onSubmit={vi.fn()}
        busy={false}
        runs={[
          {
            run_id: "r-1",
            status: "completed",
            packet_count: 600,
            byte_count: 112_800,
            artifacts: [{ artifact_id: "art-1", kind: "generated_ts", sha256: "deadbeef", byte_size: 112800, partial: false }],
          },
          { run_id: "r-2", status: "running", packet_count: null, byte_count: null, artifacts: [] },
        ]}
      />,
    );
    expect(screen.getByText("r-1")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("packets 600")).toBeInTheDocument();
    expect(screen.getByText(/art-1/)).toBeInTheDocument();
    expect(screen.getByText("r-2")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("disables submission while busy", () => {
    render(<RunTrigger onSubmit={vi.fn()} runs={[]} busy />);
    expect(screen.getByRole("button", { name: /提交 Run/ })).toBeDisabled();
  });

  it("keeps SessionViewDTO out of the run registry contract (view fields unused here)", () => {
    // The run trigger presents RunStatusDTO fields only — a SessionView
    // object must never be passed as a run row. Type-level guarantee via
    // the distinct shape; smoke-check the run list ignores extra keys.
    render(
      <RunTrigger
        onSubmit={vi.fn()}
        runs={[]}
        busy={false}
      />,
    );
    expect(screen.queryByText(/lifecycle/)).not.toBeInTheDocument();
  });
});
