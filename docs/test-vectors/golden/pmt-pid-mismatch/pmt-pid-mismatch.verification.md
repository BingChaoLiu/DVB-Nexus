# pmt-pid-mismatch — independent verification evidence

SPEC-506 §5 verification record for golden vector `pmt-pid-mismatch`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 independent-transform → tsduck-analyze**
  (SPEC-204 §6.4: PAT program_map_PID 4096 → 4100 with reserved bits kept
  and the PAT CRC recomputed — PAT stays valid, symptom is "points wrong").
- Independent readback — `tstables pmt-pid-mismatch.ts` (excerpts):

```
* PAT, TID 0x00 (0), PID 0x0000 (0)
    Program:     1 (0x0001)  PID: 4100 (0x1004)     <- repointed

* PMT, TID 0x02 (2), PID 0x1000 (4096)              <- real PMT, orphaned
    Program: 0x0001 (1), PCR PID: 0x0100 (256)
```

- `tsp -P continuity` on the faulted stream reports nothing beyond the
  baseline's informational table duplicates — the symptom is
  single-attributable (PAT content), no secondary continuity damage.
- Self-parse side: the pair test re-parses the faulted PAT (CRC verified
  via `verify_mpeg2_crc32`), asserts program 1 -> 4100, the untouched PMT
  packets on 4096, and that PID 4100 carries no packets.
