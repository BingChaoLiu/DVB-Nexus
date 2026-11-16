// PROTOTYPE (issue #86) — Variant C 「旅程主干带」: the journey ribbon is
// the navigation spine — always visible under the header on EVERY page,
// tracking your current position across all three modules (URL-derived,
// labelled 导航位置 ≠ 通关判定). `/` renders only a slim start strip
// (numbered next-steps, not a hero). Nav: Lab first (主干), Monitor, and
// Topologies pushed into a right-side 进阶 group with a header-corner help
// link.
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { Badge } from "../../components/ui";
import {
  deriveJourneyLocation,
  GUIDE_URL,
  JOURNEY_STEPS,
  withVariant,
  type JourneyVariantKey,
} from "./journeyPrototype";
import "./journeyPrototype.css";

export function VariantC({ variant }: { variant: JourneyVariantKey }) {
  const { pathname, search } = useLocation();
  const location = deriveJourneyLocation(pathname, search);
  return (
    <div className="dvb-shell">
      <header className="dvb-shell-header">
        <span className="dvb-shell-title">DVB-Nexus</span>
        <nav aria-label="路由区" className="dvb-shell-nav">
          <NavLink to={withVariant("/lab", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Lab <span className="dvb-proto-badge-main">主干</span>
          </NavLink>
          <NavLink to={withVariant("/monitor", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Monitor
          </NavLink>
        </nav>
        <span className="dvb-proto-nav-spacer" />
        <nav aria-label="进阶工具" className="dvb-shell-nav dvb-proto-nav-adv">
          <span className="dvb-proto-nav-group-label">进阶</span>
          <NavLink to={withVariant("/topologies", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Topologies <span className="dvb-proto-badge-adv">进阶·主干外</span>
          </NavLink>
        </nav>
        <a className="dvb-proto-guide-link" href={GUIDE_URL} target="_blank" rel="noreferrer" title="完整使用指南(中英双语)">
          ? 指南
        </a>
      </header>
      <JourneyRibbon variant={variant} location={location} />
      <main className="dvb-shell-main">
        <Outlet />
      </main>
    </div>
  );
}

/** The always-on spine: 8 main-line nodes + 2 auxiliary stations. */
function JourneyRibbon({
  variant,
  location,
}: {
  variant: JourneyVariantKey;
  location: ReturnType<typeof deriveJourneyLocation>;
}) {
  return (
    <div className="dvb-proto-ribbon" data-testid="proto-ribbon">
      <div className="dvb-proto-ribbon-line">
        <span className="dvb-proto-ribbon-origin" title="旅程起点:Lab 场景库选场景开局">
          ◎ 起点
        </span>
        {JOURNEY_STEPS.map((step) => (
          <Link
            key={step.key}
            to={withVariant("/lab", variant)}
            className={`dvb-proto-ribbon-node${step.gap ? " dvb-proto-ribbon-node-gap" : ""}`}
            title={step.hint}
          >
            {step.index}. {step.en}
          </Link>
        ))}
        <span className="dvb-proto-ribbon-aux" title="证据台 Monitor:自由观测(告警/码流/诊断/事件/CLI)——主干外的取证辅助站">
          + Monitor·证据台
        </span>
        <span className="dvb-proto-ribbon-aux dvb-proto-ribbon-aux-adv" title="拓扑编辑器:进阶工具,主干旅程绕开">
          + Topologies·进阶
        </span>
      </div>
      <div className="dvb-proto-ribbon-meta">
        <span className="dvb-proto-strip-pos">你在:{location.label}</span>
        <span className="dvb-proto-banner-sub">{location.next}</span>
        <Badge tone="warn">导航位置 ≠ 通关判定</Badge>
      </div>
    </div>
  );
}

/** Slim start page at `/` — three numbered next-steps, no hero. */
export function StartStripC({ variant }: { variant: JourneyVariantKey }) {
  return (
    <div className="dvb-proto-startstrip">
      <section className="dvb-panel">
        <h2 className="dvb-panel-title">从这开始:三步拿到第一个 PASS</h2>
        <ol className="dvb-proto-startstrip-list">
          <li>
            <b>开局</b> — <Link to={withVariant("/lab", variant)}>进入 Lab 选一个场景 →</Link>
            <span className="dvb-proto-startstrip-note">点「开始实验」= 八步闭环第 1 步(Create)</span>
          </li>
          <li>
            <b>跟着主干带走八步</b> — 页面顶部的旅程主干带会一直告诉你「你在哪、下一步去哪」。
            <span className="dvb-proto-startstrip-note">每步按钮都在 Lab 实验台里;证据下钻会联动 Monitor 证据台。</span>
          </li>
          <li>
            <b>判定通关</b> — 修复后跑第二次干净 Run,在 Verify 判定。判定 = 服务端应答的 PASS/FAIL,
            <span className="dvb-proto-startstrip-note">UI 变绿不算证据;判定只认修复后新 Run 的证据。</span>
          </li>
        </ol>
        <p className="dvb-proto-note">
          拿到 PASS 后可玩进阶:<Link to={withVariant("/topologies", variant)}>Topologies 自定义拓扑(主干外)→</Link> ·{" "}
          <a href={GUIDE_URL} target="_blank" rel="noreferrer">完整使用指南 ↗</a>
        </p>
      </section>
    </div>
  );
}
