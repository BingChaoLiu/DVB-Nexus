# TS Core Spec Index

**Package version:** 0.5.0  
**Status:** MVP_BASELINE_APPROVED  
**Normative parent:** DVB Sandbox SPEC-001/003/004/005  

| Spec ID | Document | Depends on | MVP priority | Primary output |
|---|---|---|---|---|
| SPEC-100 | [TS Packet](SPEC-100-ts-packet.md) | SPEC-003/004/105 | P0 | 188-byte packet codec, AF model, CCAllocator |
| SPEC-101 | [MPEG-2 CRC32](SPEC-101-mpeg2-crc32.md) | SPEC-004 | P0 | CRC calculate/append/verify |
| SPEC-102 | [PSI Section](SPEC-102-psi-section.md) | SPEC-100/101/004 | P0 | Section parser/serializer/assembler |
| SPEC-103 | [PAT/PMT](SPEC-103-pat-pmt.md) | SPEC-100/101/102/004 | P0 | PAT/PMT builder/parser |
| SPEC-104 | [PES](SPEC-104-pes.md) | SPEC-100/105/004 | P0 | PES parser/serializer/assembler |
| SPEC-105 | [PCR/Clock](SPEC-105-pcr-clock.md) | SPEC-003/004 | P0 | PCR/PTS/DTS codec and media clock primitives |
| SPEC-106 | [TS Packetizer](SPEC-106-ts-packetizer.md) | SPEC-100/102/104/105 | P0 | Section/PES packetization |
| SPEC-107 | [TS Mux](SPEC-107-ts-mux.md) | SPEC-100/105/106 | P0 | CBR packet-slot mux |
| SPEC-108 | [TS Generator](SPEC-108-ts-generator.md) | SPEC-100..107 | P0 | deterministic end-to-end TS generation |

## Dependency graph

```text
SPEC-101 ───────────────┐
                        v
SPEC-102 ─── SPEC-103 ──┐
                        │
SPEC-105 ──┬─ SPEC-100 ─┴─ SPEC-106 ─ SPEC-107 ─┐
          │                                   │
          └─ SPEC-104 ────────────────────────┴─ SPEC-108
```

## Status policy

All entries are `DRAFT` at package creation. When an individual Spec is approved, update its front matter and this index. Do not update any document to `IMPLEMENTED` until code merge, test evidence, and acceptance review are complete.

2026-11-14：SPEC-100~108 与 TS-CORE-INTEGRATION-CONTRACT 经 Wayfinder ticket「ts-core 规格逐份修订批准」逐份修订并批准为 MVP 基线（front-matter `status: APPROVED`、`version: 0.5.0`）。golden 向量补齐（包/section/TS 级）归 conformance ticket，阻塞实现完成而非规格批准。
