// Journey wayfinding bar (SPEC-408 §4.1, REQ-UI-408-003): permanent strip
// under the shell header — the eight mini step nodes (CONTEXT.md 八步闭环
// wording), the「你在:<区域>」position chip derived PURELY from the URL
// (deriveJourneyLocation), and the frozen position-vs-verdict disclaimer.
// Navigation wayfinding ≠ pass/fail progress: no stepper facts, no
// cross-module state, no popups.
import { useLocation } from "react-router";
import { deriveJourneyLocation } from "./journeyLocation";
import { JOURNEY_STEPS } from "./journeySteps";
import "./shell.css";

export function JourneyBar() {
  const { pathname, search } = useLocation();
  const location = deriveJourneyLocation(pathname, search);
  return (
    <div className="dvb-journey-bar" data-testid="journey-bar">
      <ol className="dvb-journey-nodes" aria-label="八步闭环路标">
        {JOURNEY_STEPS.map((step, i) => (
          <li
            key={step.key}
            className={`dvb-journey-node${step.gap ? " dvb-journey-node-gap" : ""}`}
            data-testid={`journey-node-${step.key}`}
            title={step.gap ? `${step.zh}（旅程自动跳过）` : step.zh}
          >
            {i > 0 ? <span className="dvb-journey-arrow" aria-hidden="true">→</span> : null}
            <span>{step.en}</span>
          </li>
        ))}
      </ol>
      <span className="dvb-journey-you-are" data-testid="journey-you-are" title={location.next}>
        你在：{location.label}
      </span>
      <span className="dvb-journey-disclaimer" data-testid="journey-disclaimer">
        旅程路标条只指示当前位置，不指示完成进度；通关判定只认修复后新 Run 的服务端三态判定。
      </span>
    </div>
  );
}
