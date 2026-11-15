// Call-record list (SPEC-405 §4.2, REQ-UI-405-001 / AC-405-01): the SPEC-308
// §7 nine fields + run_id under their snake_case wire names verbatim (the
// column header IS the contract anchor). Server ASC order (started_at_utc_ms)
// passes through unsorted — no client sort controls. Null paths stay explicit
// ("—" marker): SPEC-308 §7 不伪造纪律. exit_code shows the raw number with no
// success/failure decoration (SPEC-405 §7.4: single checkmark/cross/成功/失败
// labels forbidden, #3/#13). stdout/stderr render presence/length only — full
// text lives in the detail (§4.2). Controlled presentation: data in via
// props, queries live in the composition layer.
import { Badge } from "../../../components/ui";
import type { SourceTaggedCall } from "./sources";

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

const NULL_MARKER = "—";

export function isoUtcMs(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

function textCell(value: string | null | undefined): string {
  if (value === null || value === undefined) return NULL_MARKER;
  return `${value.length} chars`;
}

export function TSDuckCallList({
  rows,
  onSelect,
}: {
  rows: readonly SourceTaggedCall[];
  onSelect?: (row: SourceTaggedCall) => void;
}) {
  return (
    <table className="dvb-cli-table">
      <thead>
        <tr>
          <th>source</th>
          {WIRE_FIELDS.map((field) => (
            <th key={field}>{field}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const call = row.call;
          return (
            <tr key={`${call.started_at_utc_ms}-${call.run_id ?? "norun"}`} className="dvb-cli-row">
              <td>
                <Badge tone="info">{row.source}</Badge>
              </td>
              <td>{call.version ?? NULL_MARKER}</td>
              <td>{call.executable_path ?? NULL_MARKER}</td>
              <td>{call.argv?.length ?? 0}</td>
              <td>
                <button
                  type="button"
                  className="dvb-cli-link"
                  onClick={() => onSelect?.(row)}
                >
                  {isoUtcMs(call.started_at_utc_ms)}
                </button>
              </td>
              <td>{isoUtcMs(call.finished_at_utc_ms)}</td>
              <td>{call.exit_code ?? NULL_MARKER}</td>
              <td>{textCell(call.stdout_text)}</td>
              <td>{textCell(call.stderr_text)}</td>
              <td>{call.input_artifact_sha256 ?? NULL_MARKER}</td>
              <td>{call.run_id ?? NULL_MARKER}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
