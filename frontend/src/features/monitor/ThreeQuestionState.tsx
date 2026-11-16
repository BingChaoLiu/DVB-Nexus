// 空态三问渲染(SPEC-408 §4.6;CONTEXT.md「空态三问」词条):这是什么 ·
// 为什么空(空/失败 ≠ 干净)· 下一步去哪。静态路标,非弹窗。文案逐字来自
// copy.ts(MONITOR_EMPTY_STATE_COPY),本组件只负责三行排版。
import type { ThreeQuestionCopy } from "./copy";

export function ThreeQuestionState({ copy, testid }: { copy: ThreeQuestionCopy; testid?: string }) {
  return (
    <div className="dvb-empty-state" data-testid={testid}>
      <p className="dvb-empty-title">{copy.what}</p>
      <p className="dvb-empty-note">{copy.why}</p>
      <p className="dvb-empty-note dvb-mon-next">下一步:{copy.next}</p>
    </div>
  );
}
