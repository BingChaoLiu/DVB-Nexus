---
status: accepted
date: 2026-11-14
---

# 架构基线评审：五层保留、L0 推迟出 MVP、混合路线 C、端口级拓扑、TSDuck Adapter 接口面

评审对象是 ChatGPT v0.4 规格包的系统架构（chatgpt-v04.md §2/§3/§4/§8/§10/§15 与 SPEC-001/003/200/202），依据四张调研结论：TSDuck Windows 环境验证（[#3](https://github.com/BingChaoLiu/DVB-Nexus/issues/3)）、生态与替代方案（[#4](https://github.com/BingChaoLiu/DVB-Nexus/issues/4)）、Python 性能可行性（[#5](https://github.com/BingChaoLiu/DVB-Nexus/issues/5)）、标准条款核查（[#6](https://github.com/BingChaoLiu/DVB-Nexus/issues/6)）。评审过程见 [#7](https://github.com/BingChaoLiu/DVB-Nexus/issues/7)。本 ADR 修正 [ADR-0003](0003-frozen-tech-stack.md) 第 6 条，其余 ADR 不受影响。

## 决定（逐条 go/no-go）

### 1. 五层分层 —— GO，不合并

Presentation / Application / Domain / Runtime / Adapters 五层保留为**单进程内的逻辑分层**：React 前端独立技术栈；后端四层用包结构 + import 规则（import-linter）表达，不引入服务/进程拆分（ADR-0003 已冻结 Modular Monolith）。后端四层互不合并：Application 与 Domain 分离保住"API 层不含 TS 编码细节、Domain 不碰 FastAPI/SQLite/TSDuck"两条纪律（SPEC-001 §3.2/§3.3）；Runtime 层是扩展主轴（SIM_TS → 未来 SIM_STATE/LIVE）；Adapters 层隔离外部依赖。代码命名采用 SPEC-001 层名，禁用 L1~L5 架构层级编号（CONTEXT.md：L0/L1 只作保真级名，不作架构层编号）。

### 2. 双 Runtime —— GO for L1-only，L0（SIM_STATE）推迟出 MVP

八步闭环（Create → Generate → Inject → Analyze → Diagnose → Inspect → Recover → Verify，ADR-0002）逐步核对，无一步依赖 SIM_STATE。L0 的两项价值中，"免生成秒级反馈"已被 #5 削弱（20Mbps 生成仅占 0.6% 单核，MVP 码率下 L1 反馈接近即时）；"状态级因果教学"不足以抵偿整条第二通路的工程成本（独立求值引擎 + 每节点求值器 + 第二观测通路 + 诊断双路径 + 拓扑健康求值 UI）。

- 统一 `SimulationRuntime` 接口（Protocol）保留，StateRuntime 后补不返工；SPEC-201/202 保持骨架。
- 拓扑画布健康显示 = Run 状态 + 诊断事件映射到节点（非因果求值）。
- 由此修订三处已写文字：chatgpt-v04 §10.1 "L0 Engine P0"、chatgpt-v04 §10.2 "节点健康状态和故障传播"验收目标、SPEC-001 §13 "SIM_STATE 和 SIM_TS 可通过统一 Session API 启停"——修订随规格基线批准（ticket #10~#12）落地，不静默改归档底稿。
- 状态级教学因果传播（L0）进 `docs/roadmap.md`。

### 3. 生成路线 —— GO，采纳修正版混合路线（路线 C）

自研 TS Core 收窄为**语义层**：TS 包/Section 打包模型（含 CRC32）、PAT/PMT/SDT、CC/PCR 调度、FaultDefinition 双路由、Packet 级构造过程可视化事件流。**推迟**：PES/音视频打包、多节目 MPTS 复杂调度、T2-MI。TSDuck 承担**三重角色**：外部验证器 + 传输层故障注入器（fuzz/craft/slice/filter/pcredit）+ MVP 期生成兜底（tsxml → tstabcomp → tsp 链路，#3 实测字节级确定）。依据 #4 实测："TSDuck 只做验证"前提不成立，但语义级故障与生成过程可视化是插件链硬边界，只有自研能做。本条修正 ADR-0003 第 6 条；CONTEXT.md TSDuck/TS Core 词条同步修订。

### 4. 模块划分 —— GO，11 包维持 + 目录融合版

`api / application / topology / simulation / ts / faults / observation / diagnosis / tsduck / storage / knowledge` 十一个包维持。范围注记：`simulation` MVP = 统一 Runtime 接口 + TSRuntime；`topology` MVP = 模型 + 校验（因果求值器随 L0 后补）；`knowledge` MVP = 静态标准引用数据（供诊断解释消费，无独立交互面）；chatgpt-v04 §3.2 的 `workers/` 包删除（TSDuck 本就是 asyncio 子进程，生成是离线批处理）。

目录取融合版：chatgpt-v04 §3.2 的嵌套骨架（`domain/` 收 topology/observation/diagnosis，`adapters/` 收 tsduck/storage）+ `ts/` 顶层独立（核心资产，未来可换实现而上层接口不变；SPEC-001 §3.5 把 TS Core 列入 Adapters 层只表达"不污染 Domain"，TS Core 不是外部依赖）。依赖规则落 import-linter 契约：

- `ts` 与 `domain/*` 纯净：不 import 任何上层包；`ts` 不 import `tsduck`（生成兜底由 simulation/application 调用，防外部工具反向污染核心资产）。
- `domain/*` 不 import FastAPI/SQLite/文件系统/TSDuck CLI。
- `api` 不含 TS 二进制编码细节；`diagnosis` 只消费 observation，不碰 TSDuck 进程、不解析原始 TS。
- `faults` → `ts`（FaultDefinition 应用到包模型）+ `tsduck` 接口（传输级路由）；`simulation` → `ts`/`faults`/`adapters`；`application` → 全部；`api` → `application`。
- `observation` 为统一事件交换接口。

### 5. 拓扑模型 —— GO，端口级连线保留、五平面维持

`SignalPlane` 五平面按 [ADR-0002](0002-mvp-ts-first-closed-loop.md) 维持（扩展位保留，MVP 只启用 `MPEG_TS`，未启用平面禁止连线）。连线保持端口级（`from_node/from_port → to_node/to_port`，SPEC-202/SPEC-003 §2.1 契约）：线性链中 Mux 天然多输入端口，node-to-node 模型在此处失效，退回节点对会在第一个多端口节点返工迁移存档拓扑。MVP 前端可做"默认端口自动生成"——用户拖节点对，落库端口对。

### 6. TSDuck Adapter 接口面 —— GO，三操作 + 五模块

接口面 = `analyze` / `inject` / `generate`（兜底，接口 MVP 预留，使用策略归 #14/#11）+ 进程管理。`adapters/tsduck/` 五模块：`process.py`（spawn/timeout/cancel/进程组清理）、`client.py`（三类操作）、`command_builder.py`（白名单 argv 构建，MVP 白名单 = #4 实测插件集 fuzz/craft/filter/slice/pcredit/inject/null/file + 生成链 tsxml/tstabcomp/tsp；用户配置不得直通任意 CLI 插件）、`report_parser.py`（JSON → Observation）、版本检测（`tsp --version` 正则提取并缓存，可执行文件 PATH 优先 + fallback 探测）。

#3 环境事实直接进契约：exit 0 ≠ 内容有效，必须过 JSON 内容门（`ts.bytes > 0 && ts.services.total >= 1`）；stderr 为 GBK 本地化输出，只做日志展示不做语义解析；注入 `TSDUCK_NO_VERSION_CHECK=1`；参数数组启动、禁 `shell=True`（ADR-0003 第 4 条）；每次调用记录版本/路径/argv/起止时间/退出码/stdout/stderr/输入 Artifact SHA-256（SPEC-001 §7）。TSDuck 输出的 Observation 一律 `source=tsduck, confidence=parsed`（CONTEXT.md 禁标 measured）。

## Consequences

- **#13 补写契约**：SPEC-104（PES）/SPEC-107（Mux 多节目调度）按语义层收窄重排优先级；SPEC-108 预留 TSDuck 生成兜底接口。
- **#12 缝合批准**：simulation 模块扩写按 L1-only 范围（含统一 Runtime 接口）；observation 扩写按双通路禁令不变。
- **#11 ts-core 修订**：并入 #6 标准核查订正项 5/6/7。
- **规格基线修订**：决策 2 所列三处文字随基线批准落地；归档 provenance（chatgpt-v04.md）不改。
- map 的 fog 项"模块依赖与代码目录结构定版"由本 ADR 决策 4 消解。
- 状态级教学因果传播（L0）延后至 roadmap；MVP 拓扑画布健康显示降级为 Run 状态 + 诊断事件映射。
