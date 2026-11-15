// Runtime environment derivations (SPEC-400 §4.1: same-origin posture).
// The SPA is served behind the same origin as the API (dev/preview: the Vite
// proxy; production deployment: whatever reverse proxy fronts the stack), so
// the default API base is empty and WS derives from the page location.

export function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
}

export interface LocationLike {
  protocol: string;
  host: string;
}

export function wsBaseFromLocation(loc: LocationLike): string {
  const scheme = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${loc.host}/ws/v1`;
}
