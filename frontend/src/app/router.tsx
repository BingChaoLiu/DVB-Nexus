// Router assembly (SPEC-400 §4.2 + SPEC-408 §4.1): shell layout wraps the
// registry routes. `/` is now a REAL route (the home foyer lives in the
// registry) — no region redirects anywhere. Unregistered paths render an
// explicit unknown-region state (consistent with deriveJourneyLocation's
// 「其他/未知页面」 area) instead of silently bouncing to another region.
import { createBrowserRouter, Link } from "react-router";
import { AppShell } from "./AppShell";
import { appRoutes } from "./routes";

function UnknownRegion() {
  return (
    <div className="dvb-unknown-region dvb-panel" data-testid="unknown-region">
      <h1 className="dvb-panel-title">未知页面</h1>
      <Link to="/">回旅程起点（/）</Link>
    </div>
  );
}

export function createAppRouter() {
  return createBrowserRouter([
    {
      element: <AppShell />,
      children: [
        ...appRoutes.map((route) => ({
          path: route.path,
          element: <route.element />,
        })),
        { path: "*", element: <UnknownRegion /> },
      ],
    },
  ]);
}
