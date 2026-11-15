// Application shell (SPEC-400 §4.2): nav from the route registry + the routed
// region outlet. WS connection status surfaces here later (features own the
// stream instance; the shell stays registry-driven).
import { Suspense } from "react";
import { NavLink, Outlet } from "react-router";
import { appRoutes } from "./routes";

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
            >
              {route.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="dvb-shell-main">
        <Suspense fallback={<div className="dvb-region-loading">加载中…</div>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
