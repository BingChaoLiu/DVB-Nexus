// Route registry (SPEC-400 §4.2): the ONE shared file later tickets extend.
// Adding a route = one entry here + one import below — shell logic never
// changes (additive-only shared face, 裁定 C). The array order is the nav order.
import { lazy } from "react";
import type { ComponentType } from "react";

export interface AppRouteRecord {
  path: string;
  label: string;
  element: ComponentType;
}

export const appRoutes: AppRouteRecord[] = [
  {
    path: "/topologies",
    label: "Topologies",
    element: lazy(() => import("../features/topologies/Region")),
  },
  {
    path: "/monitor",
    label: "Monitor",
    element: lazy(() => import("../features/monitor/Region")),
  },
  {
    path: "/lab",
    label: "Lab",
    element: lazy(() => import("../features/lab/Region")),
  },
];
