# pat-pmt-multi — independent verification evidence

SPEC-506 §5 verification record for golden vector `pat-pmt-multi`.
Tool: tsp (TSDuck - The MPEG Transport Stream Toolkit) 3.40-4165 (local reference machine; CI installs its own TSDuck — version drift never invalidates the frozen sha256, #14 Q8).

- Verification path: **L2 tsduck-generate → self-parse** (SPEC-506 §5).
- Generation chain: tsxml sources `tools/tsduck-tsxml/pat-multi-*.xml`
  (2 programs, 4 stream types 0x1B/0x0F/0x02/0x03) → `tstabcomp` →
  `tsp -I null 60 -P inject -p 0x0 ... -P inject -p 0x1000 ... -P inject
  -p 0x1100 ... -O file pat-pmt-multi.ts`.
- Independent readback — `tstables pat-pmt-multi.ts` (excerpts):

```

* PAT, TID 0x00 (0), PID 0x0000 (0)
  Version: 0, sections: 1, total size: 20 bytes
  - Section 0:
    TS id:       1 (0x0001)
    Program:     1 (0x0001)  PID: 4096 (0x1000)
    Program:     2 (0x0002)  PID: 4352 (0x1100)

* PMT, TID 0x02 (2), PID 0x1000 (4096)
  Version: 0, sections: 1, total size: 26 bytes
  - Section 0:
    Program: 0x0001 (1), PCR PID: 0x0100 (256)
    Elementary stream: type 0x1B (AVC video), PID: 0x0101 (257)
    Elementary stream: type 0x0F (MPEG-2 AAC Audio), PID: 0x0102 (258)

* PMT, TID 0x02 (2), PID 0x1100 (4352)
  Version: 0, sections: 1, total size: 26 bytes
  - Section 0:
    Program: 0x0002 (2), PCR PID: 0x0110 (272)
    Elementary stream: type 0x02 (MPEG-2 Video), PID: 0x0111 (273)
    Elementary stream: type 0x03 (MPEG-1 Audio), PID: 0x0112 (274)
```

- Self-parse side: conformance test parses PAT (2 programs) and both PMTs
  (4 ES entries) with the self parser and asserts identical values.
