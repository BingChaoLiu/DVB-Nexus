---
status: accepted
date: 2026-11-17
---

# Phase 2 BISS 加解扰实现路径：libdvbcsa dlopen 批量 API + pycryptodome，加扰器为 ADR-0007 包级过滤器新类型

裁决 BISS Mode 1/Mode E 在沙盘中的实现路径。裁决过程 = Phase 2 地图 [#103](https://github.com/BingChaoLiu/DVB-Nexus/issues/103) 细裁票 [#109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109)（常设授权「按推荐处理」，决议评论留全量审计记录）；证据 = 验证层 research 票 [#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)（libdvbcsa 本机编译/ctypes 绑定向量/性能实测/CISSA 可得性，全留档）。规格承载 = SPEC-610/611（modules/biss/，DRAFT_FOR_REVIEW）。

## 决定（逐条）

### 1. 组件形态

- **BISS1**：DVB-CSA1 核心走 libdvbcsa **SSE2 批量 API**（ctypes + dlopen 动态加载——不进 import 图、不静态链接，规避许可证耦合）；session word 的 DES-ECB 走 pycryptodome。实测依据：SSE2 batch 335k 包/s ≈ 497 Mbps（7.5 倍余量）；单包 API 贴线（104 Mbps）不采用；纯 Python CSA1 仅 0.305 Mbps（差 321 倍）**禁止进运行时路径**，只作测试夹具/CI oracle。
- **BISS2**：CISSA（DVB-CISSA，ETSI TS 103 127 §6.3）纯 Python（pycryptodome AES-128-CBC 每包重启 + 固定 IV），实测 134 Mbps 达标，零原生依赖进 CI 全测。
- 拒绝项（留证）：纯 Python CSA1 运行时（性能）、CLI 子进程（进程开销 + 无流式接口）。
- 适配器落 `src/adapters`（dlopen + ctypes 封装）；**DLL 缺失 = 显式降级错误**（诚实态，不静默回落）。

### 2. 管线接入：加扰器 = ADR-0007 包级 payload 过滤器新类型

- BISS 加扰是逐包 payload 变换：包头 4 字节 clear、包长 188 不变、包序不变——`apply(index, packet)` 契约原样适用，**不新增传输级组件形态**。
- 构造特性（场景声明密钥）与 fault 注入（FaultDefinition.params 错配密钥）驱动**同一**加扰器过滤器，差别仅密钥来源；tee 双写、prepare 绑定指纹、等位替换不变式全部延续（[ADR-0007](0007-fault-injection-pipeline-contract.md) 增补条目：filters 族新增 scrambler 类型，作用层 layer="BISS"）。

### 3. 密钥面：明文沙盘语义

- 场景文档 `biss` 段（mode/session_word/encrypted_sw/injected_id/pid_scope，camelCase wire）声明密钥；fault plan `FaultDefinition.params` 携带错配密钥。
- 沙盘为单机训练环境（127.0.0.1、无鉴权，SPEC-500 既有口径），密钥材料明文进配置**可接受**；不新增服务端密钥存储/管理面（生产 CA 语义明确出界）。
- **密钥本体永不落** mutation log/journal/artifact/E2E 断言；日志只落密钥指纹（哈希前缀）。

### 4. 证据面

- 加扰侧：mutation log 记 before/after 包摘要 + 密钥指纹 + fault_id/注入点（AC-204-04 evidence locator 延续）。
- 解扰侧：按声明密钥解扰 + 结构自检；**解扰失败 ≠ 码流损坏**（显式区分，C1 教学核心）；`biss.*` 事件（[#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113) 注册表 additive）。
- BISS 无 ECM（CA_PID 固定 0x1FFF，Tech 3292）；C2 的 CA 全貌（ECM/EMM）属 SPEC-612（Phase 3+），场景文档诚实标注语境差异。

### 5. CI 门与测试策略

- CI（ubuntu）无 MSYS2/DLL 构建面：libdvbcsa 绑定测试 CI 上 skip + NOT RUN（照 [SPEC-506](../spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/Platform/SPEC-506-conformance-suite.md) TSDuck 先例「缺失不冒绿」）；DLL 本地构建脚本随 #106 research 分支留档。
- CI 全测面：纯 Python CSA1 夹具对拍已知向量（正确性 oracle）+ CISSA/AES/DES 纯 Python 全链 + Mode E 派生向量（J.96）。

## 后果

- 实现票需落 DLL 构建脚本（本地）与 dlopen 适配器；golden 向量扩容（J.96/Tech 3292-s1/TS 103 127）随 SPEC-610/611 §11 承载。
- 后续翻转成本：若 libdvbcsa 出现维护风险，替换点收敛在 src/adapters 适配器（接口 = 批量加解扰 + 向量对拍），决策可逆性高。
