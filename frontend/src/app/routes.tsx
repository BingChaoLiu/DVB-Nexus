// Route registry (SPEC-400 §4.2): the ONE shared file later tickets extend.
// Adding a route = one entry here + one import below — shell logic never
// changes (additive-only shared face, 裁定 C). The array order is the nav order.
// SPEC-408 §4.1: home foyer joins as the first entry (four route regions);
// the three module regions keep their registry order — no regrouping.
import { lazy } from "react";
import type { ComponentType } from "react";

export interface AppRouteRecord {
  path: string;
  label: string;
  element: ComponentType;
  /** Optional nav badge (SPEC-408 §4.1: Lab 主干 / Topologies 进阶). */
  badge?: string;
}

export const appRoutes: AppRouteRecord[] = [
  {
    path: "/",
    label: "主页",
    element: lazy(() => import("../features/home/HomePage")),
  },
  {
    path: "/topologies",
    label: "Topologies",
    badge: "进阶",
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
    badge: "主干",
    element: lazy(() => import("../features/lab/Region")),
  },
];
