// CLI console section (SPEC-405 §4.1/§4.2): the session-scoped composition —
// source filter + call-record list + detail over ONE §4.8 query. State
// matrix (§7.5): pending line / honest empty / filtered-empty / 404
// session-absence / 501 unbound / other failures with envelope fields.
// Freshness: default query-cache posture (no stream topic maps to this face
// in the SPEC-305 §8 matrix — refreshed on mount/filter actions).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { isApiError } from "../../../api";
import { Panel } from "../../../components/ui";
import { cliKeys } from "./cliKeys";
import { filterCalls, CLI_SOURCE_ALL, type SourceSelection, type SourceTaggedCall } from "./sources";
import { SourceFilter } from "./SourceFilter";
import { CallStates, type CallState } from "./states";
import { TSDuckCallDetail } from "./TSDuckCallDetail";
import { TSDuckCallList } from "./TSDuckCallList";
import { listTSDuckCalls } from "./tsduckCalls";

export function CliConsoleSection({ sessionId }: { sessionId: string }) {
  const [selected, setSelected] = useState<SourceSelection>(CLI_SOURCE_ALL);
  const [runIdFilter, setRunIdFilter] = useState("");
  const [selectedRow, setSelectedRow] = useState<SourceTaggedCall | null>(null);

  const trimmedRunId = runIdFilter.trim();
  const query = useQuery({
    queryKey: [...cliKeys.calls(sessionId, trimmedRunId === "" ? null : trimmedRunId)],
    queryFn: () => listTSDuckCalls(sessionId, trimmedRunId === "" ? undefined : trimmedRunId),
  });

  let state: CallState | null = null;
  if (query.isPending) {
    state = null; // pending line below
  } else if (query.error !== null) {
    const error = query.error;
    if (isApiError(error)) {
      state = {
        kind: "error",
        errorCode: error.errorCode,
        message: error.message,
        requestId: error.requestId,
        retryable: error.retryable,
        notBound: error.status === 501,
        onRetry: error.retryable ? () => void query.refetch() : undefined,
      };
    } else {
      state = {
        kind: "error",
        errorCode: "REQUEST_FAILED",
        message: String(error),
        requestId: null,
        retryable: true,
        onRetry: () => void query.refetch(),
      };
    }
  } else if (query.data.length === 0) {
    state = selected === CLI_SOURCE_ALL ? { kind: "empty" } : { kind: "filtered-empty", selected };
  }

  const rows = query.data ?? [];
  const visible = state === null ? filterCalls(rows, selected) : [];

  return (
    <Panel title="CLI 对照">
      <p className="dvb-cli-note">
        「CLI 对照」= 来源标识区分（真实 TSDuck 输出 vs 模拟日志，禁混标）——不是双解析器 diff
        （SPEC-309 归 roadmap）。有效性判定不在本页（见详情页内容门标注）。
      </p>
      <SourceFilter selected={selected} onSelectChange={setSelected} />
      <input
        aria-label="run id 过滤"
        placeholder="run id 过滤（可选）"
        value={runIdFilter}
        onChange={(e) => setRunIdFilter(e.target.value)}
      />

      {query.isPending && <p className="dvb-mon-line">加载中…</p>}
      {state !== null && <CallStates state={state} />}
      {state === null && visible.length > 0 && (
        <TSDuckCallList rows={visible} onSelect={setSelectedRow} />
      )}
      {/* A zero-hit filter replaces the list with the honest state (§7.5). */}
      {state === null && visible.length === 0 && (
        <CallStates state={{ kind: "filtered-empty", selected }} />
      )}
      {selectedRow !== null && <TSDuckCallDetail row={selectedRow} />}
    </Panel>
  );
}
