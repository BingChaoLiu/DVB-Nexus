# TSDuck Windows 环境验证调研报告（Issue #3）

- 调研日期：2026-11-14
- 调研方式：本机（Windows 10.0.26200 x64）实测 + 本地离线 User Guide（随安装附带）+ 官网/GitHub/winget 在线核对
- 本报告只做调研，不涉及 GitHub issues 或 git 操作

---

## 1. 结论速览

| 项目 | 结论 |
|---|---|
| 本机是否已安装 | **已安装**，TSDuck 3.40-4165（官方 installer 安装） |
| 安装路径 | `D:\Program Files\TSDuck`（可执行文件在 `bin\`，已在 PATH） |
| 当前最新稳定版 | **3.45-4798**（本机 3.40-4165 落后若干版，运行时会自提示） |
| 安装方式 | 官方 exe installer（传统）/ **winget**（官方推荐：`winget install tsduck`）；另有 portable zip；**无官方 scoop/choco 包** |
| `tsanalyze --json` | **实测可用**；输出 JSON 顶层键 `pids / services / tables / time / ts`；支持 `--json / --json-line / --json-tcp / --json-udp` |
| Windows 退出码/stderr | 成功=0；失败=1 且错误仅走 stderr（`* Error: ` 前缀）；**垃圾输入也是 exit=0**，Worker 必须校验 JSON 内容而非只看退出码 |
| tsp Windows 插件 | 13 input + 13 output + 约 85 processor 全部可用（含 dvb/dektec/hides/vatek/srt/rist/hls/pcap/fork/memory）；硬件调谐受限（DirectShow/BDA） |
| 下游决策 a（golden streams 验证） | **Windows 上完全可行**，且已产出可复现的 golden stream 生成链路（见 §4、§6.1） |
| 下游决策 b（Worker 子进程接口） | 接口面已实测定型（见 §6.2）：stdout=JSON、stderr=日志、退出码 0/1、支持 stdin 管道 |

---

## 2. 本机安装状态（实测）

### 2.1 已安装事实

- `where tsp` / `where tsanalyze` 命中：`D:\Program Files\TSDuck\bin\tsp.exe`、`...\tsanalyze.exe`
- `tsp --version` / `tsanalyze --version`：`TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165`
- 安装根目录 `D:\Program Files\TSDuck\`：`bin\`、`doc\`、`setup\`、`LICENSE.txt`、`OTHERS.txt`、`TSDuckUninstall.exe`
- `bin\` 共 130 个文件：37 个 `.exe` + 74 个 `tsplugin_*.dll` + `tsduck.dll`/`tscore.dll` + 数据模型文件（`tsduck.tables.model.xml`、`tsduck.dtv.names` 等）
- 安装来源：`winget list --name TSDuck` 显示 ARP（添加/删除程序）条目 `TSDuck 3.40-4165`，即官方二进制 installer 安装；本机未装 scoop/choco
- 随附完整离线文档：`doc\tsduck.html`（User Guide 全文）、`doc\tsduck-dev.html`、`doc\CHANGELOG.txt` —— 离线环境下可直接查文档

### 2.2 版本时效

- tsp 运行时自提示：`* new TSDuck version 3.45-4798 is available (yours is 3.40-4165), use 'tsversion --upgrade' or see https://tsduck.io/`
- winget 源中 `TSDuck.TSDuck` 当前版本即 3.45-4798（发布说明指向 GitHub tag `v3.45-4798`）
- 环境变量 `TSDUCK_NO_VERSION_CHECK`（非空即生效）可关闭该在线检查；`TSDUCK_GITHUB_API_TOKEN` 可增强 GitHub API 访问（均见 User Guide 环境变量表）

---

## 3. Windows 安装方式与系统要求（官方文档 + winget 核对）

### 3.1 官方安装途径

1. **winget（官方 User Guide §1.3.1 称为 "modern method"、首选）**：
   ```
   winget install tsduck
   ```
   包 ID `TSDuck.TSDuck`，发布者 TSDuck（tsduck.io），作者 Thierry Lelegard，许可证 BSD。User Guide 明确 winget "should be pre-installed on all recent Windows 10 and Windows 11 systems"。
2. **官方二进制 installer（传统方式）**，托管在 GitHub Releases（下载页 https://tsduck.io/download/tsduck/ ）：
   - `TSDuck-Win64-3.45-4798.exe`（Intel x64）
   - `TSDuck-Arm64-3.45-4798.exe`（ARM64）
   - **portable zip**：`TSDuck-Win64-3.45-4798-Portable.zip` / `TSDuck-Arm64-3.45-4798-Portable.zip`（免安装、免管理员权限，适合 CI/沙箱）
   - installer 内可选 **"Development" 组件**（头文件/库，用于编译 TSDuck 扩展）
3. **scoop / chocolatey**：官方均无包（官网下载页与构建文档均不提及；核对结论：不存在官方 scoop/choco manifest）

### 3.2 系统要求

- 官方未列明 RAM/CPU 等硬性要求；下载页仅区分 **Intel 64 位 / Arm 64 位**
- User Guide 对 Windows 的平台描述覆盖 Windows 7/10/11（winget 场景按微软口径为 Windows 10 1809+/Windows 11）
- 无服务/守护进程，纯命令行工具集，安装后 `bin\` 直接进 PATH

### 3.3 版本升级路径

- `tsversion --upgrade`（TSDuck 自带升级命令）或 `winget upgrade tsduck`
- 建议 DVB-Nexus 文档中锁定测试基线版本（本机 3.40-4165），升级前跑回归

---

## 4. `tsanalyze --json` 能力（本机实测）

### 4.1 最小合法 TS 的构建（golden stream 生成链路，已跑通）

手工拼包容易在 section_length/CRC 上出错（调研中实际踩坑：手写 PMT 被 TSDuck 判为 Unreferenced）。**推荐用 TSDuck 自身工具链生成**，全程可复现：

1. 用 TSDuck XML 格式描述 PAT/PMT（正确 schema 见 `bin\tsduck.tables.model.xml`；PAT 子元素为 `<service service_id="1" program_map_PID="0x1000"/>`，PMT 为 `<component stream_type="0x1B" elementary_PID="0x0101"/>`）
2. `tstabcomp data/pat.xml data/pat.bin`（编译为二进制 section，CRC 由 TSDuck 计算）
3. 注入 null 流：
   ```
   tsp -I null 1000 -P inject -p 0 --inter-packet 100 data/pat.bin -P inject -p 4096 --inter-packet 100 data/pmt.bin -O file data/golden.ts
   ```
   产出 188000 字节 / 1000 包（188×1000），含 PAT(PID 0)、PMT(PID 0x1000)、PCR(PID 0x100)、AVC video(PID 0x101)、null(PID 8191)

> 注：本机 3.40 的 inject 插件要求每个实例显式 `-p PID`，且必须三选一指定 `--replace` / `--bitrate` / `--inter-packet`；两个 PID 需两个 inject 实例串联。文件可直接给 `.xml`（插件自动识别），重复率可用 `文件名=毫秒` 语法。

实测产物与脚本已留存：
- 生成器脚本（备用纯 Python 方案，含 MPEG CRC-32）：`.scratch\research\scripts\gen_min_ts.py`
- golden stream 与中间产物：`.scratch\research\data\`（`pat.xml`、`pmt.xml`、`pat.bin`、`pmt.bin`、`golden.ts`、`golden.json` 等）

### 4.2 JSON 输出结构（3.40-4165 实测）

顶层 5 个键：**`pids`（数组）、`services`（数组）、`tables`（数组）、`time`、`ts`（全局）**

- `ts`：`bitrate`、`bitrate-204`、`bytes`、`duration`、`packets{total, invalid-syncs, transport-errors, suspect-ignored}`、`pcr-bitrate(-204)`、`user-bitrate(-204)`、`pids{total, clear, scrambled, pcr, unreferenced, global{pids[], packets, bitrate...}}`、`services{total, clear, scrambled}`、`id`（transport_stream_id）
- `pids[]`（每 PID 一个对象）：`id`、`description`（如 "PAT"/"PMT"/"AVC video"/"Stuffing"/"PCR (not otherwise referenced)"）、`global`/`unreferenced`/`pmt` 布尔、`audio`/`video`/`ecm`/`emm`/`iip`/`t2mi`/`is-scrambled` 布尔、`service-count`、`services[]`（service_id 列表）、`pes`、`invalid-pes-prefix`、`bitrate(-204)`、`packets{total, clear, scrambled, af, discontinuities, duplicated, pcr, pcr-leap, pts, pts-leap, dts, dts-leap, invalid-scrambling}`、`unit-start`
- `services[]`：`id`、`tsid`、`pmt-pid`、`pcr-pid`、`pids[]`、`name`/`provider`（本流为 "(unknown)"，无 SDT）、`type`+`type-name`、`hidden`、`ssu`、`t2mi`、`is-scrambled`、`bitrate(-204)`、`packets`、`components{total, clear, scrambled}`
- `tables[]`：`pid`、`tid`、`tid-ext`、`tables`、`sections`、`repetition-pkt`、`min/max-repetition-pkt`、`versions[]`、`first/last-version`
- `time`：`local`/`utc` 各含 `system{first{date,time,seconds-since-2000}, last{...}}`

要点：
- 只有当 PAT→PMT 关联成功后，`services` 数组才有内容、PMT PID 的 `pmt` 字段才为 true —— **可用 `ts.services.length >= 1` 与 `ts.bytes > 0` 作为 "输入确为合法 TS" 的判定**（实测：垃圾文件两者均为 0，见 §4.4）
- 流无 PCR/无 PES 时相关 bitrate/duration 为 0（golden null 流即如此），符合预期

### 4.3 JSON 输出选项族

- `--json`：JSON 报告输出到 **stdout**（实测）
- `--json-line[='prefix']`：单行 JSON 经消息日志器输出，**默认走 stderr**（实测确认：stdout 0 字节、stderr 4259 字节）；适合行式日志采集
- `--json-tcp ip:port`（默认每条消息新建连接，`--json-tcp-keep` 保持连接）/ `--json-udp ip:port`（≤64 kB，`--json-udp-local` 指定多播本地接口）、`--json-buffer-size`
- 官方 User Guide §2.7.2：**所有能产出 normalized report 的工具/插件都支持 `--json`**。3.40 本地指南中明确列出的支持者：
  - 命令行工具：`tsanalyze`、`tscmp`、`tsdektec`、`tspacketize`、`tspsi`、`tstables`、`tsxml`、`tstabcomp`（后者为 JSON **输入**编译）
  - tsp 插件：`analyze`、`bitrate_monitor`、`continuity`、`psi`、`splicemonitor`、`tables`、`inject`（JSON 输入）、`dvb`（输入，JSON 设备报告）、`srt`（输入/输出）
  - 反例（实测）：`tstabdump --json` 在 3.40 报 unknown option —— 表格数据的交换格式是 XML，JSON 用于分析报告（官方 §2.7.3 立场：XML 是表结构的 reference format，另有 automated XML-to-JSON conversion 规则可用）
- 管道内分析：`tsp -I file x.ts -P analyze --json -O drop` 实测与 `tsanalyze --json` 输出一致（6562 字节同构）

### 4.4 退出码、stderr、stdin 行为（Worker 关键面，全部实测）

| 场景 | exit | stdout | stderr |
|---|---|---|---|
| 正常分析（文件/stdin） | 0 | 完整 JSON | 空 |
| 文件不存在 | **1** | 0 字节 | `tsanalyze: cannot open data/no_such.ts: <本地化系统消息>` |
| 垃圾/非 TS 输入（16 字节随机数据） | **0** | 合法 JSON，但 `ts.bytes=0`、`packets.total=0`、`services` 缺失/空 | 空 |
| 无参数（`tsanalyze --json`） | 0 | JSON（读 stdin，空输入即零包报告） | 空 |
| `tsp -P 不存在的插件` | **1** | 0 字节 | `* Error: nosuchplugin.dll: ...` + `* Error: processor plugin ... not found` |
| `tsp -I file 不存在的文件` | **1** | — | `* Error: file: cannot open ...` |
| 正常 tsp 管线（zap/until/continuity/analyze） | 0 | — | 空（偶发版本检查提示，见下） |

补充实测事实：
- **stdin 管道可用**：`cat data/golden.ts | tsanalyze --json` 与文件输入输出完全一致（6562 字节，exit 0，stderr 空）→ Worker 可用管道避免临时文件路径转义问题
- **stderr 不要做语义解析**：TSDuck 在中文 Windows 上把系统错误消息按系统代码页（GBK）输出，按 UTF-8 读取即乱码（实测 `iconv -f GBK` 部分可还原为 "系统找不到的文件"）；错误行有 `* Error: ` 前缀但文本不可靠，**依赖退出码 + stdout JSON**
- 运行时偶发 `* new TSDuck version ... is available` 提示（周期性在线检查，带缓存，复现不稳定）；设 `TSDUCK_NO_VERSION_CHECK=1` 可彻底消除该 stderr 噪声

---

## 5. tsp 在 Windows 的插件可用性（`tsp --list-plugins` 实测 + 文档）

### 5.1 本机实际可用插件（`tsp --list-plugins`，3.40-4165）

- **input（13）**：craft、dektec、dvb、file、fork、hls、http、ip、memory、null、pcap、rist、srt
- **output（13）**：dektec、drop、file、fork、hides、hls、http、ip、memory、play、rist、srt、vatek
- **processor（约 85）**：analyze、aes、bat、bitrate_monitor、boostpid、cat、clear、continuity、count、craft、cutoff、datainject、debug、decap、descrambler、dump、duplicate、eit、eitinject、encap、feed、file、filter、fork、fuzz、history、inject、ip、isdbinfo、limit、merge、mpe、mpeinject、mux、nit、nitscan、pat、pattern、pcradjust、pcrbitrate、pcrcopy、pcredit、pcrextract、pcrverify、pes、pidshift、pmt、psi、psimerge、reduce、regulate、remap、rmorphan、rmsplice、scrambler、sdt、sections、sifilter、skip、slice、spliceinject、splicemonitor、stats、stuffanalyze、svremove、svrename、svresync、t2mi、tables、teletext、time、timeref、timeshift、trace、trigger、tsrename、until、zap 等
- 实测通过的处理器：`zap`（按 service 1 选流）、`continuity`（校验）、`until`、`analyze --json`、`inject`（建流）—— 均 exit 0

### 5.2 Windows 平台已知限制（官方 User Guide）

1. **DVB 调谐硬件（dvb 输入插件）—— 最主要限制**（§7.1.2.2）：
   - Windows 上调谐设备经 **DirectShow/BDA**（Broadcast Device Architecture）访问；系统**不带任何预装 BDA 驱动**，全靠厂商驱动
   - **无法查询调谐器实际锁定的传输参数**（Linux 上 `tslsdvb -v` 可显示实际参数）；Windows 上 dvb 插件只能用 PCR 分析估算 bitrate
   - 官方明言 DirectShow 框架的开发"似乎已停止"，新调制标准支持受限；User Guide §7.1.2 的 Windows cons：shell 环境受限 + 调谐器硬件支持受限
   - 设备名为 DirectShow filter 名（含 USB 设备实例路径，冗长）；拔插/重启后顺序可能变化，建议用完整序列号定位
   - **对 DVB-Nexus 的影响：文件/网络/内存输入完全不受影响**；仅"直播硬件调谐"场景在 Windows 受限
2. **Dektec（dektec 插件）**：Windows 驱动为二进制直接安装（§7.2.2），支持良好；`tsdektec --info` 可显示 DirectShow graph
3. **HiDes 调制器（hides 输出）**：Windows 驱动为二进制 zip 安装（§7.3.3），设备名为 DirectShow filter 名
4. **SRT 插件**：官方注明"srt 仅在编译期 libsrt 可用时提供，通常 macOS/Windows/Fedora 31+/Ubuntu 19.04+ 可用" —— 本机已包含
5. **平台差异细节**：
   - 插件/扩展搜索：Windows 使用系统 PATH（+ `TSPLUGINS_PATH`，路径分隔符 `;`）
   - 用户配置文件：`%APPDATA%\tsduck\tsduck.ini`
   - fork/merge 插件在 Windows 提供 `--buffered-packets` 管道缓冲选项（进程间管道可行）
   - `-O play` 依赖系统注册的媒体播放器（VLC 等）路径

---

## 6. 对下游决策的结论输入

### 6.1 决策 a：conformance / golden streams 验证策略在 Windows 上的可行性

**结论：可行，且推荐完全基于文件 + JSON 的纯软件链路（不依赖任何硬件）。**

- golden stream 生成已有可靠链路：XML（TSDuck 模型）→ `tstabcomp` → `tsp -I null -P inject ... -O file`；产物字节确定（188000 B / 1000 包），可入库为 golden 期望值。手工 Python 拼包不推荐（section_length/CRC 易错，已实际踩坑）
- 校验命令 `tsanalyze --json <golden.ts>` 的 JSON 覆盖面足以支撑 conformance 断言：TS 级（字节/包数/无效同步/传输错误计数）、PID 级（连续性/重复/加扰/AF/PCR/PTS/DTS 计数）、service 级（pmt-pid/pcr-pid/组件 pids）、表级（tid/tid-ext/version/重复周期）
- 关键断言建议：`ts.bytes > 0 && ts.services.total >= 1` 作为"输入是合法 TS"前置；再加 golden 期望值逐字段比对。**不能只依赖 exit code**（垃圾输入也 exit 0，见 §4.4）
- 约束与注意：
  - `time.system` 字段与 `duration` 等是运行时相关值，golden 比对应排除
  - 版本差异可能影响 JSON 细节字段：基线锁定 3.40-4165（本机），或升级到 3.45-4798 后重新生成 golden 期望值；建议 CI 与开发机版本一致
  - portable zip（无 admin 权限）可作为 CI 环境的安装方案
- 需要文件格式变体时（M2TS/RS204），tsanalyze 自带 `--format` 输入选项；JSON 中对应 `bitrate-204` 字段

### 6.2 决策 b：TSDuck Worker 子进程接口面

**结论：接口面清晰稳定，建议按以下契约实现。**

- **命令行**：`tsanalyze --json <file>`（或 stdin 管道：`spawn('tsanalyze', ['--json'])` 后写入 stdin）；不需要 shell
- **stdout**：唯一 JSON 输出（UTF-8，pretty-printed 多行）；Worker 直接 `JSON.parse(stdout)`
- **stderr**：日志/错误通道（`* Error: ` 前缀），文本受系统代码页影响不可靠，**只用于日志展示，不参与解析**；成功时为空，但需容忍偶发版本检查提示 → 建议在 Worker 环境注入 `TSDUCK_NO_VERSION_CHECK=1`
- **退出码**：0=进程成功（不代表内容有效）；1=无法执行（文件不存在、插件不存在等）。语义判定一律走 JSON 内容
- **超时**：文件输入为有限流、自然结束；stdin 模式务必显式关闭写端否则会挂起等待（实测空 stdin 立即 EOF 返回，但持续写端会阻塞）
- **流式替代**：若需要边分析边上报，可用 `--json-line`（stderr 单行 JSON）或 `tsp -P analyze --json`/`--json-tcp/--json-udp`；常规批处理用 `--json` + stdout 最简单
- **可执行文件定位**：优先 PATH 查找 `tsp`/`tsanalyze`；fallback 探测 `%ProgramFiles%\TSDuck\bin` 与自定义盘安装路径（本机在 `D:\Program Files\TSDuck\bin`）
- **版本探测**：`tsp --version` 输出形如 `TSDuck - The MPEG Transport Stream Toolkit - version 3.40-4165`，正则 `version (\d+\.\d+-\d+)` 可提取；建议 Worker 启动时缓存版本并与 golden 期望值的生成版本比对

---

## 7. 来源

- TSDuck 下载页（installer/portable 文件名、架构）：https://tsduck.io/download/tsduck/
- TSDuck 官网下载入口：https://tsduck.io/download.html
- TSDuck 构建/安装文档（winget 官方推荐、无 scoop/choco）：https://tsduck.io/docs/tsduck-build.html
- GitHub 仓库与 Releases：https://github.com/tsduck/tsduck 、release tag v3.45-4798（winget 发行说明 URL：https://github.com/tsduck/tsduck/releases/tag/v3.45-4798 ）
- winget 包信息（本机 `winget show tsduck` 实测）：ID `TSDuck.TSDuck`，版本 3.45-4798
- 本地离线 User Guide（随 3.40-4165 安装）：`D:\Program Files\TSDuck\doc\tsduck.html` —— 引用其 §1.3.1（Windows 安装）、§2.7（JSON/normalized 格式）、§6.1（搜索路径/环境变量）、§7.1.2.2（Windows/DirectShow/BDA 限制）、§7.2.2/§7.3.3（Dektec/HiDes Windows）
- 本机实测：版本/路径/插件清单/退出码/stderr/stdin/JSON 结构（详见 §2/§4/§5，原始产物在 `.scratch\research\data\`）

## 8. 实测产物索引（`.scratch\research\`）

| 文件 | 说明 |
|---|---|
| `scripts\gen_min_ts.py` | 纯 Python 最小 TS 生成器（备用；含 MPEG CRC-32 实现；注意其手工 section 有缺陷，勿直接用于 golden） |
| `data\pat.xml` / `data\pmt.xml` | TSDuck XML 表描述（正确 schema） |
| `data\pat.bin` / `data\pmt.bin` | `tstabcomp` 编译产物 |
| `data\golden.ts` | golden stream（1000 包 / 188000 字节，含 PAT/PMT/PCR/AVC/null） |
| `data\golden.json` | `tsanalyze --json golden.ts` 输出（6562 字节） |
| `data\analyze.json` | `tsanalyze --json min.ts` 输出（手工 TS，含 PMT 未关联的反例） |
| `data\min.ts` / `data\big.ts` | Python 生成的基础 TS（32/402 包） |
| `data\stdin.json` | stdin 管道方式输出（与 golden.json 一致） |
