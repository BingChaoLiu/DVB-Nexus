// Application shell (SPEC-400 §4.2 + SPEC-408 §4.1): nav from the route
// registry (home entry first, Lab/Topologies badges) + the guide link + the
// permanent journey wayfinding bar under the header + the routed region
// outlet. WS connection status surfaces here later (features own the stream
// instance; the shell stays registry-driven).
import { Suspense } from "react";
import { NavLink, Outlet } from "react-router";
import { appRoutes } from "./routes";
import { GUIDE_URL } from "./journeySteps";
import { JourneyBar } from "./JourneyBar";
import "./shell.css";

export function AppShell() {
  return (
    <div className="dvb-shell">
      <header className="dvb-shell-header">
        <span className="dvb-shell-title">DVB-Nexus</span>
        <nav aria-label="路由区" className="dvb-shell-nav">
          {appRoutes.map((route) => (
            <NavLink
              key={route.path}
              to={route.path}
              className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}
              data-testid={`nav-link-${route.path === "/" ? "home" : route.path.slice(1)}`}
            >
              {route.label}
              {route.badge ? (
                <span
                  className={`dvb-badge ${route.path === "/lab" ? "dvb-badge-info" : "dvb-badge-neutral"} dvb-nav-badge`}
                  data-testid={`nav-badge-${route.path === "/" ? "home" : route.path.slice(1)}`}
                >
                  {route.badge}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <a
          className="dvb-shell-guide"
          data-testid="shell-guide-link"
          href={GUIDE_URL}
          target="_blank"
          rel="noreferrer noopener"
        >
          查看使用指南 ↗
        </a>
      </header>
      <JourneyBar />
      <main className="dvb-shell-main">
        <Suspense fallback={<div className="dvb-region-loading">加载中…</div>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
