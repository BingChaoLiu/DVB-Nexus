# OPEN-006 调研报告：Python 性能可行性 —— CBR 生成吞吐评估

- **Issue**: BingChaoLiu/DVB-Nexus #5（OPEN-006）
- **日期**: 2026-11-14
- **性质**: 调研 + 本机基准实测（未修改任何 issue / 未做 git 操作 / 未改动仓库代码）
- **脚本**: `D:\Document\Project\DVB-Nexus\.scratch\research\python-ts-bench\bench.py`（stdlib-only，可丢弃不入库）
- **原始数据**: 同目录 `results.json`

---

## 1. 结论摘要（TL;DR）

1. **纯 Python 完全满足 MVP 目标，余量约 164 倍。** 端到端实测（packet-slot 调度 + 188B 序列化 + 顺序写盘）达到 **2.19M 包/s ≈ 3.29 Gbps 等效吞吐**（单核）。20 Mbps CBR 实时只需 13,298 包/s，占用约 **0.6% 单核预算**。
2. **离线生成 100 万包（188 MB）预估 0.5~4 s**（简化管线实测外推 0.46 s；含对象模型/PES/PCR 的完整管线预估 1~4 s）。建议验收上限定 10 s，余量 ≥ 2.5 倍。
3. **瓶颈在 Python 对象构造，不在 IO。** frozen dataclass 构造 ~1046 ns/包，是序列化（166~257 ns）与调度决策（136 ns）的 4~8 倍；写盘 967 MB/s 完全不构成约束。
4. **不需要 Cython / Rust(PyO3) / C++ 子进程迁移**。三条路径的成本对比见 §6，并给出未来触发评估的显式条件，防止过早优化。
5. **勘误**：issue 中"15~20 Mbps ≈ 1370 packets/s"换算有误。188 B = 1504 bit，正确值为 **9,974 ~ 13,298 包/s**（1370 包/s 只对应 ~2.06 Mbps）。本报告按更严苛的 13,298 包/s 评估。
6. **定档建议**见 §7：MVP 按"离线生成 + 分析"批处理定档，不承诺实时；建议冻结码率范围 1~100 Mbps、默认 preset 100 万包（188 MB）、单文件硬上限 200 万包（376 MB）、生成耗时上限 10 s。

---

## 2. 目标工作负载（依据 SPEC）

| SPEC | 对本次基准的约束 |
|---|---|
| **SPEC-100（ts-packet）** | `TSPacket` 为 frozen dataclass，8 个字段（pid / cc / payload / adaptation_field / tei / pusi / priority / tsc）；`to_bytes()` 输出恰好 188 B；CCAllocator 按 PID 独立维护状态（仅 payload 包推进计数） |
| **SPEC-107（ts-mux）** | packet-slot 调度：slot 时基必须整数化（`slot_time(n) = floor(n × 1504 × 27e6 / B)`，禁止 float 累加）；每个 slot 恰好输出 1 个 188 B 包；无到期候选时填 Null Packet（PID 0x1FFF、payload 0xFF、CC 固定 0）；**"CBR 是媒体时间调度定义，不要求 Generator 在真实墙钟上实时发送"** |
| **SPEC-108（ts-generator）** | `generate_to(config, sink)` 迭代输出恰好 `output_packet_count` 个包，每次 `sink.write` 恰好 188 B；`analysis_only` profile（合成 payload，不承诺可播放）；确定性 seed；返回 GenerationSummary |

本次基准采用的典型 MVP 负载：16 Mbps CBR（video 12 Mbps + audio 1.5 Mbps + PAT/PMT 各 100 ms + PCR 40 ms + Null 填充），多 PID Bresenham 整数相位累加（与 SPEC-107 的整数时基要求等价）。

---

## 3. 测试环境与方法

| 项 | 值 |
|---|---|
| CPU | **AMD Ryzen 9 5900X**（Zen 3，12C/24T，基频 3.7 GHz）；单线程运行 |
| 内存 | 32 GB |
| OS | Windows 11（win32 10.0.26200）/ Git Bash |
| Python | **3.10.11**（tags/v3.10.11, MSC v.1929, 64 bit, AMD64，Windows Store 版），以 `python -I` 运行 |
| 磁盘 | 三块盘并存；基准数据写入项目所在盘（Samsung SSD 980 500GB，**NVMe**） |
| 计时 | `time.perf_counter()`，每组 3 次取 best/median，GC 保持开启（另测 GC-off 变体） |

**简化声明（不影响量级结论）**：调度用 Bresenham 整数累加（等价 SPEC-107 slot_time 公式）；AF 只实现 PCR 路径；PES/PSI payload 用预合成常量 bytes；未实现 deadline-miss / tie-break / 过载分支。这些简化去掉的都是低频路径（表包占比 <0.5%）或只会让真实管线更慢的分支——量级判断成立。

---

## 4. 实测数据

### (a) dataclass 构造速率（100 万个 TS 包对象）

| 变体 | best | median | 吞吐（包/s） | ns/包 | 内存/对象 |
|---|---:|---:|---:|---:|---:|
| **frozen dataclass（SPEC-100 模型，位置参数）** | 1.046 s | 1.065 s | 0.96 M | **1046** | 192 B |
| frozen dataclass + 关键字参数 | 1.170 s | 1.179 s | 0.85 M | 1170 | — |
| 普通（非 frozen）dataclass | 0.628 s | 0.666 s | 1.59 M | 628 | 192 B |
| frozen + `slots=True` | 0.943 s | 0.955 s | 1.06 M | 943 | **96 B** |
| tuple（8 元组） | 0.172 s | 0.186 s | 5.82 M | 172 | 104 B |
| frozen dataclass + GC 关闭 | 0.805 s | 0.833 s | 1.24 M | 805 | — |

要点：GC 开启贡献约 **23%** 开销（1M 次分配触发大量 gen0 回收）；`slots=True` 内存减半但几乎不提速（省内存为主）；关键字参数比位置参数慢 ~12%。100 万 frozen 对象全量保留需 ~192 MB（SPEC-108 的 Iterator 设计本就不保留，实际无此压力）。

### (b) bytes 级序列化速率（header 4B 编码 + 184B payload → 188 B）

| 变体 | best | median | 吞吐（包/s） | ns/包 | 折算 GB/s |
|---|---:|---:|---:|---:|---:|
| `struct.pack(">BBBB")` + payload 拼接 | 0.249 s | 0.250 s | 4.02 M | 249 | 0.76 |
| `bytes((b0,b1,b2,b3))` + payload 拼接 | 0.257 s | 0.258 s | 3.89 M | 257 | 0.73 |
| bytearray 模板拷贝 + `bytes(buf)` | 0.166 s | 0.166 s | 6.03 M | 166 | 1.13 |
| bytearray 复用、无最终拷贝 | 0.056 s | 0.056 s | **18.0 M** | 56 | 3.38 |

要点：两种"正统"写法（struct / bytes 元组）在 4% 以内，~250 ns/包；模板/缓冲复用可再省 35%~78%（复用缓冲仅在 sink 立即消费时安全，如 `f.write(buf)`）。

### (c) 顺序写文件速率（100 万包 = 188 MB，188-byte 包流）

| 变体 | best | median | 吞吐（包/s） | 折算 MB/s |
|---|---:|---:|---:|---:|
| 每包 `f.write(188B)`（默认 8 KB 缓冲，SPEC-108 语义） | 0.194 s | 0.224 s | 5.14 M | **967** |
| 96 KB 块写 + 1 MB 缓冲（上限参考） | 0.051 s | 0.053 s | 19.8 M | 3723 |

注：数字含 OS write-back cache；NVMe 980 持续写约 1.3~1.7 GB/s，188 MB 级突发可全速吸收，此结论不受 cache 影响。**20 Mbps 实时只需 2.5 MB/s 写盘，离线一次性写出也远在盘速之下——IO 永远不是瓶颈。**

### (d) packet-slot 调度端到端速率（50 万 slot = 94 MB）

负载：16 Mbps CBR，video 12M / audio 1.5M / PAT·PMT 各 100ms / PCR 40ms（挂 video AF 包）/ Null 填充；整数 Bresenham 相位累加 + 按 PID 确定性优先轮转。

| 变体 | best | median | 吞吐（slot/s） | ns/slot |
|---|---:|---:|---:|---:|
| 仅调度决策（相位累加 + 表周期 + null 判定 + CC 状态） | 0.068 s | 0.068 s | 7.36 M | **136** |
| **端到端**（决策 + 头编码 + 188B 序列化 + `sink.write`） | 0.229 s | 0.232 s | **2.19 M** | **457** |

分布自检（与理论配比一致，验证调度逻辑正确性）：video 74.4%（另有 PCR 包 ~0.24%）、audio 9.4%、PAT/PMT ~0.19%、null 15.8%；文件 94,000,000 B = 500,000 × 188 ✓。

---

## 5. 外推结论

### 5.1 需求换算（含 issue 勘误）

- 1 个 TS 包 = 188 B = **1504 bit**。
- 15 Mbps CBR → **9,974 包/s**（slot 预算 100.3 µs）；20 Mbps → **13,298 包/s**（slot 预算 75.2 µs）。
- issue 中的"≈1370 packets/s" = 1370 × 1504 ≈ **2.06 Mbps**，低估约 10 倍；疑为换算笔误。下文按正确的 13,298 包/s（更严苛口径）评估。

### 5.2 15~20 Mbps"实时"是否轻松？

**轻松，且实际上根本不是实时需求。** 端到端实测 457 ns/slot，20 Mbps 的 slot 预算是 75,200 ns → 占 **0.61% 单核**，余量 **~164×**；15 Mbps 余量 ~219×。即使完整 SPEC 管线（PES framing、AF 对象、逐包校验、表 CRC32）把每包成本放大 5~10 倍，占用仍 ≤ 6% 单核。且 SPEC-107 §3.2 明确 CBR 是媒体时间调度定义、不要求墙钟实时发送——实时性在 MVP 中是伪需求。

### 5.3 离线 100 万包 / 188 MB 耗时预估

| 路径 | 预估耗时 |
|---|---:|
| 简化管线（调度 + 序列化 + 写盘，不物化对象）——实测直接外推 | **~0.5 s** |
| 加每包物化 frozen `TSPacket`（Iterator 模式，不保留） | ~1.5 s |
| 完整 SPEC 管线（PES framing、AF 对象、PCR 编码、逐包校验）预估（×3~8 衰减） | **1~4 s** |
| 追加 SHA-256（188 MB，SHA-NI 加速） | +0.1~0.4 s |
| **建议验收上限** | **≤ 10 s**（余量 ≥ 2.5×） |

内存：frozen 对象 192 B/包，即使临时物化 100 万包峰值也仅 ~192 MB；`generate_to()` 按 Iterator 逐包消费则峰值更小。**无内存风险。**

### 5.4 瓶颈定位（每包成本排序）

```
对象构造(frozen) 1046 ns  >>  序列化 166~257 ns  >  写盘 ~194 ns  >  调度决策 136 ns
```

- **热点 1 = dataclass 构造**（frozen 的 `__setattr__` 拦截是主因）。免费缓解：热路径用位置参数（-12%）；`generate_to()` 期间 `gc.disable()`（-23%；TS 包对象由 int/bytes 组成、无引用环，安全）；需要省内存时用 `slots=True`（-50% 内存，-10% 时间）。
- **热点 2 = 序列化拼接** → bytearray 模板/缓冲复用（-35%~-70%），仅在 sink 立即消费时使用。
- **IO 不是瓶颈**（967 MB/s vs 20 Mbps 实时所需的 2.5 MB/s）。
- 结论：**没有需要 C 扩展才能解决的环节**；上述纯 Python 缓解已覆盖全部热点。

### 5.5 能力换算参考

- 2.19M 包/s ≈ **3.29 Gbps 等效生成能力**（单核、含写盘）。
- 完整管线按 5× 衰减 → ~0.44M 包/s ≈ **655 Mbps 等效**，仍远超 MVP 1~100 Mbps 冻结范围 6 倍以上。

---

## 6. 热点迁移路径评估（仅评估，不实现）

**结论先行：按当前实测（164× 余量），三条路径在 MVP 阶段都不应启动。** 以下对比仅供未来触发条件成立时参考。

| 维度 | Cython | Rust (PyO3) | C++ 子进程 |
|---|---|---|---|
| 预期收益 | 调度+序列化热循环 10~50×，逼近内存带宽 | 同级；批量 buffer API 下最稳、上限最高 | 无 FFI 边界，吞吐上限最高 |
| 开发量 | 1~3 天 spike（cdef 循环 + typed memoryview） | 3~5 天（学习曲线 + maturin/wheel 链） | 3~5 天（CMake + MSVC、配置 JSON→TS 文件 IPC、摘要/SHA 回传协议） |
| 构建链负担 | 每台开发机/CI 需 MSVC 或 MinGW；需发布预编译 wheel | 需 Rust 工具链；maturin 打包较顺 | C++ 工具链；Python 侧只剩进程管理 |
| 集成形态 | import 扩展模块，Python API 不变 | import 扩展模块；**必须设计批量 API**（如 `encode_slots(n0, n1) -> bytes`），逐包跨 FFI 会吃掉 ~80% 收益 | 双进程：Python 只写配置、读摘要 + SHA-256；与"离线生成"架构天然契合 |
| 确定性风险 | 低（语义同 Python 实现） | 低 | **中**（双实现配置校验易漂移，版本对齐是长期负担） |
| 调试/维护 | 中（C/Python 混合栈，符号调试麻烦） | 中（ABI 安全，但依赖团队 Rust 经验） | 低-中（边界清晰，排障跨语言） |
| 何时才值得 | 完整管线实测 > 30 s/百万包 且 profiler 确认热点在 Python 层 | 同左，且团队确定长期投入 Rust | 需要 Python 之外的运行形态（独立 CLI、CI 大批量流水）时 |

迁移触发条件（建议写进 Performance Spec）：**完整管线实测 100 万包 > 30 s（验收上限 10 s 的 3 倍）且 profiler 证明热点在 Python 层** → 再启动 §6 评估。当前数据表明该条件距离成立有 10 倍以上距离。

---

## 7. OPEN-006 定档建议（MVP 性能目标）

**定位校准**：MVP = 离线生成 + 分析（`analysis_only`），生成是批量作业而非实时流处理；SPEC-107 明确不要求墙钟实时发送。**按"离线批处理"定档，防止过度工程。**

| 项 | 建议值 | 依据 |
|---|---|---|
| MVP 支持码率范围（配置校验冻结） | **1 ~ 100 Mbps** | SPEC-108 §5 将范围留给 Performance Spec；实测等效能力 3.29 Gbps，对 100 Mbps 余量 ≥ 30×；覆盖常见 DVB-S/S2 TS 速率 |
| 默认生成 preset | **1,000,000 包 = 188 MB**（16 Mbps ≈ 94 s 媒体时长） | 与本次基准同口径；体量对自研 parser 与 TSDuck 分析都友好 |
| 单 artifact 硬上限 | **2,000,000 包 = 376 MB**（20 Mbps ≈ 150 s 媒体时长） | 满足"分钟级样本"分析需求，同时防止 UI 误配超大任务 |
| 生成耗时验收上限 | **188 MB / 100 万包 ≤ 10 s（目标 ≤ 3 s），含 SHA-256** | 实测简化管线 0.5 s、完整管线预估 1~4 s，留 ≥ 2.5× 余量 |
| 生成进程内存上限 | 峰值 ≤ 512 MB | Iterator 模式不保留全量对象；即便物化也有余 |
| 实时承诺 | **MVP 不承诺实时输出/低延迟**。若未来需要"近实时生成预览"，按 ≥ 50 Mbps 等效（33,300 包/s）设定即可，实测余量 ~66× | 该需求在 MVP 中不存在 |
| 明确不做（防过度工程） | 实时流式输出 / RT 时钟同步、多线程/多进程生成、C 扩展、> 376 MB 单文件 | 见 §5/§6 |

**测试与验收写法建议**：

1. CI 不做绝对墙钟断言（跨机器 flaky）：功能测试只验正确性；性能用宽松 smoke 阈值（如 100 万包 ≤ 60 s）防数量级回归。
2. 正式性能验收在本机按 bench.py 口径复测记录（命令见 §8），数据写入 IMPLEMENTATION_REPORT。
3. 把 §6 末尾的"迁移触发条件"写成显式条款，避免未来凭直觉引入原生扩展。

---

## 8. 附录：复现方法与局限性

**复现**（Git Bash，Windows）：

```bash
python -I "D:/Document/Project/DVB-Nexus/.scratch/research/python-ts-bench/bench.py" --quick   # ~5s 冒烟
python -I "D:/Document/Project/DVB-Nexus/.scratch/research/python-ts-bench/bench.py"           # 全量 ~30s
# 输出: 同目录 results.json；benchdata/*.bin 用后自动删除
```

**局限性**：

1. (c)(d) 写盘数字含 OS write-back cache；持续盘速 ~1.3-1.7 GB/s 不改变结论。
2. 调度为 Bresenham 简化，未覆盖 SPEC-107 的 deadline-miss、tie-break、过载拒绝等低频分支。
3. PES/PSI/AF 内容为预合成常量；真实管线含 PES 头、CRC32（仅表包）与逐包校验，已在 §5.3 按 3~8× 衰减预估。
4. 桌面环境未绑核，存在 ±10% 噪声；每组 3 次 best/median 已覆盖。
5. 本机为 Python 3.10.11；3.11+ 一般再快 10~25%、3.12+ 对 dataclass/对象模型有持续优化——可作为免费提速项，但**不是 MVP 必要项**（当前余量下无实质收益）。
