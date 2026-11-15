// Call-record list (SPEC-405 §4.2, AC-405-01): the nine wire fields + run_id
// rendered under their snake_case names verbatim; server ASC order passes
// through unsorted; null paths stay explicit. Shape assertions only — never
// full-DOM snapshots (tests/README §6).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SourceTaggedCall } from "./sources";
import { TSDuckCallList } from "./TSDuckCallList";
import { fullCall, nullPathCall, taggedCall } from "./fixtures";

const WIRE_FIELDS = [
  "version",
  "executable_path",
  "argv",
  "started_at_utc_ms",
  "finished_at_utc_ms",
  "exit_code",
  "stdout_text",
  "stderr_text",
  "input_artifact_sha256",
  "run_id",
] as const;

describe("TSDuckCallList — nine-field wire contract (AC-405-01)", () => {
  it("renders every wire field name as a column header, snake_case verbatim", () => {
    render(<TSDuckCallList rows={[taggedCall("tsduck", fullCall)]} />);
    for (const field of WIRE_FIELDS) {
      expect(screen.getByText(field), `column header ${field}`).toBeInTheDocument();
    }
  });

  it("renders the record values for the full-field fixture", () => {
    render(<TSDuckCallList rows={[taggedCall("tsduck", fullCall)]} />);
    expect(screen.getByText("3.40")).toBeInTheDocument();
    expect(screen.getByText("C:\\Program Files\\TSDuck\\bin\\tsduck.exe")).toBeInTheDocument();
    // argv: array length in the list column (elements verbatim in the detail)
    expect(screen.getByText("4")).toBeInTheDocument();
    // epoch-ms presented as ISO-8601 UTC
    expect(screen.getByText("1970-01-01T00:00:01.000Z")).toBeInTheDocument();
    expect(screen.getByText("1970-01-01T00:00:02.500Z")).toBeInTheDocument();
    // exit code raw number, no success/failure decoration
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("a3f1...deadbeef")).toBeInTheDocument();
    expect(screen.getByText("run-1")).toBeInTheDocument();
    // stdout/stderr presence markers (full text only in the detail)
    expect(screen.getByText(/stdout_text/)).toBeInTheDocument();
  });

  it("keeps null paths explicit: null exit_code/stderr render as the null marker, not 0/empty", () => {
    render(<TSDuckCallList rows={[taggedCall("tsduck", nullPathCall)]} />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  });

  it("preserves the server ASC order as given (no client re-sort)", () => {
    const later = taggedCall("tsduck", { ...fullCall, started_at_utc_ms: 900 });
    const earlier = taggedCall("tsduck", { ...nullPathCall });
    const { container } = render(<TSDuckCallList rows={[later, earlier]} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("1970-01-01T00:00:00.900Z");
    expect(rows[1]?.textContent).toContain("1970-01-01T00:00:03.000Z");
  });

  it("shows the source badge with the wire literal on each row", () => {
    render(<TSDuckCallList rows={[taggedCall("tsduck", fullCall)]} />);
    expect(screen.getByText("tsduck")).toBeInTheDocument();
  });

  it("raises the selected record verbatim on row activation", async () => {
    const onSelect = vi.fn();
    render(<TSDuckCallList rows={[taggedCall("tsduck", fullCall)]} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: /1970-01-01T00:00:01\.000Z/ }));
    const arg = onSelect.mock.calls[0]?.[0] as SourceTaggedCall | undefined;
    expect(arg?.call.started_at_utc_ms).toBe(1_000);
    expect(arg?.call.argv).toEqual(fullCall.argv);
    expect(arg?.source).toBe("tsduck");
  });
});
