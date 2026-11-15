// Solution panel (SPEC-406 §4.7, REQ-UI-406-007): hidden_reference_solution
// reveal behind the PASS gate. Lock rule: the page-held verdict must be
// exactly "PASS" — the SAME verdict string the VerifyResultCard renders
// (SPEC-406 §4.7 纪律; no local verdict derivation exists anywhere in the
// Lab). The reveal fetch itself is delegated to the parent via onRequest —
// the panel is presentational and NEVER calls the api seam. The backend
// reveal gate (裁定 F: GET .../solution?session_id= → 403
// SIM_SCENARIO_SOLUTION_LEAK without a PASS row) is the authority; the
// client-side unlock is only a precondition, so a 403 answer renders the
// server refusal and the panel stays locked.
import { Badge, EmptyState } from "../../components/ui";

export interface SolutionFetchState {
  /** The answered hidden_reference_solution (null = scenario declares none). */
  text: string | null;
}

export interface SolutionErrorState {
  errorCode: string;
  message: string;
}

export function SolutionPanel({
  scenarioId,
  sessionId,
  verdict,
  solution,
  error,
  onRequest,
}: {
  scenarioId: string;
  sessionId: string;
  /** The page-held VerificationResultDTO.verdict (null = no verdict yet). */
  verdict: string | null;
  solution: SolutionFetchState | null;
  error: SolutionErrorState | null;
  onRequest: (scenarioId: string, sessionId: string) => void;
}) {
  const unlocked = verdict === "PASS";
  return (
    <div className="dvb-lab-solution" data-testid="lab-solution-panel">
      <div className="dvb-lab-solution-head">
        <Badge tone={unlocked ? "good" : "neutral"}>hidden_reference_solution</Badge>
      </div>
      {error !== null && (
        <div className="dvb-lab-solution-error" data-testid="lab-solution-error">
          <span className="dvb-lab-code">{error.errorCode}</span> · {error.message}
        </div>
      )}
      {solution !== null ? (
        solution.text === null ? (
          <EmptyState title="本场景未声明参考解" note="服务端应答 hidden_reference_solution=null（OQ-3 契约）。" />
        ) : (
          <pre className="dvb-lab-solution-text" data-testid="lab-solution-text">
            {solution.text}
          </pre>
        )
      ) : error === null && unlocked ? (
        <button
          type="button"
          className="dvb-lab-solution-reveal"
          onClick={() => onRequest(scenarioId, sessionId)}
        >
          展开参考解
        </button>
      ) : (
        <>
          <button type="button" className="dvb-lab-solution-reveal" disabled>
            展开参考解
          </button>
          <div className="dvb-lab-solution-locked" data-testid="lab-solution-locked">
            参考解保持锁定——通关判定为 PASS 后展开（后端 reveal 门核验：session+scenario 存在
            verdict=PASS 判定行方可取得；当前
            {verdict === null ? "尚无通关判定" : `通关判定为 ${verdict}`}）。
          </div>
        </>
      )}
    </div>
  );
}
