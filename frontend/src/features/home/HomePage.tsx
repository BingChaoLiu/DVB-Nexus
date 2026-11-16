// Home foyer (SPEC-408 §4.2, REQ-UI-408-001 / AC-408-01): the journey's
// static entrance — hero goal, big CTA into the Lab library, the eight-step
// journey map (§1 overview table verbatim; Analyze row annotated as the
// declared gap) and the three module cards (§4.2 frozen copy, verbatim).
// Zero popups/tours/mode switches (SPEC-408 §12.1 review item). The Monitor
// card's 「一键演示」 button is a DISABLED placeholder — behavior is wired by
// ticket #99; never render a fake-clickable button.
import { Link } from "react-router";
import { ANALYZE_GAP_NOTE, JOURNEY_STEPS } from "../../app/journeySteps";
import "./home.css";

export default function HomePage() {
  return (
    <div className="dvb-home" data-testid="home-foyer">
      <section className="dvb-home-hero" aria-label="旅程门厅">
        <h1 className="dvb-home-hero-goal" data-testid="home-hero-goal">
          目标：不看任何文档，30 分钟内独立走通八步闭环，拿到 PASS。
        </h1>
        <Link to="/lab" className="dvb-home-cta" data-testid="home-cta-start">
          从这里开始：选一个场景
        </Link>
      </section>

      <section className="dvb-home-map dvb-panel" data-testid="home-journey-map" aria-label="八步闭环旅程地图">
        <h2 className="dvb-panel-title">八步闭环旅程地图</h2>
        <ol className="dvb-home-map-list">
          {JOURNEY_STEPS.map((step) => (
            <li
              key={step.key}
              data-testid={`home-journey-step-${step.key}`}
              className={`dvb-home-map-row${step.gap ? " dvb-home-map-row-gap" : ""}`}
            >
              <span className="dvb-home-map-index">{step.index}</span>
              <span className="dvb-home-map-en">{step.en}</span>
              <span className="dvb-home-map-zh">{step.zh}</span>
              <span className="dvb-home-map-what">{step.what}</span>
              <span className="dvb-home-map-where">发生在哪：{step.where}</span>
              {step.gap ? (
                <span className="dvb-home-map-gap-note" data-testid="home-journey-step-analyze-gap">
                  {ANALYZE_GAP_NOTE}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </section>

      <section className="dvb-home-cards" aria-label="三模块导航卡">
        <article className="dvb-home-card dvb-panel" data-testid="home-card-lab">
          <h3 className="dvb-panel-title">Lab（主干）</h3>
          <p className="dvb-home-card-body">这是主干旅程所在：场景库列出五个场景，实验台走完八步。</p>
          <p className="dvb-home-card-next">下一步 = 点击上方 CTA 选一个场景。</p>
        </article>

        <article className="dvb-home-card dvb-panel" data-testid="home-card-monitor">
          <h3 className="dvb-panel-title">Monitor（证据台）</h3>
          <p className="dvb-home-card-body">这是自由观测台（free observation deck），按 session 展示真实运行证据。</p>
          <p className="dvb-home-card-body">需先有 session 才有内容：从 Lab 进入，或粘贴 UUID，或一键演示。</p>
          <p className="dvb-home-card-next">下一步按钮 = 「一键演示」（演示门，§4.3）。</p>
          <button type="button" className="dvb-home-card-action" data-testid="home-monitor-demo-start" disabled>
            一键演示
          </button>
        </article>

        <article className="dvb-home-card dvb-panel" data-testid="home-card-topologies">
          <h3 className="dvb-panel-title">Topologies（进阶）</h3>
          <p className="dvb-home-card-body">
            这是进阶工具：手工搭建与校验 MPEG-TS 拓扑。主干旅程使用场景自带初始拓扑，不读这里保存的拓扑。
          </p>
          <p className="dvb-home-card-next">下一步 = 拿到第一次 PASS 之后再回来探索。</p>
        </article>
      </section>
    </div>
  );
}
