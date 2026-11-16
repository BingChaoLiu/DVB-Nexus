# Lab Pack v2（Phase 2 靶场，草稿）

四份场景文档**草稿**（落笔票 [#118](https://github.com/BingChaoLiu/DVB-Nexus/issues/118)，Phase 2 地图 [#103](https://github.com/BingChaoLiu/DVB-Nexus/issues/103)）。**schema_version: 2**——依赖 Phase 2 引擎面（fault_registry >= 0.6.0 的新原语、t2mi_nodes 节点类型），**不进 `scenarios/` 运行时目录**（MVP 场景扫描器会读到未实现的 fault_type）；实现票落库时复制到 `scenarios/` 并按已批准规格校准。

| 场景 | fault_type | 作用层 | 教学锚点（roadmap §4 订正文本为准） |
|---|---|---|---|
| SC-06 | T2MI_PLP_MISMATCH | T2MI | B1：外层绿灯但 Inner TS 无业务——demux 锁数据 PLP 0 而业务在 PLP 1；PLP 选择与内层解析分层解耦（TS 102 773 §5.1） |
| SC-07 | BBHEADER_SYNC_FAULT | BBFRAME | B2：SYNCD 是位距不是同步字节；BBHEADER 出处 = EN 302 755 §5.1.7，TS 102 773 全文不含 BBHEADER |
| SC-08 | BISS_KEY_MISMATCH | BISS | C1：Mode 1 = 12 位十六进制（48-bit）session word；BISS 无 ECM（CA_PID 0x1FFF）；解扰失败 ≠ 码流损坏 |
| SC-09 | PMT_PID_DRIFT | TS/PMT | C2 的 TS 层等价：PID 树时间轴上定位声明与实际漂移；CA 全貌（ECM/EMM）属 SPEC-612，不伪装 |

## 判据口径

`pass_criteria` = 结构性 `fault_inactive`（与 Lab Pack v1 同构，判据六 kind 不扩）；新原语的观测证据（t2mi.plp_mismatch / bbframe.recovery_failed / biss.descramble_failed）走 `expected_observations` 与诊断候选链（SPEC-303/307 Phase 2 修订章），SC-02~05 式观测类判据口径维持诚实 INCONCLUSIVE（#113 裁决）。

## 三级子图拓扑说明

SC-06/07 使用 `t2mi_encapsulator` / `t2mi_demux` 节点（T2MI 平面连线，[#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110) 裁决结构）；SC-08/09 沿用 MVP 拓扑形态（加扰器是过滤器不是节点，[#109](https://github.com/BingChaoLiu/DVB-Nexus/issues/109) 裁决；BISS 配置在场景文档 `biss` 段）。
