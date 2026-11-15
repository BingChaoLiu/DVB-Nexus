// Router assembly (SPEC-400 §4.2): shell layout wraps the registry routes;
// unknown paths redirect to the first registry entry (the three MVP regions
// are the whole app surface for now).
import { createBrowserRouter, Navigate } from "react-router";
import { AppShell } from "./AppShell";
import { appRoutes } from "./routes";

export function createAppRouter() {
  return createBrowserRouter([
    {
      element: <AppShell />,
      children: [
        ...appRoutes.map((route) => ({
          path: route.path,
          element: <route.element />,
        })),
        { path: "/", element: <Navigate to={appRoutes[0]?.path ?? "/topologies"} replace /> },
      ],
    },
    { path: "*", element: <Navigate to={appRoutes[0]?.path ?? "/topologies"} replace /> },
  ]);
}
