// Topology editor page (SPEC-401 §4.2/§7). Thin wiring over the pure
// editorState reducer: server facts flow through the query cache (qk
// vocabulary, SPEC-400 §5) and every mutation the page performs is one
// dispatch — the canvas itself is the controlled React Flow instance
// (ADR-0009 decision 4). Save = PUT/POST → fixed third step validate →
// in-place display (§7.4); click-to-add exists alongside palette DnD as the
// accessible add path (drag remains the primary REQ-UI-401-002 interaction,
// exercised end-to-end in e2e/topology.spec.ts).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ConnectionMode, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import type { Connection, Edge, EdgeChange, NodeChange } from "@xyflow/react";

import {
  createTopology,
  getTopology,
  isApiError,
  listTopologies,
  saveTopologyRevision,
  validateTopology,
  type TopologyConnectionDTO,
} from "../../api";
import { qk } from "../../query/keys";
import { editorReducer, initialEditorState, createNodeFromType } from "./editorState";
import { canConnect, nextConnectionId, toWire } from "./graphMapping";
import {
  IllegalEndHandlesContext,
  connectionAttempted,
  connectionStarted,
  idleConnectionFeedback,
  illegalEndHandles,
  type ConnectionAttempt,
  type ConnectionFeedback,
} from "./connectionFeedback";
import { CanvasEmptyOverlay, ConnectionHint, SaveGateNote, SaveSuccessNote, TopologyGuidanceBanner } from "./guidance";
import { nodeTypeSpec } from "./nodeTypes";
import { NODE_TYPE_MIME, NodePalette } from "./NodePalette";
import { TopologyNode } from "./TopologyNode";
import { ViolationPanel } from "./ViolationPanel";
import { computeInspectorGate } from "./inspector/inspectorGate";
import { mapLocChain, type FieldError } from "./inspector/locChain";
import { NodeInspector } from "./inspector/NodeInspector";
import "./topologyEditor.css";

const nodeTypes = { topology: TopologyNode };

// RF connection-callback shapes (structural supersets — no @xyflow/system
// import; the generated/hoisted types stay RF-internal). §4.5 item 4 wires
// these into the connectionFeedback machine (落空原因提示 + 拖拽预览标记).
interface ConnectStartParams {
  nodeId: string | null;
  handleId: string | null;
  handleType: "source" | "target" | null;
}
interface ConnectionEndHandle {
  nodeId: string;
  id?: string | null;
  type: "source" | "target";
}
interface ConnectionEndInfo {
  isValid: boolean | null;
  fromHandle: ConnectionEndHandle | null;
  toHandle: ConnectionEndHandle | null;
}

// jsdom (the vitest environment) lacks ResizeObserver, which React Flow's
// ZoomPane uses at mount; browsers — the real target — always provide it.
// Install a no-op fallback ONLY when the runtime lacks one, so the shell's
// region tests can render this page unmodified.
if (typeof window !== "undefined" && typeof window.ResizeObserver === "undefined") {
  class ResizeObserverFallback {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  window.ResizeObserver = ResizeObserverFallback as unknown as typeof ResizeObserver;
}

export function TopologyEditorPage() {
  return (
    <ReactFlowProvider>
      <TopologyEditor />
    </ReactFlowProvider>
  );
}

function TopologyEditor() {
  const queryClient = useQueryClient();
  const { screenToFlowPosition, setCenter } = useReactFlow();
  const [state, dispatch] = useReducer(editorReducer, undefined, initialEditorState);
  const [saving, setSaving] = useState(false);
  // #63 (SPEC-402 §7.4): 口径 A backfill from a 400 save rejection — cleared
  // on the next successful save; graph-level locs stay on the ApiError banner.
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const autoLoadedFor = useRef<Set<string>>(new Set());
  // §4.5 item 4: connection-attempt feedback (preview marker + 落空原因 line).
  const [feedback, setFeedback] = useState<ConnectionFeedback>(idleConnectionFeedback);
  const attemptRef = useRef<ConnectionAttempt | null>(null);
  // §4.5 item 5: the per-save declaration (已保存为 revision N) — cleared when
  // the editing context changes (load / new draft), never by mere edits.
  const [savedNoteRevision, setSavedNoteRevision] = useState<number | null>(null);

  // Server facts via the query cache (§7.6 load flow).
  const listQuery = useQuery({ queryKey: qk.topologies(), queryFn: () => listTopologies() });

  const loadTopology = useCallback(
    async (topologyId: string) => {
      try {
        const topology = await getTopology(topologyId);
        setSavedNoteRevision(null); // the declaration describes a save action, not the loaded row
        dispatch({ type: "loaded", topology });
        // §7.6: opening a stored revision shows its real state immediately.
        const validation = await validateTopology(topologyId, topology.revision);
        dispatch({ type: "validationSucceeded", violations: validation.violations ?? [] });
      } catch (error) {
        dispatch({
          type: "loadFailed",
          error: isApiError(error)
            ? { errorCode: error.errorCode, message: error.message }
            : { errorCode: "UNKNOWN", message: String(error) },
        });
      }
    },
    [],
  );

  // Auto-load the first listed topology once per list identity (fresh page).
  const list = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  useEffect(() => {
    const first = list[0];
    if (first && state.topologyId === null && !autoLoadedFor.current.has(first.topology_id)) {
      autoLoadedFor.current.add(first.topology_id);
      void loadTopology(first.topology_id);
    }
  }, [list, state.topologyId, loadTopology]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    const request = toWire(state.nodes, state.connections);
    try {
      const saved = state.topologyId
        ? await saveTopologyRevision(state.topologyId, request)
        : await createTopology(request);
      dispatch({ type: "saveSucceeded", topologyId: saved.topology_id, revision: saved.revision });
      setSavedNoteRevision(saved.revision); // §4.5 item 5: EVERY save shows its declaration line
      setFieldErrors([]); // #63: a successful save clears the loc-chain backfill
      await queryClient.invalidateQueries({ queryKey: qk.topologies() });
      // §7.4 fixed third step: the server validates the STORED graph only.
      const validation = await validateTopology(saved.topology_id, saved.revision);
      dispatch({ type: "validationSucceeded", violations: validation.violations ?? [] });
    } catch (error) {
      // #63 (SPEC-402 §7.4): 口径 A — 400 loc chains land under form fields;
      // every other failure keeps the banner-only channel.
      setFieldErrors(
        isApiError(error) && error.status === 400 && error.errorCode === "REQUEST_BODY_INVALID"
          ? mapLocChain(error.details, state.nodes.map((n) => n.id))
          : [],
      );
      dispatch({
        type: "saveFailed",
        error: isApiError(error)
          ? { errorCode: error.errorCode, message: error.message }
          : { errorCode: "UNKNOWN", message: String(error) },
      });
    } finally {
      setSaving(false);
    }
  }, [queryClient, state.connections, state.nodes, state.topologyId]);

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      const source = state.nodes.find((n) => n.id === connection.source);
      const target = state.nodes.find((n) => n.id === connection.target);
      if (!source || !target) return false;
      return canConnect({
        source,
        target,
        sourceHandle: connection.sourceHandle ?? null,
        targetHandle: connection.targetHandle ?? null,
        connections: state.connections,
      });
    },
    [state.connections, state.nodes],
  );

  // §4.5 item 4 handlers — pure machine wiring (connectionFeedback.ts). The
  // end handle of a click-connect comes from the DOM data attributes (RF's
  // click-path state carries no handles); a pointer drag reports it through
  // FinalConnectionState.toHandle. Legality is ONLY ever explainConnection —
  // the same four prechecks canConnect runs (SPEC-401 §7.2; backend stays the
  // double-layer authority, §7.4).
  const onConnectStart = useCallback((_: unknown, params: ConnectStartParams) => {
    if (params.nodeId === null || params.handleType === null) return;
    const attempt: ConnectionAttempt = { nodeId: params.nodeId, handleId: params.handleId, handleType: params.handleType };
    attemptRef.current = attempt;
    setFeedback((current) => connectionStarted(current, attempt));
  }, []);

  const onConnectEnd = useCallback(
    (_: unknown, info: ConnectionEndInfo) => {
      const start = attemptRef.current;
      attemptRef.current = null;
      const end: ConnectionAttempt | null = info.toHandle
        ? { nodeId: info.toHandle.nodeId, handleId: info.toHandle.id ?? null, handleType: info.toHandle.type }
        : null;
      setFeedback((current) =>
        connectionAttempted(current, start, end, { nodes: state.nodes, connections: state.connections }),
      );
    },
    [state.connections, state.nodes],
  );

  const onClickConnectEnd = useCallback(
    (event: Event, _connectionState: unknown) => {
      const start = attemptRef.current;
      attemptRef.current = null;
      const handleEl =
        event.target instanceof Element ? event.target.closest<HTMLElement>(".react-flow__handle") : null;
      const nodeId = handleEl?.getAttribute("data-nodeid") ?? null;
      const end: ConnectionAttempt | null =
        handleEl && nodeId
          ? {
              nodeId,
              handleId: handleEl.getAttribute("data-handleid"),
              handleType: handleEl.classList.contains("source") ? "source" : "target",
            }
          : null;
      setFeedback((current) =>
        connectionAttempted(current, start, end, { nodes: state.nodes, connections: state.connections }),
      );
    },
    [state.connections, state.nodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      // §7.2: illegal drags just do not connect — no error surface. The
      // backend remains the authority (double layer, §7.4).
      if (!isValidConnection(connection)) return;
      const fromPort = state.nodes
        .find((n) => n.id === connection.source)!
        .data.node.ports.find((p) => p.port_id === connection.sourceHandle);
      const toPort = state.nodes
        .find((n) => n.id === connection.target)!
        .data.node.ports.find((p) => p.port_id === connection.targetHandle);
      if (!fromPort || !toPort) return;
      const wire: TopologyConnectionDTO = {
        connection_id: nextConnectionId(state.connections),
        from_node: connection.source,
        from_port: connection.sourceHandle!,
        to_node: connection.target,
        to_port: connection.targetHandle!,
        plane: fromPort.plane,
      };
      dispatch({ type: "connected", connection: wire });
    },
    [isValidConnection, state.connections, state.nodes],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => dispatch({ type: "nodesChanged", changes: changes as never }),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => dispatch({ type: "edgesChanged", changes: changes as never }),
    [],
  );

  const addNodeTypeAtViewportCenter = useCallback(
    (nodeType: string) => {
      if (!nodeTypeSpec(nodeType)) return;
      const position = screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
      dispatch({ type: "nodeAdded", node: createNodeFromType(nodeType, position, state.nodes) });
    },
    [screenToFlowPosition, state.nodes],
  );

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const nodeType = event.dataTransfer.getData(NODE_TYPE_MIME);
      if (!nodeType) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      dispatch({ type: "nodeAdded", node: createNodeFromType(nodeType, position, state.nodes) });
    },
    [screenToFlowPosition, state.nodes],
  );

  const locate = useCallback(
    (nodeId: string) => {
      const node = state.nodes.find((n) => n.id === nodeId);
      if (node) {
        void setCenter(node.position.x + 120, node.position.y + 60, { zoom: 1.1, duration: 300 });
      }
    },
    [setCenter, state.nodes],
  );

  const notWired = state.error !== null && state.error.errorCode === "HTTP_501";

  // §7.6 拖拽预览 (review-fix F2): while an attempt is in flight the page
  // computes the ILLEGAL END set for EVERY visible handle from the SAME four
  // prechecks (canConnect, frozen signature) and hands it to the rendered
  // Handles via context — direction/cardinality/plane/self-loop all dim
  // before the drop, not just the drag direction. Idle (connecting === null)
  // → empty set → no handle is ever dimmed by the preview.
  const illegalEnds = useMemo(
    () => illegalEndHandles(feedback.connecting, { nodes: state.nodes, connections: state.connections }),
    [feedback.connecting, state.nodes, state.connections],
  );

  // #63 (SPEC-402 §7.6): three-part joint gate (G1 completeness ∧ G2 validate
  // report ∧ G3 field errors) — reasons nonempty disables the save entry.
  // The editor renders no session-start entry (SPEC-402 §6.2); monitor/lab
  // adopt computeInspectorGate additively in their own tickets.
  const gate = computeInspectorGate({
    nodes: state.nodes.map((n) => ({ node_id: n.id, node_type: n.data.node.node_type, config: n.data.node.config })),
    validation: state.validation,
    fieldErrors,
  });
  // §4.5 item 3: the honest pending count — incomplete config nodes (G1) +
  // validation report entries (G2) + displayed field errors (G3).
  const pendingCount = useMemo(() => {
    let count = 0;
    for (const reason of gate.reasons) {
      if (reason.kind === "config_incomplete") {
        count += reason.nodeIds.length;
      } else if (reason.kind === "structural_violations") {
        count +=
          state.validation.entries.length + state.validation.graphEntries.length + state.validation.planErrors.length;
      } else {
        count += fieldErrors.length;
      }
    }
    return count;
  }, [gate, state.validation, fieldErrors]);
  const selected = state.nodes.find((n) => n.selected) ?? null;

  return (
    <div className="dvb-topo-editor">
      <h2 className="dvb-topo-region-title">Topologies</h2>
      {/* §4.5 item 1: 页内常驻说明条 — static wayfinding, no closability. */}
      <TopologyGuidanceBanner />
      <header className="dvb-topo-toolbar">
        <label className="dvb-topo-toolbar-field">
          拓扑
          <select
            value={state.topologyId ?? ""}
            onChange={(event) => {
              if (event.target.value) void loadTopology(event.target.value);
            }}
            aria-label="选择拓扑"
          >
            <option value="">— 未选择 —</option>
            {list.map((summary) => (
              <option key={summary.topology_id} value={summary.topology_id}>
                {summary.topology_id} @ r{summary.revision}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="dvb-topo-new"
          onClick={() => {
            setSavedNoteRevision(null);
            dispatch({ type: "newDraft" });
          }}
        >
          新建拓扑
        </button>
        <span className="dvb-topo-revision">
          {state.topologyId === null ? "未保存草稿" : `revision ${state.revision ?? "?"}`}
          {state.dirty ? "（未保存修改）" : ""}
        </span>
        {/* §4.5 item 4: 落空后工具栏状态区一行原因提示 (key remount gives every
            rejection a fresh ~4 s window); inline, never a modal. */}
        <ConnectionHint key={feedback.attempt} rejection={feedback.rejection} />
        <button
          type="button"
          className="dvb-topo-save"
          onClick={() => void handleSave()}
          disabled={!state.dirty || saving || gate.reasons.length > 0}
        >
          保存为新 revision
        </button>
        {/* §4.5 item 3: the gate explanation area lives next to the save
            button — three states + the saveable zero-noise state. Replaces the
            old hover-only title (撤除). */}
        <SaveGateNote saving={saving} dirty={state.dirty} pendingCount={pendingCount} reasons={gate.reasons} />
      </header>
      {savedNoteRevision !== null && <SaveSuccessNote revision={savedNoteRevision} />}
      {state.error !== null && (
        <p className="dvb-topo-error" role="alert">
          {notWired ? "未接线：" : ""}
          [{state.error.errorCode}] {state.error.message}
        </p>
      )}
      <div className="dvb-topo-main">
        <NodePalette onAdd={addNodeTypeAtViewportCenter} />
        <div
          className="dvb-topo-canvas"
          data-testid="dvb-topo-canvas"
          data-connecting={feedback.connectingFrom ?? undefined}
          onDrop={onDrop}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
          }}
        >
          <IllegalEndHandlesContext.Provider value={illegalEnds}>
            <ReactFlow
              nodes={state.nodes}
              edges={state.connections}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={onConnectStart}
              onConnectEnd={onConnectEnd}
              onClickConnectStart={onConnectStart}
              onClickConnectEnd={onClickConnectEnd}
              isValidConnection={isValidConnection}
              connectionMode={ConnectionMode.Strict}
              fitView
            />
          </IllegalEndHandlesContext.Provider>
          {/* §4.5 item 2: 画布空态三问覆盖层 — only while the canvas has no
              nodes; the first dropped node removes it. pointer-events stay off
              the overlay (link re-enables them) so drops pass through. */}
          {state.nodes.length === 0 && <CanvasEmptyOverlay />}
        </div>
        {/* #63: inspector + violations share the third grid column (inline
            flex wrapper keeps the approved additive face to this file only). */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
          <NodeInspector
            key={selected?.id ?? "none"}
            node={selected}
            fieldErrors={fieldErrors}
            onApply={(nodeId, config) => dispatch({ type: "configApplied", nodeId, config })}
          />
          <ViolationPanel
            entries={state.validation.entries}
            planErrors={state.validation.planErrors}
            validated={state.validation.status === "done"}
            onLocate={(entry) => {
              const target = entry.target; // const so narrowing survives the find callback
              let located: string | undefined;
              if (target.kind === "node" || target.kind === "port") {
                located = target.nodeId;
              } else if (target.kind === "edge") {
                located = state.connections.find((e) => e.id === target.connectionId)?.source;
              }
              if (located) locate(located);
            }}
          />
        </div>
      </div>
    </div>
  );
}
