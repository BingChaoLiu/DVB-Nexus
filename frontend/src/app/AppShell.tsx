// Application shell (SPEC-400 §4.2): nav from the route registry + the routed
// region outlet. WS connection status surfaces here later (features own the
// stream instance; the shell stays registry-driven).
//
// PROTOTYPE (issue #86, DEV-only): when a journey variant (?variant= A/B/C,
// localStorage fallback) is active, chrome delegates to the prototype shell;
// the stock render below is byte-identical to pre-prototype and is what
// tests and production builds see.
// PROTOTYPE (issue #87, DEV-only): the example-data suite (?data= A/B/C) is
// orthogonal to the journey suite — its pill + plan card render in BOTH
// chrome branches, and vanish entirely (null) when the suite is off.
import { Suspense } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { appRoutes } from "./routes";
import { readJourneyVariant } from "./prototype/journeyPrototype";
import { PrototypeSwitcher } from "./prototype/PrototypeSwitcher";
import { VariantA } from "./prototype/VariantA";
import { VariantB } from "./prototype/VariantB";
import { VariantC } from "./prototype/VariantC";
import { readExampleDataVariant } from "./prototype/exampleDataPrototype";
import { ExampleDataSwitcher } from "./prototype/ExampleDataSwitcher";

export function AppShell() {
  const { search } = useLocation();
  const variant = readJourneyVariant(search);
  const dataVariant = readExampleDataVariant(search);
  const dataSuite = <ExampleDataSwitcher current={dataVariant ?? "off"} />;
  if (variant !== null) {
    const Chrome = variant === "A" ? VariantA : variant === "B" ? VariantB : VariantC;
    return (
      <>
        <Chrome variant={variant} />
        <PrototypeSwitcher current={variant} />
        {dataSuite}
      </>
    );
  }
  return (
    <>
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
      {dataSuite}
    </>
  );
}
