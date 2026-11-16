# TSDuck t2mi 插件实测（解封装真流验证 + 封装能力探测）

- Research 票：[#104](https://github.com/BingChaoLiu/DVB-Nexus/issues/104)（父票 #103，下游 #108）
- 实测日期：2026-11-16/17
- 实测环境：Windows 10.0.26300 x64 + Git Bash，TSDuck **3.45-4798**（`tsp --version` 实测；注意：票面与 roadmap §5 写的"本机 3.40"已过时，机器已升级到 3.45-4798，见 §8 版本基线建议）
- 方法：无现成公开 T2-MI 样流 → 按 TS 102 773 §5.1 + TSDuck 源码**自造最小 T2-MI 封装流**（脚本与产物全部入库，见 §7），在真实 TSDuck 二进制上跑完整命令链取证
- 诚实声明：本报告的"解封装验证"基于**合成样流**（格式逐字段对齐 ETSI TS 102 773 §5.1 / EN 302 755 §5.1.7-5.1.8，并经 TSDuck 自身 `tsanalyze`/`t2mi --identify` 反向确认可识别），未在真实广播 T2-MI 捕获流上验证

---

## 1. 结论速览

| 问题 | 结论 |
|---|---|
| 1. 解封装 `--extract` 是否可用 | **可用，且字节级确定**。HEM 布局样流上：`tsp -P t2mi --extract` 输出与封装前 Inner TS **sha256 逐字节一致**（重复运行、`--pid/--plp` 显式指定、`--output-file` 旁路模式全部一致）。但有**版本敏感的硬坑**：3.45-4798 只能正确解 187-byte UP（HEM 式）布局；**规范 TS Normal Mode（CRC-8 替换 sync 字节）流解出来是全损垃圾**（0 包匹配），NM 支持只在 master（2026-11-06 commit 147deab3，尚未发布） |
| 输出形态 | Inner TS 本体（188-byte TS 包流）。默认模式：**替换**整个输入流输出；`--output-file` 模式：Inner TS 落盘、输入流原样旁路 |
| 确定性 | 同输入 → 同输出（sha256 重复一致）；但**失败路径全部静默**：exit=0 + 空 stderr + 空/截断/损坏输出（Worker 必须做内容校验，见 §4.4） |
| 2. 封装/构造 T2-MI | **不能**。t2mi 插件选项面只有 extract/identify/log/t2mi-file 四个方向；102 个 processor 插件 help 扫描仅 t2mi 自身提及 T2-MI 且无任何构造选项；42 个 exe 无一涉及；changelog 历史只有解封装方向的功能。**封装侧缺口实锤 → T2-MI builder 必须自研 Python** |
| 3. BBFrame/BBHEADER | **无任何用户侧能力**。User Guide 与 Dev 文档全文 0 次 "bbframe"；无 BBFrame 工具/插件/选项。BBHEADER 仅作为 t2mi 解封装的**内部实现细节**被解析（3.45 连 BBHEADER CRC-8 都不校验；master 才解析 MODE/UPL/ISSY/NPD） |
| 4. 角色边界 | ADR-0003 三重角色**无需扩容、需收窄**：验证器 ✔（含 T2-MI 流的 PID/PLP 识别）；传输层注入器 ✔（与 T2-MI 无关）；**生成兜底 ✘ 对 T2-MI 不成立**（不能封装）——Phase 2 的 T2-MI 封装与 BBFrame 生成/解析归自研 Python 层；解封装可交 TSDuck 但必须锁版本 + 内容校验（详见 §6） |

---

## 2. 环境与语法确认（实测）

- Windows 上**没有** `tsduck` 顶层命令（票面假设的 `tsduck t2mi --extract` 语法跑不通，`bash: tsduck: command not found`）。TSDuck Windows 发行形态 = `tsp.exe` + 42 个独立工具 exe + 74 个 `tsplugin_*.dll`。
- 正确语法（t2mi 是 **processor 插件**，不是独立命令）：

  ```
  tsp -I file outer.ts -P t2mi --extract [-p <pid>] [--plp <n>] [-O file out.ts | --output-file inner.ts -O drop]
  ```
- 版本实测：`tsp --version` → `TSDuck - The MPEG Transport Stream Toolkit - version 3.45-4798`（3.40-4165 已被升级，`tsduck-env.md` 中的版本快照作废）。
- 插件自述（User Guide §5.102，离线文档 `doc\tsduck.html`）："This plugin is currently **experimental** and has some limitations. … may not work with all modes or stream adaptations"——官方自己标注实验性，与本文实测的 NM 失败互相印证。
- t2mi 插件完整选项面（`tsp -P t2mi --help` 实测）：`--append --except-label --extract --identify --keep --log --only-label --output-file --pid --plp --t2mi-file`。**没有任何构造/封装/生成方向的选项**。

## 3. 测试素材自造（最小 T2-MI 流）

### 3.1 T2-MI 包格式（构建依据）

按 ETSI TS 102 773 §5.1 构建，字段布局逐项对照 TSDuck 源码（`tsT2MI.h`/`tsT2MIPacket.cpp`/`tsT2MIDemux.cpp`，master 与 v3.45-4798 两份）确认：

```
T2-MI 包 = 6 字节头 + payload + 4 字节 CRC-32(MPEG 多项式 0x04C11DB7)
  头: [0]=packet_type(0x00=Baseband Frame)
      [1]=packet_count
      [2]=superframe_idx(高 4 位)+保留
      [3]=保留
      [4..5]=payload 长度（**单位是 bit**，16-bit 大端；字节数 = (bits+7)/8）
  Baseband Frame 的 payload: [0]=frame_idx, [1]=PLP_id,
      [2] 最高位=interleaving_frame_start（TSDuck 按**字节对齐**假设解析 BBFRAME 起点）
      [3..]=BBFRAME
  BBFRAME = BBHEADER(10B) + DATAFIELD
  BBHEADER: [0..1]=MATYPE(TS_GS=11 即 TS 模式; NPD 在 byte0 bit2)
            [2..3]=UPL(bits), [4..5]=DFL(bits), [6]=SYNC, [7..8]=SYNC_D(bits),
            [9]=CRC-8(多项式 0xD5, 覆盖前 9 字节; master 用 MODE=byte9^CRC8 判 NM/HEM)
  DATAFIELD:
    NM(TS 规范): 用户包 = CRC-8(0xD5) + 187 字节（sync 字节被 CRC-8 替换），UPL=1504
    HEM(本测试用): 用户包 = 187 字节（sync 剥除、无 CRC-8），UPL=0，BBHEADER[9]=CRC8^1
```

- 外层打包与 PSI section 完全同构（TSDuck 源码注释原文："this is exactly the same mechanism as section packetization"）：PUSI 包带 pointer_field，**T2-MI 包之间必须背靠背紧排、中间不得插 stuffing**——实测踩坑： stuffing 分隔会导致 demux 把 0xFF 填充误读为 8191 字节的"下一个 T2-MI 包"并**永久停摆**（只解出第一个包，见 §7 脚本注释）。

### 3.2 生成链（全部可复现）

1. Inner TS（500 包：null + PAT + PMT，`tsanalyze` 确认 services=1）：
   `tsp -I null 500 -P inject -p 0 --inter-packet 100 inner_pat.bin -P inject -p 0x1000 --inter-packet 100 inner_pmt.bin -O file inner.ts`
2. 外层 PAT/PMT（含 `T2MI_descriptor`，经 `tstabcomp` 编译，CRC 由 TSDuck 算）：
   外层 PMT 组件 `stream_type="0x06" elementary_PID="0x0015"` + `<T2MI_descriptor t2mi_stream_id="0"/>`（T2-MI 常规 PID 0x0015 = TS 101 162 分配）
3. Python 组包（T2-MI 头/CRC-32/BBHEADER/CRC-8 全自算）：`gen_t2mi.py` → `outer.ts`（NM 布局）/ `outer_hem.ts`(HEM 布局)
4. 反向确认：`tsanalyze --json outer_hem.ts` → PID 21 描述为 **`T2-MI (PLP: 0x00 (0))`**、`t2mi: true`、services=1 —— TSDuck 自身把我造的流识别为合规 T2-MI，说明素材格式有效。

## 4. 解封装实测（问题 1）

### 4.1 --identify / tsanalyze（PID/PLP 发现）

- `tsp -P t2mi --identify -O drop`（exit 0）：

  ```
  * t2mi: found T2-MI PID 0x0015 (21)
  * t2mi: PID 0x0015 (21), found PLP 0
  * t2mi: summary: found 1 PID's with T2-MI
  * t2mi: PID 0x0015 (21): PLP 0
  ```
- **默认发现路径实测可用**：不带 `--pid` 时插件经 PAT→PMT→`T2MI_descriptor` 自动锁定 PID 0x0015（对应真实场景"信号化齐全"）；`--pid` 显式指定亦可（对应"无信号化"场景）。
- `tsanalyze --json`：PID 21 `description="T2-MI (PLP: 0x00 (0))"`、`t2mi: true` → Phase 2 验证器可直接用 JSON 判 T2-MI PID/PLP。

### 4.2 --extract 字节级验证（HEM 布局样流）

| 测试 | 命令 | 结果 |
|---|---|---|
| 替换模式 | `tsp -I file outer_hem.ts -P t2mi --extract -O file out.ts` | **500 包 / 94000 B，与 inner.ts sha256 一致**（`d2955d0a…`），exit 0 |
| `--output-file` 旁路 | `tsp -I file outer_hem.ts -P t2mi --extract --output-file inner2.ts -O file pass.ts` | inner2.ts **与 inner.ts 一致**；pass.ts 与 outer_hem.ts **逐字节一致**（外层无损旁路） |
| 显式 `--pid 0x0015 --plp 0` | 同上 | 与 inner.ts 一致 |
| 确定性 | 重跑两次，replace 与 output-file 各一遍 | 3 份输出 sha256 全部相同 |
| 错误 PLP | `--plp 5` | **静默空输出**（exit 0，无 stderr，0 字节文件） |

### 4.3 规范 NM 布局在 3.45-4798 上失败（重要版本坑）

- 对规范 TS Normal Mode 样流 `outer.ts`（CRC-8 替换 sync、UPL=1504、MODE=0）跑同一命令：exit 0、无 stderr，输出 501 包、**与 inner.ts 精确包匹配数 = 0**（187 字节步长错切 + 逐包漂移，完全损坏），且损坏输出**确定性可复现**（两次运行 sha256 相同）。
- 根因（源码证据）：3.45-4798 的 `tsT2MIDemux::demuxTS` **不解析 BBHEADER CRC-8/MODE/UPL**，无脑按 187 字节步长切包；master 分支 commit `147deab3`（2026-11-06，"t2mi: extract TS from Normal Mode, ISSY and null packet deletion"）才重写为完整 NM/ISSY/NPD 支持——**截至本日无含该修复的发布版**（3.45-4798 是最新版）。
- 含义：真实广播 T2-MI 的 TS 载荷如走 NM（规范要求 TS 用 NM），**现发布版 TSDuck 的 `--extract` 不可用于真流验证**；需等新版本发布，或测试链路按 HEM 布局构造素材（对合成沙盘流足够）。

### 4.4 失败路径全部静默（Worker 契约证据）

| 注入缺陷（T2-MI CRC-32 均重算为合法） | 结果 |
|---|---|
| T2-MI 包 CRC-32 破坏 | 该包**静默丢弃**（不报错），后续包正常 → 480/500 包输出，exit 0，stderr 空 |
| BBHEADER CRC-8 字节破坏 | **照常解出且字节一致** → 3.45 对 BBHEADER 无完整性校验（master 会经 MODE 校验拒绝） |
| BBFRAME datafield 位翻转 | 翻转字节**原样传播**到 Inner TS 对应位置（`inner[0][101]`），无任何告警 |
| 封装 TS 包内位翻转 | 同上，静默传播（`inner[0][21]`） |

- 另一实测坑：replace 模式下插件按"每 1 个输入包出队 1 个排队输出包"排水，**外层流若没有足够填充包，流尾排队包在 EOF 被丢弃**（首版样流外层无尾部 null 时 500 只解出 491；加 50 个尾部 null 后完整）。插件文档已提示 "The number of input TS packets is usually higher than the number of output packets… Use --output-file to get the complete stream."——**Phase 2 Worker 应一律用 `--output-file` 模式**，避免该排水机制。
- 综合：**exit code 与 stderr 完全不可作为成功判据**，与 `tsduck-env.md` §4.4 的结论一致且更尖锐（部分丢弃、静默损坏、静默空输出三种形态）。Worker 必须做：包数/字节量级断言 + 与期望 golden 对比。

### 4.5 --log / --t2mi-file

- `--t2mi-file` 可把裸 T2-MI 包流抽成二进制（实测 25 包 × 3763 B = 94075 B 精确落盘），是不错的**调试/取证工具**。
- `--log` 每包一行摘要（类型/长度/count/superframe index/PLP），但实测 25 包只打出 1 行（tsp 日志节流，`--synchronous-log` 也无效）——不可依赖它做逐包审计。

## 5. 封装能力探测（问题 2）——预期"不能"全部证实

1. **t2mi 插件选项面**（§2）：只有 `--extract/--identify/--log/--t2mi-file` 四个解封装/审计方向；无 `--build/--generate/--encapsulate` 之类选项，命令行语义中 T2-MI 只能作为**输入**被解。
2. **全插件扫描**：对 3.45 全部 102 个 processor 插件的 `--help` 文本 grep `t2-mi|t2mi|bbframe|baseband`（大小写不敏感），**仅 t2mi 自身命中（2 处，均为描述文本）**；`encap`（PID 复用封装）、`mpe`（DSM-CC MPE）、`tspacketize`（SI/PSI section 包化）均与 T2-MI 无关。
3. **exe 清单**：42 个独立工具（tsanalyze…tsxml）无一涉及 T2-MI/BBFrame 构造。
4. **changelog 佐证**（随发行版 `doc\CHANGELOG.txt`，1792 行全 grep）：t2mi 相关条目只有：3.4-20171110 "Added t2mi plugin **to extract**…"、后续 `--identify`、`--output-file/--append/--keep`、`--t2mi-file`、bug fix #950——**从来没有封装方向的功能**。
5. `craft` 插件理论上可把任意字节灌进任意 PID（包括预构建的 T2-MI TS 包），但它不做任何 T2-MI 结构——等于"外部造好字节再用 TSDuck 搬运"，不构成封装能力。
6. 库层存在 `ts::T2MIDemux`/`ts::T2MIPacket` 等 API（Dev 文档），但 ADR-0003 冻结了 CLI 子进程集成、禁 binding/ABI，库层能力对 Phase 2 不可达。

**结论：TSDuck（CLI 面）不能构造/封装 T2-MI 包流。自研 Python T2-MI builder 是唯一路线，本节为该路线的关键留证。**

## 6. BBFrame 能力探测（问题 3）——预期"无"证实

- `doc\tsduck.html`（User Guide 全文）与 `doc\tsduck-dev.html`（Dev 文档全文）grep `bbframe` = **0 命中**；42 个 exe、102 个插件 help 亦 0 命中。
- TSDuck 中唯一触碰 BBHEADER 的代码是 `tsT2MIDemux::demuxTS`（t2mi 解封装的内部实现，Dev 文档无独立 BBFrame 类）：3.45 只按 187 步长切包（连 BBHEADER 都不完整解析）；master 才解析 MATYPE/UPL/DFL/SYNC_D/CRC-8/MODE/ISSY/NPD，且同样只服务于 T2-MI 解封装输出 TS。
- **没有** BBFrame 提取、BBHEADER 解析展示、BBFrame 计数/校验等任何用户可用的 CLI 能力；`tsanalyze` 的 JSON 中无 BBFrame 字段。
- **结论：Phase 2 的 BBFrame/BBHEADER 层（EN 302 755 §5.1.7/§5.1.8）解析与生成完全归自研 Python 层。**

## 7. 对下游细裁票 #108 的输入建议

1. **T2-MI 封装（builder）**：自研 Python，格式按 §3.1（CRC-32=MPEG、CRC-8=0xD5、payload 长度单位 bit、T2-MI 包背靠背紧排 + PSI 式 PUSI/pointer 打包、TS 载荷走 NM 规范布局）。`gen_t2mi.py` 已验证 NM/HEM 双布局 builder 可行，可直接演化为 Phase 2 代码或 golden 生成器。
2. **解封装（若 Phase 2 需要）**：可交 TSDuck `tsp -P t2mi --extract --output-file`，但必须：
   - 锁版本基线 3.45-4798；NM 支持等 TSDuck 新版发布后回归（盯 upstream commit 147deab3 的发布）；合成沙盘流可用 HEM 布局先跑通 roundtrip；
   - Worker 校验输出内容（包数/对 golden），exit code/stderr 不可信（§4.4）；
   - 外层流必须留足尾部填充（或干脆用 `--output-file` 旁路模式）防排水丢包；
   - `--pid` 显式传入比依赖 PMT 信号化更稳（真实流常缺 T2MI_descriptor，User Guide §6.1.9 亦如此提示）。
3. **验证器角色**：`tsanalyze --json` 的 PID 级 `t2mi` 布尔与 `description` 里的 PLP 列表可直接做 T2-MI 流的 conformance 断言输入。
4. **BBFrame**：无 TSDuck 捷径，按自研规划推进（BBHEADER CRC-8=0xD5、NM UP=CRC-8+187B 等字段表见 §3.1，可直接抄进 builder）。
5. **版本基线**：`tsduck-env.md`/roadmap 中的"3.40-4165"快照已过时，本机现为 3.45-4798；建议 Phase 2 把 TSDuck 版本钉进 golden 元数据。

## 8. ADR-0003 三重角色评估（问题 4）

- **验证器**：不扩容、可承担 T2-MI 流的识别/结构校验（§4.1），但完整性校验能力有限（3.45 不查 BBHEADER；BBFRAME 内部位翻转静默传播）——深度校验仍要靠自研语义层 + golden 比对。
- **传输层注入器**：不受影响（与 T2-MI 无关，文件/网络/memory 输入照旧）。
- **生成兜底**：**对 T2-MI 维度不成立**（§5 封装缺口实锤）。ADR-0003 的"生成兜底"应理解为"普通 TS 信号化/流结构生成兜底"；T2-MI/BBFrame 的生成属于自研 Python 层职责，建议在 Phase 2 ADR（或 #108 的实现票决议）中显式写明这一边界，避免误以为 TSDuck 能兜底 T2-MI 生成。
- **解封装归属**：可以交 TSDuck（省去 NM/ISSY/NPD 等深水区自研），代价是版本敏感（§4.3）与静默失败契约（§4.4）；若 Phase 2 需要"封装↔解封装"对称可控的沙盘闭环（自造流→解回→比对），建议解封装同样先自研（builder 已有，demux 只差 187/188 步长 + CRC-8 跳过 + SYNC_D 续包逻辑，复杂度远低于 builder），把 TSDuck t2mi 作为第二意见验证器而非主链路。

## 9. 证据索引（本分支内 `docs/research/phase2/tsduck-t2mi-data/`）

| 文件 | 说明 |
|---|---|
| `gen_t2mi.py` | 最小 T2-MI 流生成器（NM/HEM 双布局，含全部格式常量与踩坑注释） |
| `corrupt_patch.py` | 缺陷注入器（BBHEADER CRC-8 / datafield 位 rot / TS 包内翻转，T2-MI CRC-32 重算） |
| `inner.ts` | 封装前 Inner TS（500 包 / 94000 B，sha256 `d2955d0a6d57d811…`） |
| `outer.ts` / `outer_hem.ts` | NM / HEM 布局 T2-MI 封装流（PAT+PMT+T2MI_descriptor+PID 0x0015） |
| `outer_hem_analyze.json` | `tsanalyze --json outer_hem.ts`（PID 21 = "T2-MI (PLP: 0x00 (0))"，t2mi=true） |
| `identify_hem.txt` | `t2mi --identify` 原始输出 |
| `corrupt_*.ts` | 三种缺陷注入样流（对应 §4.4） |

（复现命令与输出摘录全部内嵌于本文各节；原始工作目录 `.scratch/research-t2mi/` 含更多中间产物，不入库。）

## 10. 来源

- 实测（主）：TSDuck 3.45-4798 Windows 二进制，本机 2026-11-16/17 执行（本文全部命令/输出）
- ETSI TS 102 773 V1.4.1 §5.1/§5.2（T2-MI 包格式）——经 TSDuck 源码注释交叉引用
- ETSI EN 302 755 §5.1.7（BBHEADER）、§5.1.8（用户包 NM/HEM）——同上
- TSDuck User Guide（随发行版离线 `D:\Program Files\TSDuck\doc\tsduck.html`）：§5.102 t2mi、§6.1.9 DVB-T2 Modulator Interface、§2.7 JSON
- TSDuck 源码（GitHub tsduck/tsduck）：master 与 tag v3.45-4798 的 `src/libtsduck/dtv/t2mi/tsT2MIDemux.cpp`、`tsT2MIPacket.{h,cpp}`、`src/libtsduck/plugins/data/tsT2MIPlugin.cpp`、`src/libtsduck/dtv/t2mi/tsT2MI.h`；commit 147deab3（2026-11-06，NM/ISSY/NPD 支持，未随任何发布版发行）
- 随发行版 `CHANGELOG.txt`（t2mi 功能史）；本仓 `docs/research/tsduck-env.md`（环境面与 Worker 契约前作）、`docs/adr/0003-frozen-tech-stack.md`、`docs/adr/0005-architecture-baseline.md`
