---
spec_id: SPEC-405
title: CLI Console
version: 0.5.0
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-308, SPEC-500]
requirements: [REQ-UI-405-001, REQ-UI-405-002, REQ-UI-405-003]
---

# SPEC-405 — CLI Console（CLI 对照台）

## 1. 目标

定义 CLI 对照台页面实体：TSDuck 调用记录列表（SPEC-308 §7 九字段权威，经 SPEC-500 §4.8 只读 REST 面消费）、调用详情（stderr GBK 原文只展示不解析；exit 0 ≠ 有效内容门语义显式标注）、source 徽章四值过滤（`generator / internal_parser / tsduck / hardware` 闭集，hardware MVP 恒空态）。

**「CLI 对照」钉死为来源标识区分**（CONTEXT.md「CLI 日志：真实 TSDuck 输出 vs 模拟日志，禁混标」；SPEC-308 §8）：本页面用来源徽章区分记录来源通道，**不是**双解析器结果 diff——解析器对比（自研解析器 vs TSDuck 分歧记录）归 SPEC-309（roadmap）。UI 判定禁令（CONTEXT.md「通关」词条精神）全文适用：本页对调用是否产出**有效报告**不作任何判定与暗示，有效性证据只存在于 AnalysisReport artifact 与 verify 判定（SPEC-206 三态）。

范围级预批准：ticket [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)；实现票 #66。消费契约：SPEC-308 §7/§8/§9（调用记录九字段与内容门语义权威）、SPEC-500 §4.8（`GET /api/v1/sessions/{id}/tsduck/calls` 只读面 + `TSDuckCallDTO` 逐字段）、SPEC-400 §4（路由注册与目录契约）、SPEC-503（kind=log artifact 边界，本页只读不落盘）。

## 2. 范围

### 2.1 In Scope

- CLI 对照台页面实体（`src/features/monitor/cli-console/`，SPEC-400 §4.1 目录契约下本票 OWN 的 monitor 区子面；经 Monitor 页 tab/段切换挂载，见 §4.1）。
- 调用记录列表（REQ-UI-405-001）：`GET /api/v1/sessions/{session_id}/tsduck/calls` 消费；`TSDuckCallDTO[]` 九字段 + `run_id` 逐列呈现（wire 字段名 snake_case 原样，SPEC-500 §4.8 表为准）；按 `started_at_utc_ms` 升序（服务端序，前端不重排）；可选 `run_id` query 过滤透传；空态 / 404 `SIM_SESSION_NOT_FOUND` / 501 未绑定三种非数据态的诚实区分呈现。
- 调用详情（REQ-UI-405-002）：选中记录的九字段全量展开；`stderr_text` 逐字原样等宽渲染（后端已完成 GBK→UTF-8 展示解码，前端禁再解析/再解码/trim）；`exit_code` 原值与「exit 0 ≠ 有效报告」内容门标注（SPEC-308 §9 `TSDUCK_JSON_GATE_FAILED` 家族语义）**并列显式呈现**，禁用单一对号/叉号暗示。
- source 徽章四值过滤（REQ-UI-405-003）：`generator / internal_parser / tsduck / hardware` 四值闭集过滤控件 + 每行来源徽章；来源身份按数据通道指派（§7.1），MVP 数据面唯一通道为 tsduck calls 面 ⇒ 全部记录徽章 `source=tsduck`；其余三值可选、恒诚实空态；**hardware MVP 不出现任何记录**（票面明文）。
- SPEC-405 实体文本（本文件）+ SPEC-INDEX-FRONTEND 行链接更新。

### 2.2 Out of Scope

- **交互式命令输入**：白名单 argv 由后端封装（SPEC-308 §5），本页禁提供任何命令/argv 编辑入口（不做清单，#18）。
- **终端仿真**：无 shell/PTY/光标/滚动缓冲语义；stdout/stderr 是静态展示文本块（不做清单，#18）。
- **双栏 diff**：真实 TSDuck 输出与自研解析结果的 A-B 对照归 SPEC-309（roadmap）（不做清单，#18）。
- 调用记录的写入/删除/重触发：tsduck calls 存储为 append-only（SPEC-500 §4.8），页面纯只读。
- 分页/虚拟滚动：MVP 单机单用户、记录量有界（SPEC-500 §4.8 既裁不分页）；列表整表渲染。
- TSDuck 可用性/版本探测管理面（`TSDUCK_NOT_FOUND`/`TSDUCK_VERSION_UNSUPPORTED` 是后端调用期错误码，本页不设配置入口）。
- run 日志 kind=log artifact 的浏览面板：generator 来源日志经 `RunStatusDTO.artifacts[]` + artifact content 的浏览归 Run 证据面（SPEC-403 Run 触发面 / SPEC-404 证据下钻语境）；本页列表数据面**只**为 tsduck calls 通道（数据模型裁定见 §7.1），不引入跨端点拼接聚合。

## 3. 术语

| 术语 | 定义 |
|---|---|
| 调用记录 | 一次 TSDuck 进程调用的 SPEC-308 §7 九字段持久化行 + 可选 `run_id` 关联；wire 形状 = `TSDuckCallDTO`（SPEC-500 §4.8） |
| 九字段 | `version / executable_path / argv / started_at_utc_ms / finished_at_utc_ms / exit_code / stdout_text / stderr_text / input_artifact_sha256`（SPEC-308 §7；`run_id` 为伴随关联字段，不入「九字段」计数） |
| 来源标识（source） | 记录产生通道的四值闭集 `generator / internal_parser / tsduck / hardware`（`ObservationSource` 五值中 CLI 相关四值，第五值 `rule_engine` 不入徽章）；**徽章值按数据通道指派，不是 DTO 字段**（§7.1） |
| 内容门（JSON gate） | SPEC-308 §9：`ts.bytes > 0 && ts.services.total >= 1`；门失败即 `TSDUCK_JSON_GATE_FAILED`（500）——**exit 0 的调用仍可能门失败**（垃圾输入实测 exit 0，#3） |
| GBK 展示文本 | 后端已对 stderr 做 UTF-8 decode + `errors="replace"` 后入库的 `stderr_text`（不可解码字节处为 U+FFFD）；前端拿到即**展示文本**，逐字渲染、不再解析（SPEC-308 §7「只做日志展示，不做语义解析」） |
| 诚实空态 | 空列表/空过滤结果的呈现，文案显式不得暗示「干净/无问题」（CONTEXT.md「把『无告警』等同于『干净』」禁令的空态延伸） |

## 4. 页面架构

### 4.1 路由区与页面骨架

页面实体挂载于 Monitor 路由区内，作为 `/monitor?session=<id>` 页面的**二档 tab/段切换**（「Stream Monitor」/「CLI 对照」，默认前者；无 `session` 参数时会话引导态共用，CLI 档在跟踪会话后可用）。注册方式 = `src/features/monitor/Region.tsx` **最小 additive 编辑**（tab 状态 + 条件渲染 + 一条 import；#66 批准裁定 R1，ticket #15 批准记录——`routes.tsx` 顶层三区导航结构保持不变）；CLI 组件实体全量位于 `src/features/monitor/cli-console/`（本票 OWN 子目录），Stream Monitor 既有面板 JSX 零改动（仅外层条件包裹）。

页面骨架（CLI 档）：顶部 source 过滤条（四值闭集，含「全部」视图）→ 调用记录列表（九字段列 + 来源徽章列 + 行选中进详情）→ 详情面板（九字段全量 + stdout/stderr 文本块 + 内容门标注区）。单页无子路由；详情以行选中态呈现。

### 4.2 调用记录列表（REQ-UI-405-001）

- 数据面：`GET /api/v1/sessions/{session_id}/tsduck/calls?run_id=`（SPEC-500 §4.8）；查询键走 monitor 区 canonical 约定（`["tsduck-calls", sessionId, runIdFilter?]`，SPEC-400 §5 键词表模式，feature-local 工厂导出，待共享 keys.ts additive 收编——SPEC-403 monitorKeys 同款先例）。
- 列呈现（wire 字段名 snake_case 原样为列语义权威，SPEC-500 §4.8 逐字段）：`version`、`executable_path`、`argv`（数组长度 + 展开态，逐元素原样）、`started_at_utc_ms`、`finished_at_utc_ms`（epoch-ms，UTC 呈现 ISO-8601；原始毫秒值 tooltip 保留）、`exit_code`（原值数字；`null` 呈现「—」+ 「进程未退到可回收码」提示）、`stdout_text`/`stderr_text`（列表列呈现存在性/长度，全文只在详情）、`input_artifact_sha256`（hex 原样）、`run_id`。
- 排序：服务端 `started_at_utc_ms` ASC 原序呈现，**前端不重排**（SPEC-500 §4.8 既裁）；前端排序控件不做。
- `run_id` 过滤：输入/选择 run 标识后作为 query 透传；清空恢复全量。过滤值格式前端不校验（后端语义权威）。
- 非数据态三分（§7.5）：空列表（200 + `[]`）、会话不存在（404 `SIM_SESSION_NOT_FOUND`，存在性判定 = 无存储记录且 journal 空）、存储面未绑定（501）。三态文案互相可区分，空态文案不暗示干净。

### 4.3 调用详情（REQ-UI-405-002）

- 选中行展开九字段全量（含列表省略的 `stdout_text`/`stderr_text` 全文）。
- **GBK stderr 纪律**：`stderr_text` 等宽字体逐字渲染——不 trim、不重排、不再 decode/encode、不按行解析、不提取错误摘要；U+FFFD 原样呈现（不可解码字节的后端替换标记，属诚实展示的一部分）。空串与 `null` 区分呈现（`null` = 失败路径字段显式缺省，SPEC-308 §7 不伪造纪律）。
- **exit 0 ≠ 有效标注**：详情页设置常驻「内容门语义」标注区，与 `exit_code` 原值**并列**呈现，文案钉死 SPEC-308 §9 语义：退出码 0 不代表报告有效（JSON 内容门 `ts.bytes > 0 && ts.services.total >= 1` 失败时调用仍 exit 0）；有效性证据指向 AnalysisReport artifact 与 verify 判定，本页不作有效性判定。`exit_code` 呈现禁用单一对号/叉号/「成功/失败」标签（#3/#13 禁令；数字原值 + 语义标注并列是唯一允许形态）。
- `stdout_text` 同等逐字纪律（展示文本，不解析）。

### 4.4 source 徽章与四值过滤（REQ-UI-405-003）

- 徽章：每行 + 详情头部呈现来源徽章，值为四值闭集字面量原样（`generator`/`internal_parser`/`tsduck`/`hardware`，snake_case wire 原样）；指派规则见 §7.1（通道指派，禁逐行臆造）。
- 过滤控件：四值 + 「全部」；单选（MVP 不做多选并集）。选中非 tsduck 值时呈现诚实空态：该来源在本会话暂无记录，且**显式注明不等于「干净/无问题」**；hardware 值附加注明「MVP 阶段 hardware 来源不产生记录」（票面明文 hardware MVP 不出现）。
- 词表完整性：四值闭集常量导出（`CLI_SOURCE_VALUES`），后续来源通道接入时（additive 路由/artifact 面）词表不变、仅数据面扩展。

## 5. 数据模型（消费 DTO 逐字段，wire snake_case 原样）

消费类型权威 = SPEC-500 §4.8 `TSDuckCallDTO`（OpenAPI 生成类型，`src/api/schema.gen.ts`；本票零手写 mirror——该模型自 #80 起可达）：

| 字段 | 类型 | 语义 | 呈现位 |
|---|---|---|---|
| `version` | string\|null | TSDuck 版本 | 列 + 详情 |
| `executable_path` | string\|null | 可执行路径 | 列 + 详情 |
| `argv` | string[] | 白名单 argv（数组原样，无 shell 拼接） | 列（计数）+ 详情（逐元素） |
| `started_at_utc_ms` | integer | 起始时间（epoch-ms） | 列 + 详情（ISO-8601 UTC 呈现，原值保留） |
| `finished_at_utc_ms` | integer | 结束时间 | 列 + 详情（同上） |
| `exit_code` | integer\|null | 退出码（null = 未退到可回收码） | 列（原值/—）+ 详情（原值 + 内容门标注并列） |
| `stdout_text` | string\|null | stdout 展示文本 | 列（存在性）+ 详情（全文逐字） |
| `stderr_text` | string\|null | stderr 展示文本（GBK 只展示不解析，UTF-8 decode errors="replace"） | 列（存在性）+ 详情（全文逐字，等宽） |
| `input_artifact_sha256` | string\|null | 输入 Artifact SHA-256 | 列 + 详情（hex 原样） |
| `run_id` | string\|null | 关联 run（有则填） | 列 + 详情 + 过滤入口 |

前端包装模型（组件内 props 形状，非 wire）：

```
interface SourceTaggedCall { source: CliSourceValue; call: TSDuckCallDTO }
type CliSourceValue = "generator" | "internal_parser" | "tsduck" | "hardware";  // 闭集常量 CLI_SOURCE_VALUES
```

`source` 由数据通道指派（§7.1），不伪造逐行来源。错误信封 = `ApiError`（`frontend/src/api` barrel 统一形状：`status/errorCode/message/retryable/details/requestId`）。

## 6. 公开接口

**本票无下游导出面**（#65/#67 不消费 CLI 对照台；SPEC-403 组件复用裁决 #18 Q5 不涉及本页）。页面实体为 Monitor 区内部子面；feature-local 查询键工厂 `cliKeys`（`["tsduck-calls", ...]`）随本目录导出，作为共享 `keys.ts` additive 收编候选（不强行落共享文件）。若后续票需复用九字段呈现组件，届时以 additive barrel 行评审导出，本票不预先冻结签名。

## 7. 处理算法

### 7.1 来源通道指派（REQ-UI-405-003 数据模型核心）

- 规则：**来源身份是数据通道的属性，不是记录行字段**。MVP 唯一记录通道 = `GET .../tsduck/calls`（SPEC-500 §4.8 明文该路由即 SPEC-308 §7 TSDuck 调用记录面）⇒ 该通道全部记录 `source = "tsduck"`，指派发生在数据面边界（fetch 函数返回 `SourceTaggedCall[]` 处），组件层不推断、不按内容猜测（禁「argv 含 preserve_package_names ⇒ tsduck」式臆造）。
- 扩展姿态：generator/internal_parser/hardware 来源记录若未来获得 additive 数据面（新路由或 artifact-kind 面），届时在数据面边界追加通道→来源映射；四值词表与过滤组件不变。
- 审计面说明：本模型为**单端点单投影**——列表 = 一条 REST 查询的缓存投影，无跨端点客户端拼接、无合并排序策略、无逐行来源推断，不构成第二事实源（SPEC-400 §3 查询缓存定义）；无需额外审计通道。
- 被否决备选（留档）：「tsduck calls + run log artifacts 两段聚合」——否决理由：(a) kind=log artifact 无九字段形状，混入将破坏「列表九字段与 SPEC-308 逐字段一致」验收锚（为 artifact 伪造记录形状字段 = 变相伪造）；(b) 无 run 列举 REST 面（仅 `GET /runs/{run_id}` 单查），generator 段需用户手输 run_id 才可达，交互面不成立；(c) 两段排序/合并为前端自造策略，徒增第二事实源风险面。generator 来源日志的浏览义务由 Run 证据面（SPEC-403/SPEC-404 语境）承担，本页不做清单第 5 条已显式排除。

### 7.2 过滤器（REQ-UI-405-003）

- 状态：`selectedSource: "all" | CliSourceValue`（默认 "all"）；过滤为纯前端内存过滤（记录已全量在缓存投影内，SPEC-500 §4.8 不分页既裁）。
- 谓词：`all` ⇒ 全量；其余 ⇒ `r.source === selectedSource`。稳定性：保持服务端 ASC 原序，不重排。
- 空结果：呈现所选来源的诚实空态（§7.5 文案矩阵），禁暗示干净。

### 7.3 GBK 展示纪律（REQ-UI-405-002）

- `stderr_text`/`stdout_text` 渲染管线：字符串 → 等宽 `<pre>` 语义块 → 逐字输出。禁操作清单：`trim()`、按行 split 后重组、编码检测/再解码、错误关键词高亮提取、ANSI 转义解析（后端展示文本无 ANSI 语义承诺）。
- 「GBK 原文不丢字」验收的实现含义：前端不丢字 = 渲染路径对字符串零变换；CJK 内容与 U+FFFD 均以 fixture 实测断言（§10）。

### 7.4 exit 0 ≠ 有效标注（REQ-UI-405-002，#3/#13）

- 详情页常驻标注区（不折叠、不条件隐藏）：`exit_code` 原值（数字原样 / null 说明）与标注文案**同一视区并列**。文案锚：「退出码 0 不代表报告有效 —— JSON 内容门（`ts.bytes > 0 && ts.services.total >= 1`）失败时调用仍以 0 退出（SPEC-308 §9）。有效性以 AnalysisReport 与 verify 判定为准，本页不作有效性判定。」
- 列表态禁令：`exit_code` 列禁配色/图标暗示成败（红绿/✓✗/「成功」「失败」文字标签均禁）；`null` 用「—」+ 提示。

### 7.5 非数据态文案矩阵（REQ-UI-405-001）

| 态 | 触发 | 文案锚（要点） |
|---|---|---|
| 空列表 | 200 + `[]` | 「该会话暂无 TSDuck 调用记录。MVP 生产栈不产生真实 TSDuck 调用（数据经测试/实机/fixture 种子）。空列表不是『无问题』的信号。」 |
| 过滤空态 | 过滤谓词零命中 | 「所选来源在本会话暂无记录。无记录 ≠ 干净。」；hardware 附加「MVP 阶段 hardware 来源不产生记录」 |
| 会话不存在 | `ApiError.errorCode === "SIM_SESSION_NOT_FOUND"` | 「会话不存在或无任何记录」+ 重试/换会话引导（错误信封 requestId 呈现） |
| 存储未绑定 | 501 | 「调用记录存储面在当前组合未绑定」 |
| 请求失败 | 其余 `ApiError` | 错误信封字段原样呈现（errorCode/message/retryable/requestId），重试按钮仅当 `retryable=true` |

## 8. 错误处理

- 一律经 `frontend/src/api` barrel 的 `ApiError` 信封（禁自拼 fetch、禁裸 response 检查）；`SIM_SESSION_NOT_FOUND` 404 语义按 §7.5 呈现（diagnoses 同款存在性判定，SPEC-500 §4.8）。
- 网络层失败/超时：查询缓存默认重试姿态 + 显式错误态；禁把请求失败渲染为空列表（空态专属于 200+`[]`）。
- 非法 `run_id` 过滤值：透传后端裁定（404/空列表语义后端权威），前端不预校验、不吞错。

## 9. 资源约束

- 目录契约：全部新文件位于 `src/features/monitor/cli-console/`；共享面改动 = `Region.tsx` 最小 additive 挂载编辑（tab 状态 + 条件渲染 + import 一条，裁定 R1；tab 切换不改变任何既有面板行为）、共享 `keys.ts` additive 行（候选，可延后）。禁动 `src/api/**`、禁动 Stream Monitor 既有面板 JSX（#64 落面，本票仅在 Region.tsx 做 R1 批准的最小包裹编辑并申报）。
- 类型权威：`TSDuckCallDTO` 用生成类型（schema.gen），禁手写 mirror（#80 起模型可达，#61 机制）；`CliSourceValue` 闭集为本票 OWN 常量。
- 无新增 npm 依赖；无新二进制资产（check_specs UTF-8 扫描面保持零风险）。
- 测试纪律：断言形状（wire 字段名/枚举串/排序语义/文案锚），禁整页 DOM 快照（tests/README §6）。

## 10. 测试向量

- **九字段契约 fixture**（验收锚，REQ-UI-405-001）：fixture `TSDuckCallDTO` 覆盖九字段 + `run_id` 全字段（含 null 路径：`exit_code=null`、`stderr_text=null`）；断言逐 wire 字段名呈现（snake_case 原样）+ ASC 原序保持 + `run_id` 过滤透传参数。
- **GBK 不丢字 fixture**（REQ-UI-405-002）：`stderr_text` 含 GBK 典型本地化文案 CJK（如「输入文件」「未能打开文件」类字样）+ 混入 U+FFFD；断言渲染文本与 fixture 逐字相等（零变换）；断言等宽呈现位存在。
- **exit 0 标注可见性**（REQ-UI-405-002）：`exit_code: 0` fixture ⇒ 内容门标注区文本可见；断言不存在唯一性成败暗示（无 ✓/✗/「成功」单一标签绑定 exit 0）。
- **四值过滤矩阵**（REQ-UI-405-003）：`SourceTaggedCall` fixture 覆盖四值 ⇒ 谓词矩阵逐值断言（含 "all"）；hardware 选中 ⇒ 诚实空态 + 「MVP 不产生记录」注明；空态文案断言不含「干净」暗示词。
- **非数据态**（REQ-UI-405-001）：200+`[]` / 404 `SIM_SESSION_NOT_FOUND` / 501 / 可重试错误 四态文案可区分断言。
- E2E（`e2e/cli-console.spec.ts`）：真实后端诚实空态冒烟（createStartedSession → `/monitor?session=<id>` → 切「CLI 对照」tab → 空态文案可见）；数据态交互经 Playwright route mock 注入九字段 fixture（mock 态在 spec 内显式标注；MVP 生产栈无真实 TSDuck 数据，mock 层仅用于 UI 交互冒烟，契约锚仍归组件测试）。八步闭环共享 spec 不动（无 CLI 步）。

## 11. 验收标准

- **AC-405-01**（REQ-UI-405-001）：列表呈现与 SPEC-308 §7 / SPEC-500 §4.8 `TSDuckCallDTO` 逐字段一致（wire 名 snake_case 原样断言）；按 `started_at_utc_ms` 升序原样呈现；`run_id` query 过滤透传生效。
- **AC-405-02**（REQ-UI-405-002）：`stderr_text` 逐字原样渲染不丢字（CJK + U+FFFD fixture 实测，渲染路径零变换）；`stdout_text` 同纪律；`null`/空串区分呈现。
- **AC-405-03**（REQ-UI-405-002）：`exit_code: 0` 时「exit 0 ≠ 有效报告」内容门标注与原值并列可见；禁单一对号/叉号/成败标签暗示（#3/#13）。
- **AC-405-04**（REQ-UI-405-003）：source 四值过滤矩阵正确（含 "all"）；hardware 恒无记录且空态注明 MVP 不产生；全部空态文案不暗示「干净」。
- **AC-405-05**（工程）：非数据态四分可辨（空/404/501/失败）；错误信封字段原样呈现；门禁全绿（lint/typecheck/test:run/build/dto:check/e2e + 后端三门 + check_specs 0 failed）。

## 12. 非目标

- 交互式命令输入、终端仿真、双栏 diff（不做清单，#18；§2.2）。
- 解析器对比/分歧记录（SPEC-309，roadmap）。
- 调用记录写入/删除/重试触发、分页、导出。
- 有效性判定：本页任何状态下都不产出「报告有效/无效」结论（UI 判定禁令）。
- hardware 来源记录呈现（MVP 无数据通路；词表保留四值闭集仅为过滤词表完整性）。

## 13. 兼容性与交付要求

- SPEC-500 §4.8 路由/DTO 为冻结面：本票零后端改动、零 `src/api/**` 改动；若发现共享面缺陷，上报不擅改（SPEC-005 协议）。
- Monitor 页挂载 additive（裁定 R1）：`Region.tsx` tab 状态 + 条件渲染 + import 一条，`routes.tsx` 顶层三区导航不变（SPEC-400 §4.2 结构保持）。
- 交付物：SPEC-405 文本（本文件）、INDEX 行链接、`src/features/monitor/cli-console/**`、E2E spec（可选面）、IMPLEMENTATION_REPORT（首节下游接口清单 = 无直接下游，写明共享面接触点与复用导出）贴票 #66。
- 后续增强留档：分页（additive 演进，SPEC-500 §4.8 同款路径稳定承诺）、多选过滤、generator 来源 artifact 浏览段（若获 run 列举面后重评）。
