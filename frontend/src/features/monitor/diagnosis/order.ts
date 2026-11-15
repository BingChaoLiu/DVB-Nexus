// SPEC-307 §5 ordering matrix as a pure comparator (SPEC-403 §7.3,
// REQ-UI-403-004 / AC-403-04): priority ascending -> severity descending
// (critical first) -> code lexicographic. No other sort key is allowed; the
// server's already-sorted output passes through unchanged (idempotent).
// The confidence three-tier ban (CONTEXT.md 诊断) makes confidence a
// display-only enum — it is deliberately NOT a sort key.

/** Severity weight for the descending comparison: critical sorts first. */
export const SEVERITY_RANK = { info: 1, warning: 2, error: 3, critical: 4 } as const;

export interface OrderableDiagnosis {
  code: string;
  severity: string;
  /** Candidate DTOs carry priority; table rows may not — absent sorts last. */
  priority?: number;
}

function severityWeight(severity: string): number {
  const weight = SEVERITY_RANK[severity as keyof typeof SEVERITY_RANK];
  // Unknown severity strings degrade to below info (defensive; the wire
  // vocabulary is the four-tier closed set).
  return weight ?? 0;
}

export function orderDiagnoses<T extends OrderableDiagnosis>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => {
    const pa = a.priority ?? Number.POSITIVE_INFINITY;
    const pb = b.priority ?? Number.POSITIVE_INFINITY;
    if (pa !== pb) return pa - pb;
    const sa = severityWeight(a.severity);
    const sb = severityWeight(b.severity);
    if (sa !== sb) return sb - sa;
    if (a.code !== b.code) return a.code < b.code ? -1 : 1;
    return 0; // stable: equal keys keep input order
  });
}
