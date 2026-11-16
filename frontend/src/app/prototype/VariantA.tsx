// PROTOTYPE (issue #86) — Variant A 「旅程门厅」: a dedicated homepage at `/`
// is the journey's body (hero CTA + eight-step journey map + three module
// cards with 空态三问); the shell keeps the original nav order but adds a
// 主页 link, badges (Lab 主干 / Topologies 进阶) and a compact global journey
// strip under the header.
import { NavLink, Outlet, useLocation } from "react-router";
import { Badge } from "../../components/ui";
import {
  deriveJourneyLocation,
  GUIDE_URL,
  JOURNEY_STEPS,
  withVariant,
  type JourneyVariantKey,
} from "./journeyPrototype";
// PROTOTYPE (issue #87, DEV-only): when the example-data suite is on variant
// A, the homepage Monitor card's 下一步 grows the one-click demo entry (the
// suites compose: journey foyer + demo door).
import { readExampleDataVariant } from "./exampleDataPrototype";
import { DemoSessionLauncher } from "./DataVariantA";
import "./journeyPrototype.css";

export function VariantA({ variant }: { variant: JourneyVariantKey }) {
  const { pathname, search } = useLocation();
  const location = deriveJourneyLocation(pathname, search);
  return (
    <div className="dvb-shell">
      <header className="dvb-shell-header">
        <span className="dvb-shell-title">DVB-Nexus</span>
        <nav aria-label="路由区" className="dvb-shell-nav">
          <NavLink to={withVariant("/", variant)} className="dvb-nav-link">
            主页
          </NavLink>
          <NavLink to={withVariant("/topologies", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Topologies <span className="dvb-proto-badge-adv">进阶</span>
          </NavLink>
          <NavLink to={withVariant("/monitor", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Monitor
          </NavLink>
          <NavLink to={withVariant("/lab", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Lab <span className="dvb-proto-badge-main">主干</span>
          </NavLink>
        </nav>
        <a className="dvb-proto-guide-link" href={GUIDE_URL} target="_blank" rel="noreferrer">
          查看使用指南 ↗
        </a>
      </header>
      <MiniJourneyStrip location={location} />
      <main className="dvb-shell-main">
        <Outlet />
      </main>
    </div>
  );
}

function MiniJourneyStrip({
  location,
}: {
  location: ReturnType<typeof deriveJourneyLocation>;
}) {
  return (
    <div className="dvb-proto-strip dvb-proto-strip-mini">
      <span className="dvb-proto-strip-title">八步闭环路标:</span>
      {JOURNEY_STEPS.map((step) => (
        <span key={step.key} className={`dvb-proto-strip-node${step.gap ? " dvb-proto-strip-node-gap" : ""}`} title={step.hint}>
          {step.index}. {step.en}
          {step.gap ? " ⃠" : ""}
        </span>
      ))}
      <span className="dvb-proto-strip-pos">你在:{location.label}</span>
      <span className="dvb-proto-strip-note">导航路标 ≠ 通关判定(判定只认修复后新 Run 证据)</span>
    </div>
  );
}

/** Homepage rendered at `/` while variant A is active. */
export function StartPageA({ variant }: { variant: JourneyVariantKey }) {
  const { search } = useLocation();
  const dataVariant = readExampleDataVariant(search);
  return (
    <div className="dvb-proto-home">
      <section className="dvb-panel dvb-proto-hero">
        <h1 className="dvb-proto-hero-title">DVB-Nexus 流沙盒</h1>
        <p className="dvb-proto-hero-sub">
          数字电视流的故障演练沙盒。新工程师目标:<b>不看文档,30 分钟独立走通八步闭环(Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify),拿到 PASS</b>。
        </p>
        <a className="dvb-proto-cta" href={withVariant("/lab", variant)}>
          ▶ 从这里开始:选一个场景,进入八步闭环
        </a>
        <p className="dvb-proto-hero-note">全程有真实数据和可追溯证据;通关判定只认修复后的新 Run 证据,UI 变绿不算。</p>
      </section>

      <section className="dvb-panel">
        <h2 className="dvb-panel-title">八步闭环旅程地图(点任意一步了解它是什么)</h2>
        <div className="dvb-proto-journey-grid">
          {JOURNEY_STEPS.map((step) => (
            <div key={step.key} className={`dvb-proto-journey-card${step.gap ? " dvb-proto-journey-card-gap" : ""}`} title={step.hint}>
              <div className="dvb-proto-journey-card-head">
                <span className="dvb-proto-journey-index">{step.index}</span>
                <b>{step.en}</b>
                <span className="dvb-proto-journey-zh">{step.zh}</span>
                {step.gap ? <Badge tone="neutral">不可用</Badge> : null}
              </div>
              <p className="dvb-proto-journey-hint">{step.hint}</p>
              <p className="dvb-proto-journey-where">
                {step.gap
                  ? "无需操作——当前版本此步由进程内桥承担"
                  : step.key === "inspect" || step.key === "diagnose"
                    ? "发生在 Lab 实验台,证据联动 Monitor 证据台 →"
                    : "发生在 Lab 实验台 →"}
              </p>
            </div>
          ))}
        </div>
        <p className="dvb-proto-note">Analyze 为声明缺口(进程内分析桥,REST 冻结 501):显示为「不可用」,不是待办。</p>
      </section>

      <section className="dvb-proto-modules">
        <div className="dvb-panel dvb-proto-module-card dvb-proto-module-main">
          <h2 className="dvb-panel-title">Lab <span className="dvb-proto-badge-main">主干·推荐</span></h2>
          <p><b>这是什么:</b>预置故障场景的实验区,八步闭环全程在这里发生。</p>
          <p><b>为什么看着空:</b>还没开始任何实验;点下方按钮选一个场景即可。</p>
          <p><b>下一步:</b><a href={withVariant("/lab", variant)}>进入 Lab 场景库 →</a></p>
        </div>
        <div className="dvb-panel dvb-proto-module-card">
          <h2 className="dvb-panel-title">Monitor <span className="dvb-proto-badge-info">证据台</span></h2>
          <p><b>这是什么:</b>自由观测台:告警、码流检查器、诊断、事件、CLI 台账。</p>
          <p><b>为什么看着空:</b>它需要「会话」才有内容;从 Lab 实验台进入会自动带上,或手动粘贴 session UUID。</p>
          {/* PROTOTYPE (issue #87): with the example-data suite on A, the card
              grows the one-click demo door; stock copy stays as the fallback. */}
          {dataVariant === "A" ? (
            <p>
              <b>下一步:</b>不想等开局?点下面按钮先看一眼真实数据流动;或<a href={withVariant("/lab", variant)}>先去 Lab 开局 →</a>
              <DemoSessionLauncher compact />
            </p>
          ) : (
            <p><b>下一步:</b>先去 Lab 开局;实验中途可随时来取证。</p>
          )}
        </div>
        <div className="dvb-panel dvb-proto-module-card dvb-proto-module-adv">
          <h2 className="dvb-panel-title">Topologies <span className="dvb-proto-badge-adv">进阶</span></h2>
          <p><b>这是什么:</b>拓扑编辑器:自己编排节点与链路(进阶工具)。</p>
          <p><b>为什么主干用不到:</b>Lab 场景自带预设拓扑;走通闭环不需要它。</p>
          <p><b>下一步:</b>拿到第一次 PASS 后再来玩。</p>
        </div>
      </section>

      <footer className="dvb-proto-home-footer">
        <a href={GUIDE_URL} target="_blank" rel="noreferrer">完整使用指南(中英双语)↗</a>
        <span>·</span>
        <span>卡住了?指南里有八步闭环的逐步截图说明。</span>
      </footer>
    </div>
  );
}
