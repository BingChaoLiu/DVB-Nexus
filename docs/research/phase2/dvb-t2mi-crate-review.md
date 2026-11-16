# dvb-t2mi Rust crate 成熟度复核（wayfinder #107）

- **日期**: 2026-11-16
- **对象**: crates.io [`dvb_t2mi`](https://crates.io/crates/dvb_t2mi)（`dvb-t2mi`，roadmap §5 记录 v14.0.0；本次复核发现最新为 **v15.0.0**）
- **上游仓库**: [fishloa/rust-broadcast](https://github.com/fishloa/rust-broadcast)（家族 monorepo，70+ 协议 crate 锁步发版）
- **调研方式**: 联网查 crates.io / GitHub API / PyPI / pypistats / docs.rs 一手数据 + 源码粗读（sparse clone）
- **前置文档**: [`docs/research/ecosystem-alternatives.md`](../ecosystem-alternatives.md) §4（2026-11-13 前后首查）
- **下游**: 细裁票 [#108](https://github.com/BingChaoLiu/DVB-Nexus/issues/108)（T2-MI 集成路径裁决）

所有数字与日期均为 2026-11-16 实查值，来源随条目标注。

---

## 1. 成熟度复核

### 1.1 crates.io（一手，crates.io API v1，2026-11-16）

| 指标 | 值 | 备注 |
| --- | --- | --- |
| 最新版本 | **15.0.0（2026-11-15 发布）** | 调研首查（2026-11-13 前后）记录的 v14.0.0 已过时；两天内连发 14.0.0 / 15.0.0 |
| crate 创建 | 2026-06-04 | 项目 5.5 个月大 |
| 版本总数 | 57 个（其中 2 个早期版本 yanked） | CHANGELOG.md 实际含 54 个版本小节，一致 |
| 总下载 | **1,768** | 上次调研 1,656 → 12 天 +112，低速线性增长 |
| 近 90 天下载 | **491** | 近期版本每版 20–50 下载：15.0.0=31、14.0.0=43、13.0.0=34、12.1.0=20、12.0.1=29、12.0.0=49 |
| 反向依赖 | **2**，且均为家族内部 crate：`dvb-tools` 15.0.0、`dvb-stream` 0.10.0 | **无任何第三方依赖者** |
| owner | 仅 `fishloa`（Alex Fishlock）一人 | 单人维护（bus factor 1） |
| 许可 | MIT OR Apache-2.0 | 无集成障碍 |

### 1.2 GitHub 仓库 fishloa/rust-broadcast（一手，GitHub API，2026-11-16）

| 指标 | 值 | 备注 |
| --- | --- | --- |
| stars / forks | **13 / 1** | 与上次调研持平，仍无社区增长 |
| issues | **1,464 closed / 1 open** | open 的是基础设施票（#2809 prepare-release.py 锁文件刷新）；issue 驱动开发密度极高 |
| 最后 push | **2026-11-16（今天）** | 2026-11-15 一天内 10+ commit（release wave：59 crates 锁步大版本） |
| 维护者 | 单人（Alex Fishlock），commit 稳定 | bus factor 1 不变 |
| repo 定位 | "Spec-grounded Rust crates for DVB and IP broadcast protocols … Cited to spec, round-trip tested, no_std capable" | 家族含 dvb-tools CLI、bindings/python（dvb-si-py、transmux-py） |

### 1.3 文档与工程质量（一手，源码粗读 + docs.rs）

- docs.rs `dvb-t2mi/15.0.0` 页面在线（HTTP 200）；manifest 配置 `all-features` docs.rs 构建；crate 顶部 `#![warn(missing_docs)]`，README 即 crate 根文档（`#![doc = include_str!("../README.md")]`）。
- README 质量突出：逐条引用规范版本与条款——**ETSI TS 102 773 V1.4.1**（§5.1 包头、§5.2.1–5.2.12 全部 12 种包类型、Annex A CRC-32）、**TS 101 191 V1.4.1**（§6.1 addressing functions）、**EN 302 755 V1.4.1**（§5.1、§7.2 L1-pre/post）。
- 配套：committed 实采 fixture（`fixtures/t2mi/colombia-capital-t2mi.ts`）、2 个 runnable examples、criterion bench（`t2mi_hot_paths`）、workspace 级 fuzz 目录、round-trip 测试（"payload views … each has Parse + Serialize and round-trip tests"）。
- **版本轮转极快（重要风险）**：5.5 个月 15 个 breaking major（1→15，锁步 epoch 发版）；`chrono → jiff` 的 breaking 迁移发生在 14.0.0（2026-11-14）；12.0.0→15.0.0 间隔 29 天内 4 个 major。作为**依赖**意味着每个 epoch wave 都要跟随迁移。

### 1.4 新事实：官方 PyO3 绑定已存在（上次调研称"尚无"）

- PyPI [`dvb-si-py`](https://pypi.org/project/dvb-si-py/) **0.4.0（2026-11-08 上传）**，PyO3 + maturin，abi3 wheel（CPython ≥3.9 一个 wheel 全平台）：
  - `dvb_si_py-0.4.0-cp39-abi3-win_amd64.whl`（Windows 可直接 `pip install`）
  - 另有 manylinux_2_34_x86_64 / macosx_11_0_arm64
- PyPI 下载量（pypistats.org）：近 30 天 **146**、近 7 天 38、昨日 3——同为极早期。
- **能力边界（源码 `bindings/python/src/lib.rs` 证实）**：`T2miDemux(pid)` 只是 `T2miPump::new` + `feed_ts` 的薄封装，返回 payload dict（camelCase 镜像 Rust API）。**只解析不构造**（README 明示 "read-only … does not build/serialize wire bytes"），且**没有** inner-TS 恢复、没有 PLP 过滤——`InnerTsRecovery` 未被绑定。

### 1.5 成熟度结论

| 维度 | 评价 |
| --- | --- |
| 工程质量 | **高**（spec 逐条引用、round-trip 测试、no_std、bench、fuzz、fixture） |
| 维护活跃度 | **高**（每日 commit，当天有 push） |
| 采用度 | **极低**（1.7k 总下载、13 stars、0 第三方依赖者、0.15k/月 PyPI） |
| 项目年龄/组织 | 单人、5.5 个月、无第三方生产背书 |
| API 稳定性 | **差**（5.5 个月 15 个 breaking major，锁步 epoch 强制迁移） |

与 TSDuck（BSD-2、1099 stars、十年级历史）不可同日而语；定位是"高质量个人参考实现"，不是"生产级依赖"。

---

## 2. API 面（源码粗读留证）

### 2.1 双向能力：解析 + 构造均完整

README 明示 "**Zero-copy, symmetric.** Payload views borrow the input; each has `Parse` + `Serialize` and round-trip tests"，描述行即 "parser + builder"。源码证实：

- `src/payload.rs` 及 `src/payload/{bbframe,any,fef_*,l1_current,individual_addressing,arbitrary_cells,registry}.rs` 全部实现 `Parse`/`Serialize`（trait 来自 `broadcast_common`，见 `src/traits.rs` 模块注释）。
- `packet::{Header, PacketType}`（6 字节头）、`crc::{validate_crc, CRC_LEN}`（CRC-32/MPEG-2，14.0.0 起 `broadcast_common::crc32_mpeg2`）。
- RFU 策略：payload 解析拒绝非零保留位（`Error::ReservedBits`）；序列化时 RFU 写 0——个体寻址(0x21)例外，保留首 RFU 字节原样 round-trip。
- 已知限制：HEM BBFrame 带 `MATYPE.NPD`（空包删除）时**跳过不解**（DNP 字节重建未建模），不会错解但会漏包。

### 2.2 解封装（parse）路径

| 层 | API | 覆盖度 |
| --- | --- | --- |
| TS 重装 | `pump::T2miPump::new(pid)` / `feed_ts(&[u8])` / `feed_raw`（裸 .t2mi 流） | PID 过滤、PUSI、adaptation field 跳过、TEI/CC 异常处理；仅产出 CRC 校验通过的完整 T2-MI 包，失败计入 `Stats::crc_failures` |
| 包类型 | `payload::AnyPayload`（`declare_payloads!` 生成 dispatch + drift 测试） | TS 102 773 Table 1 全部 **12 种**类型有类型化 struct（BBFrame 0x00、aux I/Q、arbitrary cells、L1-current/future、P2 bias、timestamp、individual addressing、FEF×4），未知类型落 `AnyPayload::Unknown` 保留原始字节 |
| L1 | `L1CurrentPayload::l1_pre()/l1_post()` | EN 302 755 §7.2 L1-pre/L1-post 全字段 + coded-value 枚举（GuardInterval、L1Modulation、PlpConfig/PlpDynamic 等） |
| 时间戳 | `T2TimestampPayload::emission_offset()`；`emission_time_utc()`（jiff feature） | Table 4 per-bandwidth T_sub 换算 |

### 2.3 BBFrame / inner-TS / PLP

- `inner_ts::InnerTsRecovery`：T2-MI PID → T2miPump → `AnyPayload::Bbframe` → `dvb-bbframe` BBHEADER（10 字节，NM/HEM）+ SYNCD carry-over → **inner TS 188 字节包**。三段管线合一调用。
- **PLP 支持完整**：carry-over 状态按 `plp_id` 分槽（256 槽位图，修复 issue #1034 的跨 PLP 混流 bug）；`new_for_plp(pid, plp_id)` 单 PLP 过滤；`plps_seen()` 列出见过的 PLP。多 PLP 无过滤时输出交织（各 PLP 是独立 TS）。
- **构造（builder）方向**：所有 payload `Serialize` 字节精确回写（round-trip 测试背书）；但**没有**"从 TS 出发构造 T2-MI 流"的复合 builder API——构造就是"组 payload struct → Serialize → 拼 6 字节头 + CRC"，调用方自行组流。CLI 与 Python 绑定均未暴露 builder。

### 2.4 现成 CLI（CLI 子进程路线的关键事实）

`dvb-tools t2mi <FILE> [--pid 0xNNN|raw] [--inner] [--plp N]`（`dvb-tools/src/t2mi.rs` 证实）：

- `--inner`：把恢复出的 inner TS（二进制 188 字节包流）写 stdout，可直接 `> inner.ts`；多 PLP 且未指定时**拒绝执行**并列出 PLP 清单（保守、防混流）。
- 一次性 file→stdout 设计；统计打在 stderr（`ts_packets/t2mi_packets/crc_failures/malformed/filtered_bbframes`）。
- **CLI 不暴露 builder 方向**（只有解析/提取）。

---

## 3. 集成路径评估

### 3.1 三路线对比

| 维度 | A. PyO3 薄绑定 | B. CLI 子进程（dvb-tools） | C. 不采用（自研 Python） |
| --- | --- | --- | --- |
| 需引入 Rust 工具链进 CI | 需要（自建绑定）或依赖上游 wheel（dvb-si-py abi3 win_amd64 现成） | 不进 CI，但需构建/分发二进制（本地有 cargo 1.97.1，Windows MSVC 面无碍） | 不需要 |
| 覆盖能力 | dvb-si-py：仅解析（无 inner-TS/PLP/builder）；自建绑定成本 = 绑定层 + 每 epoch 跟迁 | 仅解析/提取方向（`--inner` 二进制 stdout），**无 builder**，一次性 file→stdout | 完全自主：解析/构造/管线内嵌入均按需实现 |
| API 稳定性风险 | 高：上游 5.5 个月 15 个 breaking major，每个 epoch wave 需重绑/升级 | 中：二进制可钉版本，但输出/参数随上游漂移 | 无外部风险 |
| 采纳风险 | bus factor 1 + 零第三方背书（§1.5） | 同左（且 dvb-tools 是 workspace 90+ crate 的成员，构建闭包大） | 无 |
| 与沙盘契合 | Python 侧拿到 dict，但仿真管线（Generator→sink）需要流式构造——绑定为 read-only，**不满足** | 进程边界 + 文件级一次性，不适合在线管线 | 纯函数 Python，天然匹配确定性复现与字段级教学（ADR-0007 不变式可控） |
| 成本量级（估算，非实测） | dvb-si-py 零成本（pip install）但能力不够；自建绑定 ≈ 数百行 Rust + CI 矩阵 | 集成代码≈0，但每次调用进程开销 + 输出解析 | T2-MI 包帧（6B 头+CRC-32/MPEG-2+单 PID 重装）≈ 数百行；BBHEADER(NM/HEM/SYNCD carry-over) ≈ 数百行；builder（组头+payload+CRC）同量级 |

### 3.2 逐路线裁决要点

- **PyO3（A）不推荐**：现成 `dvb-si-py` 覆盖不了沙盘需要的能力（inner-TS 恢复/PLP/builder 均缺）；自建则要 Rust 进 CI + Windows wheel 矩阵，还要扛上游 epoch 迁移——为"本就简单"的协议付出不成比例的持续成本。
- **CLI 子进程（B）只配作开发期 oracle**：`dvb-tools t2mi --inner` 是理想的交叉验证器（二进制 stdout 可逐字节 diff），但它单向（无 builder）、进程式、文件级——**不适合作为 Phase 2 仿真管线的运行时组件**。
- **自研 Python（C）成本本就低且契合度高**：T2-MI 包结构简单（6 字节头 + CRC-32，BBHEADER 10 字节）；协议细节（RFU 策略、NPD 跳过、per-PLP carry-over）上游源码+文档把坑都写明了，可作为实现规格的参考书；builder 方向全生态唯此一家（TSDuck/FFmpeg/DVBInspector 都只有解析），自研 Python 是唯一能满足"确定性生成 + 字段级注入"的路。

---

## 4. 结论

**该 crate 质量高但不宜纳入 Phase 2 运行时依赖。** 理由：

1. **解封装方向** roadmap §5 已有三套现成方案（TSDuck `t2mi` 插件本机 3.40 实测含、FFmpeg 7.1 demuxer、DVBInspector PLP 导出），crate 的解析能力在沙盘里没有不可替代性；#108 的解封装落位裁决不受本票影响。
2. **封装（builder）方向**：crate 全生态独一份，但其价值在"参考实现"而非"依赖"——协议简单到自研 Python 成本低（§3.1 C 行），而 crate 作为依赖的风险（单人维护、零第三方依赖者、15 majors/5.5 个月的锁步 epoch）与收益不成比例。
3. **定位建议**：**开发期参考 + 交叉验证 oracle**。本地 `cargo build -p dvb-tools` 得 CLI 二进制，用 `dvb-tools t2mi --inner`（及 fixture `colombia-capital-t2mi.ts` 的期望输出）对自研 Python 解封装做 golden 逐字节 diff；builder 侧以其 round-trip 测试思路（Serialize 字节精确回写 + RFU 策略）作实现对照。不进 CI、不进运行时依赖、不进 Windows 构建面。

### 对 #108（T2-MI 集成路径细裁）的输入建议

1. 解封装落位：维持 roadmap 三方案对比（TSDuck/FFmpeg/自研）原格局裁决；dvb_t2mi crate 不改变该格局，仅可作 oracle。
2. builder 落位：**维持"自研 Python"默认裁决**，无需因 crate 存在而改道 Rust；自研实现可直接对标 crate 的 RFU 策略与个体寻址例外（§2.1）保证 wire 兼容。
3. 若 #108 仍想走 Rust 路线（不建议）：优先级应为 `pip install dvb-si-py`（零构建成本、abi3 win_amd64 wheel 现成，接受 parse-only 限制）> CLI 子进程 > PyO3 自建绑定。
4. 仿真管线接入：dvb-tools 为 file→stdout 一次性工具，不支持 Generator→sink 在线管线——支持"自研 Python 在管线内"的裁决。
5. 保真档位：若 Phase 2 维持 SIM_TS 全程，T2-MI 层本就是仿真子图边缘（TSDuck 侧 t2mi 插件/FFmpeg demuxer 已够），进一步降低 crate 引入必要性。

---

## 附：证据清单

| 证据 | 来源 | 查证时间 |
| --- | --- | --- |
| crates.io 元数据/版本表/反向依赖（dvb-tools、dvb-stream，均家族内）/owner | crates.io API v1（`/crates/dvb_t2mi`、`/versions`、`/reverse_dependencies`、`/owners`） | 2026-11-16 |
| stars/issues/最后 push/commit 内容 | GitHub API（`repos/fishloa/rust-broadcast`、`/commits`、issues 列表/计数） | 2026-11-16 |
| README（能力矩阵/feature 表/round-trip 声明） | 仓库 `dvb-t2mi/README.md`（gh api contents，sparse clone 粗读） | 2026-11-16 |
| pump/inner_ts/builder/RFU/NPD 细节 | `dvb-t2mi/src/{lib,pump,inner_ts,payload.rs,payload/*}.rs`、CHANGELOG 54 小节 | 2026-11-16 |
| CLI 能力与边界 | `dvb-tools/src/{main,t2mi}.rs`（--inner stdout 二进制、PLP 拒绝逻辑） | 2026-11-16 |
| Python 绑定能力边界 | `bindings/python/{README.md,src/lib.rs,pyproject.toml}`（T2miDemux 薄封装、read-only） | 2026-11-16 |
| PyPI wheel 矩阵/上传日期 | PyPI JSON API `/pypi/dvb-si-py/json`；下载量 pypistats.org API | 2026-11-16 |
| docs.rs 在线 | docs.rs `/crate/dvb-t2mi/15.0.0` HTTP 200 | 2026-11-16 |
| 本机 cargo | cargo 1.97.1（`cargo --version`） | 2026-11-16 |

*未实测项：三路线均未在本机做完整构建/运行 benchmark（本票以调研为主，按票面要求不构建集成）；估算行数为规模量级判断，非测量值。*
