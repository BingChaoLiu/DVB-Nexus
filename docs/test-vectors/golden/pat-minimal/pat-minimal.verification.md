# pat-minimal — independent verification evidence

SPEC-506 §5 verification record for golden vector `pat-minimal`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 tsduck-generate → self-parse** (SPEC-506 §5).
- Generation chain (ticket #3 实测): tsxml sources
  `tools/tsduck-tsxml/pat-minimal-*.xml` → `tstabcomp --output <bin> <xml>`
  → `tsp -I null 50 -P inject -p 0x0 --inter-packet 100 --stuffing
  <pat.bin> -P inject -p 0x1000 --inter-packet 100 --stuffing <pmt.bin>
  -O file pat-minimal.ts`.
- Independent readback — `tstables pat-minimal.ts`:

```

* PAT, TID 0x00 (0), PID 0x0000 (0)
  Version: 0, sections: 1, total size: 16 bytes
  - Section 0:
    TS id:       1 (0x0001)
    Program:     1 (0x0001)  PID: 4096 (0x1000)

* PMT, TID 0x02 (2), PID 0x1000 (4096)
  Version: 0, sections: 1, total size: 21 bytes
  - Section 0:
    Program: 0x0001 (1), PCR PID: 0x0100 (256)
    Elementary stream: type 0x1B (AVC video), PID: 0x0101 (257)
```

- Self-parse side: conformance test reassembles PAT/PMT with the
  SectionAssembler and asserts the same program/PMT-PID/PCR-PID/ES values.
