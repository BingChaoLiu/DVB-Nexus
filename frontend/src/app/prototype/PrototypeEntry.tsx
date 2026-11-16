// PROTOTYPE (issue #86): the `/` route element while the prototype is on.
// Variant A → StartPageA (旅程门厅首页); variant B → redirect to /lab (Lab
// 即起点); variant C → StartStripC (轻起点条); prototype off or production
// build → the stock redirect to the first registry route. Keeps the default
// render path identical to pre-prototype.
import { Navigate, useLocation } from "react-router";
import { appRoutes } from "../routes";
import { readJourneyVariant } from "./journeyPrototype";
import { StartPageA } from "./VariantA";
import { StartStripC } from "./VariantC";

export function PrototypeEntry() {
  const { search } = useLocation();
  const variant = readJourneyVariant(search);
  const stockFallback = <Navigate to={appRoutes[0]?.path ?? "/topologies"} replace />;
  if (variant === null) return stockFallback;
  if (variant === "A") return <StartPageA variant={variant} />;
  if (variant === "B") return <Navigate to="/lab" replace />;
  return <StartStripC variant={variant} />;
}
