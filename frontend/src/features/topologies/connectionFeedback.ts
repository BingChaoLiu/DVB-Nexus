// Connection feedback guidance state (SPEC-408 §4.5 item 4 / §7.6): a small
// PURE state machine over React Flow connection attempts. It feeds three
// faces: (1) the canvas preview — while an attempt is in flight, the
// ILLEGAL END handle set is computed per visible handle from the SAME four
// prechecks canConnect runs (direction / cardinality / plane / self loop ALL
// enter the preview, review-fix F2; the old direction-only CSS hook could
// not show cardinality/plane/illegality). The set rides
// IllegalEndHandlesContext down to the rendered Handles; (2) the one-line
// toolbar rejection reason — explainConnection's §7.6 line, shown for ~4 s
// (CONNECTION_HINT_VISIBLE_MS) after an attempt falls short, inline, never a
// modal. canConnect/explainConnection stay the only legality authority
// (canConnect's signature frozen); the backend remains the double-layer
// authority (SPEC-401 §7.4).
import { createContext } from "react";

import { canConnect, explainConnection, type TopologyFlowEdge, type TopologyFlowNode } from "./graphMapping";

/** §4.5: 落空后一行原因提示,约 4 秒自动消失 (inline, not a modal). */
export const CONNECTION_HINT_VISIBLE_MS = 4000;

export interface ConnectionAttempt {
  nodeId: string;
  handleId: string | null;
  handleType: "source" | "target";
}

export interface ConnectionFeedback {
  /** Origin handle type while an attempt is in flight, else null — drives the
   * canvas wrapper's data-connecting CSS hook. */
  connectingFrom: "source" | "target" | null;
  /** The FULL origin attempt while in flight (review-fix F2) — the
   * illegal-end preview set derives from it (origin node + handle feed the
   * four-precheck computation). */
  connecting: ConnectionAttempt | null;
  /** The §7.6 reason line for the latest rejected attempt, else null. */
  rejection: string | null;
  /** Monotonic attempt counter — remounts the hint component so EVERY new
   * rejection gets a fresh auto-dismiss window even with identical text. */
  attempt: number;
}

export const idleConnectionFeedback: ConnectionFeedback = {
  connectingFrom: null,
  connecting: null,
  rejection: null,
  attempt: 0,
};

/** onConnectStart / onClickConnectStart: a fresh attempt clears any standing
 * rejection (the user has moved on) and records the origin attempt. */
export function connectionStarted(feedback: ConnectionFeedback, start: ConnectionAttempt): ConnectionFeedback {
  return { connectingFrom: start.handleType, connecting: start, rejection: null, attempt: feedback.attempt };
}

/** onConnectEnd / onClickConnectEnd. `end` is the handle the attempt landed on
 * (null = dropped on the pane / cancelled — preview off, standing reason
 * untouched). A landed attempt is normalized to (source → target) from the
 * origin's type and labeled via explainConnection; legal ends clear the
 * reason. */
export function connectionAttempted(
  feedback: ConnectionFeedback,
  start: ConnectionAttempt | null,
  end: ConnectionAttempt | null,
  graph: { nodes: TopologyFlowNode[]; connections: TopologyFlowEdge[] },
): ConnectionFeedback {
  if (start === null) return feedback;
  if (end === null) {
    return { ...feedback, connectingFrom: null, connecting: null };
  }
  const source = start.handleType === "source" ? start : end;
  const target = start.handleType === "source" ? end : start;
  const sourceNode = graph.nodes.find((n) => n.id === source.nodeId);
  const targetNode = graph.nodes.find((n) => n.id === target.nodeId);
  const rejection =
    sourceNode && targetNode
      ? explainConnection({
          source: sourceNode,
          target: targetNode,
          sourceHandle: source.handleId,
          targetHandle: target.handleId,
          connections: graph.connections,
        })
      : null;
  return { connectingFrom: null, connecting: null, rejection, attempt: feedback.attempt + 1 };
}

// --- §7.6 拖拽预览: the per-handle illegal END set (review-fix F2) -----------

/** Stable DOM/consumption key for one handle (node id + port id — port ids
 * are port_id verbatim; the `::` separator keeps node/handle namespaces
 * apart). */
export function illegalHandleKey(nodeId: string, handleId: string): string {
  return `${nodeId}::${handleId}`;
}

/** The §7.6 preview set: every visible handle that CANNOT legally end the
 * in-flight attempt, computed with the frozen-signature canConnect (the same
 * four prechecks: direction, self loop, cardinality, single plane). A
 * target-type origin is normalized (candidate = source, origin = target) —
 * the exact mirror of connectionAttempted. No attempt in flight → empty set
 * (preview off). The ORIGIN handle itself lands in the set via the self-loop
 * rule (same node + same port is never a legal end). */
export function illegalEndHandles(
  start: ConnectionAttempt | null,
  graph: { nodes: TopologyFlowNode[]; connections: TopologyFlowEdge[] },
): ReadonlySet<string> {
  if (start === null || start.handleId === null) return new Set<string>();
  const startNode = graph.nodes.find((n) => n.id === start.nodeId);
  if (startNode === undefined) return new Set<string>();
  const illegal = new Set<string>();
  for (const node of graph.nodes) {
    for (const port of node.data.node.ports) {
      const fromSource = start.handleType === "source";
      const verdict = canConnect({
        source: fromSource ? startNode : node,
        target: fromSource ? node : startNode,
        sourceHandle: fromSource ? start.handleId : port.port_id,
        targetHandle: fromSource ? port.port_id : start.handleId,
        connections: graph.connections,
      });
      if (!verdict) illegal.add(illegalHandleKey(node.id, port.port_id));
    }
  }
  return illegal;
}

/** Context the page feeds to the rendered Handles (TopologyNode consumes it
 * per handle). Default = permanently empty (idle): outside a drag nothing is
 * ever dimmed by the preview. */
export const IllegalEndHandlesContext = createContext<ReadonlySet<string>>(new Set<string>());
