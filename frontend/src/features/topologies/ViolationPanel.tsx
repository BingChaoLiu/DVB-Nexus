// Violation panel (SPEC-401 §7.4/§7.5): one same-channel display for the two
// error producers — path-addressed topology validate entries (verbatim
// code/path/message) and run prepare 422 error strings (verbatim, tagged
// run_prepare). Entity entries ask the canvas to locate/highlight the target.
// #63/#64 consume this panel + the entry types as the §6.2 shared contract.
import type { ViolationEntry, PlanErrorEntry } from "./violations";

export function ViolationPanel({
  entries,
  planErrors,
  validated,
  onLocate,
}: {
  entries: ViolationEntry[];
  planErrors: PlanErrorEntry[];
  /** false = no server report yet (尚未校验); true = a report is displayed. */
  validated: boolean;
  onLocate?: (entry: ViolationEntry) => void;
}) {
  const empty = entries.length === 0 && planErrors.length === 0;
  return (
    <section className="dvb-topo-violations" aria-label="校验面板">
      <h4 className="dvb-topo-violations-title">校验</h4>
      {empty && !validated && <p className="dvb-topo-violations-empty">尚未校验</p>}
      {empty && validated && <p className="dvb-topo-violations-empty">无违规</p>}
      <ul className="dvb-topo-violations-list">
        {entries.map((entry) => (
          <li key={`${entry.code}:${entry.path}`} className="dvb-topo-violation">
            <button
              type="button"
              className="dvb-topo-violation-code"
              onClick={() => onLocate?.(entry)}
              disabled={entry.target.kind === "graph"}
            >
              {entry.code}
            </button>
            <span className="dvb-topo-violation-path">{entry.path}</span>
            <span className="dvb-topo-violation-message">{entry.message}</span>
          </li>
        ))}
        {planErrors.map((entry) => (
          <li key={entry.message} className="dvb-topo-violation dvb-topo-violation-plan">
            <span className="dvb-topo-violation-source">run_prepare</span>
            {entry.nodeIds.length > 0 && (
              <span className="dvb-topo-violation-nodes">节点: {entry.nodeIds.join(", ")}</span>
            )}
            <span className="dvb-topo-violation-message">{entry.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
