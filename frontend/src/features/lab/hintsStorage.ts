// hints persistence seam (SPEC-408 §5 L188, REQ-UI-408-011 / AC-408-06):
// the ONLY localStorage key family in the whole spec —
// `dvb-lab-hints:{scenario_id}` holding the revealed-hint COUNT for that
// scenario. Every function is best-effort and honest: any storage access
// failure (privacy mode, quota, SecurityError) surfaces as available:false /
// false so the UI degrades to page memory and SAYS SO (SPEC-408 §8) instead
// of faking persistence. Reveal state is UI-local fact only — it NEVER
// enters any verify/verdict/evidence path (data flow: storage → UI display,
// one direction). The useHintsReveal hook binds the seam into React: views
// (detail page ladder / console collapsible block) each instantiate it and
// share the SINGLE per-scenario key as their common state source (same-key
// read/write), never a deep link.
import { useCallback, useState } from "react";

const HINTS_STORAGE_PREFIX = "dvb-lab-hints:";

/** Verbatim per-scenario key: `dvb-lab-hints:{scenario_id}` (SPEC-408 §5). */
export function hintsStorageKey(scenarioId: string): string {
  return `${HINTS_STORAGE_PREFIX}${scenarioId}`;
}

export interface HintsStorageRead {
  /** false = localStorage unusable (privacy mode etc.) — the caller must
   * fall back to page memory and disclose 「本地记录不可用，刷新将复位」. */
  available: boolean;
  /** Revealed count when a well-formed record exists; null = absent or
   * corrupted (a corrupted record is ignored, not trusted). */
  stored: number | null;
}

/** Read the revealed-hint count for a scenario (honest availability). */
export function readRevealedHintCount(scenarioId: string): HintsStorageRead {
  try {
    const raw = window.localStorage.getItem(hintsStorageKey(scenarioId));
    if (raw === null || !/^\d+$/.test(raw)) return { available: true, stored: null };
    return { available: true, stored: Number(raw) };
  } catch {
    return { available: false, stored: null };
  }
}

/** Write the revealed-hint count for a scenario; false = storage unusable
 * (caller keeps page memory and discloses the degradation). Non-integer or
 * negative counts are refused without touching the key. */
export function writeRevealedHintCount(scenarioId: string, count: number): boolean {
  if (!Number.isInteger(count) || count < 0) return false;
  try {
    window.localStorage.setItem(hintsStorageKey(scenarioId), String(count));
    return true;
  } catch {
    return false;
  }
}

/** Remove the scenario's record (重做场景可清空). Best-effort: false only
 * means the storage refused — the caller's in-memory reset still applies. */
export function clearRevealedHintCount(scenarioId: string): boolean {
  try {
    window.localStorage.removeItem(hintsStorageKey(scenarioId));
    return true;
  } catch {
    return false;
  }
}

export interface HintsReveal {
  /** Revealed-hint count for the scenario (from the shared key). */
  count: number;
  /** false = localStorage unusable — the UI must disclose the degradation
   * (counts live in page memory only, refresh resets them). */
  storageOk: boolean;
  /** 揭示下一条: increments the count with write-through to the key. */
  revealNext: () => void;
  /** 重置提示: wipes the key and zeroes the count. */
  resetHints: () => void;
}

/** React binding over the seam. Views mount per scenario (Region keys them
 * by scenarioId/sessionId), so the lazy initializer IS the hydration point
 * (刷新不丢): it reads the shared key once; every mutation writes through
 * and updates the mirror. No effects, no render-phase storage reads. */
export function useHintsReveal(scenarioId: string): HintsReveal {
  const [state, setState] = useState<{ storageOk: boolean; count: number }>(() => {
    const record = readRevealedHintCount(scenarioId);
    return { storageOk: record.available, count: record.available ? record.stored ?? 0 : 0 };
  });

  const revealNext = useCallback(() => {
    const next = state.count + 1;
    if (writeRevealedHintCount(scenarioId, next)) {
      setState({ storageOk: state.storageOk, count: next });
      return;
    }
    // Refused write → degrade to page memory with the disclosure; the count
    // stays usable for this page life (honest, never faked as persisted).
    setState({ storageOk: false, count: next });
  }, [scenarioId, state.count, state.storageOk]);

  const resetHints = useCallback(() => {
    const cleared = clearRevealedHintCount(scenarioId);
    setState((prev) => ({ storageOk: prev.storageOk && cleared, count: 0 }));
  }, [scenarioId]);

  return { count: state.count, storageOk: state.storageOk, revealNext, resetHints };
}
