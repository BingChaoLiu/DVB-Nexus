---
status: accepted
date: 2026-11-17
---

# Phase 2 T2-MI/BBFrame 集成路径：自研分层流水线、TSDuck 收窄为第二意见验证器、crate 开发期 oracle

裁决 Phase 2（高级封装层）T2-MI 链在沙盘中的集成路径。裁决过程 = Phase 2 地图 [#103](https://github.com/BingChaoLiu/DVB-Nexus/issues/103) 细裁票 [#108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108)（按 repo 主常设授权「按推荐处理」，决议评论留全量审计记录）；证据 = 三张验证层 research 票 [#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104)/[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105)/[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107)（TSDuck 实测 / FFmpeg 证伪 / crate 复核）。规格承载 = SPEC-600~603（modules/t2mi/，DRAFT_FOR_REVIEW）。拓扑形态裁决在 [#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)（独立票，不在本 ADR 重复）。

## 决定（逐条）

### 1. 解封装与封装均自研 Python 为主路径

- 解封装器与封装器（builder）落 `src/ts` 语义层包族，位级工具复用 SPEC-100 既有（bytesutil/crc）。
- 证据链：TSDuck 无封装能力（[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104) 选项面仅 extract/identify/log）；FFmpeg **从不存在** t2mi demuxer（[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105) 零 commit 历史——roadmap §5 该条失实，随本 ADR 订正）；TSDuck 解封装 3.45-4798 有两个实测缺陷（不解析 BBHEADER CRC-8/MODE/UPL、多 UP BBFrame 尾包丢失），修复在未发布 master commit 147deab3；失败路径全部静默（exit 0 + 空 stderr），作为主路径不可接受。
- 沙盘需要**字段级确定性与故障注入点**（靶场 B1/B2），这是自研的决定性理由；T2-MI 包结构与 BBHEADER 位级语义简单，自研成本低（MVP Python 吞吐余量 164 倍先例，[ADR-0008](0008-mvp-performance-envelope.md)）。

### 2. TSDuck 三重角色在 T2-MI/BBFrame 域收窄（对 ADR-0003/0005 的修订条目）

- [ADR-0003](0003-frozen-tech-stack.md) 第 6 条「TSDuck 三重角色」：**T2-MI/BBFrame 域内生成兜底不成立**；解封装不作主路径。TS 传输层 MVP 既有角色不变（验证器/传输层注入器/生成兜底对纯 TS 仍有效）。
- [ADR-0005](0005-architecture-baseline.md)：语义层自研职责延伸至 T2-MI/BBFrame 封装与解封装（决策 3 的 Phase 2 兑现）；平面启用 = `SignalPlane.T2MI` 加入 `MVP_ENABLED_PLANES`（[#110](https://github.com/BingChaoLiu/DVB-Nexus/issues/110)）。
- TSDuck 保留角色 = **第二意见交叉验证器**（SPEC-603 对拍协议），**前置条件 = 升级到含 master 147deab3 修复的发布版并复测 NM/ISSY/NPD 与多 UP 尾包用例**（样流底座在 #104/#105 research 分支）；未过复测前对拍结果标注 NOT TRUSTED。

### 3. 分层流水线：ADR-0007 过滤器架构逐层复制

- 三级封装建模为分层流水线：Inner TS → BBFrame → T2-MI → 外层 mux；每层「生成 → 本层 fault 过滤器 → 本层封装/传递」。
- `FaultDefinition` 新增 `layer` 属性（{TS, BBFRAME, T2MI, BISS}，默认 TS 保 MVP 兼容，[#111](https://github.com/BingChaoLiu/DVB-Nexus/issues/111)）；等位替换不变式**逐层**保持（同 index 同包/帧数）；tee 双写 artifact 面维持最外层，中间层证据走 mutation log 与包检查器数据面。
- `prepare()` 绑定 fault plan、run() 签名不变、plan 入确定性指纹——MVP 契约（[ADR-0007](0007-fault-injection-pipeline-contract.md)）全部延续。

### 4. dvb-t2mi crate = 开发期交叉验证 oracle，不进运行时

- crate v15.0.0 API 双向完整但单人维护、家族锁步频繁 breaking（[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107)）；官方 PyPI 绑定 dvb-si-py 仅 parse-only。
- 定位：开发期本地 `cargo build` 产物做 golden diff（stdout 二进制对拍）；不进运行时依赖、不进 CI、不进 import 图。

### 5. 仿真保真档位：Phase 2 全程 SIM_TS

- 封装/解封装/加解扰均无实时面；SIM_STATE 留 Phase 3（RF 状态模型）、LIVE 留 Phase 4。

## 后果

- roadmap §5 订正：FFmpeg 条目删除、TSDuck 版本快照更新、builder 复核结论回填（随 #117 落笔执行）。
- conformance/golden 扩容与性能预算随 SPEC-600~603 §11/§9 承载。
- 后续翻转成本：若未来 TSDuck 发布修复版且对拍全绿，可将解封装主路径切换为「自研 + TSDuck 双活」，规格接口不变——决策可逆性中等（管线接口已按契约隔离）。
