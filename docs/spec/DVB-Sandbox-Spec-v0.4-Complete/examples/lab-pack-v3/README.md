# Lab Pack v3（Phase 3 靶场，草稿）

两份场景文档**草稿**（落笔票 [#157](https://github.com/BingChaoLiu/DVB-Nexus/issues/157)，Phase 3 地图 [#143](https://github.com/BingChaoLiu/DVB-Nexus/issues/143)）。**schema_version: 3**——依赖 Phase 3 引擎面（`l0_state_evaluators >= 0.7.0` 的 L0 状态求值器、`fault_registry >= 0.7.0` 的 state 层故障路由、RF/SEC_CONTROL 平面启用），**不进 `scenarios/` 运行时目录**（MVP 场景扫描器会读到未实现的 fault_type；照 Lab Pack v2 先例）；实现票落库时复制到 `scenarios/` 并按已批准规格校准。

| 场景 | fault_type | 作用层 | 教学锚点（roadmap §4 订正文本为准） |
|---|---|---|---|
| SC-10 | UB_SLOT_CONFLICT | SEC | A1：SCR 展开 Satellite Channel Router（EN 50494；非 Subscriber Channel Radio）；冲突本质 = 同一 User Band 被两接收端占用致 SCR 堆叠信号互扰，**不是 LNB 本振冲突**；EN 50607（dCSS）扩展至 32 UB |
| SC-11 | TONE_RESIDUE | RF | A2：残留 22kHz → LO 停 10600 → 低频段请求 IF 偏移 850 MHz（远超漂移 ±3MHz）→ 失锁或错锁同 IF 槽位高频段转发器；高频段正常的不对称性由 14 态真值表直接推出 |

## 判据口径

`pass_criteria` = 结构性 `fault_inactive`（与 Lab Pack v1/v2 同型，判据 kind 不扩）；状态域观测证据（`rf.state_observed` / `sec.state_observed` 快照、CauseRef 冲突对、tone 双字段错配）走 `expected_observations` 与诊断候选链（SPEC-303/307 Phase 3 修订章）。SC-01~09 式观测类判据口径维持诚实 INCONCLUSIVE（#113 裁决）。

## 拓扑说明

SC-10/11 均为 **SIM_STATE Run**（状态域八步闭环：Generate = L0 求值产出状态观测流，无 TS artifact；ADR-0012）。SC-10 使用共享同轴拓扑——lnb 输出端口 `maxConnections: 2` 承载 1:N 扇出（[#148](https://github.com/BingChaoLiu/DVB-Nexus/issues/148) 机制面零扩展裁决），SCR 配置在 lnb 节点 `scr` 子段（结构归 SPEC-623）；SC-11 为直连双 tuner 对照拓扑（低/高频段请求并排，凸显不对称症状）。两场景均无 `diseqc_switch` 节点（首版 1.x 命令子集场景未涉开关切换）。

## 与 v2 的差异

- schema_version 2 → 3：引擎依赖从「Phase 2 引擎面（fault_registry/t2mi_nodes >= 0.6.0）」升级为「Phase 3 引擎面（fault_registry/l0_state_evaluators >= 0.7.0）」。
- 证据形态从码流/包级（t2mi.plp_mismatch 等）切换为状态观测流（rf.*/sec.* 快照 + CauseRef）。
- `pass_criteria` 判据 kind 不变（fault_inactive）——通关 = 修复后的新 Run 证据，纪律跨 Phase 一致。
