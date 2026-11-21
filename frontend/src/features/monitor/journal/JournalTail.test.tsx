// Journal tail (SPEC-403 §4.8, REQ-UI-403-007 presentation face): reads the
// canonical journal cache (qk.events(sessionId,'journal')) — the throttle
// refetch surface — NOT a frame-driven DOM stream. Renders the most recent N
// envelopes with wire fields. Phase 2 assertions (#134): the nine registered
// t2mi.*/bbframe.*/biss.*/gen.* types render their payload registry-driven
// (eventRender table), wire enums verbatim, discipline sentences via copy.ts.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JournalEnvelope } from "../../../ws/SessionStream";
import { qk } from "../../../query/keys";
import { JOURNAL_TAIL_N, JournalTail } from "./JournalTail";
import { EVENT_HONESTY_COPY, MONITOR_EMPTY_STATE_COPY } from "../copy";

const envelope = (seq: number): JournalEnvelope => ({
  schema_version: "1.0",
  event_id: `e-${seq}`,
  event_type: "ts.generated",
  journal_seq: seq,
  severity: "info",
  producer: { producer_id: "gen-0", producer_version: "1", instance_id: "i-1" },
});

const phase2Envelope = (seq: number, eventType: string, payload: Record<string, unknown>): JournalEnvelope => ({
  ...envelope(seq),
  event_id: `e2-${seq}`,
  event_type: eventType,
  payload,
});

function renderTail(seed: JournalEnvelope[]) {
  const queryClient = new QueryClient();
  queryClient.setQueryData([...qk.events("s-1", "journal")], seed);
  return render(
    <QueryClientProvider client={queryClient}>
      <JournalTail sessionId="s-1" />
    </QueryClientProvider>,
  );
}

describe("JournalTail — cache-driven tail window", () => {
  it("renders wire fields per envelope (seq/event_type/severity/producer)", () => {
    renderTail([envelope(1), envelope(2)]);
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("ts.generated")).toHaveLength(2);
    expect(screen.getAllByText("info")).toHaveLength(2);
    expect(screen.getAllByText("gen-0")).toHaveLength(2);
  });

  it("caps at the most recent JOURNAL_TAIL_N entries (newest first)", () => {
    const seed = Array.from({ length: JOURNAL_TAIL_N + 10 }, (_, i) => envelope(i + 1));
    renderTail(seed);
    const rows = screen.getAllByTestId(/^journal-row-/);
    expect(rows).toHaveLength(JOURNAL_TAIL_N);
    // newest first: the highest seq at the top, and the oldest shown is
    // seq = total - N + 1
    expect(rows[0]).toHaveAttribute("data-testid", `journal-row-${JOURNAL_TAIL_N + 10}`);
    expect(rows.at(-1)).toHaveAttribute("data-testid", `journal-row-11`);
  });

  it("renders an explicit empty state before any journal frame arrives", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <JournalTail sessionId="s-1" />
      </QueryClientProvider>,
    );
    const c = MONITOR_EMPTY_STATE_COPY.journal;
    expect(screen.getByText(c.what)).toBeInTheDocument();
    expect(screen.getByText(c.why)).toBeInTheDocument();
    expect(screen.getByText(`下一步:${c.next}`)).toBeInTheDocument();
  });
});

describe("JournalTail — Phase 2 事件注册表驱动渲染(#134,SPEC-403 §Phase2)", () => {
  it("renders t2mi.plp_mismatch payload keys verbatim with the 缺失 ≠ 零 discipline sentence", () => {
    renderTail([
      phase2Envelope(7, "t2mi.plp_mismatch", {
        expected_plp: 0,
        actual_plp: 1,
        business_absent_evidence: {
          plps_seen: [1],
          bbframe_packet_count: 12,
          filtered_packet_count: 0,
          total_packet_count: 12,
        },
      }),
    ]);
    const block = screen.getByTestId("journal-payload-7");
    expect(block).toBeInTheDocument();
    // wire key names verbatim (the #129 key set), values verbatim.
    expect(screen.getByTestId("journal-payload-7-expected_plp")).toHaveTextContent("expected_plp");
    expect(screen.getByTestId("journal-payload-7-expected_plp")).toHaveTextContent("0");
    expect(screen.getByTestId("journal-payload-7-actual_plp")).toHaveTextContent("1");
    expect(screen.getByTestId("journal-payload-7-business_absent_evidence")).toHaveTextContent("plps_seen");
    // the honesty discipline sentence rides the event copy (copy.ts carrier).
    expect(screen.getByTestId("journal-discipline-7")).toHaveTextContent(
      EVENT_HONESTY_COPY["t2mi.plp_mismatch"]!,
    );
    expect(screen.getByTestId("journal-discipline-7")).toHaveTextContent("缺失 ≠ 零");
  });

  it("renders honest null as null (缺失 ≠ 零: actual_plp null is never a 0)", () => {
    renderTail([
      phase2Envelope(8, "t2mi.plp_mismatch", {
        expected_plp: 0,
        actual_plp: null,
        business_absent_evidence: {
          plps_seen: [],
          bbframe_packet_count: 4,
          filtered_packet_count: 0,
          total_packet_count: 4,
        },
      }),
    ]);
    const cell = screen.getByTestId("journal-payload-8-actual_plp");
    expect(cell).toHaveTextContent("null");
    expect(cell).not.toHaveTextContent(/null0|0null/);
  });

  it("renders biss.descramble_failed with the 解扰失败 ≠ 码流损坏 sentence and fingerprint reference verbatim", () => {
    renderTail([
      phase2Envelope(9, "biss.descramble_failed", {
        pid_scope: [256, 257],
        failed_indices_sample: [3, 17],
        self_check_kind: "structure_probe",
        key_fingerprint_ref: "sha256:abc123",
        mode: "E",
      }),
    ]);
    expect(screen.getByTestId("journal-payload-9-self_check_kind")).toHaveTextContent("structure_probe");
    expect(screen.getByTestId("journal-payload-9-key_fingerprint_ref")).toHaveTextContent("sha256:abc123");
    expect(screen.getByTestId("journal-payload-9-mode")).toHaveTextContent("E");
    expect(screen.getByTestId("journal-payload-9-failed_indices_sample")).toHaveTextContent("3, 17");
    // 密钥本体零渲染:仅指纹引用出现。
    expect(screen.getByTestId("journal-discipline-9")).toHaveTextContent("解扰失败 ≠ 码流损坏");
  });

  it("renders gen.packet_sampled sampling facts (layer enum verbatim + sha256 digest)", () => {
    renderTail([
      phase2Envelope(10, "gen.packet_sampled", {
        layer: "BBFRAME",
        packet_index: 3,
        byte_size: 190,
        sha256: "a".repeat(64),
      }),
    ]);
    expect(screen.getByTestId("journal-payload-10-layer")).toHaveTextContent("BBFRAME");
    expect(screen.getByTestId("journal-payload-10-packet_index")).toHaveTextContent("3");
    expect(screen.getByTestId("journal-payload-10-byte_size")).toHaveTextContent("190");
    expect(screen.getByTestId("journal-payload-10-sha256")).toHaveTextContent("a".repeat(64));
    // 构造事件无规格锚定的纪律句 — 零渲染副作用。
    expect(screen.queryByTestId("journal-discipline-10")).not.toBeInTheDocument();
  });

  it("renders t2mi.stage_summary distributions with wire enum keys verbatim (bbframe/padding)", () => {
    renderTail([
      phase2Envelope(11, "t2mi.stage_summary", {
        packet_count: 42,
        padding_count: 5,
        packet_type_distribution: { bbframe: 37, padding: 5 },
        plp_distribution: { "0": 37 },
      }),
    ]);
    const dist = screen.getByTestId("journal-payload-11-packet_type_distribution");
    expect(dist).toHaveTextContent("bbframe");
    expect(dist).toHaveTextContent("padding");
    expect(dist).toHaveTextContent("37");
  });

  it("renders the gen.stage_completed derivation face on biss.scramble_applied only when present", () => {
    renderTail([
      phase2Envelope(12, "biss.scramble_applied", {
        pid_scope: [100],
        packet_count: 500,
        key_fingerprint: "sha256:deadbeef",
        mutation_log_ref: "ml-1",
        mode: "1",
      }),
      phase2Envelope(13, "biss.scramble_applied", {
        pid_scope: [100],
        packet_count: 500,
        key_fingerprint: "sha256:deadbeef",
        mutation_log_ref: "ml-2",
        mode: "E",
        derivation_ref: { session_word: "sha256:cafe" },
        mismatch_variants: ["wrong_esw"],
      }),
    ]);
    // mode "1" row: no derivation keys render (absent optional face).
    expect(screen.queryByTestId("journal-payload-12-derivation_ref")).not.toBeInTheDocument();
    // mode "E" row: derivation face renders verbatim.
    expect(screen.getByTestId("journal-payload-13-derivation_ref")).toHaveTextContent("session_word");
    expect(screen.getByTestId("journal-payload-13-mismatch_variants")).toHaveTextContent("wrong_esw");
  });

  it("keeps MVP envelopes on the generic wire face with no payload block (v1 zero regression)", () => {
    renderTail([envelope(1)]);
    expect(screen.getByText("ts.generated")).toBeInTheDocument();
    expect(screen.queryByTestId("journal-payload-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-discipline-1")).not.toBeInTheDocument();
  });

  // --- #170: rf./sec. state_observed 走同一注册表渲染面(零特制) -------------
  it("renders rf.state_observed registry-driven with the honesty axes verbatim (state_evaluator + simulated 不混标)", () => {
    renderTail([
      phase2Envelope(20, "rf.state_observed", {
        node_id: "tuner-b",
        health: "error",
        causes: [{ node_id: "lnb-0" }],
        source: "state_evaluator",
        confidence: "simulated",
        lock_state: "unlocked",
        if_frequency_khz: 11234500,
        ber_state: "severe",
        locked_transponder_id: null,
        stale: true,
      }),
    ]);
    const row = screen.getByTestId("journal-row-20");
    expect(row).toHaveClass("dvb-mon-journal-row-phase2");
    // wire keys/values verbatim — lock_state/ber_state enum strings unchanged.
    expect(screen.getByTestId("journal-payload-20-lock_state")).toHaveTextContent("unlocked");
    expect(screen.getByTestId("journal-payload-20-ber_state")).toHaveTextContent("severe");
    expect(screen.getByTestId("journal-payload-20-source")).toHaveTextContent("state_evaluator");
    expect(screen.getByTestId("journal-payload-20-confidence")).toHaveTextContent("simulated");
    expect(screen.getByTestId("journal-payload-20-stale")).toHaveTextContent("true");
    // unlocked → locked_transponder_id honestly null (缺失 ≠ 零).
    expect(screen.getByTestId("journal-payload-20-locked_transponder_id")).toHaveTextContent("null");
    // CauseRef list renders as the wire array shape.
    expect(screen.getByTestId("journal-payload-20-causes")).toHaveTextContent("node_id=lnb-0");
    // 无规格锚定纪律句 — 零渲染副作用 (诚实禁令: 规格外不落句).
    expect(screen.queryByTestId("journal-discipline-20")).not.toBeInTheDocument();
  });

  it("renders sec.state_observed (lnb snapshot) with unpowered nulls verbatim", () => {
    renderTail([
      phase2Envelope(21, "sec.state_observed", {
        node_id: "lnb-0",
        health: "ok",
        causes: [],
        source: "state_evaluator",
        confidence: "simulated",
        voltage: "off",
        tone_commanded: "none",
        tone_actual: "none",
        tone_composite: "none",
        band_selected: "none",
        lo_frequency_khz: null,
        polarization_delivered: "none",
        short_circuit_state: "normal",
        ub_assignments: [],
      }),
    ]);
    const row = screen.getByTestId("journal-row-21");
    expect(row).toHaveClass("dvb-mon-journal-row-phase2");
    expect(screen.getByTestId("journal-payload-21-voltage")).toHaveTextContent("off");
    expect(screen.getByTestId("journal-payload-21-band_selected")).toHaveTextContent("none");
    // 未供电 lo_frequency_khz = null — never coerced to 0.
    expect(screen.getByTestId("journal-payload-21-lo_frequency_khz")).toHaveTextContent("null");
    expect(screen.getByTestId("journal-payload-21-source")).toHaveTextContent("state_evaluator");
    expect(screen.queryByTestId("journal-discipline-21")).not.toBeInTheDocument();
  });
});
