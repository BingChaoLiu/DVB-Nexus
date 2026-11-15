// QueryClient posture (SPEC-400 §4.3): server state lives in the query cache;
// freshness arrives via WS-triggered invalidation (the bridge), so window
// refetching and aggressive retries are off. staleTime 0 keeps REST refetches
// cheap-correct; specific features tune per query where warranted.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 0,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

export function AppQueryProvider({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [memoClient] = useState(() => client ?? createAppQueryClient());
  return <QueryClientProvider client={memoClient}>{children}</QueryClientProvider>;
}
