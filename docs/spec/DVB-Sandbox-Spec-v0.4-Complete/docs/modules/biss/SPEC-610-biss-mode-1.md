---
spec_id: SPEC-610
title: BISS Mode 1（加扰与解扰接口）
version: 0.5.1
status: APPROVED
phase: P2
owner: BISS
priority: P2
depends_on: [SPEC-100, SPEC-204, SPEC-301]
requirements: [REQ-610-001, REQ-610-002, REQ-610-003, REQ-610-004, REQ-610-005]
---

# SPEC-610 — BISS Mode 1（加扰与解扰接口）

## 1. 目标

定义 **BISS Mode 1** 的加扰（构造侧）与解扰验证（观测侧）接口：底层算法 = DVB-CSA1（libdvbcsa）+ DES（session word 加密）。靶场 C1（BISS 密钥错位）的语义主场。管线接入 = ADR-0007 包级 payload 过滤器（「加扰器」过滤器类型，[细裁 #109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109) 裁决）。

依据：[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)（libdvbcsa MSYS2 本地编译 + ctypes 绑定向量 2/2 PASS；SSE2 batch API 497 Mbps 7.5 倍余量；TSDuck descrambler 不支持 BISS 留证）、[#109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109)、[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)（BISS_KEY_MISMATCH 原语）、[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)（biss.* 事件）；标准权威 = EBU Tech 3292（免费原文，已留档）与 ITU-T J.96（向量）。

## 2. 范围

### 2.1 In Scope

- 加扰接口：TS 包 payload 域加扰（包头 4 字节 clear、包长 188 不变、包序不变）。
- 解扰与验证：按声明密钥解扰 + 结构自检（解扰成功/失败证据面）。
- 密钥面：session word（12 位十六进制 = 48-bit，roadmap §4 C1 订正口径；**非**「16 字节密钥」旧说）；CW 派生（SW → 奇偶 CW，公式照 Tech 3292/J.96，[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106) 三实现交叉印证）。
- 场景文档 `biss` 段（camelCase wire）与 fault plan 错配参数的 wire 字段（[#109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109) Q3）。
- `biss.scramble_applied` / `biss.descramble_failed` 事件 payload（[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)）。
- mutation log 密钥指纹语义（哈希前缀，不落密钥本体）。
- libdvbcsa 适配器契约（dlopen + ctypes，DLL 缺失显式降级）。

### 2.2 Out of Scope

- Mode E/BISS2 面（SPEC-611）；DVB-CA/ECM/EMM（SPEC-612，Phase 3+）；诊断规则细节（SPEC-307 declarations 机制承载，[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)）；前端渲染（SPEC-404 修订，#119）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| Session Word | BISS Mode 1 密钥：12 位十六进制（48-bit）；CW 派生输入 |
| 加扰器（Scrambler） | ADR-0007 语义流式过滤器架构内的包级 payload 变换过滤器类型（构造特性与 fault 注入共用，密钥来源不同） |
| 密钥指纹 | 密钥的哈希前缀（进 mutation log/事件），密钥本体不落日志 |
| 结构自检 | 解扰后对 TS 包的完整性检查（CRC/字段合法性）——解扰失败的证据形态 |
| pid_scope | 加扰适用 PID 范围（场景声明/fault 参数） |
| CA_PID 0x1FFF | BISS 无 ECM 的固定值（Tech 3292；C2 语境区分依据） |

## 4. 架构

- **管线接入**（#109 Q2）：BISS 加扰 = 逐包 payload 变换——包头不动、包长不变、包序不变，`apply(index, packet)` 契约原样适用；构造特性（场景声明密钥）与 fault 注入（FaultDefinition.params 错配密钥）驱动同一过滤器。
- **适配器**（#109 Q1）：`src/adapters` 内 dvbcsa 适配器 = dlopen + ctypes 封装 libdvbcsa（SSE2 batch API），DLL 缺失显式降级错误（诚实态，不静默）；DES 面走 pycryptodome。
- 事件经进程内桥进信封注册表（biss.*，additive）。
- BISS 层原语（layer="BISS"，#111）经作用层路由实例化。

## 5. 数据模型

- `BissMode1ConfigDTO`（场景文档 biss 段，camelCase）：`mode: "1" / session_word: string(12 hex) / pid_scope: [int] / ca_pid: 0x1FFF（常量语义标注）`。
- Fault 参数（BISS_KEY_MISMATCH）：`wrong_session_word: string(12 hex) / pid_scope`。
- `biss.scramble_applied` payload：`pid_scope / packet_count / key_fingerprint / mutation_log_ref`。
- `biss.descramble_failed` payload：`pid_scope / failed_indices_sample / self_check_kind / key_fingerprint_ref`（声明密钥指纹引用，错配证据互链）。

## 6. 公开接口（接口级契约）

- `biss1.scramble(packets, session_word, pid_scope) -> packets`：确定性；payload 域变换；等位替换不变式维持（同 index 同包数同长度）。
- `biss1.descramble(packets, session_word, pid_scope) -> (packets, self_check_results)`：解扰 + 结构自检逐包结果。
- `biss1.derive_cw(session_word) -> (odd_cw, even_cw)`：公式照 Tech 3292/J.96（golden 钉扎）。
- `biss1.key_fingerprint(key) -> str`：哈希前缀（进日志/事件）。
- 事件发射：`biss.*` 两事件（#113 命名空间）。

## 7. 处理算法（接口级行为义务）

- 加扰确定性：同流同密钥同 pid_scope → 同输出（CSA transport mode 批次边界语义由 libdvbcsa batch API 承载，包粒度不变式不受影响；批次细节 golden 钉扎）。
- 解扰失败 ≠ 码流损坏：错密钥解扰的产物特征（结构自检失败）与真实传输损伤（丢包/位翻转）显式区分（C1 教学核心，#109 Q4）。
- faulted run：错配密钥仅作用于 faulted 支路（tee 双写骨架不变）；baseline 用声明密钥。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| libdvbcsa DLL 缺失 | 显式降级错误（启动/prepare 时报告，不静默回落）——CI 上对应测试 NOT RUN（#109 Q5，照 SPEC-506 先例） |
| session word 格式非法（非 12 hex） | prepare 前拒绝（schema 校验） |
| 解扰后结构自检失败 | biss.descramble_failed 证据（候选 ≠ 事实；诊断规则归 SPEC-307 机制） |
| pid_scope 含不存在的 PID | prepare 前拒绝或显式警告态（实现票裁量，落 REGISTER schema） |

## 9. 资源约束

- 性能预算：加解扰吞吐 ≥ 497 Mbps 实测余量口径（SSE2 batch，[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)）；纯 Python CSA1（0.305 Mbps）**禁止进运行时路径**，仅作测试夹具/CI oracle。
- 密钥本体不进：mutation log、journal 事件、artifact、E2E 断言（密钥指纹除外）。
- 许可证纪律：libdvbcsa 以 dlopen 动态加载（不进 import 图、不静态链接）；CI 不构建 DLL（ubuntu 无 MSYS2），本地构建脚本随 research 分支留档（#109 Q5）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-100 | 包模型 | payload 域变换对象 |
| SPEC-204（#111 修订后） | 原语契约 | BISS_KEY_MISMATCH（layer=BISS） |
| SPEC-301/ADR-0006 | 事件注册表 | biss.* additive |
| SPEC-502/503 | 持久化/artifact | mutation log 落点 |
| EBU Tech 3292 + ITU-T J.96 | 标准权威（免费原文） | 密钥面/CW 派生/向量 |
| libdvbcsa（dlopen） | 外部库 | CSA1 核心（#106 编译验证留档） |
| #106 research 分支 | 构建脚本/向量底座 | 实现票输入 |

## 11. 测试向量

- 正向：J.96 示例（SW → CW → 加解扰 roundtrip True，[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106) 端到端 demo）；libdvbcsa 自带静态向量 2/2；纯 Python CSA1 夹具对拍（CI oracle——正确性对拍、性能无关）。
- 负向：错配密钥（C1 形态：解扰结构自检失败证据链）、pid_scope 边界（范围外包不加扰）、DLL 缺失降级态。
- 密钥指纹：同密钥同指纹、不同密钥不同指纹、日志无密钥本体（审查项）。

## 12. 验收标准

- **AC-610-01**（REQ-001/002）：加扰/解扰双向接口在位；确定性 + 等位替换不变式测试钉扎。
- **AC-610-02**（REQ-003）：J.96 向量绿；CI 上 DLL 测试诚实 NOT RUN、夹具对拍绿。
- **AC-610-03**（REQ-004）：biss.* 两事件入注册表并发射；密钥指纹纪律全链审计通过（无密钥本体泄漏）。
- **AC-610-04**（REQ-005）：C1 原语全链绿（错配注入 → 解扰失败证据 → 诊断候选 → 包检查器 BISS 标注）。
- **AC-610-05**（全门）：后端三门 + dto 漂移锁绿。

## 13. 非目标

- Mode E/ESW/Injected ID/BISS2（SPEC-611）；ECM/EMM/DVB-CA 全貌（SPEC-612 Phase 3+，场景文档须诚实标注语境差异）；密钥管理面/安全存储（沙盘明文语义，#109 Q3 留档）；前端计算器式交互（#114 排除）。

## 14. 兼容性与交付要求

- additive-only（biss.* 命名空间、场景文档 biss 段、fault 参数 schema）；批准流 DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED。
- C1 场景教学叙事以 roadmap §4 C1 订正文本为准（48-bit session word、BISS 无 ECM）。
