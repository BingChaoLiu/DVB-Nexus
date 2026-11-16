---
spec_id: SPEC-611
title: BISS Mode E（ESW/Injected ID 与 CISSA）
version: 0.5.1
status: APPROVED
phase: P2
owner: BISS
priority: P2
depends_on: [SPEC-610, SPEC-100]
requirements: [REQ-611-001, REQ-611-002, REQ-611-003, REQ-611-004]
---

# SPEC-611 — BISS Mode E（ESW/Injected ID 与 CISSA）

## 1. 目标

定义 **BISS Mode E** 的密钥派生与验证接口（ESW + Injected ID）及 **BISS2/CISSA** 加扰面：AES-128（DVB-CISSA，ETSI TS 103 127）。消费方 = SPEC-610 同族管线（同一加扰器过滤器架构）、Lab Pack v2 C1 场景的 Mode E 变体。

依据：[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)（CISSA 纯 Python 134 Mbps 达标；Mode E 派生公式 oscam/dvbipitools/DVBStreamer5 三实现交叉印证；pycryptodome 4.5.0 全密钥面 roundtrip PASS）；标准权威 = EBU Tech 3292-s1（BISS-CA）与 ETSI TS 103 127 §6.3（CISSA 完全公开，免费原文）。

## 2. 范围

### 2.1 In Scope

- Mode E 密钥派生：`derive_sw(esw, injected_id) -> session_word`（ESW = 16 位十六进制加密 Service Word，带外下发；Injected/Buried ID = 128-bit **静态预置接收端**、不在流中传输——roadmap §4 C1 订正口径）。
- CISSA（BISS2）加扰/解扰：AES-128-CBC 每包重启 + 固定 IV（TS 103 127 §6.3）+ 尾部明文规则；纯 Python（零原生依赖，[#109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109) Q1 裁决）。
- `CA_system_ID = 0x2602`（BISS2）与 CA_PID 0x1FFF 的常量语义标注。
- Mode E 变体的场景文档 biss 段字段（`encrypted_sw / injected_id`）与 fault 参数（错 ESW/错 Injected ID）。
- 事件复用 `biss.*`（#113 命名空间，payload 增 mode 字段）。

### 2.2 Out of Scope

- Mode 1 CSA1 面（SPEC-610）；ECM/EMM/DVB-CA（SPEC-612）；密钥分发协议面（带外语义即边界，不做模拟 KDC）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| ESW | Encrypted Service Word：16 位十六进制，固定 Session Key 加密 SW 后带外下发 |
| Injected/Buried ID | 128-bit 静态标识，预置于接收端设备内、**不在流中传输**（C1 教学点：不是动态数据） |
| CISSA | Common Inner Scrambling System A（DVB-CISSA）：BISS2 的 AES-128 加扰算法（TS 103 127） |
| BISS2 | 采用 CISSA 的 BISS 第二代；CA_system_ID = 0x2602 |
| 每包重启 | CISSA 的 CBC 链每 TS 包重置（固定 IV），包间无链——等位替换不变式天然成立 |

## 4. 架构

- 与 SPEC-610 同一加扰器过滤器架构（管线接入/tee 双写/指纹纪律全部继承）；差异仅算法实现（CISSA 纯 Python pycryptodome，无 DLL 依赖）与密钥派生入口。
- 派生链：`injected_id → session key（Tech 3292-s1 语义）→ DES-ECB 解 ESW → session word → CW`（公式照标准原文 + 三实现交叉印证留档，golden 钉扎）。

## 5. 数据模型

- `BissModeEConfigDTO`：`mode: "E" / encrypted_sw: string(16 hex) / injected_id: string(32 hex) / pid_scope / ca_pid: 0x1FFF / ca_system_id: 0x2602`。
- Fault 参数变体：`wrong_esw` / `wrong_injected_id`。
- `biss.*` payload 增 `mode`（"1"/"E"/"2"）与派生链引用（不落密钥本体）。

## 6. 公开接口（接口级契约）

- `bisse.derive_sw(esw, injected_id) -> session_word`：确定性；派生公式 golden 钉扎（J.96/Tech 3292-s1 向量）。
- `biss2.scramble/descramble(packets, ciss_key, pid_scope)`：CISSA 纯 Python；每包重启语义（包间独立 → 同 index 同包数同长度不变式天然保持）。
- 复用 SPEC-610 的 key_fingerprint / 事件面 / 结构自检纪律。

## 7. 处理算法（接口级行为义务）

- CISSA：AES-128-CBC，IV 固定（TS 103 127 §6.3），每 TS 包重启链；尾部明文规则照标准（golden 钉扎）。
- Mode E fault 注入：错 ESW → 派生出错误 SW → 解扰失败（与 Mode 1 错配同证据形态）；错 Injected ID → 派生失败/错 SW（区分两种错配教学点）。
- 派生失败（ESW 格式非法等）显式态，不静默回退。

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| ESW/Injected ID 格式非法 | prepare 前拒绝（schema 校验：16/32 hex） |
| 错 ESW / 错 Injected ID | 解扰失败证据（biss.descramble_failed）+ 派生链指纹引用——两种错配在证据中可区分 |
| pycryptodome 不可用 | 显式降级错误（依赖声明面，无 DLL 降级问题） |

## 9. 资源约束

- CISSA 纯 Python 134 Mbps 实测达标（[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)）——零原生依赖进 CI 全测（与 SPEC-610 的 DLL 面 CI 门差异明示）。
- 密钥纪律同 SPEC-610（指纹进日志、本体不落）。

## 10. 依赖

| 依赖 | 性质 | 消费点 |
|---|---|---|
| SPEC-610 | 过滤器架构/事件/指纹纪律 | 继承复用 |
| SPEC-100 | 包模型 | payload 域 |
| EBU Tech 3292-s1 / ETSI TS 103 127 | 标准权威（免费原文留档） | 派生公式/CISSA 语义 |
| pycryptodome | AES/DES 实现 | 加解密核心（既有依赖） |
| #106 research 分支 | 派生公式三实现交叉印证/向量底座 | 实现票输入 |

## 11. 测试向量

- 正向：Mode E 派生向量（J.96/Tech 3292-s1）；CISSA roundtrip（TS 103 127 向量 + pycryptodome 对拍）；每包重启独立性（改包 k 不影响包 k+1 输出）。
- 负向：错 ESW / 错 Injected ID 两种错配的证据可区分性；格式非法拒绝。
- golden：派生链端到端（injected_id + ESW → SW → CW → CISSA roundtrip）一条入 docs/test-vectors/。

## 12. 验收标准

- **AC-611-01**（REQ-001/002）：派生接口与 CISSA 双向接口在位；确定性钉扎。
- **AC-611-02**（REQ-003）：派生 golden 向量入册；每包重启独立性测试绿。
- **AC-611-03**（REQ-004）：Mode E 变体全链绿（场景 biss 段 → 加扰 → 解扰证据 → 诊断候选）；两种错配可区分。

## 13. 非目标

- Mode 1 CSA1（SPEC-610）；ECM/EMM/CA 全貌（SPEC-612）；KDC/密钥分发模拟；前端计算器式交互（#114）。

## 14. 兼容性与交付要求

- additive-only；批准流 DRAFT_FOR_REVIEW → repo 主通读确认 → APPROVED。
- C1 场景 Mode E 变体叙事照 roadmap §4 C1 订正（ESW 带外、Injected ID 静态预置非动态数据）。
