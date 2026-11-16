// Connection feedback guidance state (SPEC-408 §4.5 item 4 / §7.6): a small
// PURE state machine over React Flow connection attempts. It feeds two faces:
// (1) the canvas preview marker — while an attempt is in flight, handles that
// cannot end it by direction dim (CSS hook on the canvas wrapper, 实现自裁:
// per-handle dimming stays with React Flow's own hovered-invalid marking);
// (2) the one-line toolbar rejection reason — explainConnection's §7.6 line,
// shown for ~4 s (CONNECTION_HINT_VISIBLE_MS) after an attempt falls short,
// inline, never a modal. canConnect/explainConnection stay the only legality
// authority; the backend remains the double-layer authority (SPEC-401 §7.4).
import { explainConnection, type TopologyFlowEdge, type TopologyFlowNode } from "./graphMapping";

/** §4.5: 落空后一行原因提示,约 4 秒自动消失 (inline, not a modal). */
export const CONNECTION_HINT_VISIBLE_MS = 4000;

export interface ConnectionAttempt {
  nodeId: string;
  handleId: string | null;
  handleType: "source" | "target";
}

export interface ConnectionFeedback {
  /** Origin handle type while an attempt is in flight, else null — drives the
   * canvas wrapper's data-connecting CSS hook (非法把手降透明度预览). */
  connectingFrom: "source" | "target" | null;
  /** The §7.6 reason line for the latest rejected attempt, else null. */
  rejection: string | null;
  /** Monotonic attempt counter — remounts the hint component so EVERY new
   * rejection gets a fresh auto-dismiss window even with identical text. */
  attempt: number;
}

export const idleConnectionFeedback: ConnectionFeedback = {
  connectingFrom: null,
  rejection: null,
  attempt: 0,
};

/** onConnectStart / onClickConnectStart: a fresh attempt clears any standing
 * rejection (the user has moved on) and records the origin handle type. */
export function connectionStarted(feedback: ConnectionFeedback, start: ConnectionAttempt): ConnectionFeedback {
  return { connectingFrom: start.handleType, rejection: null, attempt: feedback.attempt };
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
    return { ...feedback, connectingFrom: null };
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
  return { connectingFrom: null, rejection, attempt: feedback.attempt + 1 };
}
