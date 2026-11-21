---
spec_id: SPEC-506
title: Conformance Suite
version: 0.7.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-108]
requirements: [REQ-CNF-506-001, REQ-CNF-506-002, REQ-CNF-506-003, REQ-CNF-506-004, REQ-CNF-506-005, REQ-CNF-506-006]
---

# SPEC-506 — Conformance Suite

## 1. 目标

MPEG-TS 标准测试向量与 golden streams 的**管理机制与验收策略**：目录结构、登记格式、三层来源验收地位、独立验证规则、CI 门（含 TSDuck 安装策略）与批准/失效流程。0.5.0（ticket #13 Q6）只定机制骨架；0.6.0 并入 golden streams 与 conformance 策略票据（[#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）的全部裁决：向量内容、首批清单、来源分层、CI 行为与生命周期粒度，本版即为权威。0.7.0（ticket #172）最小 additive 修订：新增 `state_eval` 向量类型承载 Phase 3 state 域向量转正（机制零变更——三件套/sha 身份/独立验证红线/CI 门全部沿用）。

## 2. 范围

### 2.1 In Scope

- golden 向量目录布局与三件套。
- 登记格式与索引（含 `verification` 字段与 status 流转）。
- 独立验证红线与三层来源验收地位（#14）。
- 首批 golden 清单与覆盖口径（#14）。
- CI 门、TSDuck 安装策略与 NOT RUN 兜底语义（#14）。
- 向量生命周期（批准粒度、身份与重验触发，#14）。

### 2.2 Out of Scope

- 性能基准（SPEC-507，P1）。
- 向量自动生成流水线（#14 裁决：**不做**，见 §6）。
- 首批向量字节实体的产出与登记执行（实现期按 §7 清单逐条入库，#14 只裁决内容与路径）。

## 3. golden 目录布局（#14：仓库级迁移）

```
docs/test-vectors/
├── TEST-VECTOR-INDEX.md              # 权威索引（位级文档 + golden 三件套清单）
├── CRC32-MPEG2.md / PCR-PTS.md       # 既有位级向量文档（随 0.6.0 迁出规格包）
└── golden/<vector_id>/
    ├── <vector_id>.ts                # 字节（TS 流或位级样本；state_eval 向量
    │                                 #  为向量表的 canonical JSON 序列化，见 §4）
    ├── manifest.json                 # 机器可读登记（§4）
    └── expectations.json             # 期望观测（§4）
```

- 0.5.0 曾将本目录置于规格包内；0.6.0 迁至仓库级（#14：测试资产不是规格归档内容，归档包保持 pristine 精神）。
- 三件套缺一不予登记。
- `vector_id` 语义 slug（如 `pat-minimal`、`cc-discontinuity`），全局唯一。
- 0.7.0（#172）：`state_eval` 向量的数据文件承载向量表的 **canonical JSON 序列化**（`json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` + 尾随换行，UTF-8，LF 换行）——sha256 对该字节序列计算，即身份；canonical 形由 conformance 测试往返钉扎。

## 4. 登记格式

**manifest.json**（机器可读，conformance 测试与 golden_loader 消费）：

```json
{
  "vector_id": "pat-minimal",
  "kind": "generated_ts | faulted_ts | bit_level | state_eval",
  "related_specs": ["SPEC-103", "SPEC-108"],
  "generator_version": "tsduck 3.45-4798（外源 provenance；自研生成时为 Generator 版本）",
  "config_hash": "sha256:...",
  "sha256": "文件内容 SHA-256",
  "packet_count": 1500,
  "fault_plan_ref": null,
  "verification": {
    "path": "tsduck-cross | bit-level-review",
    "direction": "tsduck-generate→self-parse | self-generate→tsduck-analyze",
    "evidence_ref": "docs/research/... 实测报告锚点"
  }
}
```

**expectations.json**（期望观测，与 FaultDefinition `expected_observations` **同构互证**——[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 5 条字段结构）：

```json
{
  "expectations": [
    {"event_type": "ts.psi_section_observed", "locator": {"pid": 0}},
    {"event_type": "ts.continuity_error", "locator": {"pid": 256, "packet_index": 12000}}
  ]
}
```

- 等位替换 golden：baseline 与 faulted 向量**共用包序 frame**（packet_index 同槽位，ADR-0007 第 4 条）；faulted 向量 `fault_plan_ref` 指向对应 baseline。
- `TEST-VECTOR-INDEX.md` 每行指向 golden 目录，标注 status（`planned / registered / deprecated`）。
- `generator_version`/`config_hash` 对外源向量仅为 **provenance 记录**，不是有效性判据（§6 重验条款，#14）。
- 0.7.0（#172）`state_eval` 语义：Phase 3 state 域向量（L0 求值纯函数的规格表转录——逐格真值表/逐位帧布局/公式数值）。数据文件 = 向量表 canonical JSON（§3）；expectations 条目的 `event_type` 标向量事实所属的 SPEC-301 §4 家族面（state 域 = `rf.state_observed`/`sec.state_observed`），`locator`/`detail` 承载向量行标识与期望字段；`packet_count`/`config_hash`/`fault_plan_ref` 为 null（state 域无码流/无 config 指纹/无 fault 对）。conformance 消费面 = 生产纯函数对拍 golden 表（如 `select_band`/`build_tuning_message`/`t_value`）。

## 5. 独立验证红线与三层来源地位（#14）

TEST-VECTOR-INDEX 既有规则**升格为规格条款**：

> golden 文件不得仅因同一实现解析自身输出而接受——至少一条**独立验证路径**（TSDuck 双向交叉分析，或独立评审的位级向量）。

三层来源的验收地位（#14 Q1）：

| 层 | 内容 | 验收地位 |
|---|---|---|
| L1 外部位级向量 | 标准条款表格人工推导（`CRC32-MPEG2.md`/`PCR-PTS.md` 模式） | **权威基准**：算法级正确性验收证据，独立评审推导脚本即可，无需 TSDuck |
| L2 TSDuck 交叉验证 | **双向均算**：自研生成→TSDuck 分析；TSDuck 生成（tstabcomp）→自研解析 | **合格独立验证路径**：满足红线，可作登记验证证据 |
| L3 自研 round-trip | Generator 产出→自家解析器解析 | **仅回归覆盖**：永不构成独立验收证据 |

- 独立验证证据（方向 + 工具版本 + 报告锚点）登记进 manifest `verification` 字段（实现期细化字段 schema）。
- 同源自证 = 登记拒绝。
- 0.7.0（#172）`state_eval` 向量的独立验证路径：TSDuck 交叉不适用（state 域无码流）——走 **L1 规格表权威推导**（normative 表逐格/逐位/逐例转录，无 src 参与；`bit-level-review` 登记路径家族），并要求实现侧存在**第二独立转录**互证（向量先钉纪律的测试常量）+ conformance 生产纯函数对拍（实现对拍规格转录，非自身输出）。

## 6. CI 门与向量生命周期（#14）

- conformance 层测试（SPEC-505 §3）加载**全部 registered 向量**：SHA-256 校验 + expectations 断言（经 SPEC-305 查询或 journal 重放取得观测）。
- **CI TSDuck 主路径**：Windows CI job 安装 TSDuck（winget 官方包 `TSDuck.TSDuck`，静默安装；`tsp --version` 输出记录进日志）。`tsduck` 标记测试在 CI **全量跑**，不是可选项；**安装失败 = CI 失败**（基础设施故障，不算 skip）。调研底档（#14）：winget 静默开关 `/S /all=true`，BSD-2 无许可障碍；Linux 侧走 release 直链 .deb。
- **NOT RUN 兜底语义（仅本地开发者机器）**：TSDuck 缺失 → SPEC-505 `tsduck` fixture 探测 skip（理由显式可见）；conformance 汇总报告对应向量标 **NOT RUN**，以独立区块呈现，永不计入 PASS、不冒绿。
- **向量变更 = 重新登记 + 批准**：字节变了就是新 vector_id（或同 id bump 内容并重走批准），sha256/manifest/expectations 三者必须一致；失效向量标 `deprecated` 不删除（provenance 纪律），被依赖方迁移后清理。
- **批准粒度（#14 Q5）**：首批按 §7 清单打包预批准（#14 裁决即授权）；此后新增向量逐条走流程：提案 → 独立验证证据 → 三件套登记 → PR review 批准入索引。
- **向量身份与重验触发（#14 Q8）**：有效性 = sha256 字节不变 + expectations 与现行规格一致；重验触发仅两类——(a) expectations 依赖的规格变更（SPEC-301 事件注册表 / SPEC-204 故障语义 / SPEC-307 规则集），(b) 显式 deprecated。TSDuck 版本升级、Generator 版本升级**不**自动触发重验（Generator 的 conformance 走 expectations 断言，与 golden 字节无耦合）。
- **无自动生成流水线（#14 Q7）**：向量是冻结资产（sha256 即身份），不是可再生成的构建产物。tools/ 下脚本确定性构造（同脚本 + 同版本 + 同参数 ⇒ 同字节），人工评审后**入库提交**；CI 只验 sha 一致，**永不重新生成覆盖**；字节漂移走重登记流程。

## 7. 首批 golden 清单（#14 Q2，裁决即批准）

10 条目 / 14 个字节文件：

| # | vector_id | kind | 内容 | related_specs | 验证路径 |
|---|---|---|---|---|---|
| 1 | `packet-header-set` | bit_level | 188-byte 包头样本集（TEI/PUSI/优先级/CC 边沿） | SPEC-100 | L1：spec 表推导脚本 + 人工评审 |
| 2 | `pat-minimal` | generated_ts | 最小合法 TS（PAT+PMT 单节目，~50 包） | SPEC-103/108 | L2：tstabcomp 生成→自研解析 |
| 3 | `pat-pmt-multi` | generated_ts | PAT/PMT 变体：双节目、多流类型 | SPEC-103/108 | L2：tstabcomp 生成→自研解析 |
| 4 | `cc-wrap` | generated_ts | CC 15→0 回绕序列（单 PID ≥17 payload 包） | SPEC-100 §5.4 | L2：脚本构造→TSDuck analyze |
| 5 | `pcr-wrap` | generated_ts | PCR 回绕边界（2³³−δ 前后手工置值 + modular_delta 半周期窗口），不做真实长流 | SPEC-105 | L2：脚本构造→TSDuck analyze |
| 6 | `section-fragmentation` | generated_ts | PUSI/pointer、section 跨 3 包 | SPEC-102/106 | L2：脚本构造→TSDuck analyze |
| 7 | `pat-missing` | faulted_ts 对 | PAT_MISSING：Null 包顶替窗口（§6.1 变换语义） | SPEC-204 | L2：独立变换脚本→TSDuck 复核 |
| 8 | `pmt-invalid-crc` | faulted_ts 对 | PMT_INVALID_CRC：persistent/invert | SPEC-204 | 同上 |
| 9 | `cc-discontinuity` | faulted_ts 对 | CC_DISCONTINUITY：相对偏移持续 | SPEC-204 | 同上 |
| 10 | `pmt-pid-mismatch` | faulted_ts 对 | PMT_PID_MISMATCH：PAT CRC 重算 | SPEC-204 | 同上 |

- **faulted 向量字节由 tools/ 独立变换脚本从 baseline 生成**（变换照 SPEC-204 §6/§7 冻结语义，不经自研 Generator、不经过滤器），兼任**过滤器集成测试的字节级 oracle**（过滤器输出 SHA 与 golden faulted 一致断言）。
- 自研 Generator（SPEC-108）实现后，对同配置流断言**同一 expectations 可观测**，不做字节比对（不同 muxer 决策字节必然不同）。
- **畸形输入集不入 golden**（expectations 机制只承载正向观测断言）：落 `tests/data/malformed/`，unit 层测试（SPEC-102 错误码、SPEC-308 JSON 内容门），自带 README 注明来源。
- TEST-VECTOR-INDEX.md 相应行随向量入库 `planned → registered` 逐行更新。

## 8. 测试规格

- 登记校验器：三件套完整性、SHA 一致性、事件类型合法性（SPEC-301 §4 注册表，对齐 SPEC-307 §8）。
- golden_loader round-trip：manifest ↔ 文件 ↔ expectations 一致。
- 等位替换向量对：baseline/faulted packet_index 同槽位断言。
- 过滤器 oracle：integration 层过滤器输出 SHA 与 golden faulted 一致（§7 faulted 对）。
- 全量加载门：CI conformance 层零静默跳过；NOT RUN 仅出现在本地 TSDuck 缺失场景且以独立区块呈现（§6）。

## 9. 验收标准

- `REQ-CNF-506-001`：golden 三件套目录布局与登记格式落地，缺一拒绝。
- `REQ-CNF-506-002`：独立验证红线生效（同源自证拒绝），三层来源地位按 §5 执行。
- `REQ-CNF-506-003`：CI 门加载全量 registered 向量（SHA + expectations 断言）。
- `REQ-CNF-506-004`：向量生命周期（变更重登记、deprecated 标记、批准粒度）可执行。
- `REQ-CNF-506-005`：首批 §7 清单（10 条目）按 planned→registered 流转入库，畸形输入集落 `tests/data/malformed/`。
- `REQ-CNF-506-006`：CI 安装 TSDuck 全量跑（安装失败即 CI 失败）；本地缺失走 NOT RUN 显式语义，不冒绿。

## 10. 非目标与风险

- 不做向量自动生成流水线（#14 裁决）；不做覆盖率数字目标。
- 0.5.0 风险条款"生成器版本耦合"已解决：向量身份 = sha256（字节冻结），generator 字段仅 provenance，重验触发见 §6。
- 新风险：CI TSDuck 安装依赖 winget 源可用性——安装失败即 CI 失败（fail-fast，不静默降级）；必要时换用 release 直链安装（#14 调研底档）。
- 风险：向量与规格语义耦合（expectations 依赖 SPEC-301/204/307）——规格变更触发重验已入 §6 条款。

## 11. 交付要求

- `docs/test-vectors/`（仓库级：索引 + 位级向量文档 + `golden/` 三件套目录）。
- 构造/变换脚本入 `tools/`（确定性、可重跑、人工评审后产物入库）。
- golden_loader 入 `tests/conformance/golden_loader.py`（SPEC-505 fixture 体系）；登记校验器入 `tools/`。

## 12. 参考

- `docs/test-vectors/TEST-VECTOR-INDEX.md`（仓库级权威索引，0.6.0 起承载 §7 首批清单）。
- SPEC-505（conformance 测试层与 golden_loader fixture）、SPEC-108（生成器版本与 config_hash）。
- [ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 4/5 条（共用包序 frame、expected_observations 同构）。
- golden streams 与 conformance 策略票据（[#14](https://github.com/BingChaoLiu/DVB-Nexus/issues/14)）——0.6.0 全部修订的决议来源；TSDuck CI 安装调研底档见该票决议评论（tsduck.io/tsduck-binaries、winget-pkgs `TSDuck.TSDuck`）。
