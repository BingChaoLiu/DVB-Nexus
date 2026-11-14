# 生态与替代方案调研：复核"自研 TS Core"（ADR-0003）

- **对应 Issue**: BingChaoLiu/DVB-Nexus #4（生态与替代方案调研）
- **日期**: 2026-11-14
- **调研方式**: 本机 TSDuck 3.40-4165 实测（Windows，`D:\Program Files\TSDuck`）+ Web 调研；复核对象为 ChatGPT 生成规格包（`temp/chatgpt-v04.md`）§6/§15 的"自研 Python TS Core + TSDuck 仅作外部验证器"主张
- **性质**: 纯调研，未改动任何 GitHub issue / 仓库文件 / git 状态

---

## 0. 结论摘要（TL;DR）

1. **"TSDuck 只是验证器、不是生成器"这个前提不成立**。TSDuck 官方文档有专门章节"Creating a transport stream from scratch"（User Guide §5.2.21.2/§5.2.21.3），本机实测 `tsxml → tstabcomp → tsp -I null -P inject` 链路可从零生成合法 TS，且**两次独立运行字节级一致（md5 相同）**。
2. **ChatGPT §15 的"平台自主性"理由部分成立但被夸大**。实测用纯 TSDuck 插件链把 §6 定义的 F001–F006 六类故障全部注入成功并全部可验证（PAT 缺失 / CRC 错 / CC 跳变 / CC 重复 / PCR 异常 / 随机误码），`fuzz --seed` 有官方文档保证的字节级复现。因此**"TSDuck 插件拼装"作为 MVP 是够用的**。
3. 但 TSDuck 插件链有**真实的表达力边界**（语义级故障、生成过程可视化），"展示每个 Packet 的生成过程"这一教学沙盘核心差异化能力只有自研核心能做到——这是三条理由中唯一"硬"的一条。
4. **推荐：混合路线（修正版）**——自研 Python TS Core 收窄为"语义层"（PSI/表/字段级故障的构造期注入 + Packet 级可视化模型），传输层故障（丢包/误码/抖动）与验证全部交给 TSDuck（`fuzz/craft/slice/filter/pcredit + tsanalyze/pcrverify/continuity`）。五维总分 21/25，高于完全自研 19/25 与纯 TSDuck 拼装 18/25。
5. **ADR-0003 需要修正而非推翻**："自研 TS Core 作为长期技术资产"成立；"完全自研、TSDuck 只做验证"不成立。TSDuck 应同时承担验证器、传输层故障注入器、（MVP 期）生成兜底三重角色。
6. 远期 T2-MI：解封装现在就有三套现成方案（TSDuck `t2mi` 插件、FFmpeg 7.1 `t2mi` demuxer、DVBInspector PLP 导出）；若需要 T2-MI **封装（builder）**，Rust crate [`dvb-t2mi`](https://crates.io/crates/dvb_t2mi) 是唯一现成实现（v14.0.0，2026-11-13 发布，MIT OR Apache-2.0），可用 PyO3/CLI 集成，不阻塞当前架构。

---

## 1. 调研方法与实测环境

| 项 | 值 |
| --- | --- |
| 本机 TSDuck | 3.40-4165（2025-02-23 发布），离线文档 `doc/tsduck.html` / `tsduck-dev.html` |
| 实测工具链 | `tsxml → tstabcomp → tsp → tsanalyze/tsanalyze --json / tstabdump / tscmp / continuity / pcrverify` |
| 插件规模（实测 `tsp --list-plugins`） | **13 个输入 + 13 个输出 + 77 个处理插件**（比规格包说的"约 85 个处理插件"略多） |
| 实验产物 | 临时目录 `/tmp/tsduck-exp`（仓库外，未入库）：golden.ts、f001–f006.ts、pcr-golden2.ts、fuzzA1/A2/B.ts |
| Web 数据 | GitHub API（stars/license/最后 push）、crates.io API、TSDuck User/Developer Guide、各项目官网 |

golden 流定义：PAT（TSID=1，program 1 → PMT_PID 0x0101）+ PMT（service 1，PCR_PID 0x0102，两个 component PID 0x0102/0x0103）+ 79 个空包，共 100 包 / 18,800 字节。

---

## 2. 问题 1：TSDuck 能否"按配置生成带特定故障的确定性 TS"？

### 2.1 生成路径（能力存在，且是官方文档化用例）

- **从零建流**：User Guide §5.2.21.2/§5.2.21.3（"Creating a transport stream from scratch / with PCR"）官方给出的范式即 `tsp -I null` + 表注入插件：null 输入插件生成空包，`inject`（注入 tables/sections，支持 XML/JSON/binary 输入与重复周期）、`mux`（插入整段 TS 并自动维护 CC）、`eitinject`（EIT）、`datainject`/`mpeinject` 等逐层"偷换"空包。
- **表编译**：`tsxml`/`tstabcomp` 把 XML/JSON 描述编译为带正确 CRC32 的二进制 section；`tspacketize` 独立完成"表 → TS 包"打包。TSDuck 内置完整表模型（`tsduck.tables.model.xml`），可生成 PAT/PMT/SDT/NIT/BAT/EIT/CAT/AIT/私有表等几乎所有 DVB 表。
- **字节级构造**：`craft` 插件（同时提供 input 与 processor 两种形态）可逐字段构造/改写 TS 包：`--pid`（改 PID）、`--continuity-counter`、`--pcr`、`--pusi`、`--error`、`--discontinuity`、`--payload-pattern/--payload-xor/--payload-and/--payload-or` + `--offset-pattern`、`--scrambling` 等——这就是官方自带的"字段级包构造器"。
- **结论**：生成能力存在且被官方文档正面支持。ChatGPT 规格包里"TSDuck 是验证工具、不是生成器"的定位表述与文档不符。

### 2.2 故障注入实测：F001–F006 全部可注入、可验证

golden 流 + 下列插件链，全部在 3.40-4165 上实测通过（命令与验证结果）：

| 故障 | 插件配方（实测通过） | 验证手段与结果 |
| --- | --- | --- |
| F001 PAT 缺失 | `tsp -I file golden.ts -P filter -p 0x0000 --negate -O file f001.ts` | `tsanalyze`：PID 0x0000/PAT 消失 ✓ |
| F002 PAT CRC 错 | `-P craft -p 0x0000 --payload-xor 000000FF --offset-pattern 12`（CRC32 位于 PAT payload 偏移 12–15） | `tables --invalid-sections`：**"Invalid section, invalid CRC32"** 显式报告 ✓ |
| F004 CC 跳变（丢包） | `-P filter -i 20 --negate -i 30 --negate`（按绝对包号丢两个 PMT 包） | `continuity`：`PID 0x0101, missing 2 packets` ✓ |
| F005 CC 冻结/重复 | `-P craft -p 0x0101 --continuity-counter 3` | `continuity`：`missing 15 packets` + `duplicate packets` ✓ |
| F006 PCR 异常 | 三级链：`-P filter -p 0x0102 --set-label 1 -P filter --only-label 1 --every 2 --set-label 2 -P pcredit --only-label 2 --unit millisecond --add-pcr 50`（只偏移每隔一个 PCR 包 +50ms） | `pcrverify`：报出最高 **243,428 µs** 的 PCR jitter ✓ |
| 随机误码 | `-P fuzz --corrupt-probability 1/20 --seed <hex>` | `tsanalyze` 检出 sync/传输错误；见 2.3 确定性 ✓ |

配套事实：

- `fuzz` 之外的故障工具还有：`pattern`（按 PID 替换字节模式）、`slice`（按包号/毫秒分窗丢包或替换空包）、`time`（按时间调度）、`trigger`/`filter --set-label`（事件标记）、`pcrduplicate`（复制 PCR 包）、`limit/reduce`（码率截断）、`until`、独立工具 `tsfuzz.exe`（不经过 tsp 直接 fuzz 文件）。
- 每个故障都可用 TSDuck 自身完成"故障注入 → 观测"闭环：`tsanalyze`（含 `--json`）、`continuity`、`pcrverify`、`tables`（CRC/版本校验）、`history`、`stats`——这正是教学沙盘需要的"通关必须由新的观测结果证明"的机制（§6.3），且 TSDuck 已内建。

### 2.3 确定性复现实测：成立

1. **生成链确定性**：同一条 `tsp -I null 100 -P inject ×2` 命令独立运行两次，输出 **md5 完全相同**（`69581057…`）。
2. **fuzz 确定性（官方保证）**：`fuzz --help` 原文——"Using the same seed on the same TS file will result in exactly the same corruptions. Without this parameter, a random seed is used and the corruptions cannot be identically reproduced."。实测：同 seed 两次 md5 相同（`162dd1b1…`），换 seed 输出不同（`c91833b4…`）。**字段级随机误码可以做到固定 seed 字节级复现**。
3. **注意**：`pcredit --random`（随机时间戳破坏）没有 seed 参数，不可复现——确定性 PCR 故障必须用固定值 `--add-pcr`（实测即如此做）。这属于"选对参数"问题，不是能力缺陷。
4. **整个 tsp 链不引入时间/随机源**（除非显式使用 `timeref`/`--random`/无 seed 的 fuzz），文件输出是纯确定性变换。

### 2.4 插件链的表达力边界（实测发现的坑与拼不出的东西）

实测过程中确认的实现细节/坑（对"配置 → 插件参数"编译器很重要）：

- `tsp -I null` 的包数是**位置参数**（`-I null 100`），不存在 `--packet-count` 全局选项；`inject` 必须给重复率（`file=rate` / `--inter-packet` / `--bitrate`）。
- `filter` 多条件默认 **OR** 合取；`--set-label` 是"只标记不丢包"；`-i`（包号区间）按**到达该插件阶段的包**计数——跨插件做"某 PID 的第 N 包"要用 `--only-label` 两级链（实测 f004c/f006 均验证）。
- `craft` 的 `--pid` 是"改 PID"（输入选择与重命名同一选项）；`--payload-*` 偏移是 **payload 相对偏移**，且模式默认跨整个 payload 重复（手术式单点损坏要 `--no-repeat`）。
- PAT 的 XML 子节点是 `<service service_id=… program_map_PID=…>`（不是直觉的 `<program>`），需要对照 `tsduck.tables.model.xml`。

**拼装路线真正做不到/很难做的**：

1. **语义级故障**：如"PAT version 不按规范递增""PMT 与 PAT 联动错误且 CRC 合法""PCR base 与 ext/extension 字段不一致""descriptor 边界越界但长度合法"——插件层只能在"整段 payload 覆盖/字节 XOR"层面操作，无法在"保持 CRC 正确的前提下修改字段"（`regenerate` 类插件反而会自动修 CRC，方向相反）。这类故障需要自研核心在构造期注入。
2. **生成过程可视化**：插件链是黑盒管线，外部只能看到"配置 → 命令行 → 文件 + 事后 dump"。TSDuck 有 `dump` 插件可逐包十六进制输出，但那是"事后解释"，不是"每一步构造的因果展示"。教学沙盘的差异化能力（学生看到"这一步写了这 4 字节 CRC"）在 B 路线无法实现。
3. **故障描述与实现的耦合**：每加一种故障都要找/拼插件参数组合，`FaultDefinition`（§6.1）到 tsp 参数的映射面大且脆；自研核心里故障只是"构造函数参数"。

**判定**：TSDuck 插件链**能**组合出"按配置生成带特定故障的确定性 TS"（MVP 四类故障全部实测通过），但表达力上限低于自研核心，且无法支撑生成过程可视化。

---

## 3. 问题 2：竞品/同类工具

### 3.1 对比总表

| 工具 | 定位 | 语言/集成 | 许可证 | 维护状态（2026-11 查证） | 生成能力 | 故障注入 | 教学沙盘适配 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TSDuck** | TS 全家桶（分析+处理+生成+验证） | C++，官方 Python/Java 绑定（`import tsduck`） | **BSD-2-Clause** | **极活跃**：约 3–4 个月一个版本（v3.40 2025-02 → v3.45 2026-09），仓库 2026-11-11 仍有 push，1099 stars | ✅ 官方文档化（§5.2.21 从零建流；null+inject/mux/craft/tspacketize） | ✅ 系统化（fuzz/craft/slice/pattern/pcredit/filter/trigger…，fuzz 支持 seed 复现） | **高**：CLI 可被 Python 编排、可装 Python 绑定、插件生态最大 |
| **DVBInspector** | 深度分析/教学查看器 | Java 21（Swing GUI） | **GPL-3.0** | 活跃：v1.21.0（2025），仓库 2026-10 仍有 push，241 stars | ❌ 仅分析（最多导出 T2-MI PLP 为新 TS） | ❌ | 中：可作为"第二参考视图"独立使用；GPL 传染风险使其不宜直接集成进沙盘代码 |
| **OpenCaster** | TS 生成器工具集（PSI/SI/EPG 生成、复用、播出） | Python + C（Debian/Linux） | **GPL-2.0+** | **基本停滞**：上游约 2014 年后无正式 release，社区 fork（如 aventuri/opencaster，2024-05 有零星 push，74 stars） | ✅ 强（但面向播出链路） | ❌ 无系统化注入 | 低：Linux 老工具链，Windows 沙盘不适配，依赖陈旧 |
| **GStreamer `mpegtsmux`** | 多媒体复用器 | C（gst-plugins-bad，monorepo） | LGPL-2.1+ | 活跃（随 GStreamer monorepo 滚动） | ✅ 有 mux + SI section 事件注入 + m2ts 模式 | ❌ | 低：重型运行时依赖；输出未承诺确定性；PID/复现细节难控 |
| **FFmpeg mpegts muxer** | 通用复用器 | C | LGPL-2.1+（部分 GPL） | 极活跃 | ✅ 有（PAT/PMT 自动生成，参数化程度低） | ❌ | 低：语义控制颗粒度粗，不适合字段级教学 |
| **kynesim/tstools**（BBC 系） | TS/PS/ES 读写库与工具 | C | **GitHub 未提供 license 元数据**（许可不明确） | **停滞**：最后 push 2019-05，无 release | 部分（es2ts/ts_packet_insert 等） | 无（tsplay 可"introduced errors"但极简） | 低 |
| **Comcast/gots** | TS 解析库 | Go | MIT | 低活跃（2026-08 有 push，310 stars，多年低频） | 部分 | ❌ | 低：Go 语言，与 Python 技术栈不符 |
| **threefive** | SCTE-35 解析/编码 | Python | MIT | 活跃（164 stars） | 解析为主 | ❌ | 远期 SCTE-35 实验可参考 |
| **dvb-t2mi（Rust）** | T2-MI parser + **builder** | Rust（sans-IO） | MIT OR Apache-2.0 | 活跃但**采用度低**（v14.0.0 发布于 2026-11-13，总下载 1,656；家族仓库 13 stars） | T2-MI 层 builder | ❌ | 远期（见 §4） |

结论：**没有任何单一开源工具同时满足"确定性生成 + 字段级故障注入 + 教学沙盘 UI 集成"**。最接近的是 TSDuck（三样里有两样半：生成 ✅、故障注入 ✅、UI 集成半✅——可编排可嵌入但生成过程不可视化）。DVBInspector/OpenCaster/GStreamer/FFmpeg 各自只覆盖一角。TSDuck 的 BSD-2 许可证对沙盘集成无传染风险（对比 DVBInspector 的 GPL-3、OpenCaster 的 GPL-2）。

### 3.2 关键链接

- TSDuck：官网/用户指南 <https://tsduck.io/docs/tsduck.html>；开发者指南（Python 绑定）<https://tsduck.io/docs/tsduck-dev.html>；仓库 <https://github.com/tsduck/tsduck>（BSD-2-Clause）
- DVBInspector：<https://github.com/EricBerendsen/dvbinspector>；主页 <https://www.digitalekabeltelevisie.nl/dvb_inspector>
- OpenCaster：<https://github.com/aventuri/opencaster>（fork；上游 Avalpa，SourceForge 归档）
- GStreamer mpegtsmux：<https://gstreamer.freedesktop.org/documentation/mpegtsmux/mpegtsmux.html>
- tstools：<https://github.com/kynesim/tstools>；gots：<https://github.com/Comcast/gots>；threefive：<https://github.com/futzu/threefive>

---

## 4. 问题 3：dvb-t2mi Rust crate 现状

- **crate**: [`dvb-t2mi`](https://crates.io/crates/dvb_t2mi)——"ETSI TS 102 773 DVB-T2 Modulator Interface parser + builder"（**既解析也封装**，这点独特：TSDuck/FFmpeg/DVBInspector 都只有解封装方向）。
- **版本/活跃度**: v14.0.0 发布于 **2026-11-13（调研前一天）**；属于 [`fishloa/rust-broadcast`](https://github.com/fishloa/rust-broadcast) 工作区（70+ 个 spec 对齐的广播协议 crate：`dvb-si`/`dvb-t2mi`/`dvb-bbframe`/`dvb-conformance`/`dvb-tools` 等，同 tag 锁步发版，2,046 commits，仓库 2026-11-14 仍有 push）。家族质量工程（spec 引用、round-trip 测试、`no_std`、sans-IO）看起来很专业。
- **成熟度风险**: 总下载仅 **1,656**、仓库 13 stars/1 fork——**采用度极低、单人项目特征**，无第三方生产背书；与 TSDuck（1099 stars、十年级历史）不可同日而语。
- **许可证**: MIT OR Apache-2.0（仓库级 Apache-2.0）——商业/教学集成都无障碍。
- **Python 集成可行性**: 家族已有 `bindings/python`（`dvb-si-py`、`transmux-py`），**但 dvb-t2mi 本身尚无官方 Python 绑定**。可行路径：(a) 用 `dvb-tools` CLI 子进程（`dvb-tools t2mi` 子命令）；(b) 仿照 `dvb-si-py` 用 PyO3 写一层薄绑定（crate 是 sans-IO 纯 Rust，绑定成本低）；(c) 通过 PyO3 的 maturin 脚手架发布 wheel。
- **横向对照（T2-MI 生态）**: 解封装（decode）方向已有三套现成方案——TSDuck `t2mi` 处理插件（本机 3.40 已含）、**FFmpeg 7.1（2024-09）新增 `t2mi` demuxer**（`libavformat/t2midec.c`）、DVBInspector 的 T2-MI PLP 导出。封装（encode/builder）方向目前只有 dvb-t2mi crate。
- **裁决输入**: T2-MI 是远期需求且是"解封装为主"的场景（从卫星分发流还原 TS），**现在不引入任何依赖**；远期优先用 TSDuck/FFmpeg 现成解码，若真需要"构造 T2-MI 流"再评估 dvb-t2mi crate（届时它的成熟度需重新复核，或用 PyO3 自制绑定）。**不阻塞、不影响当前 TS Core 决策。**

---

## 5. 问题 4：三路线五维对比与裁决

评分 1–5（5 最好）。"完全自研"= ChatGPT §15 原方案（自研生成 + TSDuck 仅验证）；"TSDuck 拼装"= Python 编排 tsp 插件链承担生成+注入；"混合"= 自研核心管语义层 + TSDuck 管传输层故障与验证。

| 维度 | A. 完全自研 TS Core | B. TSDuck 插件拼装 | C. 混合（自研语义层核心 + TSDuck 补边/验证） |
| --- | --- | --- | --- |
| **字段级故障注入颗粒度** | **5** — 任意字节任意语义，FaultDefinition 直落 bit；语义级故障（version 不递增、CRC 合法的字段矛盾等）无限制 | **3** — F001–F006 实测全部可注入，但受插件参数空间约束（payload 相对偏移、OR 语义、标签计数），语义级/联动类故障拼不出来或越来越脆 | **5** — 语义级在构造期注入（任意表达）；传输层（丢包/误码/抖动）交 TSDuck fuzz/craft/slice（fuzz 有 seed 官方保证） |
| **确定性复现** | **5** — 纯函数生成，天然字节级确定 | **4** — 实测 golden 链 md5 一致 + fuzz seed 官方保证；扣 1 分：跨 TSDuck 版本的插件调度行为漂移需快照回归兜底 | **5** — 核心纯函数确定 + TSDuck 后处理实测确定（seed/固定参数），RunManifest 重放 → 字节一致 |
| **教学可解释性（每个包的生成过程可视化）** | **5** — 唯一能做到"构造步骤 → 字节"因果展示的路线 | **2** — 黑盒管线；只有事后 dump/分析，无生成过程 | **4** — 核心包完整可视化；TSDuck 后处理用 `tscmp` golden/fault 字节 diff + 事件时间线解释（比纯自研的"我改的"更客观）；扣 1 分：包来源需标注（core 生成 / TSDuck 变换） |
| **维护成本** | **2** — 188B 打包、section 分段、CRC32、CC/PCR 编码、PES 全要自己写自己测；协议正确性无第三方背书，教学项目"教错"代价高 | **4** — 协议正确性由 TSDuck 背书（BSD-2、3–4 月/版、2026-11 仍活跃）；只维护编排层；风险是命令行参数语法漂移 | **3** — 自研面收窄到 PSI/表/CC/PCR 调度与故障模型；传输层外包；"自研单测 + TSDuck 验证器"双保险 |
| **MVP 周期** | **2** — 最慢：PAT/PMT/null 可两周内完成，但 PES/PCR/分段/多表排期长 | **5** — 本机 0.5 天跑通 F001–F006 注入+验证全闭环；MVP ≈ 配置 → 命令模板库 | **4** — MVP 只需"自研 PSI 层 + 空包调度 + TSDuck 补边"，PES/视频可后置（MVP 期用 TSDuck inject/pattern 充当假负载） |
| **总分** | **19 / 25** | **18 / 25** | **21 / 25** |

**裁决**：

- A（完全自研）输在维护成本与 MVP 周期，赢的两项（颗粒度、可解释性）恰是 C 同样能拿到的——A 相对 C 没有增量优势。
- B（纯拼装）输在教学可解释性——这是本项目定位（教学 + 排查沙盘）的**核心差异化**，不是可妥协项；且长期会撞上语义级故障的表达力墙。
- **C（混合）胜出**。注意 C 与 ChatGPT 版"混合/自研"的差异：ChatGPT 的 C 是"自研生成 + TSDuck 只验证"；实测修正后的 C 是"**自研核心负责语义层（表/字段级故障构造 + 包可视化），TSDuck 承担传输层故障注入 + 验证 + MVP 期生成兜底**"——TSDuck 的故障注入插件（fuzz/craft/slice）本来就是为了"在成品流上做变换"，与自研核心是互补而非竞争关系。

---

## 6. 对 ChatGPT §15 理由的独立判定

原文："不要把 TS Generator 完全交给 TSDuck 插件拼装，否则以后你想研究字段级故障注入、实现自定义协议演练、展示每一个 Packet 的生成过程时，平台的自主性会受到限制。TSDuck 应该帮助你验证生成器，而不是替代生成器。"

| 论点 | 独立判定 | 依据 |
| --- | --- | --- |
| "TSDuck 不是生成器，只应做验证器" | **不成立（前提错误）** | User Guide §5.2.21.2/§5.2.21.3 官方文档化"从零创建 TS"；本机实测生成链确定性成立 |
| "字段级故障注入需要自主性" | **部分成立，被夸大** | 实测 TSDuck 插件链已能确定性注入 F001–F006 全部四类故障（§2.2），MVP 完全够用；但语义级故障与复杂联动确有表达力墙（§2.4），长期看自研核心在此维度更优 |
| "展示每个 Packet 的生成过程需要平台自主性" | **成立（唯一硬理由）** | 插件链是黑盒，无法做构造过程可视化；这是教学沙盘的差异化核心，只有自研核心能提供 |
| "自定义协议演练需要自主性" | **大体成立** | 私有表/描述符可通过 TSDuck XML 模型注入一部分，但"自定义协议行为演练"超出插件参数空间；不过此需求在 MVP 中排期靠后，不构成现在的决策依据 |
| （隐含）"自主性 = 必须完全自研生成器" | **不成立** | TSDuck 有官方 Python 绑定（`import tsduck`，Developer Guide §2.4.5，Windows 安装包可选组件）且可被 subprocess 精细编排——"平台自主"可以在"Python 拥有数据模型与编排权、TSDuck 作为可嵌入引擎"的架构下实现，不必二选一 |
| （ChatGPT 遗漏）确定性 | **未提及但可满足** | golden 链 md5 复现 + `fuzz --seed` 官方保证（§2.3）；这恰恰是"不用完全自研也能拿到"的第五维度关键分 |

---

## 7. 最终推荐与 ADR-0003 修正建议

**推荐：采用修正版混合路线（C）。**

1. **保留** ADR-0003 的"自研 Python TS Core 为长期技术资产"，但**收窄 MVP 范围**：
   - 核心只做：TS 包/Section 打包模型（含 CRC32）、PAT/PMT/SDT（+NIT/EIT 按需）、CC 调度、PCR 调度、`FaultDefinition` 双路由（语义级 → 构造期参数；传输级 → TSDuck 插件参数）、Packet 级构造过程可视化事件流。
   - **明确推迟**：PES/视频音频打包、多节目 MPTS 复杂调度、T2-MI。
2. **TSDuck 三重角色**写入 ADR：验证器（`tsanalyze --json`/`continuity`/`pcrverify`/`tables`）、传输层故障注入器（`fuzz --seed`/`craft`/`slice`/`filter`/`pcredit`）、MVP 期生成兜底（`tsxml→tstabcomp→inject`）。§6.3"通关必须由观测证明"直接复用 TSDuck 的 JSON 观测输出作为判分依据。
3. **回归防线**：对每条 golden/故障链保存 md5 + `tsanalyze --json` 快照，升级 TSDuck 时跑快照测试（应对 §2.4 所述行为漂移）。
4. **集成方式**：MVP 用 `asyncio subprocess` + 文件中转（避免管道编排复杂度）；TSDuck 官方 Python 绑定（Windows 安装包可选组件，本机当前未装）作为后续优化项。
5. **T2-MI（远期）**：解封装用 TSDuck `t2mi`/FFmpeg 7.1 现成能力；若需 builder 再评估 `dvb-t2mi` crate（当前采用度过低，暂不引入）。
6. **ADR 记录修正点**：推翻"完全自研、TSDuck 仅验证"的二分表述；补充实测证据（本报告 §2）作为裁决依据。

---

## 8. 附录 A：实测命令记录（TSDuck 3.40-4165，Windows）

```bash
BIN="D:/Program Files/TSDuck/bin"

# golden 生成（两次运行 md5 一致：695810573d9c533494c65373511b80eb）
$BIN/tstabcomp -o pat.bin pat.xml   # PAT: TSID=1, service 1 -> PMT_PID 0x0101 (16B)
$BIN/tstabcomp -o pmt.bin pmt.xml   # PMT: service 1, PCR_PID 0x0102 (26B)
$BIN/tsp -I null 100 -P inject -p 0x0000 --inter-packet 10 pat.bin \
        -P inject -p 0x0101 --inter-packet 10 pmt.bin -O file golden.ts

# F001 PAT 缺失
$BIN/tsp -I file golden.ts -P filter -p 0x0000 --negate -O file f001.ts
# F002 PAT CRC 错 -> "Invalid section, invalid CRC32"
$BIN/tsp -I file golden.ts -P craft -p 0x0000 --payload-xor 000000FF --offset-pattern 12 -O file f002.ts
$BIN/tsp -I file f002.ts -P tables --invalid-sections -O drop
# F004 CC 跳变 -> "missing 2 packets"
$BIN/tsp -I file golden.ts -P filter -i 20 --negate -i 30 --negate -O file f004.ts
$BIN/tsp -I file f004.ts -P continuity -O drop
# F005 CC 冻结 -> "missing 15 packets" + "duplicate packets"
$BIN/tsp -I file golden.ts -P craft -p 0x0101 --continuity-counter 3 -O file f005.ts
$BIN/tsp -I file f005.ts -P continuity -O drop
# F006 PCR 异常 -> pcrverify 报 243,428 us 抖动（三级标签链，只偏移每隔一个 PCR）
$BIN/tsp -I file pcr-golden2.ts -P filter -p 0x0102 --set-label 1 \
        -P filter --only-label 1 --every 2 --set-label 2 \
        -P pcredit --only-label 2 --unit millisecond --add-pcr 50 -O file f006.ts
# fuzz 确定性：同 seed 两次 md5 相同；换 seed 不同
$BIN/tsp -I file golden.ts -P fuzz --corrupt-probability 1/20 --seed <64hex> -O file fuzzA1.ts
```

PCR 基线流构造（含实测坑）：`filter --every 10 --set-label` + `craft --only-label --pid 0x0102 --pcr 300000 --payload-pattern FF` 把空包改造成 PCR 包（注意 `filter` 条件默认 OR、`craft -p/--pid` 是同一选项），再 `pcradjust --bitrate 2000000` 让 PCR 线性递增后 `pcrverify` 才有参考基准。

## 附录 B：来源链接

- TSDuck User Guide（§5.2.21 从零建流、fuzz/inject/mux 插件）: <https://tsduck.io/docs/tsduck.html>
- TSDuck Developer Guide（§2.4.5 Python 绑定）: <https://tsduck.io/docs/tsduck-dev.html>
- TSDuck GitHub（BSD-2-Clause，v3.45-4798 2026-09-12）: <https://github.com/tsduck/tsduck>
- TSDuck releases: <https://github.com/tsduck/tsduck/releases>
- DVBInspector（GPL-3.0，v1.21.0）: <https://github.com/EricBerendsen/dvbinspector> / <https://www.digitalekabeltelevisie.nl/dvb_inspector>
- OpenCaster fork（GPL-2.0，上游停滞）: <https://github.com/aventuri/opencaster>
- GStreamer mpegtsmux 文档: <https://gstreamer.freedesktop.org/documentation/mpegtsmux/mpegtsmux.html>
- tstools（BBC 系，2019 年后停滞，license 元数据缺失）: <https://github.com/kynesim/tstools>
- Comcast/gots（Go，MIT）: <https://github.com/Comcast/gots>
- threefive（Python SCTE-35，MIT）: <https://github.com/futzu/threefive>
- dvb-t2mi crate（v14.0.0，2026-11-13，MIT OR Apache-2.0）: <https://crates.io/crates/dvb_t2mi>
- rust-broadcast 工作区: <https://github.com/fishloa/rust-broadcast>
- FFmpeg 7.1 Changelog（t2mi demuxer，libavformat/t2midec.c）: <https://github.com/FFmpeg/FFmpeg/blob/master/Changelog> / <https://ffmpeg.org/ffmpeg-formats.html>
- 本仓库规格包：`D:\Document\Project\DVB-Nexus\temp\chatgpt-v04.md`（§6 故障清单 F001–F006、§15 最终架构建议）
