// Editor draft state (SPEC-401 §4.3/§5.2): the application-owned canvas
// state. React Flow stays in controlled mode (ADR-0009 decision 4) — its
// internal store is never a fact source; change intents are applied HERE and
// only a save (PUT new revision) turns the draft into server facts. The
// reducer is pure so the whole interaction contract is testable without the
// canvas renderer (see editorState.test.ts); TopologyEditorPage is thin
// wiring over it.
import { applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type { EdgeChange, NodeChange } from "@xyflow/react";

import type { TopologyConnectionDTO, TopologyDTO, TopologyViolationDTO } from "../../api/endpoints/topologies";
import {
  defaultPortsFor,
  fromWire,
  nextNodeId,
  type TopologyFlowEdge,
  type TopologyFlowNode,
} from "./graphMapping";
import { nodeTypeSpec } from "./nodeTypes";
import { mapPlanErrors, mapViolations, violationIndex, type PlanErrorEntry, type ViolationEntry } from "./violations";

export interface ValidationView {
  /** idle = not yet validated; done = a server report is displayed. */
  status: "idle" | "done";
  /** path-addressed entries from POST /topologies/{id}/validate (§7.4). */
  entries: ViolationEntry[];
  /** graph-level entries (cycle etc.) for banner + panel (§7.4). */
  graphEntries: ViolationEntry[];
  /** run prepare 422 same-channel entries (§7.5). */
  planErrors: PlanErrorEntry[];
}

export interface EditorError {
  errorCode: string;
  message: string;
}

export interface EditorState {
  /** null = unsaved draft (first save goes POST → server uuid4). */
  topologyId: string | null;
  /** Latest server revision; null until first save/load. */
  revision: number | null;
  dirty: boolean;
  nodes: TopologyFlowNode[];
  connections: TopologyFlowEdge[];
  validation: ValidationView;
  error: EditorError | null;
}

export function initialEditorState(): EditorState {
  return {
    topologyId: null,
    revision: null,
    dirty: false,
    nodes: [],
    connections: [],
    validation: { status: "idle", entries: [], graphEntries: [], planErrors: [] },
    error: null,
  };
}

export type EditorAction =
  | { type: "newDraft" }
  | { type: "loaded"; topology: TopologyDTO }
  | { type: "nodeAdded"; node: TopologyFlowNode }
  | { type: "nodesChanged"; changes: NodeChange<TopologyFlowNode>[] }
  | { type: "edgesChanged"; changes: EdgeChange<TopologyFlowEdge>[] }
  | { type: "connected"; connection: TopologyConnectionDTO }
  // #63 (SPEC-402 §4.2, approved additive ①): the node inspector's apply
  // action — the ONLY way form edits enter the draft. config is the opaque
  // wire payload verbatim (serialized per SPEC-402 §5.3); never re-derived.
  | { type: "configApplied"; nodeId: string; config: Record<string, unknown> }
  | { type: "saveSucceeded"; topologyId: string; revision: number }
  | { type: "saveFailed"; error: EditorError }
  | { type: "loadFailed"; error: EditorError }
  | { type: "validationSucceeded"; violations: TopologyViolationDTO[] }
  | { type: "planErrors"; errors: string[] };

/** §7.1 drop composition: registry template ports + deterministic slug. */
export function createNodeFromType(
  nodeType: string,
  position: { x: number; y: number },
  existingNodes: TopologyFlowNode[],
): TopologyFlowNode {
  const spec = nodeTypeSpec(nodeType);
  const id = nextNodeId(existingNodes, spec?.id_prefix ?? "node");
  return {
    id,
    type: "topology",
    position,
    data: {
      node: {
        node_id: id,
        node_type: nodeType,
        config: {},
        ports: defaultPortsFor(nodeType),
      },
      violationCodes: [],
      violationPorts: [],
    },
  };
}

/** Edits that change the draft's content vs. mere UI selection. */
function isContentNodeChange(change: NodeChange<TopologyFlowNode>): boolean {
  return change.type !== "select" && change.type !== "dimensions";
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "newDraft":
      return initialEditorState();

    case "loaded": {
      const { nodes, connections } = fromWire(action.topology);
      return {
        ...state,
        topologyId: action.topology.topology_id,
        revision: action.topology.revision,
        dirty: false,
        nodes,
        connections,
        validation: { status: "idle", entries: [], graphEntries: [], planErrors: [] },
        error: null,
      };
    }

    case "nodeAdded":
      return { ...state, dirty: true, nodes: [...state.nodes, action.node] };

    case "nodesChanged": {
      const nodes = applyNodeChanges(action.changes, state.nodes);
      const dirty = state.dirty || action.changes.some(isContentNodeChange);
      return { ...state, nodes, dirty };
    }

    case "edgesChanged": {
      const connections = applyEdgeChanges(action.changes, state.connections);
      const dirty = state.dirty || action.changes.some((c) => c.type === "remove");
      return { ...state, connections, dirty };
    }

    case "connected": {
      const edge = fromWire({
        topology_id: state.topologyId ?? "",
        revision: state.revision ?? 0,
        nodes: [],
        connections: [action.connection],
      }).connections[0]!;
      return { ...state, dirty: true, connections: [...state.connections, edge] };
    }

    // #63 approved additive ① (SPEC-402 §4.2): targeted config write —
    // unknown nodeId is a no-op (function stays total, dirty untouched).
    case "configApplied": {
      let applied = false;
      const nodes = state.nodes.map((node) => {
        if (node.id !== action.nodeId) return node;
        applied = true;
        return { ...node, data: { ...node.data, node: { ...node.data.node, config: action.config } } };
      });
      return applied ? { ...state, dirty: true, nodes } : state;
    }

    case "saveSucceeded":
      return {
        ...state,
        topologyId: action.topologyId,
        revision: action.revision,
        dirty: false,
        error: null,
      };

    case "saveFailed":
    case "loadFailed":
      return { ...state, dirty: action.type === "saveFailed" ? true : state.dirty, error: action.error };

    case "validationSucceeded": {
      const entries = mapViolations(action.violations);
      const index = violationIndex(entries);
      const nodes = state.nodes.map((node) => {
        const violationCodes = index.nodeCodes.get(node.id) ?? [];
        const violationPorts = [...index.portCodes.keys()]
          .filter((key) => key.startsWith(`${node.id}:`))
          .map((key) => key.slice(node.id.length + 1));
        return { ...node, data: { ...node.data, violationCodes, violationPorts } };
      });
      const connections = state.connections.map((edge) => ({
        ...edge,
        data: { connection: edge.data!.connection, violation: index.edgeCodes.has(edge.id) },
        // RF reads className from the edge object — the §7.4 in-place edge highlight.
        className: index.edgeCodes.has(edge.id) ? "dvb-topo-edge-violation" : "",
      }));
      return {
        ...state,
        nodes,
        connections,
        validation: { status: "done", entries, graphEntries: index.graphEntries, planErrors: state.validation.planErrors },
      };
    }

    case "planErrors":
      return {
        ...state,
        validation: {
          ...state.validation,
          planErrors: mapPlanErrors(action.errors, state.nodes.map((n) => n.id)),
        },
      };

    // no default — the union is exhaustive; unknown actions are type errors
  }
}
