// Violation mapping (SPEC-401 §7.4/§7.5): backend path-addressed rejections
// → canvas entities for in-place highlight, plus the run-prepare 422
// same-channel entries. The path grammar mirrors the backend validator's
// emit set (src/simulation/state/validate.py): nodes[<id>] /
// nodes[<id>].ports[<pid>] / connections[<cid>] / topology. Unknown shapes
// degrade to graph-level entries — never silently dropped.
import type { TopologyViolationDTO } from "../../api/endpoints/topologies";

export type ViolationTarget =
  | { kind: "node"; nodeId: string }
  | { kind: "port"; nodeId: string; portId: string }
  | { kind: "edge"; connectionId: string }
  | { kind: "graph" };

export interface ViolationEntry {
  code: string;
  path: string;
  message: string;
  target: ViolationTarget;
}

const NODE_PATH = /^nodes\[(.+?)\]$/;
const PORT_PATH = /^nodes\[(.+?)\]\.ports\[(.+?)\]$/;
const CONNECTION_PATH = /^connections\[(.+?)\]$/;

export function parsePath(path: string): ViolationTarget {
  const port = PORT_PATH.exec(path);
  if (port) return { kind: "port", nodeId: port[1]!, portId: port[2]! };
  const node = NODE_PATH.exec(path);
  if (node) return { kind: "node", nodeId: node[1]! };
  const connection = CONNECTION_PATH.exec(path);
  if (connection) return { kind: "edge", connectionId: connection[1]! };
  return { kind: "graph" }; // "topology" and any unrecognized shape
}

export function mapViolations(violations: TopologyViolationDTO[]): ViolationEntry[] {
  return violations.map((v) => ({ code: v.code, path: v.path, message: v.message, target: parsePath(v.path) }));
}

export interface ViolationIndex {
  /** node_id → codes addressed to the node itself or via its ports. */
  nodeCodes: Map<string, string[]>;
  /** `${nodeId}:${portId}` → codes addressed to the port (Handle highlight). */
  portCodes: Map<string, string[]>;
  /** connection_id → codes (edge highlight). */
  edgeCodes: Map<string, string[]>;
  /** Graph-level entries (cycle, unrecognized paths) — panel + banner. */
  graphEntries: ViolationEntry[];
}

export function violationIndex(entries: ViolationEntry[]): ViolationIndex {
  const index: ViolationIndex = {
    nodeCodes: new Map(),
    portCodes: new Map(),
    edgeCodes: new Map(),
    graphEntries: [],
  };
  for (const entry of entries) {
    const { target, code } = entry;
    if (target.kind === "node") {
      push(index.nodeCodes, target.nodeId, code);
    } else if (target.kind === "port") {
      push(index.portCodes, `${target.nodeId}:${target.portId}`, code);
      push(index.nodeCodes, target.nodeId, code); // port violations light the node too
    } else if (target.kind === "edge") {
      push(index.edgeCodes, target.connectionId, code);
    } else {
      index.graphEntries.push(entry);
    }
  }
  return index;
}

function push(map: Map<string, string[]>, key: string, code: string): void {
  const bucket = map.get(key);
  if (bucket) {
    bucket.push(code);
  } else {
    map.set(key, [code]);
  }
}

// --- run prepare 422 same-channel entries (§7.5) -------------------------------

export interface PlanErrorEntry {
  source: "run_prepare";
  /** The wire error string verbatim (SIM_TS_PLAN_INVALID / SIM_TS_CONFIG_INVALID
   * details.errors[]) — free text, not parsed into entity claims. */
  message: string;
  /** Best-effort highlight: draft node ids mentioned on non-alphanumeric
   * boundaries. No other parsing is attempted (no fabricated entity mapping). */
  nodeIds: string[];
}

export function mapPlanErrors(errors: string[], draftNodeIds: string[]): PlanErrorEntry[] {
  return errors.map((message) => ({ source: "run_prepare" as const, message, nodeIds: mentionedNodeIds(message, draftNodeIds) }));
}

function mentionedNodeIds(message: string, draftNodeIds: string[]): string[] {
  return draftNodeIds.filter((id) => mentionsWord(message, id));
}

function mentionsWord(text: string, word: string): boolean {
  if (word.length === 0) return false;
  const isBoundary = (ch: string | undefined) => ch === undefined || !/[\w-]/.test(ch); // hyphen joins slugs — NOT a boundary
  let index = text.indexOf(word);
  while (index !== -1) {
    const beforeOk = index === 0 || isBoundary(text[index - 1]);
    const afterIndex = index + word.length;
    const afterOk = afterIndex === text.length || isBoundary(text[afterIndex]);
    if (beforeOk && afterOk) return true;
    index = text.indexOf(word, index + 1);
  }
  return false;
}
