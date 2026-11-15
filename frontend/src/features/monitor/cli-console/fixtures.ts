// Test fixture factories (SPEC-405 §10 test vectors). Wire shapes verbatim
// from schema.gen — tests assert against these known-good literals, never
// recompute them (tests/README §6: assert shape, not DOM snapshots).
import type { components } from "../../../api";
import type { CliSourceValue, SourceTaggedCall } from "./sources";

export type TSDuckCallDTO = components["schemas"]["TSDuckCallDTO"];

/** GBK-era localized stderr text with CJK + an undecodable-byte marker (U+FFFD). */
export const GBK_STDERR_FIXTURE =
  "错误: 未能打开输入文件 'C:\\capture\\ts\\sample.ts'（\uFFFD\uFFFD 无效参数）";

/** Full-field call: every wire field populated (SPEC-308 §7 nine + run_id). */
export const fullCall: TSDuckCallDTO = {
  version: "3.40",
  executable_path: "C:\\Program Files\\TSDuck\\bin\\tsduck.exe",
  argv: ["tsduck.exe", "analyze", "--preserve-package-names", "input.ts"],
  started_at_utc_ms: 1_000,
  finished_at_utc_ms: 2_500,
  exit_code: 0,
  stdout_text: "analysis report lines...",
  stderr_text: GBK_STDERR_FIXTURE,
  input_artifact_sha256: "a3f1...deadbeef",
  run_id: "run-1",
};

/** Failure-path call: every nullable field explicitly null (SPEC-308 §7: 不伪造). */
export const nullPathCall: TSDuckCallDTO = {
  version: null,
  executable_path: null,
  argv: [],
  started_at_utc_ms: 3_000,
  finished_at_utc_ms: 3_100,
  exit_code: null,
  stdout_text: null,
  stderr_text: null,
  input_artifact_sha256: null,
  run_id: null,
};

export const taggedCall = (
  source: CliSourceValue,
  call: TSDuckCallDTO,
): SourceTaggedCall => ({ source, call });

/** ASC fixture list spanning all four source values (filter-matrix input). */
export const fourSourceRows = (): SourceTaggedCall[] => [
  taggedCall("generator", { ...fullCall, started_at_utc_ms: 100 }),
  taggedCall("internal_parser", { ...fullCall, started_at_utc_ms: 200 }),
  taggedCall("tsduck", { ...fullCall, started_at_utc_ms: 300 }),
  taggedCall("hardware", { ...fullCall, started_at_utc_ms: 400 }),
];
