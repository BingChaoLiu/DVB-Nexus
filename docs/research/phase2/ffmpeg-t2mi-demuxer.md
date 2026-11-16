# FFmpeg t2mi demuxer 调研报告（Issue #105）

- 调研日期：2026-11-17
- 调研方式：本机（Windows 10.0.26300 x64，Git Bash）实测 + FFmpeg/TSDuck 官方源码仓库（GitHub primary sources）核对 + 官方文档
- 关联票：#105（本票）、#104（TSDuck t2mi 插件实测，并行票）、#108（T2-MI 解封装细裁票，本文为其输入）、父票 #103
- 本报告只做调研与实测留档；样流生成器与样流已入库：[`ffmpeg-t2mi-data/`](ffmpeg-t2mi-data/)（可直接供 #108 复用）

---

## 1. 结论速览

| 问题 | 结论 |
|---|---|
| FFmpeg 7.1 是否加入 t2mi demuxer | **否——票面前提不成立**。FFmpeg 任何版本（含 7.1、9.0.2、master）都没有 t2mi demuxer；mainline `libavformat` 从未有过 `t2mi.c`（GitHub commits API 对该路径返回空），patchwork 无任何 t2mi 补丁 |
| 本机 FFmpeg 版本 | 实测前未安装；本次经 winget 安装 **Gyan.FFmpeg 9.0.2 full build**（`ffmpeg version 9.0.2-full_build-www.gyan.dev`），377 个 demuxer 中无 t2mi |
| FFmpeg 对 T2-MI 流的解封装/PLP 能力 | **无**。对含 T2-MI 的 TS 只报 `bin_data`（PID 0x64, stream_type 0x06）；对纯 T2-MI 包流直接 `Invalid data found`，连容器都识别不了 |
| TSDuck t2mi 插件实测（本机 3.45-4798） | 包级（识别/CRC 校验/PLP/原始包导出）**100% 正确**；TS 解封装**前缀正确但末尾 BBFrame 的 UP2+ 丢失**（详见 §5.3）；单 UP BBFrame 流完全正确 |
| 与 TSDuck 方案可比性 | FFmpeg 侧无可比对象（不存在）；TSDuck 侧集成成本为零（CLI 子进程先例已定型） |
| 定位建议 | FFmpeg 从解封装装备候选中**剔除**；TSDuck t2mi 保持第一方案但 #108 必须绕开/复测其 3.45 尾包缺陷；golden L2 独立交叉验证器建议改由**语义层 Python 自研解封装器**承担（见 §7） |

---

## 2. 票面前提核对：FFmpeg 不存在 t2mi demuxer（primary sources）

票面问题 1 预设"FFmpeg 7.1 加入 t2mi demuxer"。按 research 纪律先回到一手来源核对，**该前提不成立**：

1. **mainline 源码树**：`git clone --filter=blob:none --sparse https://github.com/FFmpeg/FFmpeg`（master，2026-11）+ `git sparse-checkout set libavformat`，`ls libavformat | grep -i t2mi` → 无匹配（该目录共 703 个文件）；`grep -rn t2mi libavformat/ doc/ Changelog` → 零命中。
2. **GitHub commits API**：`GET /repos/FFmpeg/FFmpeg/commits?path=libavformat/t2mi.c` → 返回 `[]`——该文件在全部历史上从未存在过任何 commit。
3. **官方 patchwork**（https://patchwork.ffmpeg.org/project/ffmpeg/list/?q=t2mi ）→ "No patches to display"——连从未合入的提案补丁都没有。
4. **7.1 发布公告**（ffmpeg.org 首页存档）无 t2mi / T2-MI / DVB / Modulator Interface 字样。
5. **本机二进制实测**（FFmpeg 9.0.2 full build，见 §3）：
   - `ffmpeg -demuxers | grep -i t2mi` → 无匹配（exit 1），377 个 demuxer；
   - `ffprobe -formats | grep -i t2mi` → 无匹配（exit 1）；
   - `ffmpeg -h demuxer=t2mi` → `Unknown format 't2mi'`；
   - `grep -c -i t2mi ffmpeg.exe`（二进制字符串）→ 0 匹配——连字符串常量都没有，排除"gyan 构建裁剪"的可能。

> 推测票面前提可能混淆了 TSDuck 的 `t2mi` 插件（确实存在，见 §5）或 Tvheadend/neumoDVB 等第三方项目的 T2-MI 支持（均有未完成/半成品性质）；FFmpeg 官方从未有过。

---

## 3. 本机 FFmpeg 安装与实测（问题 1）

### 3.1 安装（winget）

本机原无 FFmpeg（`ffmpeg: command not found`）。实测 winget 安装路径可行：

```
$ winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
找到 FFmpeg [Gyan.FFmpeg] 版本 9.0.2
正在下载 https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build.zip
已成功验证安装程序哈希 → 已成功安装（命令行别名 ffmpeg/ffplay/ffprobe）
```

- 版本：`ffmpeg version 9.0.2-full_build-www.gyan.dev`（**比 7.1 新两代**；若 t2mi demuxer 真于 7.1 加入，9.0.2 必有——实测没有，反向印证 §2）
- 注意：gyan.dev full build 为 **GPL 构建**（`--enable-gpl`），若未来引入 FFmpeg 做仓库依赖需评估再分发许可证（TSDuck 为 BSD-2-Clause，对比鲜明）。

### 3.2 对 T2-MI 样流的探测（问题 2 的 FFmpeg 侧）

用 §4 的最小样流实测（样流文件见 [`ffmpeg-t2mi-data/`](ffmpeg-t2mi-data/)）：

**① 含 T2-MI 的外层 TS（`t2mi_in_ts.ts`，外层 PAT/PMT + T2-MI PID 0x64）：**

```
$ ffprobe t2mi_in_ts.ts
[mpegts] Format mpegts detected only with low score of 2, misdetection possible!
Input #0, mpegts, from 't2mi_in_ts.ts':
  Program 1
  Stream #0:0[0x64]: Data: bin_data ([6][0][0][0] / 0x0006)
Unsupported codec with id 98314 for input stream 0
```

FFmpeg 把 T2-MI PID 当作普通 `bin_data`，**无任何 T2-MI 感知**，不可能解出 Inner TS 或 PLP。

**② 纯 T2-MI 包流（`raw_t2mi.bin`，无 TS 封装）：**

```
$ ffprobe raw_t2mi.bin
[mp3] Format mp3 detected only with low score of 1, misdetection possible!
raw_t2mi.bin: Invalid data found when processing input

$ ffmpeg -i raw_t2mi.bin -f null -
Error opening input file raw_t2mi.bin.
Error opening input files: Invalid data found when processing input
```

**回答票面问题 2**：FFmpeg 侧无可回答——demuxer 不存在，"输入要求（BBFrame 还是纯 T2-MI 包流）/PLP 提取/输出形态"三问全部落空。概念澄清（供 #108 使用）：T2-MI 包（TS 102 773 §5.1）的 payload 本身就是 BBFrame（packet_type 0x00）等调制器数据，BBFrame 不是独立输入层；解封装的输入形态取决于 T2-MI 的承载方式——TSDuck 的 t2mi 插件只支持 **TS 承载**（T2-MI 包按 section 式 pointer_field 打包在单一 PID 上，见 §4.2），这是本仓库 Phase 2 唯一现实的输入形态。

---

## 4. 最小 T2-MI 样流构造（实测底座）

无公开样流可下载（业界 T2-MI 样流基本不公开），按票面预案**构造最小合法流**，格式逐字节对齐 TSDuck 源码实现（TSDuck 是 TS 102 773 的实现参考）：

### 4.1 T2-MI 包格式（TS 102 773 §5.1，对齐 TSDuck `tsT2MI.h` / `tsT2MIPacket.cpp`）

| 字段 | 偏移 | 说明 |
|---|---|---|
| packet_type | byte 0 | 0x00=Baseband Frame、0x10=L1-current、0x11=L1-future、0x20=timestamp 等 |
| packet_counter | bytes 1–3 | 24 bit 计数 |
| payload 大小 | bytes 4–5 | **bit 数**（大端），字节数 = (bits+7)/8 |
| payload | … | Baseband Frame：`frame_idx(1) + plp(1) + 保留(1) + BBHEADER(10) + data field`（§5.2 + EN 302 755 §5.1.7） |
| CRC-32 | 末 4 字节 | MPEG-2 section CRC-32（poly 0x04C11DB7），覆盖 header+payload |

生成样流的 CRC 用 TSDuck 自带 `tscrc32` 交叉验证一致：`tscrc32 body.bin` → `A91EE99D` = 生成器计算值。

BBHEADER（Normal/High Efficiency Mode 二选一，两者生成器均支持，入库样流用 HEM）：

- MATYPE-1：`TS/GS=0b11`（TS 模式，bits 7–6）；
- UPL/DFL（bits）、SYNC=0x47、SYNCD（bits）；
- 末字节 RP/MODE 与 BBHEADER CRC-8（poly 0xD5，对齐 TSDuck `T2MIDemux::BBHeaderCRC8`）异或，使 `data[9]^CRC8 = MODE`。

### 4.2 T2-MI 在 TS 中的承载（TSDuck `tsT2MIDemux.cpp` 实现参考）

- T2-MI 包连续拼接在单一 PID（样流用 0x64），PUSI 包 payload 首字节为 pointer_field（与 section 打包同机制）；
- 外层 TS 需 PAT → PMT，且 PMT 中该组件带 **T2MI_descriptor**（DVB 扩展描述符，tag 0x7F / ext id 0x11，EN 300 468 §6.4.14）才能被插件默认检测；`--pid` 可绕过。

> ⚠️ 实测踩坑（对 #108 有直接价值）：EN 300 468 扩展描述符 wire 顺序是 **[tag 0x7F][length][ext][payload]**（length 覆盖 ext+payload，见 [oxideav-mpegts 文档](https://docs.rs/oxideav_mpegts/latest/oxideav_mpegts/descriptor/enum.DescriptorBody.html) 引 EN 300 468 §6.2；与 TSDuck `tstabcomp` 自产序列 `7F 04 11 00 00 00` 一致）。先按 [tag][ext][length] 手写 `7F 11 03 ...` 被 TSDuck 判 `Invalid descriptor length: 17` → 整个 PMT 解析失败 → 默认检测 0 PID。**正确描述符可用 `tstabcomp` 从 XML 编译获得**（样流生成器内嵌的 PMT body 即 tstabcomp 产物）。

### 4.3 样流与生成器（入库：[`ffmpeg-t2mi-data/`](ffmpeg-t2mi-data/)）

| 文件 | 内容 |
|---|---|
| `gen_t2mi_sample.py` | 生成器（纯 stdlib；N_UPS/N_T2MI/FLUSH_DUMMY 环境变量可调）；含 MPEG CRC-32、BBHEADER CRC-8、外层 PAT/PMT/T2-MI 打包 |
| `t2mi_in_ts.ts`（1692 B） | 外层 TS：PAT + PMT(含 T2MI_descriptor) + 2 个 T2-MI 包（各 3 个 Inner TS 包：PAT/PMT/null），共 9 包 |
| `raw_t2mi.bin`（1168 B） | 纯 T2-MI 包流（2 包） |
| `expected_inner.ts`（1128 B） | 解封装期望输出（6 个 Inner TS 包）——逐字节比对基准 |

---

## 5. TSDuck 3.45 t2mi 插件实测（问题 3 的 TSDuck 侧）

本机 TSDuck 3.45-4798（2026-09-13 官方 Windows 构建；调研基线 `docs/research/tsduck-env.md` 记录的 3.40-4165 已升级）。插件官方文档（`doc/user/plugins/t2mi.adoc`）自带警告：**"This plugin is currently experimental and has some limitations"**。票 #104 为同一插件的并行实测票；截至本文调研时（2026-11-17）**#104 尚无评论**，故比对数据以本文实测为准。

### 5.1 插件能力面（`tsp -P t2mi --help`，一手）

| 模式 | 选项 | 实测结果 |
|---|---|---|
| 解封装 Inner TS | `-e`（默认），`--plp`、`--pid`、`--output-file` | 见 §5.3 |
| 识别 T2-MI PID/PLP | `-i --identify` | 样流（带外层 PAT/PMT/T2MI_descriptor）→ `summary: found 1 PID's with T2-MI` ✓ |
| 日志逐包 | `-l --log` | 逐包输出 type/size/counter/PLP ✓ |
| 原始 T2-MI 包导出 | `-t --t2mi-file` | 导出 1168/1168 字节，与生成器逐字节一致 ✓ |
| PID 检测 | 默认（需信号化）或 `--pid` | 信号化检测 ✓（修正 T2MI_descriptor 后）；`--pid 100` 直连 ✓ |

### 5.2 输入要求（回答票面问题 2 的 TSDuck 侧）

- 输入是 **MPEG-TS**（T2-MI 承载于 TS 单一 PID），不是裸 BBFrame，也不是无容器 T2-MI 包流；
- `--pid` 未指定时走 PMT 信号化检测（组件带 T2MI_descriptor），要求"fully compliant T2-MI signalization"（插件 help 原文）；
- 解封装路径：外层 TS → 按 pointer_field 重组 T2-MI 包 → CRC-32 校验 → 仅处理 packet_type 0x00（Baseband Frame）→ 检查 MATYPE TS/GS=0b11 → 按 BBHEADER UPL/DFL/SYNCD/MODE 拆 UP → 还原 Inner TS（sync 字节由 TSDuck 补回 0x47）。

### 5.3 解封装正确性实测（核心证据）

对样流（每 BBFrame 3 个 UP，即 3 个 Inner TS 包）逐字节比对 `expected_inner.ts`：

| 流形态 | 期望输出 | 实测输出 | 判定 |
|---|---|---|---|
| 单 UP BBFrame × N（`N_UPS=1 N_T2MI=3`） | 3 包 | 3 包，逐字节一致 | ✅ 完全正确 |
| 多 UP BBFrame × 1（`N_UPS=3 N_T2MI=1`） | 3 包 | **1 包**（只有 UP1） | ❌ 尾包丢失 |
| 多 UP BBFrame × 2 | 6 包 | 4 包（帧1 全 3 + 帧2 仅 UP1），前 4 包逐字节一致 | ❌ 帧2 UP2/UP3 丢失 |
| 多 UP BBFrame × 3 | 9 包 | 7 包（帧1/帧2 各 3 + 帧3 仅 UP1） | ❌ 帧3 UP2/UP3 丢失 |
| 多 UP BBFrame × 2（`N_UPS=2`） | 4 包 | 3 包 | ❌ 同规律 |

规律：**输出是期望流的正确前缀（字节级无误），但流末尾 BBFrame 的 UP2+ 不输出**——每个 BBFrame 的首个 UP 立即输出，其余 UP 推迟到下一个 BBFrame 处理时；流结束无后续 BBFrame，末帧残余永久滞留。尝试的 flush 手段均无效：尾部追加 type 0x20（timestamp）T2-MI 包、dfl<187 的空 BBFrame → 均不触发输出；带 1 个完整 null-UP 的 BBFrame 仅再挤出 1 个滞留包。注意真实 T2-MI 流的 BBFrame 恰恰必然是多 UP（DFL 通常数千字节），因此该缺陷对真实流**必触**。

> ⚠️ 二进制与标签源码不一致：以上行为与 GitHub 标签 `v3.45-4798` / `v3.44-4676` / 提交 `beca1b02`（2026-06-21）的 `tsT2MIDemux.cpp` 源码均不符——源码中 `while (dfl >= PKT_SIZE - 1)` 循环 + `plpp->ts` 输出环应立即输出全部完整 UP（我用 Python 忠实模拟该实现得 3+3+3，与二进制实测 3+3+1 矛盾）。另注：master 于 **2026-11-09 提交 147deab3**（"t2mi: extract TS from Normal Mode, ISSY and null packet deletion"，晚于 3.45 发布）重写了该 demux（新增 Normal Mode CRC-8/ISSY/NPD 支持）。3.45 二进制还不认 Normal Mode 的 per-UP CRC-8（NM 流会整体错位 1 字节，样流生成器因此改用 HEM）。**#108 建议用 3.45 之后的 TSDuck 版本复测本节全部用例**（`tsversion --upgrade` 或 portable zip 均可）。

### 5.4 确定性与可控性

- 同输入重跑输出恒定（无时间/环境依赖项）；错误静默（退出码 0 + summary 行，与 `docs/research/tsduck-env.md` §"退出码"结论一致）——Worker 封装须解析 `* t2mi: extracted ...` summary 行而非只看退出码；
- `--pid`/`--plp` 显式可控；`--t2mi-file`/`--identify`/`--log` 提供包级旁路视图；
- 局限：官方文档自认 experimental、可能不支持所有 mode/stream adaptation（§5.1 警告原文 + §5.3 实测佐证）。

---

## 6. 与 TSDuck 方案的可比性（问题 3）

| 维度 | FFmpeg t2mi demuxer | TSDuck `-P t2mi`（3.45-4798） |
|---|---|---|
| 存在性 | 不存在（§2） | 存在，experimental |
| 确定性 | — | 同输入恒定输出（含缺陷的恒定） |
| 可控性（选 PID/PLP/导出） | — | `--pid`/`--plp`/`--t2mi-file`/`--identify`/`--log` 全齐 |
| CLI 集成成本 | 需新增第二个外部二进制依赖（winget Gyan.FFmpeg，GPL 构建）+ 新的子进程接口适配 | **零**——tsp 子进程接口已定型（`docs/research/tsduck-env.md` §6.2），仅新增一个 `-P` 插件调用 |
| 输入形态 | — | 仅 TS 承载（对本仓库够用） |
| golden L2 独立交叉验证器（SPEC-506 三层来源先例） | — | **包级可用**（`-l`/`-t`/`-i` 100% 正确）；**Inner TS 级不可用**（尾包丢失会污染逐字节 golden 比对） |
| 许可证 | GPL 构建（再分发需评估）；LGPL 组合另说 | BSD-2-Clause |

---

## 7. 结论与对 #108 的输入建议（问题 4）

1. **FFmpeg t2mi demuxer：剔除出解封装装备候选。** 不存在、无提案补丁（patchwork 空）、无社区合并动向；本票票面"7.1 加入"前提有误。除非未来 FFmpeg mainline 合入 t2mi demuxer，否则不重评；本机 winget 安装的 9.0.2 可留作 FFmpeg 生态探针（如未来验证），不进仓库依赖。
2. **TSDuck `-P t2mi`：保持第一方案，但带三个已知边界进 #108：**
   - 3.45-4798 多 UP BBFrame 解封装**尾包丢失**（§5.3），且行为与标签源码不符 → **先升级 TSDuck 复测**（master 147deab3 已重写该 demux），复测不过再考虑自研；
   - 输入必须 TS 承载 + PAT/PMT/T2MI_descriptor（或 `--pid`）；T2MI_descriptor wire 顺序坑（[tag][len][ext]）已实测留档（§4.2），#108 造信号化时直接抄 `ffmpeg-t2mi-data/gen_t2mi_sample.py`；
   - Worker 子进程须解析 summary 行，不能只看退出码。
3. **golden L2 独立交叉验证器（SPEC-506 先例）：不建议用 3.45 的 `-e` 解封装输出做逐字节 golden 源**（尾包丢失必然误报）；建议分工：
   - **T2-MI 包级**：TSDuck `-l`/`--t2mi-file`/`-i` 已 100% 正确，可作包级校验器；
   - **Inner TS 级**：独立验证器由**语义层 Python 自研解封装器**承担（对照 SPEC-506 的独立实现交叉验证精神——TSDuck 是第一实现、Python 是第二实现；FFmpeg 本来就是"第三实现"角色，不存在后无从谈起）。本次调研的 T2-MI/BBHEADER 格式表（§4.1/4.2）即 Python 实现的规格底稿，样流 + `expected_inner.ts` 可直接做该验证器的第一个 golden 用例。
4. **复测清单**（移交 #104/#108）：升级 TSDuck ≥ 2026-11-09 master 构建后重跑 §5.3 全部用例（生成器一键可复现）；补 Normal Mode（含 per-UP CRC-8）与 ISSY/NPD 变体。

---

## 附：证据清单（本机实测，2026-11-17）

| # | 命令 | 关键输出 |
|---|---|---|
| 1 | `winget install --id Gyan.FFmpeg` | `找到 FFmpeg [Gyan.FFmpeg] 版本 9.0.2 … 已成功安装` |
| 2 | `ffmpeg -version` | `ffmpeg version 9.0.2-full_build-www.gyan.dev` |
| 3 | `ffmpeg -demuxers \| grep -i t2mi` | 无匹配（exit 1）；demuxers 共 377 行 |
| 4 | `ffmpeg -h demuxer=t2mi` | `Unknown format 't2mi'` |
| 5 | `grep -c -i t2mi ffmpeg.exe` | 0（二进制无 t2mi 字符串） |
| 6 | `ffprobe t2mi_in_ts.ts` | `Stream #0:0[0x64]: Data: bin_data` |
| 7 | `ffprobe raw_t2mi.bin` | `Invalid data found when processing input` |
| 8 | `tsp --version` | `TSDuck ... version 3.45-4798` |
| 9 | `tsp -I file t2mi_in_ts.ts -P t2mi -e -O file out.ts`（`--pid 100 --plp 0` 及信号化两种） | `extracted 4 TS packets from 2 T2-MI packets` |
| 10 | `tsp -I file t2mi_in_ts.ts -P t2mi -i` | `summary: found 1 PID's with T2-MI` |
| 11 | `tsp -I file t2mi_in_ts.ts -P t2mi -t t2mi_raw.bin` | 1168/1168 字节与生成器一致 |
| 12 | `cmp extracted.ts expected_inner.ts` | 多 UP：EOF on extracted（前缀一致）；单 UP：IDENTICAL |
| 13 | `tscrc32 body583.bin` | `A91EE99D`（与生成器 MPEG CRC-32 一致） |
| 14 | GitHub commits API `path=libavformat/t2mi.c` | `[]`（历史上从未存在） |
| 15 | patchwork.ffmpeg.org `?q=t2mi` | No patches to display |

## 附：来源

- FFmpeg mainline：https://github.com/FFmpeg/FFmpeg（`libavformat/`、`Changelog`）；patchwork：https://patchwork.ffmpeg.org/project/ffmpeg/list/?q=t2mi
- TSDuck 源码（v3.45-4798 与 master）：`src/libtsduck/dtv/t2mi/tsT2MI.h`、`tsT2MIPacket.{h,cpp}`、`tsT2MIDemux.cpp`；插件：`src/libtsduck/plugins/data/tsT2MIPlugin.cpp`；描述符：`tsT2MIDescriptor.{h,cpp}`、`tsDID.h`；插件文档 `doc/user/plugins/t2mi.adoc`（experimental 警告）；master 重写提交 `147deab3`（2026-11-09）
- ETSI TS 102 773 §5（T2-MI 包格式）、EN 302 755 §5.1.7（BBHEADER）、EN 300 468 §6.4.14（T2MI_descriptor）；扩展描述符 wire 顺序旁证：https://docs.rs/oxideav_mpegts/latest/oxideav_mpegts/descriptor/enum.DescriptorBody.html
- 关联票：#104（TSDuck 侧实测，调研时无评论）、#108（细裁实现）、SPEC-506（golden 三层来源）
