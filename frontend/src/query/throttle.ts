// Trailing-edge coalescing for hint-triggered invalidations (SPEC-400 §6.3):
// bursts of same-topic hints collapse into one invalidateQueries per prefix
// within the window. The default window is a pinned constant (250ms — plan
// R5); #64 reuses this hook instead of building a second throttling channel
// (REQ-UI-403-007's throttled refetch lands on this seam).
import type { QueryClient } from "@tanstack/react-query";

export const HINT_THROTTLE_MS = 250;

export interface ThrottledInvalidator {
  invalidate(prefix: readonly unknown[]): void;
  /** Run all pending invalidations now (tests / unmount hygiene). */
  flush(): void;
  pendingCount(): number;
}

export function createThrottledInvalidator(
  queryClient: QueryClient,
  windowMs: number = HINT_THROTTLE_MS,
): ThrottledInvalidator {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const prefixes = new Map<string, readonly unknown[]>();

  const keyOf = (prefix: readonly unknown[]) => JSON.stringify(prefix);

  const run = (key: string) => {
    timers.delete(key);
    const prefix = prefixes.get(key);
    if (prefix) {
      prefixes.delete(key);
      void queryClient.invalidateQueries({ queryKey: [...prefix] });
    }
  };

  return {
    invalidate(prefix) {
      const key = keyOf(prefix);
      if (timers.has(key)) return; // already scheduled inside the window
      prefixes.set(key, prefix);
      timers.set(
        key,
        setTimeout(() => run(key), windowMs),
      );
    },
    flush() {
      for (const key of [...timers.keys()]) {
        const timer = timers.get(key);
        if (timer !== undefined) clearTimeout(timer);
        run(key);
      }
    },
    pendingCount() {
      return timers.size;
    },
  };
}
