// Non-data states (SPEC-405 §4.2/§7.5, AC-405-05). The four-way distinction
// is contractual: 200+[] empty, filter zero-hit, 404 SIM_SESSION_NOT_FOUND
// (existence = no stored rows AND empty journal, SPEC-500 §4.8), 501 unbound
// composition, other failures. Empty copy never implies "clean"
// (CONTEXT.md ban; the clean-refusal sentence is part of the copy contract).
import { EmptyState } from "../../../components/ui";
import { CLI_SOURCE_VALUES, type SourceSelection } from "./sources";

export type CallState =
  | { kind: "empty" }
  | { kind: "filtered-empty"; selected: SourceSelection }
  | {
      kind: "error";
      errorCode: string;
      message: string;
      requestId: string | null;
      retryable: boolean;
      /** 501 unbound composition (SPEC-500 §4.8 freeze answer). */
      notBound?: boolean;
      onRetry?: () => void;
    };

export function CallStates({ state }: { state: CallState }) {
  if (state.kind === "empty") {
    return (
      <EmptyState
        title="该会话暂无 TSDuck 调用记录"
        note="MVP 生产栈不产生真实 TSDuck 调用（数据经测试/实机/fixture 种子）。空列表不是「无问题」的信号。"
      />
    );
  }

  if (state.kind === "filtered-empty") {
    const { selected } = state;
    const hardwareNote =
      selected !== "all" && selected === CLI_SOURCE_VALUES[3]
        ? "MVP 阶段 hardware 来源不产生记录。"
        : null;
    return (
      <EmptyState
        title={`所选来源（${selected}）在本会话暂无记录`}
        note={
          <>
            无记录 ≠ 干净。{hardwareNote}
          </>
        }
      />
    );
  }

  const { errorCode, message, requestId, retryable, notBound, onRetry } = state;
  const title = notBound
    ? "调用记录存储面在当前组合未绑定"
    : errorCode === "SIM_SESSION_NOT_FOUND"
      ? "会话不存在或无任何记录（无存储记录且 journal 空）"
      : "调用记录请求失败";
  return (
    <div className="dvb-cli-error dvb-empty-state" role="alert">
      <p className="dvb-empty-title">{title}</p>
      <p className="dvb-empty-note">
        {errorCode}: {message}
        {requestId !== null && <> · requestId: {requestId}</>}
      </p>
      {retryable === true && onRetry !== undefined && (
        <button type="button" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
