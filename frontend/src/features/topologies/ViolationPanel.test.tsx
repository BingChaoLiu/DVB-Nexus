// ViolationPanel seam tests (SPEC-401 §7.4/§7.5): entries render verbatim
// (code/path/message — snake_case wire discipline), plan-422 entries carry the
// run_prepare source tag, and clicking an entity entry asks for location.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mapPlanErrors, mapViolations } from "./violations";
import { ViolationPanel } from "./ViolationPanel";

const VIOLATIONS = [
  { code: "SIM_TOPO_CARDINALITY", path: "nodes[mux-0].ports[ts_in_1]", message: "port carries 2 connections, above max_connections=1" },
  { code: "SIM_TOPO_CYCLE", path: "topology", message: "cycle through demux-0" },
];

describe("ViolationPanel — verbatim same-channel display", () => {
  it("renders code/path/message of each topology validate entry", () => {
    render(<ViolationPanel entries={mapViolations(VIOLATIONS)} planErrors={[]} validated />);
    expect(screen.getByText("SIM_TOPO_CARDINALITY")).toBeInTheDocument();
    expect(screen.getByText("nodes[mux-0].ports[ts_in_1]")).toBeInTheDocument();
    expect(screen.getByText("port carries 2 connections, above max_connections=1")).toBeInTheDocument();
    expect(screen.getByText("SIM_TOPO_CYCLE")).toBeInTheDocument();
  });

  it("renders run prepare 422 entries with the run_prepare source tag (§7.5 same channel)", () => {
    const planErrors = mapPlanErrors(["fault_plan[0]: bogus_key is not a v1 parameter"], []);
    render(<ViolationPanel entries={[]} planErrors={planErrors} validated />);
    expect(screen.getByText("fault_plan[0]: bogus_key is not a v1 parameter")).toBeInTheDocument();
    expect(screen.getByText("run_prepare")).toBeInTheDocument();
  });

  it("distinguishes the not-yet-validated state from a clean report", () => {
    const { rerender } = render(<ViolationPanel entries={[]} planErrors={[]} validated={false} />);
    expect(screen.getByText("尚未校验")).toBeInTheDocument();
    rerender(<ViolationPanel entries={[]} planErrors={[]} validated />);
    expect(screen.getByText("无违规")).toBeInTheDocument();
    expect(screen.queryByText("尚未校验")).not.toBeInTheDocument();
  });

  it("asks the canvas to locate an entity entry on click", async () => {
    const onLocate = vi.fn();
    render(<ViolationPanel entries={mapViolations(VIOLATIONS)} planErrors={[]} validated onLocate={onLocate} />);
    await userEvent.click(screen.getByText("SIM_TOPO_CARDINALITY"));
    expect(onLocate).toHaveBeenCalledWith(expect.objectContaining({ target: { kind: "port", nodeId: "mux-0", portId: "ts_in_1" } }));
  });
});
