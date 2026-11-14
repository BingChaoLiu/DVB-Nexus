# section-fragmentation — independent verification evidence

SPEC-506 §5 verification record for golden vector `section-fragmentation`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 script-construct → tsduck-analyze** (SPEC-506 §5).
- Construction: `tools/make_golden_ts_vectors.py section-fragmentation` —
  a 100-program PAT (412-byte section, own CRC-32/MPEG-2 implementation
  checked against the published `123456789` → `0x0376E6E7` check value)
  spanning 3 packets (pointer_field 0 + PUSI on packet 0).
- Independent readback — `tstables section-fragmentation.ts` reassembles
  the full 412-byte table across the 3 packets (excerpts):

```

* PAT, TID 0x00 (0), PID 0x0000 (0)
  Version: 0, sections: 1, total size: 412 bytes
  - Section 0:
    TS id:       1 (0x0001)
    Program:     1 (0x0001)  PID:  257 (0x0101)
    Program:     2 (0x0002)  PID:  258 (0x0102)
… (100 program entries) …
    Program:    98 (0x0062)  PID:  354 (0x0162)
    Program:    99 (0x0063)  PID:  355 (0x0163)
    Program:   100 (0x0064)  PID:  356 (0x0164)
```

- Self-parse side: the SectionAssembler rebuilds one 412-byte section and
  `parse_pat_sections` returns all 100 programs.
