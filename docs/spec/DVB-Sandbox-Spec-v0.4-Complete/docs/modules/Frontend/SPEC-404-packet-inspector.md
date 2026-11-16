---
spec_id: SPEC-404
title: Packet Inspector
version: 0.6.0
status: APPROVED
phase: MVP
owner: Frontend
priority: P0
depends_on: [SPEC-100, SPEC-305, SPEC-503]
requirements: [REQ-UI-404-001, REQ-UI-404-002, REQ-UI-404-003, REQ-UI-404-004]
---

# SPEC-404 — Packet Inspector（最小证据下钻）

## 1. 目标

定义 `/monitor` 诊断区的最小证据下钻实体：诊断 evidence locator（`{artifact_id, pid, packet_index}` 三元组，SPEC-403 §6 已交付可点击呈现位与 `onEvidenceSelect` 回调签名）被点击后，按 `packet_index × 188` 从 artifact content（SPEC-500 §4.4 Range 单区间语义）取单包 188 字节，前端纯函数解码为 hex dump + TS header 字段视图（sync/TEI/PUSI/priority/PID/scrambling/AFC/continuity_counter + Adaptation Field length/flags + random_access_indicator/PCR_flag + PCR base/extension），供证据链在包字节层落地（SPEC-306 §6 链末端：EvidenceRef）。

位级语义权威 = SPEC-100 §3 Header 位表与 §4 数据模型（实现镜像 `src/ts/packet.py`）；PCR 位编码语义 = SPEC-105（实现镜像 `src/ts/pcr.py`）。解码是**纯前端函数**（188 字节 → 字段视图）：不引入 WASM、不引入第三方 TS/解析库、后端零改动（范围级预批准 [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18) Q1 既裁——REGISTRY 原 P1「Packet 列表、Header/Hex/字段下钻」收编为 MVP 内最小证据下钻）。

UI 判定禁令（CONTEXT.md「诊断」延伸 + SPEC-400 §8）适用：本规格只呈现 wire/位域原样事实，不推导结论、不渲染诊断置信度为分数、不把「包可解析」当作任何判定证据。

范围级预批准：ticket [#18](https://github.com/BingChaoLiu/DVB-Nexus/issues/18)；实现票 #65。消费契约：SPEC-100 §3/§4/§5（位表与 AF 规则）、SPEC-105（PCR 位编码）、SPEC-305（artifact 几何与 Range 相关查询面）、SPEC-500 §4.4（REST artifact content）、SPEC-503（E2E 与门）、SPEC-403 §6（locator 呈现位与回调签名，冻结面）。

## 2. 范围

### 2.1 In Scope

- locator 点击入口接线（REQ-UI-404-001）：SPEC-403 导出组件 `DiagnosisCandidateList` 的 `onEvidenceSelect(locator, row)` 上接下钻状态（locator 三元组原样，组件不导航不解码的既有纪律不变）；Monitor Region 最小 additive 挂载（#66 R1 先例：一 import + 下钻状态 + 条件渲染）。
- 单包取数（REQ-UI-404-002）：元数据先行（`GET /api/v1/artifacts/{id}` → `ArtifactMetaDTO`，`packet_size` 应为 188、`packet_count` 用于越界预判）+ `GET /api/v1/artifacts/{id}/content` + `Range: bytes=<188*index>-<188*index+187>`（经 `src/api` barrel `packetRange`/`getArtifactContent`，禁自拼 fetch）；206 命中呈现 + 416/400 错误分支显式呈现。
- hex 呈现（REQ-UI-404-003）：188 字节逐字节 hex dump（offset + 16 字节/行 + ASCII 列），header 4 字节与 AF 区域标注。
- TS header 字段解码（REQ-UI-404-004）：SPEC-100 §3 位表逐字段（§7.1 抽取表）+ AF length/flags 布尔位（random_access_indicator 0x40、PCR_flag 0x10 等 8 位）+ PCR_flag=1 时 PCR base(33bit)/extension(9bit) 解码（SPEC-105 位装填）。
- 纯函数解码模块：`frontend/src/features/monitor/packet-inspector/` 内 `decode.ts`（无 React 依赖、无第三方解析依赖），单元测试以 golden 向量真实字节驱动（§10）。
- closed-loop E2E Inspect 步翻转（driver: rest → ui，本票 owner，additive 只动本步）。
- SPEC-404 实体文本（本文件）+ SPEC-INDEX-FRONTEND 行链接更新。

### 2.2 Out of Scope

- PSI section 树（PAT/PMT 重组、section 解析视图）——后续增强（#18 既裁不做）。
- PES 包解析视图——后续增强（#18 既裁不做）。
- baseline/faulted A/B 对照（同槽位并排 diff）——后续增强（#18 既裁不做；等位替换不变式保证将来增量小，#18）。
- Packet 列表页 / 全流浏览（REGISTRY 原 P1 形态的「Packet 列表」列；MVP 只有单包下钻，无列表、无翻页、无流内导航）。
- WASM、第三方 TS/十六进制解析库——解码为纯前端函数（#18；简报 §7.3）。
- 任何 Python 侧/后端变更（#18 后端零改动；artifact Range 服务面已由 SPEC-305/500 交付）。
- 事件浏览页（events UI 归 SPEC-407 roadmap；本票不新增 events 呈现面）。
- AF 私有数据/OPCR/splice countdown/extension 的完整解析呈现——只解析到 flags 位布尔与 PCR 值（#18 最小版；简报 §7.3「不要求完整 AF 私有数据解析」）。

## 3. 术语

| 术语 | 定义 |
|---|---|
| locator | 诊断 evidence 三元组 `{artifact_id, pid, packet_index}`（`DiagnosisEvidenceDTO`，SPEC-403 §6 回调原样上抛） |
| 单包 Range | `Range: bytes=<188*packet_index>-<188*packet_index+187>`（`TS_PACKET_SIZE=188`，SPEC-100 §3；服务端命中回 206 + `Content-Range: bytes start-end/size` + `Accept-Ranges: bytes`） |
| 等位替换 | baseline 与 faulted 共享 ADR-0007 item 4 同一 packet order（同 index = 同槽位）；本票不消费该对照（Out of Scope），仅依赖「packet_index 指向唯一槽位」这一几何事实 |
| AFC | `adaptation_field_control`（byte 3[5:4]，2 bit）：00 reserved/invalid；01 payload only；10 adaptation only；11 both（SPEC-100 §3） |
| AF | Adaptation Field：byte 4 为 length（0..183），length>0 时首内容字节为 8 个 flags（SPEC-100 §5.2） |
| PCR | 6 字节 Program Clock Reference：base(33) + reserved(6，须 `111111`) + extension(9)；合成 tick = base×300+extension（SPEC-105；`src/ts/pcr.py` L9-17） |
| 元数据先行 | 先 `GET /artifacts/{id}` 取 `ArtifactMetaDTO`（`packet_size`/`packet_count`）再发 Range 请求；`packet_size ≠ 188` 或 `packet_index ≥ packet_count` 时进入显式分支 |
| wire 原样 | 呈现值直接来自 wire 字节/字段，不经 UI 推导、重排或二次编码 |

## 4. 页面架构

### 4.1 挂载位与骨架

下钻面板挂载于 `/monitor` 诊断 Panel 内（SPEC-403 页面区，SPEC-400 §4.1 目录契约下本票 OWN `src/features/monitor/packet-inspector/` 子目录）。Monitor Region 承载最小 additive 接线（#66 R1 先例：一 import + 一段下钻状态 + 条件渲染；`DiagnosisCandidateList` 增加 `onEvidenceSelect` prop 一行）：Region 持 `drillDown: DiagnosisEvidenceDTO | null` 状态，回调仅 `setDrillDown(locator)`（locator 原样，无派生），面板组件受控呈现（data in via props + 自取数 query，SPEC-403 §6「组件不导航不解码」纪律由 Region 侧接线保持）。无新路由、无新 tab、无 routes.tsx 变更。

### 4.2 locator 点击入口（REQ-UI-404-001）

呈现位由 SPEC-403 交付（候选行 `dvb-mon-locator` 按钮，仅候选行携带 evidence；`DiagnosisDTO` 行无 evidence 字段）。本规格交付回调消费：点击 → 下钻面板以该三元组为查询输入。同 artifact 重复点击同槽位（React Query key 含三元组）不重复取数；点击另一 locator → 面板切槽位。再次点击同 locator 或关闭动作可清空面板（无证据选中态 = 面板不渲染，诚实空态）。

**深链入口（§4.1 挂载的补充进入路径，实现期申报 D6）**：`/monitor?session=<id>&inspect_artifact=<id>&inspect_pid=<n>&inspect_packet=<n>` 以同一三元组语义种子同一面板——动机是结构性事实：analyze REST 面冻结 501（M4 裁定 B），UI 链路无 `ts.*` 分析事实 → 诊断候选诚实为零 → 候选行 locator 在闭环 UI 链内不可达；深链让证据数据链（meta 门 → Range 取包 → 解码呈现）可在真实后端上端到端走通，locator 点击链由组件层测试覆盖（mocked api seam + 冻结回调签名）。参数畸形（缺参/负数/非整数）→ 种子为空（诚实缺席，禁伪造 locator）；本页面对 `inspect_*` 参数只读不写（回写面归 tracker 既有行为）。

### 4.3 单包取数（REQ-UI-404-002）

流程（§7.3 分支表为准）：

1. `getArtifactMeta(artifactId)`（`src/api` barrel）：`packet_size` 存在且 ≠ 188 → 显式「非 188 包几何」分支（不发送 Range 请求）；`packet_count` 存在且 `packet_index ≥ packet_count` → 显式越界分支（416 语义预判，仍以服务端裁决为权威——若并发几何变化，真实 416 走 §8 错误分支）。
2. `getArtifactContent(artifactId, { range: packetRange(packetIndex) })`：期待 `status === 206`；`bytes.length === 188`（不足 → 显式截断分支）；`contentRange`（如 `bytes 9400-9587/37600`）与 `acceptRanges`（`bytes`）原样呈现作可追溯证据。
3. ApiError（400 `HTTP_RANGE_MALFORMED` / 416 / 网络）→ §8 分支显式呈现，禁伪装成功、禁静默重试吞错。

### 4.4 hex 呈现（REQ-UI-404-003）

188 字节 → 12 行 hex dump（11 行 × 16 字节 + 末行 12 字节；纯函数 `toHexDump`）：行首 4 位 hex offset（0x0000 起），每行 16 个 2 位 hex 字节位 + 右侧 ASCII 列（可打印 0x20..0x7E 原字符，否则 `.`）。header 字节（0..3）与 AF 起始（byte 4，AFC∈{10,11} 时）以 CSS 标注。渲染值 = 字节真值（大小写、分组、列宽为呈现惯例，值本身零变换）。

### 4.5 字段视图呈现（REQ-UI-404-004）

§7.1 抽取表逐字段一行：字段名 + 原始位值（hex/dec 原样）+ 语义注记（如 `PID 0x1FFF = null 包`、`AFC 01 = payload only`、`scrambling 00 = 不扰码`）。AF 段：`af_length` + 8 个 flags 布尔（bit→名，含 random_access_indicator=bit 0x40、PCR_flag=bit 0x10）；PCR_flag=1 时渲染 `pcr base / extension / 合成 tick`（§7.2 装填公式）。AFC=00 渲染显式「reserved/invalid（SPEC-100 §3）」分支（wire 事实呈现，不抛错不静默）。sync_byte ≠ 0x47 渲染显式告警行（`TS_SYNC_BYTE` 语义），其余字段仍按位呈现（不阻断）。

## 5. 数据模型（消费 DTO 与派生视图，wire snake_case 原样）

### 5.1 消费 DTO（`src/api` barrel 权威，禁镜像改动）

| DTO | 来源 | 本票消费字段 |
|---|---|---|
| `DiagnosisEvidenceDTO` | SPEC-403 `onEvidenceSelect` 回调（wire 原样） | `artifact_id` / `pid`（13 bit 值）/ `packet_index`（≥0） |
| `ArtifactMetaDTO` | `getArtifactMeta` | `packet_size`（应 188）/ `packet_count`（越界预判）/ `byte_size` / `kind`（呈现上下文） |
| `ArtifactContentResult` | `getArtifactContent(artifactId, { range })` | `status`（期待 206）/ `bytes: Uint8Array`（期待 188）/ `contentRange: string \| null` / `acceptRanges: string \| null` |
| `ApiError` | barrel | `status` + errorCode 信封（§8 分支键） |

### 5.2 派生视图（本票 OWN，纯函数输出）

```ts
// decode.ts — 188 字节 → 字段视图；位语义权威 SPEC-100 §3（实现镜像 src/ts/packet.py L51-118）
export interface TsHeaderView {
  sync_byte: number;                     // byte 0，应 0x47
  sync_byte_ok: boolean;
  transport_error_indicator: boolean;    // byte 1 bit7（TEI）
  payload_unit_start_indicator: boolean; // byte 1 bit6（PUSI）
  transport_priority: boolean;           // byte 1 bit5
  pid: number;                           // byte1[4:0]<<8 | byte2，13 bit
  pid_is_null: boolean;                  // === 0x1FFF（SPEC-100 §5.1）
  transport_scrambling_control: number;  // byte 3[7:6]；00 不扰码，01/10/11 用户定义（DVB 惯例 10/11=偶/奇）
  adaptation_field_control: number;      // byte 3[5:4]
  afc_reserved: boolean;                 // === 0
  continuity_counter: number;            // byte 3[3:0]，0..15
}
export interface AfView {
  af_length: number;                     // byte 4（AFC∈{10,11} 时存在）
  flags_present: boolean;                // af_length > 0（SPEC-100 §5.2：length=0 无 flags）
  flags: number | null;                  // 8 bit 原值
  discontinuity_indicator: boolean;      // flags 0x80
  random_access_indicator: boolean;      // flags 0x40
  elementary_stream_priority_indicator: boolean; // flags 0x20
  pcr_flag: boolean;                     // flags 0x10
  opcr_flag: boolean;                    // flags 0x08
  splice_countdown_flag: boolean;        // flags 0x04
  transport_private_data_flag: boolean;  // flags 0x02
  adaptation_field_extension_flag: boolean;      // flags 0x01
  pcr: PcrView | null;                   // pcr_flag=1 时 6 字节解码
}
export interface PcrView {
  base: number;        // 33 bit（0..2^33-1）
  reserved_ok: boolean; // 6 bit 须 0b111111（SPEC-105）
  extension: number;   // 9 bit（0..299）
  combined_ticks: number; // base*300 + extension
}
export interface TsPacketView {
  header: TsHeaderView;
  adaptation_field: AfView | null; // AFC=01/00 → null（01 无 AF；00 reserved 不解析）
}
export function parseTsPacket(packet: Uint8Array): TsPacketView;
export function toHexDump(bytes: Uint8Array): HexRow[]; // 12 行结构化行（offset/字节/ASCII）
```

## 6. 公开接口

- 不新增公开 barrel 行：locator 呈现位与回调签名已由 SPEC-403 `components` barrel 冻结交付（`DiagnosisCandidateList { onEvidenceSelect? }`），本票只消费。
- `src/features/monitor/packet-inspector/` 内部面：`decode.ts`（§5.2 纯函数，内部导出）、`usePacketDrillDown.ts`（meta+content 查询 hook）、`PacketInspectorSection.tsx`（受控面板组件，仅 Region 挂载消费）、`packet-inspector.css`。
- Monitor Region additive 接线（申报面）：1 import + `drillDown` state + `onEvidenceSelect` prop 一行 + 条件渲染面板。
- canonical `src/query/keys.ts` 不动（共享面禁改；下钻查询键为组件内局部 query key，随受控挂载生灭，无失效义务——artifact content 不可变字节）。

## 7. 处理算法

### 7.1 TS Header 位抽取表（SPEC-100 §3 权威镜像；REQ-UI-404-004）

| 字节/位 | 字段 | 掩码/移位 | 宽 | 值语义 |
|---|---|---|---:|---|
| 0 | `sync_byte` | `b[0]` | 8 | 固定 `0x47`（≠ 时 §4.5 告警行） |
| 1[7] | `transport_error_indicator` | `(b[1] >>> 7) & 1` | 1 | TEI |
| 1[6] | `payload_unit_start_indicator` | `(b[1] >>> 6) & 1` | 1 | PUSI |
| 1[5] | `transport_priority` | `(b[1] >>> 5) & 1` | 1 | 优先级 |
| 1[4:0]+2 | `pid` | `((b[1] & 0x1F) << 8) \| b[2]` | 13 | 0..8191；`0x1FFF` = null 包 |
| 3[7:6] | `transport_scrambling_control` | `(b[3] >>> 6) & 0x3` | 2 | 00 不扰码；01/10/11 用户定义（DVB 惯例 10/11 = 偶/奇钥） |
| 3[5:4] | `adaptation_field_control` | `(b[3] >>> 4) & 0x3` | 2 | 00 reserved/invalid；01 payload only；10 adaptation only；11 both |
| 3[3:0] | `continuity_counter` | `b[3] & 0x0F` | 4 | 0..15，per-PID 连续 |

### 7.2 AF 与 PCR 解码（SPEC-100 §5.2 + SPEC-105 装填；REQ-UI-404-004）

- AFC∈{10,11}（`10`=adaptation only、`11`=both）→ byte 4 为 `af_length`（0..183；AFC=11 上限 182）；`af_length === 0` → 无 flags 字节（`flags_present=false`）。
- `af_length > 0` → byte 5 为 8 bit flags；位→布尔映射（实现镜像 `src/ts/adaptation_field.py` L237-244/367-369）：`0x80` discontinuity、`0x40` random_access_indicator、`0x20` elementary_stream_priority、`0x10` PCR_flag、`0x08` OPCR_flag、`0x04` splice_countdown、`0x02` transport_private_data、`0x01` extension。flags 后可选字段只解析到 PCR（OPCR/splice/private data/extension 仅呈现 flag 布尔，不做完整解析——Out of Scope §2.2）。
- `pcr_flag === 1` → 紧随 flags 的 6 字节 PCR（装填公式，SPEC-105；实现镜像 `src/ts/pcr.py` L9-14）：
  - `base = (be32(b0..b3) << 1) | (b4 >>> 7)`（33 bit）
  - `reserved = (b4 >>> 1) & 0x3F`，`reserved_ok = (reserved === 0x3F)`
  - `extension = ((b4 & 0x01) << 8) | b5`（9 bit）
  - `combined_ticks = base * 300 + extension`（27 MHz tick；纯整数，不用浮点）
- 边界守卫：`af_length` 超过剩余字节（理论畸形 wire）→ 显式截断注记行，不静默、不抛错中断其余字段呈现。
- AFC=01 → `adaptation_field = null`；AFC=00 → `afc_reserved=true`，不解析 AF 区域（§4.5 分支）。

### 7.3 Range 取数分支（SPEC-500 §4.4；简报 §2.4 实测语义；REQ-UI-404-002）

| # | 条件 | 结果 | 呈现 |
|---|---|---|---|
| 1 | `packet_size` 存在且 ≠ 188 | 本地预判门 | 显式「非 188 包几何」分支（不发 Range 请求；显示实际 packet_size） |
| 2 | `packet_count` 存在且 `packet_index ≥ packet_count` | 本地越界预判（416 语义） | 显式越界分支（显示 index 与 packet_count；服务端真实 416 仍以 §8 分支兜底） |
| 3 | Range 命中 | 206 + `Content-Range` + `Accept-Ranges: bytes` | hex + 字段视图；`contentRange`/`acceptRanges` 原样呈现 |
| 4 | `start >= size`（含 suffix 形态不适用本票） | 416 + `Content-Range: bytes */size` | ApiError 分支：显式 416 呈现（含 size） |
| 5 | multi-range/语法畸形/`end < start` | 400 `HTTP_RANGE_MALFORMED` | ApiError 分支：显式 400 呈现（本票 header 由 `packetRange` 生成，正常不可达；保底显式分支） |
| 6 | `bytes.length !== 188`（服务端截断等） | — | 显式截断分支（显示实际字节数），不进入解码 |
| 7 | meta 请求失败（404 等） | — | ApiError 分支显式呈现 |

分支 3 之外一律不渲染 hex/字段视图（不伪装成功）；错误分支文案带 errorCode/状态码原样。

### 7.4 查询编排（REQ-UI-404-002）

- 查询键（组件内局部）：`["packet-inspector", artifact_id, packet_index]` 覆盖 meta+content 两个 `useQuery`（content 查询 `enabled = meta 门通过`）。artifact 字节不可变 → `staleTime: Infinity` 语义，无失效义务（§6）。
- `pid` 不参与取数（Range 只由 `packet_index` 决定），呈现为字段视图注记：「locator pid X，本包 header PID Y」——两值可不同（locator 指向证据事件锚定的槽位，包 PID 为 wire 事实），禁互相覆盖呈现。

## 8. 错误处理

| 源 | 形状 | 呈现 |
|---|---|---|
| Range 400 | `HTTP_RANGE_MALFORMED`（信封三键） | 面板内显式错误态：状态码 + errorCode 原样 + 人话一行 |
| Range 416 | `Content-Range: bytes */size` | 显式越界态：packet_index、换算 start、服务端 size 原样 |
| meta 404 / 网络错误 | `ApiError` | 显式错误态（状态码 + message），不重试风暴（React Query 默认重试关闭面与 403 既有纪律一致） |
| 解码边界（sync≠0x47 / AFC=00 / AF 截断） | wire 事实 | 不抛错：对应注记/告警行 + 其余字段照常呈现（§4.5） |
| 非 188 packet_size / 截断响应 | 几何门 | 显式分支（§7.3 行 1/6），不进入解码 |

禁令：任何错误分支不得回退为空态/上一包内容/「无数据」混淆呈现；`ApiError` 不得吞为 console-only。

## 9. 资源约束

- 每次下钻恰 1 次 meta GET + 1 次 Range GET（188 字节响应体）；无轮询、无 WS 依赖、无预取邻包。
- 解码与 hex 为同步纯函数（188 字节 O(n) 常数级），无 Worker/WASM/第三方库。
- 组件测试断形状不快照 DOM（SPEC-400 测试纪律）；fixture 用 golden 向量真实字节（§10），禁手造伪字节替代 golden。
- 后端零改动（#18）：`src/api/**`、`src/query/**`、`schema.gen.ts` 均 NOT-TOUCH。

## 10. 测试向量

权威向量（TEST-VECTOR-INDEX，全部 registered，sha256 门生效）：

| 向量 | 用途 | 断言 |
|---|---|---|
| `docs/test-vectors/golden/packet-header-set/packet-header-set.ts`（10 包）+ `expectations.json` | 解码字段 oracle（TEI/PUSI/优先级/PID 边界/scrambling/AFC/CC 边沿 + packet 6 PCR base=12345/extension=0） | 逐包 `parseTsPacket(bytes[188i:188i+188])` 每字段 === expectations（含 packet 3 PID 8191=null、packet 5 scrambling=1 reserved、packet 7 AFC=10、packet 8 discontinuity/RAI flags） |
| `docs/test-vectors/golden/cc-discontinuity{,-baseline}/*.ts` | 188×index 偏移纪律（等位替换同槽位：同 index 两流同槽位字节面） | 每包切片 `b[0] === 0x47`（188×index 对齐即 sync 恒中）；同 index 的 baseline/faulted 包头 PID/CC 面与各自 expectations 一致（delta 落点 slot 50 前后） |
| `pcr-wrap`（6 包 PCR 边界） | PCR 装填公式边界（base 2^33−δ） | base/extension/combined_ticks 与 manifest/expectations 一致 |

fixture 纪律（验收「取包落点与 artifact 字节逐位一致」）：单元测试文件以 `fs` 读 golden 真实字节（仓库相对路径解析，.ts 后缀为 MPEG-TS 资产不入 UTF-8 扫描面——`tools/check_specs.py` BINARY_SUFFIXES），逐位驱动 `parseTsPacket`/`toHexDump`；禁在测试内手造字节替代 golden、禁快照 DOM。

## 11. 验收标准

| AC | 映射 REQ | 内容 |
|---|---|---|
| AC-404-1 | 001 | 从 SPEC-403 诊断列表 locator 点击到 hex+header 解码呈现全链路可走通：locator 点击链（候选行按钮 → 回调 → 面板）由组件层测试覆盖（mocked api seam）；closed-loop E2E Inspect 步以 ui 驱动走通数据链（深链入口，真实后端字节逐位对拍）并钉死诚实零候选态（analyze 冻结 501 的结构性结果，M4 裁定 B） |
| AC-404-2 | 002 | 取包落点与 artifact 字节逐位一致：Range header 为 `bytes=<188*i>-<188*i+187>`；单元 fixture 以 golden 真实字节断 188×index 偏移（每包切片 sync=0x47、字段===expectations）；E2E 断 `contentRange` 与 206 |
| AC-404-3 | 003 | 188 字节 hex dump 逐字节呈现（offset/ASCII 列），值 = wire 真值零变换 |
| AC-404-4 | 004 | 解码字段与 SPEC-100 §3 语义一致：§7.1 表逐字段（golden packet-header-set expectations 逐字段对拍）+ AF flags 位 + PCR base/extension（SPEC-105 装填，pcr-wrap 向量对拍） |
| AC-404-5 | 002 | 416（index ≥ packet_count）/400 畸形/非 188 packet_size/截断响应：错误分支显式呈现，不伪装成功 |
| AC-404-6 | 001..004 | 纯前端解码成立：无 WASM、无第三方解析库、`src/api` barrel 复用（禁自拼 fetch）、后端零改动 |

## 12. 非目标

- PSI section 树、PES、baseline/faulted A/B 对照（三项 #18 既裁后续增强；等位替换不变式保证将来等位替换/增量实现不破坏本票槽位几何）。
- Packet 列表/全流浏览、包间导航、多包 Range（服务端单区间语义内本票只用单包公式）。
- AF 私有数据/OPCR/splice/extension 内容解析；TEI 纠正或任何「修复」语义（SPEC-100 §2.2）。
- 事件浏览页、时间轴（SPEC-407 roadmap）。
- 通关判定相关任何状态（本票为证据呈现面，UI 状态不作证据——CONTEXT.md 通关禁令延伸）。

## 13. 兼容性与交付要求

- 上游冻结面：SPEC-403 `components` barrel 签名（`onEvidenceSelect(locator, row)`）原样消费，不改 #64 已落文件除 Region 最小 additive 挂载（§4.1，申报）；`src/api/**` 接口面（`getArtifactMeta`/`getArtifactContent`/`packetRange`）原样复用。
- 下游影响：#67（SPEC-406）复用 SPEC-403 候选组件时获得同款下钻入口（SPEC-406 通关卡「诊断候选跳转」与本面板天然衔接，#67 无需新面）；本票不新增 barrel 导出义务。
- 交付物：`packet-inspector/` 模块 + Region additive 接线 + 单元/组件测试 + E2E Inspect 步翻转（`frontend/e2e/closed-loop.spec.ts` 仅 Inspect 步 + 步骤地图注记行）+ SPEC-404 文本（本文件）+ SPEC-INDEX-FRONTEND 行链接。
- 本地门：`npm run lint / typecheck / test:run / build / dto:check / e2e` + 后端三门（pytest 四组、`PYTHONPATH=$PWD/src lint-imports`、`python -I tools/check_specs.py` 0 failed）。
- git：merge `integration/m5`（tip 可能因 #63 并行前进；冲突禁擅断，报 orchestrator）；禁推远端、禁关票。

## Phase 2 定点修订（随落笔票 #119，DRAFT_FOR_REVIEW 0.6.0；依据：细裁 [#113](https://github.com/BingChaoLiu/DVB-Nexus/issues/113)/[#114](https://github.com/BingChaoLiu/DVB-Nexus/issues/114)，SPEC-600~603/610/611 依赖）

- **视图参数 additive**：包检查器新增 `view` 参数（`view=t2mi|bbframe|ts`，默认 `ts` 保 MVP 兼容）；既有 locator（pid + packet_index + artifact）语义不变，深链三元组（inspect_artifact/inspect_pid/inspect_packet）不追加语义，仅 view 参数扩展（Lab 诊断证据深链与 Monitor 直达共用）。
- **T2-MI 包视图**（view=t2mi）：6 字节包头逐字段解析（TS 102 773 §5.1）+ CRC-32 校验结果 + BBFrame 载荷指针；数据源 = artifact 字节 + 自研解封装器结构 JSON（json_map 生成链，禁手写 mirror）。
- **BBFrame 视图**（view=bbframe）：BBHEADER 10 字节逐字段（MATYPE/UPL/DFL/SYNC/SYNCD/CRC-8，EN 302 755 §5.1.7）+ CRC-8 校验 + UP 边界标注；文案教学锚点「SYNCD 是数据字段内首个 UP 的位距离，不是同步字节」直接入视图文案。
- **BISS 加扰态标注**：payload 层 scrambled/clear 标注 + 密钥指纹引用（密钥本体永不渲染）；biss.descramble_failed 证据与 mutation log 互链。
- 排除项维持（#114）：不做 BISS Mode E 计算器式交互（ESW/Injected ID 计算过程展示属 SPEC-611 语义面，UI 只呈证据）；不做 section 树/PES/A-B 对照（既有非目标延续）。
