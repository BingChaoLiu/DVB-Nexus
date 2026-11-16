# DVB-Nexus 远期路线图（Roadmap）

> **定位**：本文件是 MVP 之外全部远期工作的**唯一权威索引**（ADR-0002）。MVP = TS-first 传输层八步闭环；这里承载其余一切——保证 MVP 完成后，v0.3 愿景中的射频沙盘、高级封装、实况接入等 idea 有直接的继续条件。
>
> **推进方式**：每个 Phase 启动时另开一张 wayfinder map（对照 map [#1](https://github.com/BingChaoLiu/DVB-Nexus/issues/1) 的模式），先验证层后决策层，不直接开工。

## 1. 与 MVP 的边界

| 属于 MVP | 属于本路线图 |
|---|---|
| MPEG-TS 传输层八步闭环（Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify） | RF/LNB/DiSEqC/Unicable、T2MI/BBFrame/PLP、BISS/CA、Live Mode、Time Machine |
| 188-byte 包长、`analysis_only` profile、最小前端 UI | RS204/M2TS、`playback_ready`、完整物理层、真实音视频编码 |
| `SignalPlane` 只启用 `MPEG_TS`（模型保留五平面扩展位） | `RF` / `SEC_CONTROL` / `T2MI` / `IP` 平面的实际启用 |

**已预留的扩展点**（MVP 实现时不得砍掉）：拓扑模型 `SignalPlane` 五平面枚举、节点类型注册表机制、仿真保真级 `SIM_STATE`/`SIM_TS`/`LIVE` 三档、SPEC-600+ 编号空间、Observation 的 `hardware`/`measured` 来源与置信枚举。

## 2. 阶段划分

源自 SPEC-000 §6 与 provenance/chatgpt-v04.md，MVP（Phase 1）之后：

| Phase | 主题 | 核心内容 | 前置条件 |
|---|---|---|---|
| **Phase 2** | 高级封装层 | T2-MI 解封装三级子图、BBFrame/PLP 提取、BISS Mode 1 加解扰、教学靶场 B/C 系列案例 | MVP TS 闭环验收通过；语义级故障注入能力（构造期注入）可用 |
| **Phase 3** | RF/SEC 沙盘 | LNB/DiSEqC/Tuner/Unicable 的 L0 状态模型与物理视图、DiSEqC 命令模型、A 系列靶场 | L0 求值引擎成熟（架构评审裁决其 MVP 形态）；端口模型扩展 |
| **Phase 4** | Live Engineering | Linux DVB Frontend 接入、实况流监测与告警、D2 系列实战案例 | Linux/WSL2 运行环境（见 §5 Windows 限制）；Observation 告警链路成熟 |
| **Later** | 工程增强 | Time Machine（Ring Buffer/事件冻结/回放）、TS Differential Analyzer（双流差异）、`playback_ready` 档、MPTS 多节目调度 | 按需另启 effort |

## 3. SPEC-600+ 未来模块目录

源自规格包 `REGISTRY.md` §F（编号原样保留，规格文本未编写；实现前需按 map 流程编写并批准）：

| Spec ID | 名称 | 范围 | 优先级 |
|---|---|---|---|
| SPEC-600 | T2MI Parser | T2-MI Packet 基础解析 | P2 |
| SPEC-601 | BBFrame Parser | BBHEADER、BBFrame 边界和 CRC | P2 |
| SPEC-602 | PLP Extractor | T2-MI PLP ID 过滤与提取 | P2 |
| SPEC-603 | Inner TS Reconstruction | BBFrame 解封装和 Inner TS 输出 | P2 |
| SPEC-610 | BISS Mode 1 | BISS-1 参数、解扰接口和证据 | P2 |
| SPEC-611 | BISS Mode E | ESW/Injected ID 计算和验证 | P2 |
| SPEC-612 | DVB-CA | PMT CA Descriptor、ECM/EMM 关系 | P3 |
| SPEC-620 | RF Simulation | RF 参数和质量状态模型 | P2 |
| SPEC-621 | LNB Model | 本振、极化、电压和频段状态 | P2 |
| SPEC-622 | DiSEqC Controller | 命令模型、端口和控制状态 | P2 |
| SPEC-623 | Unicable | EN 50494/EN 50607 槽位与调谐模型 | P2 |
| SPEC-630 | Linux DVB Frontend Adapter | Linux DVB API 接入 | P3 |
| SPEC-631 | Live TS Input | 文件/网络/硬件输入统一接口 | P2 |
| SPEC-632 | Live Monitoring | 实况指标与告警 | P2 |
| SPEC-640 | Time Machine | Ring Buffer、事件触发、冻结与回放 | P2 |
| SPEC-641 | TS Differential Analyzer | 双码流结构与指标差异分析 | P2 |

前端远期行 **SPEC-407 Timeline & Replay UI**（P2，依赖 SPEC-640/501）自规格包 `REGISTRY.md` §D 移入本目录（[编号体系重建 #10](https://github.com/BingChaoLiu/DVB-Nexus/issues/10)）：随 Time Machine（SPEC-640，Later Phase）另启 effort，规格文本未编写。

**生成过程可视化（packet 级构造事件流）**：属自研语义层职责（ADR-0005 决策 3），但 UI 与事件类型清单均 MVP 外（[前端最小 UI 范围裁决 #18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)）——SPEC-301 §4 预留条款原样保持，TS Core MVP 无发射义务；事件类型注册表与生成可视化 UI 在 roadmap 期一并裁决。**已清账（2026-11-17，[#112](https://github.com/BingChaoLiu/DVB-Nexus/issues/112)）**：采纳分级粒度（gen.* 阶段级 + 抽样包级，全量 packet 级流关闭）+ Lab 实验台只读折叠区最小 UI；详见 SPEC-303 Phase 2 修订章与 SPEC-600~603。

## 4. v0.3 故障案例库（远期靶场素材）

> 原文见 `docs/spec/provenance/v03.md` §7。以下条目已按标准核查报告（`docs/research/standards-audit.md` §8）**订正**——⚠️ 标注处为对 v0.3 原文的修正，实现知识卡片时以本节为准。
>
> **MVP 裁决（2026-11-14，[v03 故障案例库 → MVP 靶场映射 #17](https://github.com/BingChaoLiu/DVB-Nexus/issues/17)）**：八案例**全部不在 MVP**——A1/A2/B1/B2/C1/C2/D1 依赖 RF/T2MI/BISS/CA/FastScan 域（ADR-0002 划出），D2 是唯一 TS 层案例但需 MVP 外的新故障原语；MVP 靶场 = 四类故障原语（ADR-0007）直接构造的内置 Lab Pack v1 五景，不逐案对应 v03 案例（详见 #17 决议）。

### 领域 A：射频与前端供电链路（Phase 3）

- **A1 Unicable 频道槽位冲突**：多 tuner 共享单根同轴电缆，两个接收端被分配相同 **User Band 槽位频率**（如 1210 MHz），导致无法锁定。⚠️ 订正：SCR 展开名为 **Satellite Channel Router**（EN 50494；非"Subscriber Channel Radio"）；冲突本质是同一 User Band 被两个接收端占用导致 SCR 堆叠信号互相干扰，**不是 LNB 本振冲突**。EN 50607（dCSS/Unicable II）扩展至最多 32 个 UB。
- **A2 22kHz 持续音调残留**：高频段正常、切低频段时 BER 飙升——LNB 供电/多路开关异常使低频段指令混入残留 22kHz，LNB 错误切入高频本振。训练目标：物理视图电压（13/18V）× 22kHz 组合逻辑排查。

### 领域 B：多流与嵌套封装（Phase 2）

- **B1 T2MI PLP ID 映射错位**：外层锁定正常、T2MI 节点绿灯，但内层 TS 无业务——Demux 锁了数据 PLP 0 而业务在 PLP 1。三级子图（外层 TS Packet → BBFrame → Inner TS）✅ 已核实与 TS 102 773 §5.1 一致；PLP 选择与内层解析分层解耦。
- **B2 BBHEADER 帧同步错位**：⚠️ 订正出处——**BBHEADER/SYNCD 定义在 EN 302 755 §5.1.7**（MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8 共 10 字节），**TS 102 773 全文不含 BBHEADER**（它只规定 T2-MI 包封装：包头 6 字节 + CRC-32）。SYNCD（2 字节）是"数据字段内首个 UP 的位距离"，**不是同步字节**。教学引用改为：EN 302 755 §5.1.7（BBHEADER）+ TS 102 773 §5.1（T2-MI 包）。

### 领域 C：加扰与条件接收（Phase 2）

- **C1 BISS 密钥错位**：⚠️ 订正——BISS **Mode 1** 密钥为 **12 位十六进制（48-bit）session word**（"16 字节密钥"的说法错误）；**Mode E** = 固定 Session Key 加密 SW 成 16 位十六进制 **ESW** 带外下发 + **静态 128-bit Injected/Buried ID 预置于接收端**（不在流中传输、不是动态数据）。BISS **无 ECM**（CA_PID 固定 0x1FFF，Tech 3292）；BISS2 的 CA_system_ID = 0x2602。底层算法：BISS1 = DVB-CSA1 + DES；BISS2 = DVB-CISSA（TS 103 127）+ AES-128。
- **C2 PID 映射混淆（CA 字错配）**：PMT 中加扰 PID 动态变更而 Demux 过滤表未同步，ECM 与加密 PES 错位。⚠️ 该案例属 DVB-CA 语境（SPEC-612），混入 BISS 案例时注意区分（BISS 无 ECM）。**MVP 交叉引用**（#17）：其"PID 树时间轴上定位声明与实际漂移"教学点由 MVP 靶场 PMT_PID_MISMATCH 场景（SC-04）部分覆盖，不阻塞 MVP。

### 领域 D：SI/PSI 与时序（Phase 2~4）

- **D1 FastScan 后 NIT 版本不同步**：运营商更新 transponder 列表后终端命中陈旧缓存（table_id_extension 版本号未变 / TSID 未同步更新）。训练目标：FastScan 面板、LC 映射、NIT 版本比对。
- **D2 PCR 抖动超标致 CC 异常**：⚠️ 订正数值——ISO/IEC 13818-1 §2.7.2 的 PCR **间隔规范限值是 100ms**（"Jitter > 500ms" 的原表述两头不靠）；**±500ns 是 TR 101 290 P2 的 PCR 准确度阈值**（另一个量）。教学叙事改为："PCR 间隔超过 100ms（ISO §2.7.2）或 PCR 抖动超出 ±500ns（TR 101 290 P2）"。**MVP 裁决**（#17）：no-go——忠实症状链（PLL 失锁→丢包保护）依赖真实解码器硬件行为，仿真管线无法诚实复现（No fake evidence），且第五故障原语 = MVP 基线冻结不扩容；**TS 等价残留教学点 = PCR 间隔/抖动故障原语候选**（观测通路 `ts.pcr_jitter_ns` metric 与 `PCR_JITTER_HIGH` 告警已在 SPEC-302/304 注册、MVP 下惰性），原语参数语义留待后续 effort 裁决。

## 5. 技术事实备忘（远期实现必读）

源自研究调研（`docs/research/`），实现对应 Phase 时先复核：

### T2-MI（Phase 2）
> **2026-11-17 实测订正**（[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104)/[#105](https://github.com/BingChaoLiu/DVB-Nexus/issues/105)/[#107](https://github.com/BingChaoLiu/DVB-Nexus/issues/107)；裁决 [ADR-0010](adr/0010-phase2-t2mi-integration-path.md)，规格 SPEC-600~603 DRAFT）：
- **解封装与封装均自研 Python 为主路径**——TSDuck 无封装能力（选项面仅 extract/identify/log）；**FFmpeg 从不存在 t2mi demuxer**（libavformat/t2mi.c 零 commit 历史，原「FFmpeg 7.1 t2mi demuxer」条目失实删除）；DVBInspector 仅离线工具非管线组件
- TSDuck `tsp -P t2mi --extract` 解封装 HEM 布局逐字节确定，但 3.45-4798 有两个实测缺陷（不解析 BBHEADER CRC-8/MODE/UPL、多 UP BBFrame 尾包丢失；修复在未发布 master 147deab3）且失败路径全静默——降为第二意见验证器，前置 = 升级发布版并复测
- Rust crate `dvb-t2mi`（现 v15.0.0，单人维护极活跃但家族锁步 breaking）不进运行时/CI，仅开发期 golden diff oracle

### BISS（Phase 2）
- ⚠️ **TSDuck descrambler 不支持 BISS**（实测仅 DVB-CSA2/AES-CBC/CTR/ATIS-IDSA/DVB-CISSA）——v0.3"实况复用 TSDuck 解 BISS"的设想不成立
> **2026-11-17 实测结论**（[#106](https://github.com/BingChaoLiu/DVB-Nexus/issues/106)；裁决 [ADR-0011](adr/0011-biss-scramble-path.md)，规格 SPEC-610/611 DRAFT）：libdvbcsa 本机编译成功（MSYS2，SSE2 batch 497 Mbps 余量 7.5 倍）+ pycryptodome DES；CISSA 纯 Python 134 Mbps 达标（TS 103 127 完全公开）；纯 Python CSA1 仅 0.305 Mbps 只作测试夹具
- BISS1 → libdvbcsa（CSA1 实现）+ DES（session word 加密）；BISS2 → CISSA（ETSI TS 103 127）+ AES-128 自研或第三方实现
- 标准原文：EBU Tech 3292（BISS2）与 Tech 3292-s1（BISS-CA）可免费下载

### Live Mode（Phase 4）
- **Windows 硬限制**（TSDuck User Guide §7.1.2.2）：DVB 调谐走 DirectShow/BDA，系统无预装驱动、**无法查询调谐器实际锁定参数**——Phase 4 需要 Linux/WSL2 环境
- 文件/网络/内存输入与全部处理插件在 Windows 完全可用（不阻塞 Phase 2/3）

### Unicable（Phase 3）
- EN 50494/EN 50607 正文付费，术语与架构层面已核实（Satellite Channel Router、User Band、dCSS 32 UB）；具体条款号实现时需购买原文核对

## 6. 参考索引

- 规格底稿：`docs/spec/`（使用规则见其 README）
- 权威决策：`docs/adr/` + [map #1](https://github.com/BingChaoLiu/DVB-Nexus/issues/1)
- 领域词汇：根目录 `CONTEXT.md`
- 独立调研：`docs/research/`（TSDuck 环境 / 生态对比 / Python 性能 / 标准核查）
- 实测资产：`docs/research/tsduck-data/`（golden.ts 生成链）、`docs/research/python-ts-bench/`（性能基准）
