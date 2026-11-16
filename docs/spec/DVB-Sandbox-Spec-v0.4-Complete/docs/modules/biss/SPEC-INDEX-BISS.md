# BISS Spec Index（加扰与条件接收，Phase 2）

**Package version:** 0.5.1（Phase 2 新增模块，随本批 DRAFT_FOR_REVIEW 落笔）
**Status:** APPROVED 0.5.1（repo 主审计确认翻批准，2026-11-17；批准流：Phase 2 地图 [#103](https://github.com/BingChaoLiu/DVB-Nexus/issues/103) 既裁）
**Normative parent:** SPEC-100（包模型）、SPEC-204（故障契约）、SPEC-301+ADR-0006（事件信封）；标准权威 = EBU Tech 3292 / Tech 3292-s1 与 ETSI TS 103 127（均免费原文留档）

Phase 2 BISS 两份规格（落笔票 [#116](https://github.com/BingChaoLiu/DVB-Nexus/issues/116)）：管线接入 = ADR-0007 包级 payload 过滤器「加扰器」类型（[细裁 #109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109)）；原语 BISS_KEY_MISMATCH 随 [#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)；事件面随 [#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)；验证层证据 = #106 research 分支（libdvbcsa 编译/性能/CISSA 达标全留档）。

| Spec ID | Document | Depends on | Priority | Primary output |
|---|---|---|---|---|
| SPEC-610 | [BISS Mode 1](SPEC-610-biss-mode-1.md) | SPEC-100/204/301 | P2 | 加扰/解扰双向接口（DVB-CSA1 + DES）、session word 48-bit 口径、密钥指纹纪律、biss.* 事件、C1 原语挂钩、DLL 显式降级契约 |
| SPEC-611 | [BISS Mode E](SPEC-611-biss-mode-e.md) | SPEC-610/100 | P2 | ESW/Injected ID 派生接口、BISS2/CISSA 纯 Python（AES-128 每包重启）、Mode E 变体 fault 参数、错 ESW/错 ID 证据可区分 |

## 裁决要点（详见各 spec 与 Phase 2 地图决议链）

- **密钥口径**（roadmap §4 C1 订正权威）：Mode 1 session word = **12 位十六进制（48-bit）**（「16 字节密钥」旧说废弃）；Mode E = ESW 带外下发 + Injected/Buried ID 128-bit **静态预置接收端**（不在流中传输、非动态数据）。
- **BISS 无 ECM**：CA_PID 固定 0x1FFF（Tech 3292）；C2 教学点的 CA 全貌（ECM/EMM）属 SPEC-612（Phase 3+），场景文档须诚实标注语境差异，不伪装 CA 完整语义。
- **组件形态**（#109）：BISS1 = ctypes + libdvbcsa SSE2 batch API（dlopen，DLL 缺失显式降级；CI 上 DLL 测试诚实 NOT RUN、纯 Python CSA1 夹具当 CI oracle）；BISS2 = 纯 Python CISSA（TS 103 127，134 Mbps 达标，零原生依赖进 CI 全测）；纯 Python CSA1 与 CLI 子进程进运行时路径均被拒绝。
- **证据纪律**：解扰失败 ≠ 码流损坏（结构自检区分）；错 ESW 与错 Injected ID 两种错配证据可区分；密钥本体永不落日志/artifact（指纹前缀除外）。
