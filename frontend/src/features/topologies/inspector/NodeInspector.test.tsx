// NodeInspector seam tests (SPEC-402 §4.1/§6.2/§11): declarative rendering
// off the descriptor table (component holds zero field literals — guarded in
// fieldInventory.test.ts), FieldError in-place placement, apply → wire
// serialization (TV-402-01 round-trip), rows editing, and the honest empty
// states. The component is a pure draft-composition surface: it never talks
// to the network and never validates (no real-time checking — §2.2).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TopologyFlowNode } from "../graphMapping";
import type { FieldError } from "./locChain";
import { NodeInspector } from "./NodeInspector";

function flowNode(nodeType: string, config: unknown, nodeId = "gen-0"): TopologyFlowNode {
  return {
    id: nodeId,
    type: "topology",
    position: { x: 0, y: 0 },
    data: {
      node: { node_id: nodeId, node_type: nodeType, config: config as Record<string, unknown>, ports: [] },
      violationCodes: [],
      violationPorts: [],
    },
  };
}

/** TV-402-01: examples/ts-generator-minimal.json verbatim. */
const MINIMAL_EXAMPLE = {
  schema_version: 1,
  profile: "analysis_only",
  deterministic: true,
  seed: 20260101,
  initial_media_clock_27mhz: 0,
  target_bitrate_bps: 3008000,
  output_packet_count: 1000,
  program: {
    transport_stream_id: 1,
    program_number: 1,
    pmt_pid: 4096,
    pcr_pid: 256,
    version_number: 0,
    program_descriptors: "",
    streams: [
      {
        pid: 256,
        stream_type: 27,
        stream_id: 224,
        bitrate_bps: 120320,
        payload_profile: "synthetic_test_data",
        payload_seed_offset: 0,
      },
    ],
  },
  pat_period_ms: 101,
  pmt_period_ms: 103,
  pcr_interval_ms: 40,
  pcr_insertion_policy: "payload_packet_first",
};

const TOP_LABELS = [
  "schema_version",
  "profile",
  "deterministic",
  "seed",
  "initial_media_clock_27mhz",
  "target_bitrate_bps",
  "output_packet_count",
  "program（节目）",
  "pat_period_ms",
  "pmt_period_ms",
  "pcr_interval_ms",
  "pcr_insertion_policy",
];

describe("NodeInspector (SPEC-402 §4.1)", () => {
  it("shows the empty state when no node is selected", () => {
    render(<NodeInspector node={null} fieldErrors={[]} onApply={vi.fn()} />);
    expect(screen.getByText("未选中节点")).toBeInTheDocument();
  });

  it("renders every top-level descriptor field of a generator node (declarative, no literals in the component)", () => {
    render(<NodeInspector node={flowNode("ts_generator", MINIMAL_EXAMPLE)} fieldErrors={[]} onApply={vi.fn()} />);
    for (const label of TOP_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // program group children render too (leaf labels are the full wire paths)
    expect(screen.getByText("program.transport_stream_id")).toBeInTheDocument();
    expect(screen.getByText("program.streams")).toBeInTheDocument();
    expect(screen.getByText("program.program_descriptors")).toBeInTheDocument();
  });

  it("prefills wire defaults and pinned initial on an empty config (schema_version=1, 101/103/40, analysis_only)", () => {
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={vi.fn()} />);
    const valueOf = (label: string) =>
      (screen.getByText(label).nextElementSibling as HTMLInputElement | null)?.value ??
      (within(screen.getByText(label).parentElement!).getByRole("combobox") as HTMLSelectElement).value;
    expect(valueOf("schema_version")).toBe("1");
    expect(valueOf("pat_period_ms")).toBe("101");
    expect(valueOf("pmt_period_ms")).toBe("103");
    expect(valueOf("pcr_interval_ms")).toBe("40");
    expect(within(screen.getByText("profile").parentElement!).getByRole("combobox")).toHaveValue("analysis_only");
  });

  it("locks the deterministic checkbox to the contract single value true (SPEC-108 §4)", () => {
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={vi.fn()} />);
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeDisabled();
    expect(checkbox).toBeChecked();
  });

  it("honest state for config_schema=null node types (zero inputs)", () => {
    render(<NodeInspector node={flowNode("ts_mux", {})} fieldErrors={[]} onApply={vi.fn()} />);
    expect(screen.getByText("该类型无配置字段（config 恒 {}）")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("honest state for an unregistered node type (never guesses fields)", () => {
    render(<NodeInspector node={flowNode("tuner_from_legacy_fixture", {})} fieldErrors={[]} onApply={vi.fn()} />);
    expect(screen.getByText("该类型无配置字段（config 恒 {}）")).toBeInTheDocument();
    expect(screen.getByText("未注册类型")).toBeInTheDocument();
  });

  it("round-trips the wire example: loads stored config and re-applies it byte-equal (TV-402-01)", async () => {
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("ts_generator", MINIMAL_EXAMPLE)} fieldErrors={[]} onApply={onApply} />);
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("gen-0", MINIMAL_EXAMPLE);
  });

  it("serializes typed edits: seed entered as text arrives as a number; defaults ride along", async () => {
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={onApply} />);
    await userEvent.type(screen.getByText("seed").nextElementSibling as HTMLInputElement, "20260101");
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    const config = onApply.mock.calls[0]![1] as Record<string, unknown>;
    expect(config.seed).toBe(20260101);
    expect(config.schema_version).toBe(1);
    expect(config.pat_period_ms).toBe(101);
    expect(config.profile).toBe("analysis_only");
    expect((config.program as Record<string, unknown>).streams).toEqual([]);
    // required-but-unfilled fields stay absent (G1 will block the gate)
    expect(config.target_bitrate_bps).toBeUndefined();
  });

  it("edits stream rows: add prefilling wire defaults, fill, apply, and remove", async () => {
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={onApply} />);
    await userEvent.click(screen.getByRole("button", { name: "增行" }));
    await userEvent.type(screen.getByText("program.streams[].pid").nextElementSibling as HTMLInputElement, "256");
    await userEvent.type(screen.getByText("program.streams[].stream_type").nextElementSibling as HTMLInputElement, "27");
    await userEvent.type(screen.getByText("program.streams[].stream_id").nextElementSibling as HTMLInputElement, "224");
    await userEvent.type(screen.getByText("program.streams[].bitrate_bps").nextElementSibling as HTMLInputElement, "120320");
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    let config = onApply.mock.calls[0]![1] as Record<string, unknown>;
    expect((config.program as Record<string, unknown>).streams).toEqual([
      {
        pid: 256,
        stream_type: 27,
        stream_id: 224,
        bitrate_bps: 120320,
        payload_profile: "synthetic_test_data",
        payload_seed_offset: 0,
      },
    ]);
    await userEvent.click(screen.getByRole("button", { name: "删行" }));
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    config = onApply.mock.calls[1]![1] as Record<string, unknown>;
    expect((config.program as Record<string, unknown>).streams).toEqual([]);
  });

  it("places a field-level FieldError under its field and a config-root one as the form banner", () => {
    const fieldErrors: FieldError[] = [
      { nodeId: "gen-0", fieldPath: "target_bitrate_bps", message: "must be in 1000000..100000000 bps" },
      { nodeId: "gen-0", fieldPath: "config", message: "Input should be a valid object" },
    ];
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={fieldErrors} onApply={vi.fn()} />);
    const fieldBox = screen.getByText("target_bitrate_bps").closest(".dvb-inspector-field") as HTMLElement;
    expect(within(fieldBox).getByText("must be in 1000000..100000000 bps")).toBeInTheDocument();
    expect(screen.getByText("Input should be a valid object")).toBeInTheDocument();
  });

  it("places a node-level FieldError (fieldPath null) under the node heading", () => {
    const fieldErrors: FieldError[] = [{ nodeId: "gen-0", fieldPath: null, message: "Bad node" }];
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={fieldErrors} onApply={vi.fn()} />);
    expect(screen.getByText("Bad node")).toBeInTheDocument();
  });

  it("ignores field errors of other nodes", () => {
    const fieldErrors: FieldError[] = [{ nodeId: "gen-1", fieldPath: null, message: "someone else" }];
    render(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={fieldErrors} onApply={vi.fn()} />);
    expect(screen.queryByText("someone else")).not.toBeInTheDocument();
  });

  it("shows the unsaved-divergence hint while the form differs from the applied config, and hides it after apply", async () => {
    const { rerender } = render(
      <NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={vi.fn()} />,
    );
    expect(screen.queryByText("有未应用修改")).not.toBeInTheDocument();
    await userEvent.type(screen.getByText("seed").nextElementSibling as HTMLInputElement, "7");
    expect(screen.getByText("有未应用修改")).toBeInTheDocument();
    const onApply = vi.fn();
    const applySpy = vi.fn((_nodeId: string, config: Record<string, unknown>) => {
      rerender(<NodeInspector node={flowNode("ts_generator", config)} fieldErrors={[]} onApply={applySpy} />);
    });
    rerender(<NodeInspector node={flowNode("ts_generator", {})} fieldErrors={[]} onApply={applySpy} />);
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    // parent now feeds the applied config back via props — hint must clear
    expect(screen.queryByText("有未应用修改")).not.toBeInTheDocument();
    void onApply;
  });
});

// --- Phase 2 (SPEC-401 §Phase2 × SPEC-402 §5.1): the per-schema tables -------

describe("NodeInspector — Phase 2 schemas (T2miEncapsulator/T2miDemux via fieldInventoryFor)", () => {
  it("renders the encapsulator descriptors from its own table (no generator fields leak)", () => {
    render(<NodeInspector node={flowNode("t2mi_encapsulator", {}, "enc-0")} fieldErrors={[]} onApply={vi.fn()} />);
    expect(screen.getByText("plp_assignment（PLP 分配表）")).toBeInTheDocument();
    expect(screen.getByText("bbframe_params（BBFrame 封装参数）")).toBeInTheDocument();
    expect(screen.getByText("plp_assignment.entries")).toBeInTheDocument(); // rows header (row fields appear after 增行)
    expect(screen.getByText("bbframe_params.npd_enabled")).toBeInTheDocument();
    // generator-only fields stay absent — the table selection is by schema name
    expect(screen.queryByText("seed")).not.toBeInTheDocument();
    expect(screen.queryByText("program（节目）")).not.toBeInTheDocument();
  });

  it("applies a filled encapsulator form as the exact #121 wire shape (checkbox → boolean, rows → entries)", async () => {
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("t2mi_encapsulator", {}, "enc-0")} fieldErrors={[]} onApply={onApply} />);
    await userEvent.click(screen.getByRole("button", { name: "增行" }));
    await userEvent.type(screen.getByText("plp_assignment.entries[].plp_id").nextElementSibling as HTMLInputElement, "0");
    await userEvent.type(screen.getByText("plp_assignment.entries[].source_tag").nextElementSibling as HTMLInputElement, "inner");
    await userEvent.type(screen.getByText("bbframe_params.matype_value").nextElementSibling as HTMLInputElement, "0");
    await userEvent.type(screen.getByText("bbframe_params.upl").nextElementSibling as HTMLInputElement, "1504");
    await userEvent.type(screen.getByText("bbframe_params.n_ups").nextElementSibling as HTMLInputElement, "1");
    await userEvent.type(screen.getByText("bbframe_params.issy_mode").nextElementSibling as HTMLInputElement, "simple");
    // npd_enabled: leave the free checkbox untouched → serializes boolean false
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("enc-0", {
      plp_assignment: { entries: [{ plp_id: 0, source_tag: "inner" }] },
      bbframe_params: { matype_value: 0, upl: 1504, n_ups: 1, issy_mode: "simple", npd_enabled: false },
    });
  });

  it("renders the demux descriptors and applies mode/expected_plp with the strict_crc default riding along", async () => {
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("t2mi_demux", {}, "dmx-0")} fieldErrors={[]} onApply={onApply} />);
    expect(screen.getByText("plp_filter（期望 PLP 过滤）")).toBeInTheDocument();
    // plp_filter.mode: the wire Literal enum rendered verbatim
    const modeSelect = within(screen.getByText("plp_filter.mode").parentElement!).getByRole("combobox");
    await userEvent.selectOptions(modeSelect, "expected");
    await userEvent.type(screen.getByText("plp_filter.expected_plp").nextElementSibling as HTMLInputElement, "0");
    // strict_crc: untouched free checkbox prefilled with its wire default true
    expect(screen.getByRole("checkbox")).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("dmx-0", {
      plp_filter: { mode: "expected", expected_plp: 0 },
      strict_crc: true,
    });
  });
});

// --- Phase 3 #169: the #160 config DTO faces through the SAME mechanism -------
//
// The Phase 3 inventories (nodeTypes.ts) introduce two wire shapes the earlier
// inventories never carried: two-level nesting (diseqc_commands.target_register
// — dotted child paths must serialize NESTED, not flat) and OPTIONAL groups
// (lnb.scr / tuner.diseqc_commands — a content-empty optional group serializes
// to ABSENT, never to an empty {} that the backend would reject). The mechanism
// core (kinds set, switch renderer, single rows, G1 semantics) is untouched.
describe("NodeInspector — Phase 3 config serialization (ticket #169)", () => {
  const numberInput = (path: string) =>
    within(screen.getByText(path).parentElement!).getByRole("spinbutton") as HTMLInputElement;
  const selectOf = (path: string) =>
    within(screen.getByText(path).parentElement!).getByRole("combobox") as HTMLSelectElement;
  const checkboxOf = (path: string) =>
    within(screen.getByText(path).parentElement!).getByRole("checkbox") as HTMLInputElement;

  it("lnb apply with scr untouched → lnb_kind + lo_frequencies present, scr ABSENT (optional empty group omitted)", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("lnb", {}, "lnb-0")} fieldErrors={[]} onApply={onApply} />);
    await user.selectOptions(selectOf("lnb_kind"), "universal");
    await user.type(numberInput("lo_frequencies.low_khz"), "9750");
    await user.type(numberInput("lo_frequencies.high_khz"), "10600");
    await user.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("lnb-0", {
      lnb_kind: "universal",
      lo_frequencies: { low_khz: 9750, high_khz: 10600 },
    });
  });

  it("lnb apply with scr filled → nested scr object with protocol + ub_assignments rows (wire keys per UbAssignmentDTO)", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("lnb", {}, "lnb-0")} fieldErrors={[]} onApply={onApply} />);
    await user.selectOptions(selectOf("lnb_kind"), "universal");
    await user.type(numberInput("lo_frequencies.low_khz"), "9750");
    await user.type(numberInput("lo_frequencies.high_khz"), "10600");
    await user.selectOptions(selectOf("scr.protocol"), "EN50494");
    await user.click(screen.getByRole("button", { name: "增行" }));
    await user.type(numberInput("scr.ub_assignments[].ub_slot"), "0");
    await user.type(numberInput("scr.ub_assignments[].ub_center_freq_mhz"), "1210");
    await user.type(screen.getByLabelText("scr.ub_assignments[].tuner_node"), "tuner-a");
    await user.type(screen.getByLabelText("scr.ub_assignments[].position"), "A");
    await user.click(screen.getByRole("button", { name: "应用到草稿" }));
    const config = onApply.mock.calls[0]![1] as Record<string, unknown>;
    expect(config.scr).toEqual({
      protocol: "EN50494",
      ub_assignments: [
        { tuner_node: "tuner-a", ub_slot: 0, ub_center_freq_mhz: 1210, position: "A", ub_bandwidth_mhz: 46 },
      ],
    });
  });

  it("tuner apply with diseqc_commands untouched → tuning_request only; ub_slot/diseqc_commands ABSENT", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("tuner", {}, "tuner-0")} fieldErrors={[]} onApply={onApply} />);
    await user.type(numberInput("tuning_request.frequency_khz"), "11095000");
    await user.selectOptions(selectOf("tuning_request.polarization"), "vertical");
    await user.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("tuner-0", {
      tuning_request: { frequency_khz: 11095000, polarization: "vertical" },
    });
  });

  it("tuner apply with intent → dotted target_register paths serialize NESTED (DiseqcCommandsDTO wire shape)", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("tuner", {}, "tuner-0")} fieldErrors={[]} onApply={onApply} />);
    await user.type(numberInput("tuning_request.frequency_khz"), "11095000");
    await user.selectOptions(selectOf("tuning_request.polarization"), "vertical");
    await user.click(checkboxOf("diseqc_commands.target_register.committed"));
    await user.click(screen.getByRole("button", { name: "增行" }));
    await user.selectOptions(selectOf("diseqc_commands.nibble_writes[].register"), "committed");
    await user.selectOptions(selectOf("diseqc_commands.nibble_writes[].nibble"), "high");
    await user.type(numberInput("diseqc_commands.nibble_writes[].value"), "1");
    await user.click(screen.getByRole("button", { name: "应用到草稿" }));
    const config = onApply.mock.calls[0]![1] as Record<string, unknown>;
    expect(config.diseqc_commands).toEqual({
      target_register: { committed: true, uncommitted: false },
      nibble_writes: [{ register: "committed", nibble: "high", value: 1 }],
    });
  });

  it("switch apply → power_pass verbatim (SwitchConfigDTO single field)", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<NodeInspector node={flowNode("diseqc_switch", {}, "sw-0")} fieldErrors={[]} onApply={onApply} />);
    await user.selectOptions(selectOf("power_pass"), "on");
    await user.click(screen.getByRole("button", { name: "应用到草稿" }));
    expect(onApply).toHaveBeenCalledWith("sw-0", { power_pass: "on" });
  });
});
