# pat-missing-baseline — independent verification evidence

SPEC-506 §5 verification record for golden vector `pat-missing-baseline`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 self-generate → tsduck-analyze** (SPEC-506 §5).
- Generation: TS Core Generator (SPEC-108, ticket #34) with the frozen
  pull-safe geometry recorded in `tools/make_golden_baseline.py`
  (B = 3 008 000, N = 600, PAT 101 ms / PMT 103 ms / PCR 40 ms,
  ES1 256 = B/25 carrying PCR, ES2 257 = B/50, seed 1234567).
- Independent readback — `tsanalyze --json` on the registered bytes: clean
  stream, PID table exactly PAT(1) + PMT(1) + ES 256(29) + ES 257(11) +
  null 554; PCR carriers at slots 80/160/240/320/400/480/560; PAT packets
  at slots 0/202/404, PMT at 1/206/412.
- Note: table repetitions reuse CC 0 (duplicate-section semantics) —
  `tsp -P continuity` reports informational `duplicate packets` on the
  table PIDs (legal repeated identical sections), never a missing/error.
- The four baselines of the first-batch faulted pairs share this config
  and therefore these bytes; each is registered as its own vector id so
  every faulted vector's `fault_plan_ref` addresses its own baseline.
