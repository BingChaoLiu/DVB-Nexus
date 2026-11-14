# DVB Sandbox — TS Core Module Specification Pack

**Package:** `DVB-Sandbox-TS-Core-SPEC-1XX-v0.4.0-draft`  
**Baseline:** DVB Sandbox Spec v0.4  
**Spec range:** `SPEC-100` ～ `SPEC-108`  
**Package status:** `DRAFT_FOR_REVIEW`  
**Created:** 2026-11-13  
**Language:** Chinese specification, English protocol identifiers and code APIs

> 本包是 TS Core 的完整模块级规格初稿，面向架构评审和后续 Agent 实施。它不是标准文本的替代品，也不表示项目负责人已批准所有细节。所有模块 Spec 当前均为 `DRAFT`；批准前不得作为正式编码依据。

## 1. 包含内容

| 文件 | 模块 | 核心范围 |
|---|---|---|
| `SPEC-100-ts-packet.md` | TS Packet | 188-byte Packet、Header、Adaptation Field、编解码、CC 分配 |
| `SPEC-101-mpeg2-crc32.md` | MPEG-2 CRC32 | CRC-32/MPEG-2 计算、校验、增量 API、测试向量 |
| `SPEC-102-psi-section.md` | PSI Section | Section 结构、长度策略、CRC 集成、SectionAssembler |
| `SPEC-103-pat-pmt.md` | PAT / PMT | 表字段、节目/PID 关联、生成、解析、版本与分段 |
| `SPEC-104-pes.md` | PES | PES Header、PTS/DTS、长度规则、PES 分片重组 |
| `SPEC-105-pcr-clock.md` | PCR / Media Clock | 27 MHz 时基、PCR/PTS/DTS 编解码、回绕与精确换算 |
| `SPEC-106-ts-packetizer.md` | TS Packetizer | Section/PES 到 TS Packet 的封装、PUSI、AF stuffing |
| `SPEC-107-ts-mux.md` | TS Mux | CBR packet-slot 调度、表重复、PCR 插入、Null PID |
| `SPEC-108-ts-generator.md` | TS Generator | 配置模型、端到端生成、确定性、输出摘要 |
| `TS-CORE-INTEGRATION-CONTRACT.md` | 集成契约 | 模块依赖、公共类型、跨模块接口、集成顺序 |
| `TRACEABILITY.md` | 需求追踪 | REQ → Spec → 测试 → 交付证据映射 |
| `AGENT-WORK-PACKAGES.md` | Agent 工作包 | 依赖安全的任务拆分、并行边界、建议 Allowlist |
| `test-vectors/CRC32-MPEG2.md` | CRC 测试向量 | 标准算法参数和已知答案测试向量 |
| `test-vectors/PCR-PTS.md` | 时间戳测试向量 | PCR/PTS/DTS 边界和黄金编码样例 |
| `schemas/ts-generator-config.example.json` | 配置样例 | `analysis_only` 最小生成配置 |

## 2. 如何使用

1. 将本目录复制到项目仓库 `docs/modules/ts-core/`（或按仓库约定保留本包根目录）。
2. 先审阅 `TS-CORE-INTEGRATION-CONTRACT.md`，确认跨模块公共接口。
3. 逐份审阅并批准 `SPEC-100`～`SPEC-108`。可按模块独立批准，但下游 Spec 只能在依赖契约冻结后进入实现。
4. 根据 `AGENT-WORK-PACKAGES.md` 创建独立 Agent Task；每个任务必须引用 Spec 版本和 Requirement ID。
5. Agent 开发必须同时遵守基线中的 `SPEC-004 Engineering Standards` 与 `SPEC-005 Agent Development Protocol`。
6. 验收后由项目负责人更新主仓库的 `SPEC-INDEX.md` 和模块注册表状态。

## 3. 本包的关键约束

- MVP 数据包格式固定为 **188-byte MPEG-2 TS**；204-byte RS204 仅列为后续输入/分析扩展，不在本次生成器范围。
- 第一版生成 Profile 固定为 `analysis_only`。不承诺生成可播放的真实 H.264/H.265/AAC Elementary Stream。
- TS Core 是纯协议/算法模块，不依赖 FastAPI、React、SQLite、TSDuck、Artifact Storage 或 WebSocket。
- TSDuck 是外部交叉验证器，不是自研 TS Core 的实现替代品。
- `observedAtUtcMs`、Simulation Clock 与 PCR/PTS/DTS 时间基必须严格分离。
- 任何表/字段的标准符合性结论，必须基于适用版本的 ITU-T H.222.0 / ISO/IEC 13818-1 和相应测试证据。
- 未在本包明确定义的行为不得由 Agent 私自补充为全局约定；应提交 `SPEC_CHANGE_REQUEST`。

## 4. 版本与状态

| 版本 | 状态 | 说明 |
|---|---|---|
| 0.4.0 | DRAFT | 初始完整 TS Core 模块规格包 |

模块内部的算法约束和公开接口以各 Spec 正文为准；本 README 不覆盖模块 Spec。

## 5. 标准参考

- [ITU-T H.222.0 (04/2025), in force](https://www.itu.int/rec/T-REC-H.222.0-202504-I/en) — MPEG-2 Systems / Transport Stream / PES / PCR 的规范性依据。
- [TSDuck User Guide](https://tsduck.io/docs/tsduck.html) — TS 文件格式、tsanalyze、JSON 报告、分析插件和工具行为。
- [TSDuck Developer Guide](https://tsduck.io/docs/tsduck-dev.html) — `ts::TSPacket` 和相关 C++ 数据结构的工程参考。
- [TSDuck TSPacket API](https://tsduck.io/doxy/df/dc6/classts_1_1TSPacket.html) — Packet 字段辅助 API 参考。
- [RFC 4259](https://www.rfc-editor.org/rfc/rfc4259) — 对 PSI/PES 场景中 PUSI 与 Pointer Field 行为的辅助说明；规范性依据仍为 H.222.0。
- [ETSI TR 101 290](https://www.etsi.org/deliver/etsi_tr/101200_101299/101290/01.03.01_60/tr_101290v010301p.pdf) — DVB 传输流测量与诊断参考；PCR 测量门限应由单独的 Analyzer/Conformance Spec 冻结，不在 Packet 编码层硬编码。

## 6. 免责声明与实现责任

本包包含基于公开标准知识整理的工程规格，不复制标准全文。实际实现与认证前，必须使用项目有权访问的适用标准正式文本复核。TSDuck 的行为可作为互操作性参考，但不能代替标准条款和独立测试向量。
