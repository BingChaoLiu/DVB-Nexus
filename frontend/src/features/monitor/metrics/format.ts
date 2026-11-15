// Metrics point display rules (SPEC-403 §7.4): the missing≠zero discipline as
// code — value:null or quality containing "missing" is an explicit missing
// state; zero with good quality is real data and renders as "0".
export interface FormatPoint {
  start_ns: number;
  end_ns: number;
  value?: number | { [key: string]: unknown } | null;
  quality?: string[];
  revision: number;
  is_final: boolean;
}

export type PointDisplay =
  | { kind: "missing"; start_ns: number; end_ns: number; flags: string[] }
  | { kind: "value"; text: string; start_ns: number; end_ns: number; flags: string[] };

/** value:null OR quality array containing "missing" — either triggers. */
function isMissing(point: FormatPoint): boolean {
  if (point.value === null) return true;
  return Array.isArray(point.quality) && point.quality.includes("missing");
}

export function pointDisplay(point: FormatPoint): PointDisplay {
  const flags: string[] = [];
  if (point.is_final === false) flags.push("nonfinal");
  if (point.revision > 1) flags.push("revised");

  if (isMissing(point)) {
    return { kind: "missing", start_ns: point.start_ns, end_ns: point.end_ns, flags };
  }
  const text = typeof point.value === "number" ? String(point.value) : JSON.stringify(point.value);
  return { kind: "value", text, start_ns: point.start_ns, end_ns: point.end_ns, flags };
}
