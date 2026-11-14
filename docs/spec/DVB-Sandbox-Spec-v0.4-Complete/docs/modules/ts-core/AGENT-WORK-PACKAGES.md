# TS Core Agent Work Packages

**Status:** DRAFT_PLAN  
**Rule:** 这是推荐拆分方案，不构成开发授权。只有对应 Module Spec 被标记 `APPROVED` 且项目负责人创建 TASK-ID 后，Agent 才能正式编码。

## 1. 并行原则

- 所有 Agent 读取 SPEC-001/003/004/005 和 `TS-CORE-INTEGRATION-CONTRACT.md`。
- 先冻结共享接口，再并行实现互不覆盖的源文件。
- 任何两个并行任务不能同时拥有同一个公共接口文件的写权限。
- 上游依赖未合并时，下游可使用 Spec 明确的 Fake/Fixture，但不得擅自改变接口。
- Agent 必须先提交 Implementation Plan，经负责人批准后编码。

## 2. 推荐开发批次

### Batch A — 独立基础原语（接口评审通过后并行）

| 建议 Task ID | Spec | 工作包 | 建议 Allowlist |
|---|---|---|---|
| TASK-TS-101 | SPEC-101 | MPEG-2 CRC32 | `app/ts/crc.py`, `tests/unit/ts/test_crc.py` |
| TASK-TS-105 | SPEC-105 | PCR/PTS/DTS/MediaClock primitives（不依赖 TSPacket） | `app/ts/clock.py`, `pcr.py`, `timestamp.py`, `tests/unit/ts/test_clock.py` |

### Batch A2 — Packet 基础层（SPEC-105 PCR value type 接口冻结后）

| 建议 Task ID | Spec | 工作包 | 建议 Allowlist |
|---|---|---|---|
| TASK-TS-100 | SPEC-100 | TSPacket / Adaptation Field / CCAllocator | `app/ts/packet.py`, `adaptation_field.py`, `cc.py`, `tests/unit/ts/test_packet.py` |

### Batch B — 结构层（依赖 Batch A 接口冻结）

| 建议 Task ID | Spec | 工作包 | 建议 Allowlist |
|---|---|---|---|
| TASK-TS-102 | SPEC-102 | Section Parser / Serializer / Assembler | `app/ts/section.py`, `section_assembler.py`, `tests/unit/ts/test_section.py` |
| TASK-TS-104 | SPEC-104 | PES Parser / Serializer / Assembler | `app/ts/pes.py`, `pes_assembler.py`, `tests/unit/ts/test_pes.py` |

### Batch C — PSI/PID 关联和 Packetizer

| 建议 Task ID | Spec | 工作包 | 建议 Allowlist |
|---|---|---|---|
| TASK-TS-103 | SPEC-103 | PAT/PMT Builders / Parsers | `app/ts/tables/pat.py`, `pmt.py`, `table_validation.py`, tests |
| TASK-TS-106 | SPEC-106 | Section/PES Packetizer | `app/ts/packetizer/`, tests |

SPEC-103 与 SPEC-106 均依赖已冻结的 Section/Packet API。若两者并行，必须使用相同批准版本的 SPEC-102/SPEC-100 契约。

### Batch D — Mux 与 Generator

| 建议 Task ID | Spec | 工作包 | 建议 Allowlist |
|---|---|---|---|
| TASK-TS-107 | SPEC-107 | Mux scheduler / Null Packet / PCR scheduling | `app/ts/mux/`, tests |
| TASK-TS-108 | SPEC-108 | Generator config / source / orchestration | `app/ts/generator/`, tests, example config |

SPEC-108 依赖 103/104/106/107 完成接口。不得把 TS 字段编解码复制进 Generator。

### Batch E — Integration Owner

| 建议 Task ID | 范围 | 职责 |
|---|---|---|
| TASK-TS-INT | 集成 | 跨模块端到端 fixture、TSDuck `tsanalyze --json` 实测、差异报告、修复接口集成问题 |

集成任务可由主 Agent/架构 Agent 负责，不建议交给同时负责某个底层模块的 Agent 自行判定自己的合规性。

## 3. 每个 Agent 需要提交

- Implementation Plan（开始前）。
- 变更文件列表（不得越过 Allowlist）。
- 对应 Requirement ID 实现情况。
- 单元/边界/属性测试结果。
- 运行过的测试命令和原始摘要。
- Spec Deviation（None 或逐项记录）。
- Known Issues / Blockers。
- `IMPLEMENTATION_REPORT.md`。

## 4. 推荐合并顺序

`SPEC-101 + SPEC-105 + SPEC-100` → `SPEC-102 + SPEC-104` → `SPEC-103 + SPEC-106` → `SPEC-107` → `SPEC-108` → End-to-End / TSDuck validation。

SPEC-100 依赖 SPEC-105 提供的唯一 `PCR` 数据类型；SPEC-105 不得反向导入 `TSPacket`，从而保持无循环依赖。PCR 6-byte 编码唯一由 SPEC-105 负责。
