# OPEN-106 调研报告：BISS 加解扰实现路径实测（libdvbcsa 绑定 / CSA 性能 / CISSA 可得性）

- **Issue**: BingChaoLiu/DVB-Nexus #106（parent #103，下游 #109 细裁票）
- **日期**: 2026-11-17
- **性质**: 调研 + 本机实测（构建外部 C 库、ctypes 绑定验证、纯 Python 基准；未修改任何其他 issue / 未动仓库代码）
- **实测沙箱**: 全部下载代码与构建产物放在仓库外独立目录 `D:\Project\VibeCoding\dvb-external\`（`libdvbcsa\` 源码克隆、`build\` DLL 产物、`scripts\` 自写脚本、`standards\` 标准原文、`refs\` 参考实现），与仓库代码零混放；跑外部相关代码一律 `python -I` 并从仓库外传入绝对路径
- **标准原文**（均已免费下载留档于沙箱 `standards\`）:
  - ITU-T J.96 (07/2002)《Technical method for ensuring privacy…》——BISS Mode 0/1/E 的**完整规范性定义**（EBU Tech 3292 rev.2 的公开等价文本，含 DES 解密函数、ID 映射表、P() 后处理的逐 bit 定义），`itu.int/rec/T-REC-J.96`
  - EBU Tech 3292 v3.0 (2018)《BISS2 Basic Interoperable Scrambling System》——BISS2 Mode 1/E（AES-128 ESW），`tech.ebu.ch/docs/tech/tech3292.pdf`
  - ETSI TS 103 127 V1.1.1 (2013-05)——DVB-CISSA 规范（AES-128 + CBC + 固定 IV + TS 包级处理规则），`etsi.org/deliver/etsi_ts/103100_103199/103127/01.01.01_60/ts_103127v010101p.pdf`
  - EBU Tech 3292-s1《BISS-CA》——Mode CA（RSA-2048 + AES-128 + ECM/EMM，MVP 不涉及，留证即可）

---

## 1. 结论摘要（TL;DR）

1. **BISS1（Mode 1/Mode E）推荐路径：ctypes 绑定自编译 libdvbcsa DLL + pycryptodome DES。** libdvbcsa 在本机（MSYS2 mingw64 gcc 16.1.0）无需 autotools 即可编译出 generic 与 SSE2 bitslice 两个 DLL；ctypes 绑定通过其自带全部静态测试向量（2/2 encrypt+decrypt+roundtrip PASS）。单包 API 实测 ~70.6k 包/s ≈ **104 Mbps**（贴着 MVP 100 Mbps 上限），SSE2 批量 API 实测 ~335k 包/s ≈ **497 Mbps**（5 倍余量）——批量 API 是推荐接入面。
2. **纯 Python CSA1 不可用**：忠实移植 libdvbcsa（含 key schedule 8×256 表、block 56 轮、stream cipher）向量对拍 PASS，但吞吐仅 **207 包/s ≈ 0.305 Mbps**，距 100 Mbps envelope 差 **321 倍**；100 万包 preset 纯 Python 加扰需 ~1.3 h。纯 Python 只能做离线小样本/参考实现，不能做主路径。
3. **Mode E / BISS2 密钥面全部可用 pycryptodome 覆盖**（实测 4.5.0）：BISS1 Mode E = DES-ECB 解密 ESW（56→64 bit 奇偶映射 ID + 去奇偶位 + P() 旋转，ITU-T J.96 §9.3 逐 bit 明确定义）；BISS2 Mode E = AES-128-ECB（Tech 3292 v3 §4.3.4）。
4. **CISSA（BISS2 TS 加扰）完全公开、自研面极小**：ETSI TS 103 127 §6.3 规范 = AES-128 + CBC（每包重启，固定 IV `0x445642544d4350544145534349535341`，ASCII `DVBTMCPTAESCISSA`）+ 每包只加密 `payload - payload%16` 字节、尾部明文。**pycryptodome `MODE_CBC` 实测 91.1k 包/s ≈ 134 Mbps（1.4 倍余量），纯 Python 即达标，无需原生绑定**。GitHub 无独立 CISSA 库包，但存在 GPL 参考实现（dvbipitools `cissa.c` ~105 行）佐证实现难度。
5. **给 #109 的裁剪输入**：组件形态 = ctypes 绑定（CSA1）+ 纯 Python（CISSA/DES/密钥派生）双轨；管线接入 = 传输级组件（整流加扰，语义过滤器架构不适用）；需自研面 = BISS1 CW 派生（checksum 字节）、Mode E 密钥派生、TS 包循环（scrambling_control bit 置位、随机性规则）。详见 §7。

---

## 2. 可得性调查

### 2.1 libdvbcsa（DVB-CSA1 C 实现）

| 渠道 | 状态 |
|---|---|
| PyPI 现成绑定 | **无**。两轮检索（"PyPI dvbcsa / libdvbcsa python binding"）未发现任何已发布包；社区流传的 "libdvbcsa-python"（Cython 绑定）没有 PyPI 发布，且无 Windows wheel，需本地编译 Cython——相比直接 ctypes 无优势 |
| vcpkg / conda | 无收录（本机亦无 vcpkg） |
| 上游源码 | `github.com/glenvt18/libdvbcsa`（GPL-2.0+，VideoLAN 家族库，含单包 API + SIMD bitslice 批量 API） |
| **本机构建** | **MSYS2 mingw64 gcc 16.1.0 直接编译成功**（见 §3.1），无需 autotools/MSVC |

构建要点（复现命令，Git Bash 下 gcc 静默失败 exit=1，须走 `D:/Software/msys64/usr/bin/bash.exe -lc`）：

```bash
# 1) 最小 config.h（LLP64：SIZEOF_LONG=4；小端）放构建目录，-I 传入
# 2) generic（单包 API）：
gcc -O2 -Ibuild -Isrc -shared -o build/libdvbcsa.dll \
  src/dvbcsa_algo.c src/dvbcsa_block.c src/dvbcsa_key.c src/dvbcsa_stream.c
# 3) SSE2 bitslice（批量 API）——宏必须是 DVBCSA_USE_SSE（configure.ac 的定义），
#    transpose 文件二选一：SSE(uint64) 用 transpose_stream.c，不要带 _stream32
gcc -O2 -msse2 -Ibuild -Isrc -DDVBCSA_USE_SSE=1 -DHAVE_MM_MALLOC=1 -shared \
  -o build/libdvbcsa_bs.dll src/dvbcsa_bs_*.c src/dvbcsa_bs_transpose_block.c \
  src/dvbcsa_bs_transpose_stream.c src/dvbcsa_algo.c src/dvbcsa_block.c \
  src/dvbcsa_key.c src/dvbcsa_stream.c
```

产物：`libdvbcsa.dll`（117 KB）+ `libdvbcsa_bs.dll`（136 KB），导出单包 API 与 `dvbcsa_bs_*` 批量 API。CI 侧可在 MinGW 环境按同样命令打包 wheel/工件，或把 4 个 generic C 文件直接并入 Python 扩展构建。

### 2.2 BISS1 规范面（ITU-T J.96 = Tech 3292 rev.2 公开文本）

- **Mode 1**（J.96 §8）：12 hex 字符 Session Word（48 bit 自由熵）→ 64-bit CW "derived from the SW according to the DVB-CSA specification"。实践派生公式（J.96 未逐字给出，由 3 个独立实现交叉印证一致，见 §5）：
  `CW[0..2]=SW 字节 0..2；CW[3]=(CW[0]+CW[1]+CW[2]) mod 256；CW[4..6]=SW 字节 3..5；CW[7]=(CW[4]+CW[5]+CW[6]) mod 256`
  实测示例：`SW=A13DBC42908F`（J.96 示例）→ `CW=A13DBC9A42908F61`。
- **Mode E**（J.96 §9.3，逐 bit 规范）：
  1. Active ID（14 hex = 56 bit，注入 ID 必选 / 厂商 buried ID 可选）→ Mapped Active ID：56 bit 映射进 8 字节高 7 bit，每字节 LSB 补奇校验位；
  2. `SW' = DES-ECB-decrypt(key=Mapped Active ID, data=ESW)`（FIPS 46-3/81）；
  3. SW' 去奇偶：每字节删首位两位（64→48 bit）得 SW"；
  4. `P()`：注入 ID 时恒等；buried ID 时 SW" 循环右移 1 bit → 明文 SW。
  **pycryptodome DES 完全覆盖**（ECB 单块），实测 roundtrip OK（§4.4）。
- 信令：CA_system_ID `0x2600`，CA_PID `0x1FFF`，PMT 节目级 CA_descriptor，空 CAT，包 TSC bit 置 `10`（J.96 §8.1——注意 J.96 Mode 1 只定义偶键 `10`；奇键 `11` 在 CSA 语境下为 odd CW，BISS1 单 CW 场景按 `10` 实现）。

### 2.3 BISS2 规范面（Tech 3292 v3 + TS 103 127）

- **Mode 1**（Tech 3292 v3 §4.2）：32 hex（128-bit）SW，直接作为 DVB-CISSA（TS 103 127 §6）密钥；CA_system_ID `0x2602`。
- **Mode E**（§4.3.4）：`SW = AES-128-ECB-decrypt(Active ID 128-bit, ESW 128-bit)`。AES-128-ECB pycryptodome 直接覆盖。
- **CISSA（TS 103 127 §6.3 规范原文，已下载留档）**：
  - 块密码：AES-128（FIPS 197）；链接模式：CBC（SP800-38A）；固定 IV `0x445642544d4350544145534349535341`；
  - **每包独立处理**：TS header + AF 明文；`encrypted_payload_size = payload_size − payload_size mod 16`（无 AF 时 184−8=176 字节加密，尾部 8 字节明文）；CBC 每包从 IV 重启（随机访问要求）；
  - 信令：`scrambling_descriptor` mode `0x10` = DVB-CISSA v1。
- **可得性**：PyPI/GitHub 无独立 CISSA 库包（两轮检索）；算法本身完全公开（TS 103 127 免费下载），自研面 = 每 TS 包一次 AES-CBC 调用 + 长度裁剪，**<100 行 Python**。GPL-3.0 参考实现 `xplus2/dvbipitools` 的 `src/lib/scrambler/cissa.c`（105 行 C，OpenSSL EVP）证实了实现难度，其固定 IV/每包重启语义与规范原文一致。

### 2.4 参考实现交叉印证（只用作公式核对，不入仓库）

| 实现 | 用途 | 结论 |
|---|---|---|
| `dizzdizzy/HiOSCAM` `oscam-chk.c` `set_cw_checksum` | CSA CW checksum = `(b0+b1+b2)&0xff`（oscam 系大规模部署验证） | 与 dvbipitools、DVBStreamer5 一致 |
| `xplus2/dvbipitools` `biss1e.c`/`hex.c` | Tech 3292 rev.2 Mode E 全流程（DES 去奇偶、P() 旋转、checksum 填充） | 与 J.96 逐 bit 定义一致 |
| `Monkipnet/DVBStreamer5` `Biss1Key.h` | 12-hex → CW 派生 + 16-hex 校验 | 与上两者一致 |
| `glenvt18/libdvbcsa` | CSA1 核心 + 自带静态测试向量 | 作为本次实测对拍基准 |

（注：以上均为 GPL 系，**只作可得性与公式核对证据，不复制代码入仓库**；沙箱 `refs\` 留档原始文件。）

---

## 3. 实测一：libdvbcsa ctypes 绑定（含测试向量对拍）

### 3.1 环境

| 项 | 值 |
|---|---|
| CPU | AMD Ryzen 9 5900X（12C/24T），单线程 |
| Python | 3.14.3 原生 Windows（`python -I`） |
| 编译器 | MSYS2 mingw64 gcc 16.1.0（Git Bash 内直接调用 gcc 会静默 exit=1，必须经 `msys64/usr/bin/bash.exe -lc`） |
| 绑定方式 | ctypes `CDLL`，无第三方依赖 |

### 3.2 向量对拍

libdvbcsa 自带 2 组静态测试向量（`test/testdec.c`，CW×加密 payload×明文 184 B 三元组，程序化提取避免手抄）。ctypes 绑定（`DVBCSA_BUILD\libdvbcsa.dll` / `libdvbcsa_bs.dll`）对每组向量做三项检查：

- `dvbcsa_encrypt(plain) == scrambled`
- `dvbcsa_decrypt(scrambled) == plain`
- 同 buffer roundtrip 一致性

**结果：2/2 组 × 3 项全 PASS**（generic 与 bs DLL 各自独立验证）。

### 3.3 吞吐实测（184 B payload/包，3 轮取代表值）

| API | 吞吐（包/s） | 等效 Mbps | 对 100 Mbps envelope（66,489 包/s） |
|---|---:|---:|---|
| `dvbcsa_encrypt` 单包 API（每包 1 次 ctypes 调用） | ~70,600 | **~104** | 1.06×，贴线 |
| `dvbcsa_bs_encrypt` 批量 API（SSE2，batch=128 包/次，含 Python 侧每批构建 129 项结构数组的开销） | ~335,000 | **~497** | **7.5×**（纯库内部更高） |

判定：**批量 API 是唯一推荐接入面**——单包 API 在 100 Mbps 满负载下无余量（且 Python 侧还有解复用/打包开销），批量 API 的余量足以覆盖 MVP 全 envelope（1~100 Mbps）。批量用法要点：batch 以 `{data,len}` 数组 + NULL 终止项传入，`maxlen` 须为 8 的倍数（TS 184 天然满足）；每批 ≤ `dvbcsa_bs_batch_size()`（SSE2 构建 = 128）包。

### 3.4 端到端最小验证（BISS1 Mode 1 全链路）

```
SW=A13DBC42908F (J.96 示例) → CW=A13DBC9A42908F61（checksum 派生）
→ libdvbcsa.dll dvbcsa_key_set + dvbcsa_encrypt(184B TS 包)
→ dvbcsa_decrypt → roundtrip True；scrambled[4:12]=3dd1438a6126c398
```

---

## 4. 实测二：纯 Python CSA1 基准

### 4.1 方法

为回答"纯 Python 是否够用"，写了一个忠实移植 libdvbcsa 单包路径的纯 Python 原型（`csa_pure.py` + 自动从 C 源提取的表文件 `csa_tables.py`：block sbox/perm 256×2、stream sbox 7×32、cdef 0x400、key schedule kperm 8×256 u64）：

- key schedule（7 次 64-bit 置换 + 56 轮 key 展开）
- block cipher 56 轮（enc/dec 两个方向）
- stream cipher（A/B 64-bit 寄存器、pqzyx/cfed、sboxes/cfed 表、每字节 4 轮）
- CBC 式链（encrypt 反向链 `X_k = enc(E_k ^ X_{k+1})`；decrypt 前块 ^= 后块再解）

调试过程留档（3 个 port 陷阱，值得进 #109 的实现提示）：
1. key permute 子表输出**已含目标位布局**，不得再移位；
2. A/B 寄存器 `<<=4` 必须 mask 64-bit（C 的 uint64 自然截断，Python 不会）；
3. 全包链中 `data[8:]` 切片是**拷贝**，原地 XOR 必须传索引；decrypt 链方向是"前块 ^= 后块（未解）"而非相反。

### 4.2 结果

- 向量对拍：**PASS（2 enc + 2 dec，与 libdvbcsa 同一组向量）**
- 吞吐：**207 包/s ≈ 0.305 Mbps**（4.8 ms/包）

| 指标 | 值 | 判定 |
|---|---|---|
| vs 100 Mbps envelope | 66,489 ÷ 207 ≈ **321 倍差距** | 不可用 |
| 100 万包 preset（188 MB）加扰耗时 | **~1.3 h** | 不可用 |

结论：纯 Python CSA1 只可作**参考实现/小样本一致性对拍**（这正是本次实测的用途），**不能作为 BISS1 主路径**。

---

## 5. 实测三：DES / AES（pycryptodome）与 CISSA

### 5.1 pycryptodome（4.5.0，本机 pip 安装成功）

- `DES.MODE_ECB` 单块 roundtrip **OK**（覆盖 BISS1 Mode E 的 `f⁻¹()`）
- `AES-128.MODE_ECB` roundtrip **OK**（覆盖 BISS2 Mode E ESW 解密）
- `AES-128.MODE_CBC`（iv=固定 IV，176 B payload）roundtrip **OK**，且与逐块手工链逐字节一致（CISSA 语义验证）

### 5.2 CISSA 吞吐（纯 Python，pycryptodome）

| 实现方式 | 吞吐 | 判定 |
|---|---:|---|
| 逐块手工 CBC 链（11 次 ECB/包，54 µs/包） | 18.6k 包/s ≈ 27.4 Mbps | 低于 envelope |
| **`AES.new(key, MODE_CBC, iv=IV).encrypt(payload)`（C 实现，11.0 µs/包）** | **91.1k 包/s ≈ 134.1 Mbps** | **1.4× 余量，达标** |

结论：BISS2 Mode 1 的 TS 加扰用 pycryptodome `MODE_CBC` 每包一次调用即可在纯 Python 内达到 envelope 上限，**不需要为 CISSA 做任何原生绑定**（`encrypted_payload_size = payload − payload%16` 的尾部明文裁剪在调用前切片处理）。

### 5.3 Mode E 派生面（无性能压力，均为单块/一次性调用）

- BISS1 Mode E：DES-ECB ×1 + bit 重排 + P() —— 纯 Python 一次性函数
- BISS2 Mode E：AES-128-ECB ×1 —— pycryptodome 一行

---

## 6. 汇总：BISS Mode 1/Mode E 推荐实现路径

| 组件 | 推荐路径 | 需自研面 | 性能证据 |
|---|---|---|---|
| CSA1（BISS1 TS 加扰/解扰） | **ctypes 绑定自编译 libdvbcsa DLL**（batch API 优先） | DLL 构建/分发（MinGW 命令已验证）；TS 包循环 | 497 Mbps（7.5× 余量） |
| BISS1 SW→CW 派生 | 纯 Python 函数 | checksum 公式（§2.2，3 实现印证）；与 J.96 §8 对齐 | N/A（每 SW 一次） |
| BISS1 Mode E | pycryptodome DES-ECB | J.96 §9.3 逐 bit 映射/P() 实现 | N/A（每 ESW 一次） |
| CISSA（BISS2 TS 加扰） | **纯 Python pycryptodome AES-CBC** | 每包加密长度裁剪 + 尾部明文规则 | 134 Mbps（1.4× 余量） |
| BISS2 Mode E | pycryptodome AES-128-ECB | 无 | N/A |
| 拒绝项 | 纯 Python CSA1（321× 不足）；PyPI 绑定（不存在）；CLI 子进程（#109 裁：增加进程/序列化开销且 DLL 已验证可用） | — | §4.2 |

BISS-CA（Mode CA，RSA-2048+ESK/EMM）超出 MVP envelope，留证：Tech 3292-s1 已下载，MVP 不实现。

## 7. 对下游细裁票 #109 的输入建议

1. **组件形态**：双轨——CSA1 走 ctypes 绑定（构建配方 §3.1 已验证，CI 可在 MinGW 镜像复现；DLL 属构建产物不入库，可入 release 工件或 CI 期编译）；CISSA/DES/AES 走纯 Python pycryptodome。建议统一在一个 `descrambler/scrambler` 组件内以"算法后端"接口隔离（`scramble(packet, cw) / descramble(packet, cw)`），后端选择由加扰算法标识（BISS1→CSA1 后端；BISS2→CISSA 后端）决定。
2. **管线接入位置**：BISS 是**整流传输级加扰**（TSC bit 置位 + payload 加扰），不属于 ADR-0007 语义替换过滤器范畴；建议新增传输级组件（scrambler/descrambler stage），放在包生成/注入之后、写出之前（或分析路径的入口解扰），与 tee 双写骨架正交。
3. **密钥配置面（wire 形状建议）**：
   - BISS1 Mode 1：`{algo: biss1, sw: 12-hex}`（存 SW，CW 运行时派生，**不落 16-hex CW**，避免 checksum 双写分歧）；
   - BISS1 Mode E：`{algo: biss1e, esw: 16-hex, id: 14-hex, id_type: injected|buried}`；
   - BISS2 Mode 1：`{algo: biss2, sw: 32-hex}`；BISS2 Mode E：`{algo: biss2e, esw: 32-hex, id: 32-hex}`；
   - 场景文档按上述形状携带；派生失败（checksum 不符/长度不符）应视为配置错误并显式报错（对拍实测：J.96 示例 SW 的派生值已留档可作回归锚点）。
4. **证据面（No fake evidence）**：加扰/解扰路径应输出 mutation log 事件（packet 数、算法、CW 指纹=SW 的 hash 而非明文）；对拍回归锚点：libdvbcsa 2 组向量（本文 §3.2）+ J.96 示例 SW→CW（§3.4）+ CISSA IV/176B 规则（§2.3）。纯 Python CSA1 原型可保留为测试夹具做 cross-check（慢但精确）。
5. **风险与边界**：单包 ctypes API 无余量（104 Mbps 贴线）——实现必须走 batch 路径；CT2 多 PID 大包量场景下 batch 划分按 PID 分 key 组（同 key 的包可合并 batch）；libdvbcsa 为 GPLv2+，**运行时动态加载（dlopen/CDLL）以避免与仓库许可证耦合**（dvbipitools 的 dlopen 模式可借鉴）。

## 8. 实测产物索引（仓库外沙箱，均可复现）

```
D:\Project\VibeCoding\dvb-external\
├── libdvbcsa\            # glenvt18/libdvbcsa 克隆（GPL-2.0+）
├── build\                # libdvbcsa.dll / libdvbcsa_bs.dll / 最小 config.h
├── scripts\              # 自写脚本（与本仓库同源纪律：UTF-8、python -I 运行）
│   ├── test_dvbcsa_ctypes.py + test_vectors.py   # 绑定向量对拍 + 吞吐
│   ├── csa_pure.py + csa_tables.py               # 纯 Python CSA 原型 + 基准
│   └── debug_dump*.c/exe                          # C/Python 分阶段对拍工具
├── standards\            # ITU-T J.96 / Tech 3292 v3 / Tech 3292-s1 / TS 103 127 原文+提取文本
└── refs\                 # oscam-chk.c / biss1e.c / cissa.c / Biss1Key.h 等（公式核对）
```
