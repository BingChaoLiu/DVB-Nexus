// PROTOTYPE (issue #86) — Variant B 「Lab 即起点」: no homepage at all —
// `/` lands on the Lab scenario library, which carries a start banner
// (你在这:旅程起点 + 8-step preview). Nav is reordered Lab→Monitor with
// Topologies split into a separated 进阶 group; the journey strip lives
// ONLY inside the Lab banner (not global); a fixed per-page 使用指南 link
// sits bottom-right on every page. Smallest-change hypothesis: no new page,
// the existing skeleton just gets wayfinding paint.
import { NavLink, Outlet, useLocation } from "react-router";
import { Badge } from "../../components/ui";
import {
  deriveJourneyLocation,
  GUIDE_URL,
  JOURNEY_STEPS,
  withVariant,
  type JourneyVariantKey,
} from "./journeyPrototype";
import "./journeyPrototype.css";

export function VariantB({ variant }: { variant: JourneyVariantKey }) {
  const { pathname, search } = useLocation();
  const location = deriveJourneyLocation(pathname, search);
  const onLabLibrary = location.area === "lab-library";
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
          <span className="dvb-proto-nav-divider" aria-hidden="true" />
          <span className="dvb-proto-nav-group-label">进阶</span>
          <NavLink to={withVariant("/topologies", variant)} className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}>
            Topologies <span className="dvb-proto-badge-adv">进阶</span>
          </NavLink>
        </nav>
        <a className="dvb-proto-guide-link" href={GUIDE_URL} target="_blank" rel="noreferrer">
          使用指南 ↗
        </a>
      </header>
      <main className="dvb-shell-main">
        {onLabLibrary ? <LabStartBanner /> : null}
        <Outlet />
      </main>
      <a className="dvb-proto-guide-corner" href={GUIDE_URL} target="_blank" rel="noreferrer" title="完整使用指南(中英双语)">
        📖 查看使用指南
      </a>
    </div>
  );
}

function LabStartBanner() {
  return (
    <section className="dvb-panel dvb-proto-start-banner" data-testid="proto-start-banner">
      <div className="dvb-proto-banner-row">
        <span className="dvb-proto-youare-here">你在这:旅程起点</span>
        <span className="dvb-proto-banner-sub">选一个场景进入详情,点「开始实验」即完成开局(八步闭环第 1 步 Create)。</span>
      </div>
      <div className="dvb-proto-banner-steps">
        {JOURNEY_STEPS.map((step) => (
          <span
            key={step.key}
            className={`dvb-proto-banner-step${step.index === 1 ? " dvb-proto-banner-step-here" : ""}${step.gap ? " dvb-proto-banner-step-gap" : ""}`}
            title={step.hint}
          >
            {step.index}. {step.en}
          </span>
        ))}
        <span className="dvb-proto-banner-note">
          <Badge tone="warn">进度 ≠ 通关判定</Badge> 判定只认修复后新 Run 证据;Analyze 当前不可用(进程内桥),非待办。
        </span>
      </div>
    </section>
  );
}
