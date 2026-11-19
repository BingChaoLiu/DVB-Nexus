# Unicable/SCR/dCSS 语义与标准可得性研究（GitHub Issue #145）

**研究票**：[#145 研究:Unicable/SCR/dCSS 语义与标准可得性](https://github.com/BingChaoLiu/DVB-Nexus/issues/145)（Phase 3 地图 [#143](https://github.com/BingChaoLiu/DVB-Nexus/issues/143) 子票）
**研究日期**：2026-11-20
**研究对象**：EN 50494（SCR/Unicable I）与 EN 50607（dCSS/Unicable II）在正文付费背景下的免费权威替代来源；User Band/Position/Slot 频率语义精确化；UB 冲突语义（A1 订正口径）
**研究方式**：Linux kernel UAPI 源码逐行核对（torvalds/linux master）+ 四家开源实现源码交叉验证（tvheadend/VDR/MuMuDVB/minisatip，经 GitHub API 抓取原文）+ 本机 TSDuck 3.45-4798 实测 + 厂商一手文档逐页核对（Inverto 手册/数据表 PDF 逐条 grep）+ SAT>IP 规范全文检索。EN 50494/EN 50607 正文未获取（付费），相关结论全部走免费替代来源并标注置信路径。
**置信路径约定**（按 No fake evidence 红线，三类不混标）：【文档引用】= 免费可得的规范/官方文档原文核对；【实现佐证】= 开源实现源码逐行核对（标注仓库与文件）；【推断】= 从实现行为推出的语义，待原文核对。
**下游读者**：#148（端口模型扩展）、#150（SPEC-622/623 边界）——§7 为其输入建议章。

---

## 0. 结论先行

1. **Linux kernel DVB API 没有 Unicable 属性面**——frontend.h 全部 71 个 DTV 属性与全部 SEC ioctl 中无一 EN 50494/50607 专属项；内核只提供 SEC 原语（voltage/tone/DiSEqC master cmd/slave reply/mini burst）。Unicable 是**用户态消息构造层**，用 `FE_DISEQC_SEND_MASTER_CMD`（6 字节上限）把 EN 50494/50607 帧发给 SCR 设备。【文档引用：kernel UAPI 源码 + 文档树逐字 grep】——**这是 SPEC-622/623 分层的天然权威依据**（§4、§7.2）。
2. **EN 50494/EN 50607 调谐消息的位级布局已被四家独立开源实现交叉验证一致**（tvheadend/VDR/MuMuDVB/minisatip）：Unicable I = `[0xE0,0x10,0x5A,d1,d2]`（UB 3bit→8 槽、Position 1bit→A/B、极化 1bit、频段 1bit、频率字段 t 10bit），PIN 变体命令字节 0x5C（6 字节）；Unicable II = `[0x70,d1,d2,d3]`（UB 5bit→32 槽、Position 6bit、极化 1bit、频段 1bit、t 11bit），PIN 变体帧字节 0x71（5 字节）。【实现佐证，§2】
3. **频率编码公式四家一致**：Unicable I `t = round((f_IF + f_UB + 2)/4) − 350`（f_IF = transponder 经 LNB 变频后的 IF 频率，MHz；f_UB = 本机 UB 槽位中心频率），接收端前端调 `(t+350)×4 − f_IF ≈ f_UB + 2 MHz`（三家公式一致；minisatip 直接调 f_UB，存在实现分歧，见 §2.4）；Unicable II `t = f_IF − 100`，接收端前端精确调 `f_UB`（四家一致）。dCSS 语义更干净：transponder 按声明堆叠在 UB 中心。【实现佐证 + 偏置物理解释为推断】
4. **UB 冲突语义（A1 订正口径）得到实现层直接佐证**：SCR 设备按接收端命令"选择 transponder、变频到对应 User Band 频率并堆叠"（Inverto 手册原文）；同一 UB 槽位同一时间只能堆叠一路 transponder，两个接收端请求同一 UB → SCR 在同一频槽堆叠两路信号互扰 → 无法锁定。冲突发生在 SCR 堆叠层，与 LNB 本振无关。A1 的 1210 MHz 示例与两家厂商默认 UB 频率组（1210/1420/1680/2040 MHz）吻合。【文档引用：Inverto 手册；实现佐证：tvheadend 全局互斥锁的教训】
5. **本机 TSDuck 有 Unicable 参数面但没有 Unicable 处理能力**：`dvb` 输入插件有 `--unicable <version>,<slot>,<freq MHz>`（v1=EN50494，v2=EN50607，实测提取）与 `--lnb`（`tsduck.lnbs.xml` 19 条 LNB 定义）；tsp 全部处理器插件无 unicable/DiSEqC 项（TS 域工具，RF/SEC 调谐只存在于输入插件）。硬件调谐行为 NOT RUN（本机无 DVB 设备，且 Windows BDA 本就无法查询锁定参数——roadmap §5 既有结论）。TSDuck 可作 L0 参数面的第三意见参照，不承担注入/验证角色。【文档引用：本机实测 --help；§5】
6. **条款号缺口清单**（§6）：EN 50494/50607 全部条款号待原文核对；可免费核实的是结构级事实（UB 位宽、消息字节数、公式、时序界）与目录页元数据（iTeh）。SAT>IP `uni` 参数在 v1.4+ 才加入（v1.2.2 可自由下载版无此参数）——待原文核对。JESS 名称展开（"Joint European Standard for Switching"）仅二手来源。
7. 票面提到的 **"GSet" 品牌无法核实**（多轮检索无此卫星设备品牌，可能为 GSS（德国 Grundig Sat Systems，dCSS/JESS 技术源头厂商之一）笔误）；GSS 的技术角色仅行业二手来源支撑，JESS 与 EN 50607 的关系以实现代码注释（VDR："EN50607 aka JESS"）与 OpenPLI wiki 为准。

---

## 1. 免费权威替代来源清单（权威度评估）

| # | 来源 | 可得性 | 权威度 | 覆盖面 | 置信路径 |
|---|---|---|---|---|---|
| 1 | **Linux kernel DVB UAPI + 文档**（torvalds/linux：`include/uapi/linux/dvb/frontend.h` + `Documentation/userspace-api/media/dvb/`） | 免费（GPL，GitHub/docs.kernel.org） | 高（SEC 原语层的权威参考实现） | SEC ioctl 全集、DTV 属性全集、6 字节 DiSEqC 命令上限；**不含** EN 50494/50607 语义 | 文档引用（本次逐字 grep 核对） |
| 2 | **tvheadend** `src/input/mpegts/linuxdvb/linuxdvb_en50494.c`（master） | 免费（GitHub） | 高（EN 50494+EN 50607 消息构造，活跃维护） | 两协议完整消息位布局、频率公式、18V 命令交换时序、PIN 变体、重复退避 | 实现佐证（本次逐行核对） |
| 3 | **VDR** `diseqc.c` + `scr.conf`（master） | 免费（GitHub 镜像） | 高（独立第二实现；`scr.conf` 是 UB 频率配置的规范格式示例） | 同上交叉验证 + "EN50607 aka JESS" 术语注释 | 实现佐证 |
| 4 | **MuMuDVB** `src/tune.c`（mumudvb2 分支，`do_unicable`） | 免费（GitHub） | 高（第三独立实现；注释直接引用 AN2056 时序、MythTV EN 50494 patch、patchwork.linuxtv.org patch 7994） | 同上交叉验证 + 电压/音调/时序状态机 | 实现佐证 |
| 5 | **minisatip** `src/dvb.cpp`（`send_unicable`/`send_jess`） | 免费（GitHub） | 中高（第四独立实现；EN 50494 频率处理与前三家存在分歧，见 §2.4） | 同上交叉验证 | 实现佐证 |
| 6 | **Inverto Unicable II 设备手册/数据表**（inverto.tv 直下两份 PDF，本次实测下载） | 免费（厂商一手） | 中高（设备参数面一手来源，非规范文本） | UB 带宽 46 MHz 可编程 10–80 MHz、默认 UB 频率组、Dynamic/Static 模式、EN50494+EN50607 兼容声明、SCR 堆叠动作描述 | 文档引用（本次逐页 grep） |
| 7 | **SAT>IP Protocol Specification v1.2.2**（DVB BlueBook A173 语境，SES 发布，dreambox.de 镜像 PDF 本次实测下载；70 页全文检索） | 免费 | 中高（卫星位置/前端选择语义的规范级文本；**v1.2.2 无 `uni` 参数**） | `src` = 1 基卫星位置、映射 DiSEqC 端口 A–D；`freq` = IF 频率 | 文档引用 |
| 8 | **iTeh 条目页**（EN 50607:2015，standards-audit §9 既引） | 免费（仅元数据/摘要） | 中（目录页元数据，非正文） | "up to 32 receivers, 256 IF banks, DiSEqC/JESS/dCSS" | 文档引用（二手元数据） |
| 9 | **Eutelsat DiSEqC Bus Functional Specification**（镜像 PDF）+ **TI SLVA863** 应用报告 | 免费 | 中（DiSEqC 1.x/2.x 基础：框架字节 0xE0/0xE1、地址 0x10、22kHz 时序） | EN 50494 命令所构建其上的 DiSEqC 底座 | 文档引用（未本次逐条核对，roadmap §5 既记"DiSEqC 1.x/2.x 命令集公开资料充分"） |
| 10 | **TSDuck 本机 3.45-4798**（`dvb` 输入插件 --help、`tsduck.lnbs.xml`） | 本机实测 | 中（参数面参照；TS 域工具） | `--unicable <version>,<slot>,<freq MHz>` 参数语法、LNB 模型 XML | 文档引用（本机实测 --help 输出） |
| 11 | OpenPLI wiki（Unicable/JESS 概览）、Televes 目录（SCR 展开名）、MuMuDVB issue #46（UB0=1210 MHz 实例） | 免费 | 低-中（二手） | 术语命名、社区配置实例 | 文档引用（二手交叉） |

**不可得**（付费，维持 roadmap §5 既记）：EN 50494:2007 与 EN 50607:2015 正文（CENELEC）。票面 "GSet" 品牌无法核实（§0.7）。

---

## 2. 调谐消息与频率语义精确化（四实现交叉验证）

> 以下位布局与公式为**四家独立实现的源码级共识**（tvheadend `linuxdvb_en50494.c` / VDR `diseqc.c` `SetScrFrequency`+`SetScrPin` / MuMuDVB `tune.c` `do_unicable` / minisatip `dvb.cpp` `send_unicable`+`send_jess`）。EN 50494/50607 的对应条款号**待原文核对**（§6）——本节把"实现共识"与"标准断言"分开：位布局本身标注【实现佐证】，条款号归属一律不写。
>
> 记号：`f_IF` = transponder 经 LNB 本振变频后落入 950–2150（II 至 2400）MHz 的中频（无 SCR 时接收端本要调的频率）；`f_UB` = 接收端被分配的 User Band 槽位中心频率；`t` = 消息中编码的频率字段。

### 2.1 EN 50494（Unicable I）——ODU_channel_change

DiSEqC master 命令 5 字节 `[0xE0, 0x10, 0x5A, data1, data2]`；PIN（multihome）变体 6 字节，命令字节换 0x5C、追加第 3 数据字节 = PIN（0–255）。

| 字段 | 位 | 语义（tvheadend 注释原词） | 佐证 |
|---|---|---|---|
| data1 bit7–5 | 3 bit | user-band（UB 槽位 0–7，`le_id & 7`） | 四家一致【实现佐证】 |
| data1 bit4 | 1 bit | position：satellite A(0)/B(1)——Unicable I 仅 2 卫星位置（tvheadend："only 2 ports/positions are possible"） | 四家一致（MuMuDVB：`sat_no != 1` 置位）【实现佐证】 |
| data1 bit3 | 1 bit | polarization v(0)/h(1) | 四家一致【实现佐证】 |
| data1 bit2 | 1 bit | band lower(0)/upper(1)（22kHz 频段） | 四家一致【实现佐证】 |
| data1 bit1–0 + data2 bit7–0 | 10 bit | t（频率字段；上限 1023/1024，tvheadend 报错阈值） | 四家一致【实现佐证】 |

**频率编码公式**（四家一致）：

```
t = round((f_IF + f_UB + 2) / 4) − 350        （单位 MHz；VDR 注释：'+ 2' 与 '/ 4' 联合实现四舍五入）
```

**接收端前端实际调谐频率**（tvheadend/VDR/MuMuDVB 三家公式一致）：

```
f_tune = (t + 350) × 4 − f_IF    ≈  f_UB + 2 MHz（± 四 MHz 量化栅格残差）
```

**命令交换状态机**（实现注释直接给出标准界，条款号待核）：
1. 先 13V/关 tone（minisatip 显式 `FE_SET_VOLTAGE_13` + `FE_SET_TONE_OFF`）；
2. 切 **18V**（tvheadend："use 18V"；minisatip 同）；
3. 等待 powerup 时间（tvheadend 默认 15 ms，注释 "**standard: 4ms < x < 22ms**"；MuMuDVB 注释引 AN2056 "more than 4ms after 13V→18V"）；
4. 发送命令，等待 settle（tvheadend 默认 50 ms，注释 "**standard: 2ms < x < 60ms**"）；
5. 回 13V。重复发送时随机退避 68–118 ms（tvheadend 注释 "to avoid repeated collision"，典型 DiSEqC 时隙 67.5 ms）；MuMuDVB 重复间隔 100 ms 且重复帧 framing 字节换 0xE1（DiSEqC "repeated transmission" 位）。
6. tvheadend 用**全局 mutex 序列化**所有 EN 50494 tune——单进程内多 tuner 的命令互斥（这正是 A1 场景在软件层的镜像：跨进程/跨接收端无人替你互斥）。

命令字节面（tvheadend 常量）：`0x5A` normal / `0x5B` special / `0x5C` normal+PIN / `0x5D` special+PIN；satellite 常量 `SAT_A=0x00 / SAT_B=0x01`。"special" 的标准语义待原文核对【推断】。

### 2.2 EN 50607（dCSS/Unicable II）

原始 4 字节消息 `[0x70, data1, data2, data3]`（**不再用 0xE0/0x10 DiSEqC 框架**——帧字节直接 0x70/0x71，tvheadend 用 `raw_send`，minisatip/MuMuDVB 同）；PIN 变体帧字节 0x71、5 字节。VDR 注释称此协议 "EN50607 aka JESS"；MuMuDVB 分支注释 "JESS or UNICABLE II"。

| 字段 | 位 | 语义 | 佐证 |
|---|---|---|---|
| data1 bit7–3 | 5 bit | user-band（UB 槽位 0–31 → **32 UB**，与 roadmap §5 既核的 "dCSS 32 UB" 吻合） | 四家一致【实现佐证】 |
| data1 bit2–0 + data2 bit7–0 | 11 bit | t（1 MHz 分辨率；上限 2047） | 四家一致【实现佐证】 |
| data3 bit7–2 | 6 bit | position（0–63；tvheadend："only 64 ports/positions are possible"） | 四家一致（minisatip `pos & 0x3f`）【实现佐证】 |
| data3 bit1 | 1 bit | polarization v(0)/h(1) | 四家一致【实现佐证】 |
| data3 bit0 | 1 bit | band lower(0)/upper(1) | 四家一致【实现佐证】 |

**频率编码与调谐**（四家一致）：

```
t = f_IF − 100            （MHz，11 bit → 覆盖 100–2147 MHz）
f_tune = f_UB             （精确 UB 中心频率；minisatip/MuMuDVB/VDR/tvheadend 一致）
```

对比要点：dCSS 不再把 transponder 量化到 4 MHz 栅格（Unicable I 的 t 分辨率 4 MHz vs dCSS 1 MHz），接收端直接调 UB 中心——**dCSS 的堆叠语义是"transponder 居中放入 UB"**，语义干净得多【实现佐证；"居中"解释为推断，待原文核对】。

### 2.3 与 DiSEqC 底座的关系

EN 50494 帧复用 DiSEqC 框架（0xE0 = command from master/no reply/first transmission，0xE1 = repeated；地址 0x10 = "any LNB, switcher or SMATV"——MuMuDVB 注释原词），可走内核 `FE_DISEQC_SEND_MASTER_CMD`（3–6 字节）直接发送；EN 50607 的 0x70/0x71 帧虽不属 DiSEqC 1.x/2.x 框架字节，但四家实现同样经由 `FE_DISEQC_SEND_MASTER_CMD` 发送（4–5 字节在 6 字节上限内）。kernel 文档对 master cmd 的唯一硬约束即 `msg[6]`/`msg_len 3..6` 与"参见 Eutelsat DiSEqC bus spec"（frontend.h 注释原词）。【文档引用：kernel；实现佐证：四家】

### 2.4 实现分歧（诚实记录）

| 分歧点 | 三家 | minisatip | 处置建议 |
|---|---|---|---|
| EN 50494 接收端调谐频率 | `(t+350)×4 − f_IF ≈ f_UB + 2 MHz`（tvheadend/VDR/MuMuDVB） | 直接 `f_UB` | 谁对（或是否设备相关）待原文核对/实测；SPEC-623 若须取边，按多数派（f_UB + 栅格残差）并在规格中标注分歧 |
| EN 50494 t 上限判断 | tvheadend `>= 1023` 拒绝；MuMuDVB `> 1024` 报错 | 无显式检查 | 规格按 10-bit 字段宽取 0–1023【实现佐证（字段宽）】 |
| 重复退避间隔 | 68–118 ms 随机（tvheadend）/ 100 ms 固定（MuMuDVB） | diseqc repeat 通用逻辑 | 时序参数应为模型可配项，不硬编码 |

### 2.5 Slot / UB / SCR channel 术语对照

| 术语 | 出处 | 语境 |
|---|---|---|
| **User Band（UB）** | EN 50494/50607 标准术语（roadmap §5 既核；Inverto 手册 "User Band (channel)"） | 规范正名，SPEC-623 建议采用 |
| slot | TSDuck `--unicable` help 原词 "userband slot"；SAT>IP 社区资料 | TSDuck/社区用语 |
| SCR channel | VDR `scr.conf` 原词 "channel"（0–7 / JESS 至 11+） | VDR 用语 |
| UB slot | 票面 A1 用语（"User Band 槽位频率"） | 本仓库语境 |
| position / port | tvheadend "Position ID"/"ports/positions"；SAT>IP `src` | 卫星位置轴，与 UB 正交 |

**"Position"与"UB"是两条正交的轴**：position 选择卫星源（I：A/B 1 bit；II：0–63 6 bit），UB 选择同轴电缆上的频率槽位（I：0–7；II：0–31）。A1 冲突是 UB 轴上的冲突，不是 position 轴上的。【实现佐证：字段分离】

---

## 3. UB 冲突语义（A1 订正口径的佐证与精化）

A1 订正口径（roadmap §4 领域 A）：SCR = Satellite Channel Router（EN 50494，非 "Subscriber Channel Radio"）；冲突本质 = 同一 User Band 被两个接收端占用导致 SCR 堆叠信号互相干扰，不是 LNB 本振冲突。本次研究的增补证据：

1. **堆叠动作的厂商一手描述**（Inverto Unicable II multiswitch 数据表原文）："Controlled by the connected receivers over EN50494 or EN50607 protocol, the multiswitch will **select the desired transponder channel, convert its frequency to the respective User Band frequency and stack it** over the Unicable output ports"——SCR 的角色是按命令把选中的 transponder **变频到该 UB 频率并堆叠**；一个 UB 频槽堆叠两路即为互扰。【文档引用】
2. **冲突的成因在分配层不在物理层**：接收端不会主动探测 UB 占用——四家实现全部是"按配置直接发命令"（UB slot/频率来自配置文件或用户设置，无占用协商协议出现在调谐路径上；EN 50607 有 0xE1 帧 + reply 能力但实现均未用于 UB 协商）。因此冲突是**配置错误**（两个接收端被分配同一 slot）或**运行期并发**（两接收端同时调同一 UB）——不是信号劣化结果。【实现佐证 + 推断（"标准未定义协商"为推断，待原文核对）】
3. **软件层教训**：tvheadend 需要一个进程内全局 mutex 来序列化 EN 50494 命令（避免本机两 tuner 并发互踩）——跨接收端的冲突无人兜底，这正是 A1 靶场的教学内核：UB 分配表是**设备级共享资源**。【实现佐证】
4. **1210 MHz 示例吻合**：Inverto 两份数据表默认 UB 组 CH0–CH3 = 1210/1420/1680/2040 MHz（EN50494+EN50607 双兼容）；MuMuDVB issue #46 配置实例 UB0 = 1210 MHz（standards-audit §9 既引）。A1 用 1210 MHz 作冲突示例与行业默认组一致。【文档引用】
5. **UB 带宽**：Inverto 数据表 "User band (channel) bandwidth **46 MHz**, programmable 10 MHz ~ 80 MHz"（另一型号默认 30 MHz 可配 10–80）——UB 不是线频点而是带宽槽位（容纳一个 transponder），同一根电缆上的多个 UB 频率不得重叠，这正是"槽位"（slot）一词的物理含义。【文档引用；标准侧 UB 带宽定义条款待原文核对】
6. **默认频率组不止 4 个**：8 端口型号默认动态 UB 组为 985/1020/1050/1056/…/1210/1420/1680/2040 MHz 等（每端口 16 UB 可编程）——A1 知识卡片若列默认组应取厂商数据表而非硬编码。【文档引用】

---

## 4. Linux kernel DVB API 盘点（SPEC-622/623 的权威参考实现）

**核对范围**：torvalds/linux master `include/uapi/linux/dvb/frontend.h`（本次全文逐行）+ `Documentation/userspace-api/media/dvb/`（frontend-property-satellite-systems.rst、fe_property_parameters.rst、fe-diseqc-send-master-cmd.rst 等，本次逐字 grep "unicable/EN 50494/EN50494/EN 50607/SCR"——**零命中**）。

**SEC 原语面（内核权威词汇表，SPEC-622 的直接输入）**【文档引用】：

| 内核接口 | 值域/形态 | 备注 |
|---|---|---|
| `FE_SET_VOLTAGE` / `DTV_VOLTAGE`(10) | `SEC_VOLTAGE_13 / _18 / _OFF` | 枚举注释即权威定义 |
| `FE_SET_TONE` / `DTV_TONE`(11) | `SEC_TONE_ON / _OFF` | 注释："22kHz tone burst"；"Don't send … (except if the FE_DISEQC_* ioctls are called)"——DiSEqC 命令自带 tone 调制，与 EN 50494 交换前显式关 tone 的实现行为互证 |
| `FE_DISEQC_SEND_MASTER_CMD` / `DTV_DISEQC_MASTER`(7) | `struct dvb_diseqc_master_cmd { __u8 msg[6]; __u8 msg_len; }`，**msg_len 3–6** | 注释："framing + address + command, and an optional argument of up to 3 bytes"；"Check out the DiSEqC bus spec available on http://www.eutelsat.org/" |
| `FE_DISEQC_RECV_SLAVE_REPLY` / `DTV_DISEQC_SLAVE_REPLY`(14) | `struct dvb_diseqc_slave_reply` | EN 50607 双向能力的内核底座 |
| `FE_DISEQC_SEND_BURST` | `SEC_MINI_A / SEC_MINI_B` | mini-DiSEqC |
| `FE_DISEQC_RESET_OVERLOAD` / `FE_ENABLE_HIGH_LNB_VOLTAGE` | — | 过载保护/高电压允许 |
| DTV 属性全集 | `DTV_UNDEFINED(0) … DTV_SCRAMBLING_SEQUENCE_INDEX(70)` | **无任何 Unicable/SCR/dCSS 属性**；唯一的 "SCRAMBLING" 是 DVB-S2 物理层扰码索引，无关 |

**结论**：内核刻意把 EN 50494/50607 留给用户态（消息构造在四家用户态实现中完成）——**"DiSEqC 原语层（SPEC-622）在上、Unicable 消息/UB 管理层（SPEC-623）在下层之上"** 的分层不是我们的发明，而是 Linux 生态的既成架构。【文档引用 + 实现佐证】

---

## 5. 本机 TSDuck 可用面核查（实测记录）

- 环境：TSDuck 3.45-4798（`D:\Program Files\TSDuck\bin`），2026-11-20 本机实测。
- **tsp 处理器插件全量清单**（`tsp --list-plugins` 实测）：input/output/processor 三类共约 70 插件中**无任何 unicable/DiSEqC/LNB 处理器插件**——TSDuck 是 TS 域工具，RF/SEC 域的控制面只存在于硬件输入插件。
- **`dvb` 输入插件（Windows BDA）** 实测 `--help` 提取：
  - `--lnb name`：引用 `tsduck.lnbs.xml` 预配置 LNB（"The default is a universal extended LNB"）；
  - `--unicable value`：原文——"Used for satellite tuners only, in local Unicable distribution networks. Description of the Unicable switch. The value is of the form: **\<version\>,\<userband slot\>,\<userband frequency in MHz\>**. Version 1 indicates **EN50494 (Unicable I)**, version 2 indicates **EN50607 (Unicable II)**."——TSDuck 用 "userband slot" 术语，参数面 = {协议版本, UB 槽位, UB 频率}，无 position/PIN 参数（比开源实现面窄）。
- **`dektec` I/O 插件**实测 grep：有 `--lnb`/`--no-lnb-control`/DiSEqC switch position 选项，**无 `--unicable` 选项**。
- **`tsduck.lnbs.xml`**：19 条 LNB 定义（Universal/Astra/C-Band/DishPro/日本 110BS 等），每条 = `<band low high oscillator switch polarity>`；无 SCR 条目。`tsduck.hfbands.xml`/`tsduck.etuner.model.xml`（tuner emulator 模板）与 RF 域建模有关但不含 Unicable。
- **NOT RUN 项（诚实标注）**：硬件调谐行为（BDA `--unicable` 实际调谐、DiSEqC 命令下发）未运行——本机无 DVB 设备；且 Windows BDA 无法查询调谐器实际锁定参数（roadmap §5 既有结论），TSDuck 在 Windows 上的 Unicable 参数面无法端到端验证。
- **适用性结论**：TSDuck 在 Unicable 研究中只提供**参数面第三意见**（version/slot/frequency 三元组与 kernel/开源实现相互印证）；不承担 SPEC-622/623 的注入器/验证器角色（照 #104 T2MI 收窄先例的精神：外部工具适用面按实测收窄）。【文档引用（本机实测）】

---

## 6. 条款号缺口清单（全部「待原文核对」）

> 遵守"不编造条款号"契约（standards-audit 包内契约同类纪律）。以下每一项都已有**免费可核实的实现级/厂商级事实**，仅缺 EN 50494/50607 正文的条款号定位：

| # | 待核项 | 已有免费事实（可先用于规格，标注来源） |
|---|---|---|
| 1 | EN 50494 ODU_channel_change 消息定义条款（0xE0/0x10/0x5A、数据字节位分配） | 四实现位布局完全一致（§2.1）【实现佐证】 |
| 2 | EN 50494 频率字段 t 的计算公式条款（含 +2/−350 常数的规范出处） | 四实现公式一致（§2.1）【实现佐证】 |
| 3 | EN 50494 时序条款（powerup 4–22 ms、settle 2–60 ms、重复退避） | tvheadend 注释 "standard:" 原文 + MuMuDVB AN2056 引注（§2.1）【实现佐证】 |
| 4 | EN 50494 命令字节集 0x5A/0x5B/0x5C/0x5D 的标准语义（"special" 含义） | tvheadend 常量（§2.1）【实现佐证】 |
| 5 | EN 50494 Unicable I 的 UB 数量（3-bit 字段→8）与 IF 范围 950–2150 MHz 的条款 | 字段宽为实现共识；IF 范围见厂商数据表 + iTeh 元数据【文档引用（二手）】 |
| 6 | EN 50607 dCSS 消息定义条款（0x70/0x71 帧字节、24-bit 数据布局） | 四实现一致（§2.2）【实现佐证】 |
| 7 | EN 50607 的 32 UB / 64 position / IF 950–2400 MHz 条款；"256 IF banks"（iTeh 元数据）与实现面 64 position 的关系 | iTeh 条目（standards-audit 既引）+ 四实现【文档引用（二手元数据）+ 实现佐证】 |
| 8 | EN 50494 堆叠偏置（f_UB + 2 MHz）与 EN 50607 居中堆叠的标准表述 | 三实现公式推出的物理规则（§2.1/§2.4）【推断】 |
| 9 | SAT>IP `uni` 参数定义（v1.4+ 版本）与 `src`（v1.2.2 §3.5.x 有原文） | v1.2.2 无 `uni`；`src` 1 基位置映射 DiSEqC A–D 有原文【文档引用】；`uni` 待原文核对 |
| 10 | JESS 名称展开（"Joint European Standard for Switching"）与 GSS/dCSS 标准化历史 | VDR 代码注释 "EN50607 aka JESS" + OpenPLI wiki（二手）【实现佐证（VDR 原词）+ 文档引用（二手）】 |
| 11 | EN 50494/50607 的 UB 带宽定义（Inverto 数据表：46 MHz 可编程 10–80 MHz 是否即标准默认档） | 厂商一手数据表【文档引用（厂商）】 |

---

## 7. 对下游票的输入建议

### 7.1 对 #148（拓扑端口模型扩展）

1. **共享资源的建模对象是 SCR 设备的 UB 分配表，不是 tuner 端口**：A1 的多 tuner 共享单根同轴 = N 个 tuner（接收端）端口 → 1 个 Unicable 设备节点（SCR LNB 或 dCSS multischalter）→ 卫星。UB 分配表（slot → {receiver 端口, 中心频率, 带宽}）挂在 Unicable 设备节点上；冲突检测 = 同一 slot 被两个 tuner 端口同时请求（配置期静态冲突 + 运行期并发冲突两种形态，§3.2）。端口级连线契约（ADR-0005 决策 5）无需改动，扩的是节点类型与节点级共享状态。
2. **命令总线是 SCR 设备上的排队资源**：DiSEqC/Unicable 命令交换是互斥的时序过程（18V→等待→命令→settle→13V；tvheadend 全局 mutex 是软件层自保）——L0 模型建议把命令交换建模为 Unicable/DiSEqC 节点上的串行队列，使"两个 tuner 同时调谐"天然产生可观测的排队/冲突事件。
3. **Position 与 UB 是正交两轴**（§2.5）：端口模型若引入 position（卫星源）与 UB（频率槽）两维属性，A1（UB 冲突）与未来"position 配错"场景可共用同一节点模型。
4. **字段宽即容量上限**（8/32 UB、2/64 position）：拓扑校验可直接用位宽作为合法值域的第一道闸【实现佐证】。

### 7.2 对 #150（SPEC-622/623 边界）

1. **分层即 Linux 架构**（§4）：SPEC-622 DiSEqC Controller = SEC 原语层（VOLTAGE/TONE/MASTER_CMD≤6B/SLAVE_REPLY/BURST/OVERLOAD，词汇表直接取 kernel 枚举）；SPEC-623 Unicable = 消息构造 + UB 分配管理层（EN 50494/50607 帧构造、t 公式、UB 分配表、冲突语义），**建立在 622 原语之上、不自带电压/音调状态**——四家开源实现同构（都是先 FE_SET_VOLTAGE/FE_SET_TONE 再 FE_DISEQC_SEND_MASTER_CMD）。
2. **SPEC-623 参数面建议**（从 §2 归纳）：`protocol {EN50494, EN50607}`、`ub_slot`（I 0–7 / II 0–31）、`position`（I {A,B} / II 0–63）、`polarization`、`band`、`ub_center_freq`、`ub_bandwidth`、`pin`（multihome 变体，0x5C/0x71）、时序参数（powerup/settle/repeat-backoff，默认值取实现中位、允许配置）；消息帧按 §2.1/§2.2 位布局写入规格并标注"实现共识，条款号待原文核对"。
3. **SPEC-622 侧注意**：kernel 注释明确 DiSEqC 命令自带 22kHz 调制（tone 与 DiSEqC ioctl 的互斥关系）——622 的状态机须包含 tone/voltage/命令三者的先后约束，minisatip 的"先 13V+关 tone→18V→命令→13V"序列可作为状态机蓝本。
4. **术语定名**：SPEC-623 正文以 **User Band（UB）** 为正名；slot/SCR channel 记为别名（§2.5 对照表可直接进 CONTEXT.md 词条候选：Unicable/SCR/dCSS/UB/Position 五词）。
5. **TSDuck 适用面收窄结论**（照 #104 先例）：TSDuck 仅作参数面第三意见参照（§5），不进 SPEC-622/623 的运行时路径与验证链。
6. **观测面候选**（供 SPEC-620 观测扩容参考）：`unicable.*` 事件族（ub_request / ub_grant / ub_conflict / cmd_sent(framing bytes) / cmd_retry）；按 No fake evidence 红线，L0 下全部 `source=rule_engine/simulator, confidence=simulated`，帧字节内容可作为事件 payload 诚实记录（这是状态级仿真可诚实产出的数据，不需要伪造 RF 测量值）。
7. **A1 靶场规格化输入**：冲突场景的参数三元组建议 = 两个 tuner + 共享 Unicable 设备 + 同一 UB slot（默认组取 1210 MHz）+ 不同 transponder 请求；预期症状 = 双方无法锁定（SCR 堆叠互扰）；反事实验证 = 改分配 UB slot 后恢复（符合"配置错误可修复"的教学目标）。

---

## 8. 来源

**本次逐行/逐页核对的一手材料**
- Linux kernel（torvalds/linux master）：`include/uapi/linux/dvb/frontend.h`；`Documentation/userspace-api/media/dvb/frontend-property-satellite-systems.rst`、`fe_property_parameters.rst`、`fe-diseqc-send-master-cmd.rst`（经 GitHub API 抓取原文，grep 核对）
- tvheadend master：`src/input/mpegts/linuxdvb/linuxdvb_en50494.c`（511 行，本次逐段核对消息构造/时序/常量）
- VDR master：`diseqc.c`（`SetScrFrequency`/`SetScrPin`）、`scr.conf`
- MuMuDVB mumudvb2 分支：`src/tune.c`（`do_unicable`/`unicable_send_msg`）
- minisatip master：`src/dvb.cpp`（`send_unicable`/`send_jess`）
- Inverto Unicable II Multiswitch 安装手册（IDLU-UST110-CUO8O-32P，12 页）与数据表（IDLU-UST110-CUO1O-32P，3 页）——inverto.tv 直下 PDF，本次 pypdf 全文检索
- SAT>IP Protocol Specification v1.2.2（2015-01-08，SES，70 页 PDF，dreambox.de 镜像）——全文检索 `src`/`uni`/DiSEqC 映射
- 本机 TSDuck 3.45-4798：`tsp --list-plugins`、`tsp -I dvb --help`、`tsp -I dektec --help`、`tsduck.lnbs(.model).xml`、`tsduck.hfbands.xml`、`tsduck.etuner.model.xml`

**免费可得的规范/条目入口（URL）**
- Linux DVB 文档在线版：https://docs.kernel.org/userspace-api/dvb/index.html
- ETSI TS 103 129（DVB CID，与 Sat>IP 无关的**同名陷阱**，检索时勿混淆）：https://www.etsi.org/deliver/etsi_ts/103100_103199/103129/01.01.02_60/ts_103129v010102p.pdf
- SAT>IP Protocol Specification v1.2.2（DVB BlueBook A173 语境；dreambox.de 镜像）：https://dreambox.de/board/wcf/index.php?attachment/15409-satip-specification-version-1-2-2-pdf
- Inverto Unicable II multiswitch 手册：https://www.inverto.tv/download/file/59f9814ec5d89-1509523790.pdf ；32-UB 数据表：https://www.inverto.tv/download/file/598c924eb6bb1-1502384718.pdf
- EN 50607:2015 iTeh 条目（元数据）：https://standards.iteh.ai/catalog/standards/clc/1fe0792f-0ad5-4f1f-bb40-f3a9a47790dc/en-50607-2015
- Eutelsat DiSEqC Bus Functional Specification（镜像）：https://affon.narod.ru/difst/diseqc31.pdf ；TI SLVA863 应用报告：https://www.ti.com/lit/pdf/slva863
- OpenPLI wiki（Unicable/JESS 概览）：https://wiki.openpli.org/Unicable_/_Jess
- MuMuDVB SCR 特性请求与实例（UB0=1210 MHz）：https://github.com/braice/MuMuDVB/issues/46
- MuMuDVB 注释内引注：MythTV EN 50494 patch（code.mythtv.org ticket 9726）、patchwork.linuxtv.org patch 7994、AN2056 时序

**二手来源（明确标注）**
- EN 50494/50607 正文付费（CENELEC），本次未获取；条款号全部缺项见 §6
- "GSet" 品牌：多轮检索无果，无法核实（可能为 GSS 笔误）；GSS/dCSS 标准化历史仅行业二手来源（Cable Vision 03/2020 等）
- Wikipedia Single-cable distribution 条目：本环境网络不可达（curl/WebFetch 双路失败），未采信；其结论面已由 Inverto 一手文档 + 四实现覆盖

**方法说明**：位级布局结论取"四家实现一致"为通过线（tvheadend/VDR/MuMuDVB/minisatip 互相独立）；单一来源出现的行为（如 minisatip EN 50494 调谐频率分歧）按 §2.4 诚实记录不作裁决。本仓库此前结论（standards-audit §4 SCR 展开名订正、roadmap §5 Unicable 条）本次全部复核维持。
