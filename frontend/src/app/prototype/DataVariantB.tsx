// PROTOTYPE (issue #87, variant B「Lab 开局即得 baseline」): the standing
// notice that declares the auto-baseline fact. Honest automation disclosure:
// the run is REAL (submitted by the §7.1 orchestration's third hop), only the
// submission was automatic — the notice says exactly that.
import { Badge } from "../../components/ui";
import "./exampleDataPrototype.css";

export function BaselineAutoRunNote() {
  return (
    <div className="dvb-proto-dv-banner dvb-proto-dv-banner-b" data-testid="proto-autorun-note">
      <Badge tone="info">方案 B</Badge>
      <span>
        开局时已自动提交基线 Run(<b>真实沙盘数据</b>,非示例):完成后 Generate 步自动点亮,
        事件/快照面板随之填充。下一步路标:<b>注入故障</b>(Inject);注入前可先点开证据/事件看数据流动。
        Stepper 进度 ≠ 通关判定(判定只认修复后新 Run 证据)。
      </span>
    </div>
  );
}
