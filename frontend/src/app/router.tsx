// Router assembly (SPEC-400 §4.2): shell layout wraps the registry routes;
// unknown paths redirect to the first registry entry (the three MVP regions
// are the whole app surface for now).
//
// PROTOTYPE (issue #86, DEV-only): `/` routes through PrototypeEntry, which
// renders the journey-start variant when one is active and otherwise falls
// back to the exact stock redirect below.
import { createBrowserRouter, Navigate } from "react-router";
import { AppShell } from "./AppShell";
import { appRoutes } from "./routes";
import { PrototypeEntry } from "./prototype/PrototypeEntry";

export function createAppRouter() {
  return createBrowserRouter([
    {
      element: <AppShell />,
      children: [
        ...appRoutes.map((route) => ({
          path: route.path,
          element: <route.element />,
        })),
        { path: "/", element: <PrototypeEntry /> },
      ],
    },
    { path: "*", element: <Navigate to={appRoutes[0]?.path ?? "/topologies"} replace /> },
  ]);
}
