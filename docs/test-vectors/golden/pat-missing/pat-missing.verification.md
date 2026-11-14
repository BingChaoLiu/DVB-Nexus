# pat-missing — independent verification evidence

SPEC-506 §5 verification record for golden vector `pat-missing`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 independent-transform → tsduck-analyze**
  (SPEC-506 §7: faulted bytes come from `tools/golden_fault_transform.py`,
  a byte-level transform of the registered baseline — no Generator, no
  filter; SPEC-204 §6.1 semantics, window = activation slot 202 → end).
- Independent readback — `tsanalyze` PID 0x0000 packet count:

```
baseline : Packets: 3   (slots 0, 202, 404)
faulted  : Packets: 1   (slot 0 only — PAT stops at the activation window)
```

- The conformance pair test additionally verifies the slot frame: the two
  replaced slots (202, 404) hold canonical Null packets; every other slot
  is byte-identical to the baseline.
