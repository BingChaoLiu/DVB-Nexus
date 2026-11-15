# Frontend Spec Index

**Package version:** 0.5.0
**Status:** APPROVED
**Normative parent:** DVB Sandbox SPEC-001/002/003；消费平台契约 SPEC-500/501/503 与 SPEC-305

[范围预批准 ticket #18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)（2026-11-14）：SPEC-400～406 的 MVP 切集已裁决为**范围级预批准**（下表「MVP 切集」列为裁决内容）；各 spec 实体文本编写归 M5 实现流程（SPEC-400 已随实现票 #61 编写，SPEC-403 已随实现票 #64 编写，SPEC-405 已随实现票 #66 编写（APPROVED 0.5.0，ticket [#15](https://github.com/BingChaoLiu/DVB-Nexus/issues/15) 批准记录），SPEC-401/402/404/406 待各票编写）。SPEC-407 Timeline & Replay UI（P2）在 `docs/roadmap.md` §3。

| Spec ID | Document | MVP 切集（#18 裁决） | 建议依赖 | MVP priority |
|---|---|---|---|---|
| SPEC-400 | [SPEC-400-frontend-architecture.md](SPEC-400-frontend-architecture.md) | 单 SPA 三路由区（Topologies / Monitor / Lab）；服务端状态 = 查询缓存 + WS journal/hint 触发重取，前端不自建第二事实源（journal 是唯一事实源，SPEC-501 best-effort 纪律的 UI 延伸）；TS 类型权威 = SPEC-500 Pydantic DTO，漂移须 CI 捕获（机制 = OpenAPI 生成 vs 手写 mirror，编写期定）；测试最小面 = 关键交互组件测试 + 一条八步闭环 E2E 冒烟（工具编写期定）；组件库/状态管理版本本裁决不冻结，编写期定（React Flow 归 #19） | SPEC-001/003 | P0 |
| SPEC-401 | [SPEC-401-topology-editor.md](SPEC-401-topology-editor.md) | 节点面板（类型清单声明式跟随 MVP NodeType 注册表，前端不自造类型）+ 拖放建节点 + 端口级连线 + 默认端口自动生成（ADR-0005 既裁）+ MPEG_TS 单平面（未启用平面禁连线与后端一致）+ 校验错误就地展示（SPEC-202 path-addressed + run prepare 422）+ 保存 = PUT 新 revision（不可变追加）；不做：撤销/重做、复制粘贴、多 tab 并行编辑、平面切换 UI、拓扑 diff | SPEC-003/500 | P0 |
| SPEC-402 | SPEC-402-node-inspector.md（待编写） | 每节点类型声明式字段清单 → 控件映射（数据源 = SPEC-108 §4 JSON↔DTO + 节点 Config Schema）；校验错误按 schema path 定位到字段展示；draft 编辑，校验通过才可保存/启动 session；不做：通用 JSON Schema 动态表单引擎（rjsf 类）、字段级实时校验、自定义表单布局 | SPEC-401/500 | P0 |
| SPEC-403 | [SPEC-403-stream-monitor.md](SPEC-403-stream-monitor.md) | 运行控制条（validate/start/pause/resume/stop/dispose + 状态徽章，SPEC-200 穷举表驱动）+ 概览卡 + PID/指标表（metrics/query 扁平标量 + summary）+ 诊断列表（priority/severity 排序 + confidence 三档 + evidence locator 呈现）+ verify 结果卡（三态 + 判据六 kind 明细）；诊断/verify 呈现组件定义在 403、406 复用叠加场景语境；实时性 = journal/hint 帧节流重取，非流式推送渲染；不做：时间轴图表（407 roadmap）、独立告警中心页（alerts 融入监控页）、自定义 dashboard、流式曲线图 | SPEC-302/501 | P0 |
| SPEC-404 | SPEC-404-packet-inspector.md（待编写） | 最小证据下钻：诊断 evidence locator（pid + packet_index + artifact）可点击 → 按 packet_index × 188 从 artifact content（Range）取单包 → hex + TS header 字段解码（sync/PID/continuity_counter/AF/PCR flag）；不做：PSI section 树、PES、baseline/faulted A/B 对照（后续增强，等位替换不变式保证将来增量小） | SPEC-100/305/503 | P0 |
| SPEC-405 | [SPEC-405-cli-console.md](SPEC-405-cli-console.md) | 「CLI 对照」= 来源标识区分（非双解析器 diff，SPEC-309 归 roadmap）：TSDuck 调用记录列表（九字段：版本/路径/argv/起止/退出码/stdout/stderr/输入 SHA）+ 调用详情（stderr GBK 原文只展示不解析；exit 0 ≠ 有效内容门语义显式标注）+ source 徽章过滤（generator/internal_parser/tsduck/hardware 四值枚举，hardware MVP 不出现）；不做：交互式命令输入（白名单 argv 由后端封装）、终端仿真、双栏 diff | SPEC-308/501 | P0 |
| SPEC-406 | SPEC-406-training-lab-ui.md（待编写） | 场景库列表（GET /scenarios，Lab Pack v1 SC-01~05）+ 场景详情渲染（目标/分阶段 hints/步骤/pass_criteria）+ 建实验 session（scenario_id 入参 + 预设 topology/seed）+ hints 渐进揭示（点击展开下一层，纯前端无后端参与）+ 通关结果卡（verify 三态 + 判据明细 + 诊断候选跳转，复用 403 组件）+ 八步闭环 stepper（Create→…→Verify 顶部指示）+ hidden_reference_solution 通关后展开；不做：计分/进度存档/多用户、场景编辑器（场景编写归实现流程，#17 既裁） | SPEC-205/206 | P0 |

## 裁决要点（详见 ticket #18 决议）

- **404 收编**（#18 Q1）：REGISTRY 原 P1 → MVP 内最小证据下钻（P0 最小版）；完整 Packet Inspector（section 树/PES/A-B 对照）仍为后续增强。
- **诊断/verify 呈现组件归属**（#18 Q5）：定义在 SPEC-403，SPEC-406 复用并叠加场景语境，防重复建设。
- **packet 级构造可视化事件 = MVP 外**（#18 Q8）：注册表不补事件类型；SPEC-301 §4 预留条款原样保持；TS Core MVP 无发射义务（SPEC-100~108 既无）；类型清单裁决推迟到 roadmap 期与生成可视化 UI 一并裁决；信封层无需变更（ADR-0005 决策 3 的语义层职责表述不变）。
- **通关纪律**（CONTEXT.md 既有）：UI 只渲染 SPEC-206 三态判定与判据明细，UI 状态不作通关证据。
