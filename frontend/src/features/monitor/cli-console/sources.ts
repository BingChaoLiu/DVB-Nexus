// Source vocabulary for the CLI console (SPEC-405 §4.4/§7.1, REQ-UI-405-003).
//
// The four-value closed set is the CLI face of ObservationSource
// (src/domain/observation/model.py: generator/internal_parser/tsduck/hardware;
// the fifth value rule_engine never gets a badge). Source identity is a
// property of the DATA CHANNEL, not a DTO field: MVP's single record channel
// is the SPEC-500 §4.8 tsduck/calls route, so every row it returns is tagged
// at the data-face boundary (tsduckCalls.ts) — components never infer a
// source from record content. The vocabulary is frozen now so future
// channels only extend the data face, never the filter.
import type { components } from "../../../api";

export type TSDuckCallDTO = components["schemas"]["TSDuckCallDTO"];

export const CLI_SOURCE_VALUES = [
  "generator",
  "internal_parser",
  "tsduck",
  "hardware",
] as const;

export type CliSourceValue = (typeof CLI_SOURCE_VALUES)[number];

/** Filter selection: a closed-set value or the unfiltered view. */
export type SourceSelection = CliSourceValue | "all";

export const CLI_SOURCE_ALL: SourceSelection = "all";

/** A call record tagged at the data-face boundary with its channel source. */
export interface SourceTaggedCall {
  source: CliSourceValue;
  call: TSDuckCallDTO;
}

/**
 * Filter predicate (SPEC-405 §7.2): "all" keeps everything; a value keeps
 * only rows tagged with it. Server ASC order (started_at_utc_ms) is never
 * re-sorted — the input order passes through.
 */
export function filterCalls(
  rows: readonly SourceTaggedCall[],
  selected: SourceSelection,
): SourceTaggedCall[] {
  if (selected === CLI_SOURCE_ALL) return [...rows];
  return rows.filter((row) => row.source === selected);
}
