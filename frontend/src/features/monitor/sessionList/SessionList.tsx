// SessionList (SPEC-408 §4.3 会话列表区, ticket #95): the guide's main seat
// — the recent-session list from GET /api/v1/sessions (limit 20, newest
// first per contract; the frontend never re-sorts). Each row: created time /
// lifecycle badge (wire string verbatim) / scenario annotation or the
// explicit 无场景 marker / a track action navigating to ?session=<id>.
// Failure renders the explicit error face + retry (失败 ≠ 空库 — it never
// masquerades as an empty list, and the manual-UUID fallback below stays
// usable); an empty list is a fact, not an error (空 ≠ 错误).
import { useQuery } from "@tanstack/react-query";
import { listSessions, type SessionListItemDTO } from "../../../api";
import { Badge, EmptyState } from "../../../components/ui";
import { qk } from "../../../query/keys";

/** Entry-list page size (SPEC-408 §4.3: the recent list answers limit 20). */
const SESSION_LIST_LIMIT = 20;

/** Deterministic local wall-clock rendering of created_at_ms (wire ms). */
export function formatCreatedAt(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function SessionRow({ row, onTrack }: { row: SessionListItemDTO; onTrack: (sessionId: string) => void }) {
  return (
    <li className="dvb-mon-row" data-testid={`monitor-session-row-${row.session_id}`}>
      <div className="dvb-mon-row-head">
        <span className="dvb-mon-code">{row.session_id}</span>
        <span className="dvb-mon-field">
          <span className="dvb-mon-field-label">创建时间</span> {formatCreatedAt(row.created_at_ms)}
        </span>
        <Badge tone="neutral">{row.lifecycle}</Badge>
        {row.scenario_id !== null && row.scenario_id !== undefined ? (
          <Badge tone="info">
            <span>场景: {row.scenario_id}</span>
          </Badge>
        ) : (
          <Badge tone="neutral">无场景</Badge>
        )}
        <button type="button" data-testid={`monitor-track-${row.session_id}`} onClick={() => onTrack(row.session_id)}>
          跟踪
        </button>
      </div>
    </li>
  );
}

export function SessionList({ onTrack }: { onTrack: (sessionId: string) => void }) {
  const query = useQuery({
    queryKey: [...qk.sessions()],
    queryFn: () => listSessions(SESSION_LIST_LIMIT),
  });

  if (query.isPending) {
    return (
      <div data-testid="session-list-loading" className="dvb-mon-guide-list">
        <p className="dvb-mon-note">正在读取最近会话…</p>
      </div>
    );
  }

  if (query.isError) {
    return (
      <div data-testid="session-list-error" className="dvb-mon-guide-list" role="alert">
        <EmptyState
          title="最近会话读取失败"
          note="失败 ≠ 空库:GET /api/v1/sessions 请求失败。手输 UUID 兜底仍可用(下方表单)。"
        />
        <button type="button" onClick={() => void query.refetch()}>
          重试
        </button>
      </div>
    );
  }

  if (query.data.length === 0) {
    return (
      // 表外次级态(review-fix F7 申报): §4.6 总表无「列表为空」行 — 本态
      // 保留诚实空库口径,行文与 §4.6 行 1 入口三问的 next 枚举衔接(同一
      // 下一步词表,不另造分叉)。
      <div data-testid="session-list-empty" className="dvb-mon-guide-list">
        <EmptyState
          title="暂无会话记录"
          note="空 ≠ 错误：服务端尚无会话。下一步同入口三问：从 Lab 选场景开始实验；或一键演示；或手输 UUID（此列表为空，暂无可选项）。"
        />
      </div>
    );
  }

  return (
    <section className="dvb-mon-guide-list" aria-label="最近会话">
      <h3 className="dvb-mon-list-title">最近会话</h3>
      <ul className="dvb-mon-rows">
        {query.data.map((row) => (
          <SessionRow key={row.session_id} row={row} onTrack={onTrack} />
        ))}
      </ul>
    </section>
  );
}
