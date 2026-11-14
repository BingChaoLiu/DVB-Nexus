---
spec_id: SPEC-108
title: Deterministic MPEG-TS Generator
version: 0.5.0
status: APPROVED
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-100, SPEC-101, SPEC-102, SPEC-103, SPEC-104, SPEC-105, SPEC-106, SPEC-107, SPEC-004]
requirements: [REQ-TS-108-001, REQ-TS-108-002, REQ-TS-108-003, REQ-TS-108-004, REQ-TS-108-005, REQ-TS-108-006, REQ-TS-108-007, REQ-TS-108-008]
---

# SPEC-108 — TS Generator

## 1. 目标

提供配置驱动、确定性、可测试的 TS 生成入口，将节目/码率/时钟配置转换为 188-byte MPEG-2 TS Packet 序列。Generator 只生成正常基线码流；故障注入由 SPEC-204 在生成结果之后执行。

## 2. MVP Profile

唯一必需 Profile：`analysis_only`。

该 Profile 保证 TS Packet / PAT / PMT / PES framing / PCR 等已实现结构可解析和分析，但不承诺 Elementary Stream payload 是可解码的真实音视频。因此：

- PMT stream_type 的声明必须与配置一致；
- 允许使用确定性合成测试 payload；
- UI/报告必须标记 `payload_profile=synthetic_test_data`；
- 不得声称“播放器可播放”或“生成真实 H.264/AAC”；
- `playback_ready` 是未来能力，本 Spec 不实现。

## 3. 范围

**In Scope：** typed GeneratorConfig；单 Program MVP；PAT/PMT；一个或多个 ES PID；PES 测试数据；PCR；CBR Mux；固定 packet_count 输出；确定性 seed；生成摘要。  
**Out of Scope：** Fault Injection；真实编码器；DVB SI 全套；T2MI/BISS；Live DVB；Artifact 文件管理和数据库；播放验证。

## 4. 配置模型

```python
@dataclass(frozen=True)
class ElementaryStreamConfig:
    pid: int
    stream_type: int
    stream_id: int
    bitrate_bps: int
    payload_profile: str = "synthetic_test_data"
    payload_seed_offset: int = 0

@dataclass(frozen=True)
class ProgramConfig:
    transport_stream_id: int
    program_number: int
    pmt_pid: int
    pcr_pid: int
    version_number: int
    streams: tuple[ElementaryStreamConfig, ...]
    program_descriptors: bytes = b""

@dataclass(frozen=True)
class GeneratorConfig:
    schema_version: int
    profile: str  # only "analysis_only" in MVP
    deterministic: bool
    seed: int
    initial_media_clock_27mhz: int
    target_bitrate_bps: int
    output_packet_count: int
    program: ProgramConfig
    pat_period_ms: int = 100
    pmt_period_ms: int = 100
    pcr_interval_ms: int = 40
    pcr_insertion_policy: str = "payload_packet_first"
```

说明：Pydantic API DTO 在 API/Application 层做 JSON validation；`app.ts` 接收已验证的 typed config，不直接依赖 Pydantic。JSON 请求体与 `GeneratorConfig` 的字段级映射约定如下（JSON 字段名 snake_case；Pydantic DTO 权威定义在 SPEC-500 REST 契约）：

| JSON 字段 | GeneratorConfig 字段 | 约束 |
|---|---|---|
| `schema_version` | `schema_version` | int，受支持版本 |
| `profile` | `profile` | MVP 仅 `"analysis_only"` |
| `deterministic` | `deterministic` | bool，必须 true |
| `seed` | `seed` | int |
| `initial_media_clock_27mhz` | `initial_media_clock_27mhz` | int，非负 |
| `target_bitrate_bps` | `target_bitrate_bps` | int > 0 |
| `output_packet_count` | `output_packet_count` | int > 0 |
| `program.transport_stream_id` / `program_number` / `pmt_pid` / `pcr_pid` / `version_number` / `program_descriptors` | `ProgramConfig` 同名字段 | bytes 字段（`program_descriptors`）JSON 以 hex 编码 |
| `program.streams[]`（`pid` / `stream_type` / `stream_id` / `bitrate_bps` / `payload_profile` / `payload_seed_offset`） | `ElementaryStreamConfig` 同名字段 | 数组，元素字段 snake_case |
| `pat_period_ms` / `pmt_period_ms` / `pcr_interval_ms` | 同名字段 | int > 0 |
| `pcr_insertion_policy` | `pcr_insertion_policy` | 枚举，见 §5 |

## 5. 配置校验

- `schema_version` 必须受支持。
- `profile` MVP 仅允许 `analysis_only`。
- `output_packet_count > 0`。
- `target_bitrate_bps > 0`；推荐 MVP 最小配置可运行在 1 Mbps 以上，实际允许范围需在 Performance Spec 冻结。
- TSID、program_number、PID、stream_type、stream_id、bitrate 均按其字段位宽校验。
- PMT PID、ES PID、PCR PID 不得互相冲突或使用项目禁止的保留 PID；PCR_PID 可以复用一个 ES PID。
- `program_number != 0`。
- ES PID 在同一 Program 中唯一。
- 所有 ES `bitrate_bps` 与 PAT/PMT/PCR 等 overhead 必须能装入 target bitrate；无法装入则拒绝或在 Mux 可证明的范围内按策略产生 deadline miss，不得静默降低 ES 码率。
- `pat_period_ms`、`pmt_period_ms`、`pcr_interval_ms` 必须为正数。
- `pcr_insertion_policy` 只允许 `payload_packet_first` / `adaptation_only_fallback`（语义见 SPEC-107 §5.3）。
- `seed` 和 initial clock 必须进入生成指纹；不读取墙钟生成协议字段。

## 6. 公共接口

```python
@dataclass(frozen=True)
class GenerationSummary:
    packet_count: int
    byte_count: int
    target_bitrate_bps: int
    null_packet_count: int
    pcr_packet_indices: tuple[int, ...]
    pid_packet_counts: dict[int, int]
    generator_version: str

class TSGenerator:
    def validate_config(self, config: GeneratorConfig) -> list[ValidationIssue]: ...
    def iter_packets(self, config: GeneratorConfig) -> Iterator[TSPacket]: ...
    def generate_to(self, config: GeneratorConfig, sink) -> GenerationSummary: ...
```

`sink` 应是最小 `write(bytes)` Protocol/标准二进制写入对象，TS Core 不接收 Artifact 路径、不操作 SQLite。Application/Artifact Storage 将输出写到受控目录，并计算 SHA-256。

## 7. 生成流程

1. 校验 GeneratorConfig。
2. 构造 PAT 与 PMT Section（SPEC-103）。
3. 初始化 MediaClock（SPEC-105），以指定初始 27 MHz tick 开始。
4. 为每个 ES 构造 deterministic PES/test payload Source（SPEC-104）。
5. 使用 SPEC-106 packetize PAT/PMT 与 PES。
6. 将 Packet Sources、表重复和 PCR 配置交给 SPEC-107 Mux。
7. 迭代输出恰好 `output_packet_count` 个 TS Packet。
8. 每个 Packet 序列化后写入 sink；每次 write 必须恰好 188 bytes。
9. 返回 GenerationSummary；生成过程中出现任何协议/调度失败时抛 GenerationError，不返回伪成功摘要。

## 8. 确定性要求

确定性输出指相同以下输入产生相同 Packet bytes：

- Generator implementation/version；
- normalized GeneratorConfig；
- `seed`；
- `initial_media_clock_27mhz`；
- 固定算法版本和排序策略。

禁止将 UTC 时间、随机 UUID、临时文件路径、系统随机数或非确定性 dict iteration 结果写入 TS Packet。`createdAtUtcMs` 等 Artifact 元数据不属于 TS bytes，可由 Storage 层另行记录。

若配置中启用 pseudo-random payload，必须使用明确、版本固定且显式 seed 的 PRNG；不得依赖 Python `hash()` 的进程随机化行为。

## 9. Generator 输出约束

- 输出只包含 188-byte Packet；文件大小必须是 188 的整数倍。
- 第一版不输出 M2TS 192-byte、RS204 204-byte 或混合包格式。
- TS 文件正常 baseline 不含 Fault Injector 修改；faulted artifact 与 generated artifact 分开保存。
- PAT/PMT/PES/PCR 数据必须可通过自研 parser 回读。
- Null Packet 用于 CBR 填充；Null PID 不能被登记为业务 ES。
- Generator 的报告不得将“结构可解析”描述为“完整 DVB 网络合规”或“视频可播放”。

## 10. 错误码

- `GENERATOR_SCHEMA_VERSION_UNSUPPORTED`
- `GENERATOR_PROFILE_UNSUPPORTED`
- `GENERATOR_INVALID_PROGRAM_CONFIG`
- `GENERATOR_PID_COLLISION`
- `GENERATOR_INVALID_BITRATE`
- `GENERATOR_RATE_OVERCOMMITTED`
- `GENERATOR_INVALID_PACKET_COUNT`
- `GENERATOR_NONDETERMINISTIC_SOURCE`
- `GENERATOR_OUTPUT_WRITE_FAILED`
- `GENERATOR_PACKET_SIZE_INVARIANT_FAILED`
- `GENERATOR_INTERNAL_COMPONENT_FAILED`

## 11. 测试规格

- 最小单 Program 配置生成。
- 输出包数和字节数严格符合 packet_count*188。
- 文件中所有 Packet Sync Byte 均为 0x47。
- PAT/PMT 可被自研 parser 解析，CRC 正确，PID 关联正确。
- PESAssembler 可重组出与 Generator Source 一致的 PES bytes。
- PCR 可解码，时间递增并按目标周期调度。
- TS bitrate/packet slot 数符合配置模型。
- Null Packet 统计与空闲 slot 一致。
- 相同配置/seed/版本重复生成 SHA-256 相同。
- 改变 seed 仅影响明确允许的合成 payload 字节，不改变协议字段合法性。
- 不支持的 profile、PID 碰撞、bitrate 超售必须拒绝。
- 对生成结果执行 TSDuck `tsanalyze --json` 的集成测试；若环境没有 TSDuck，标记 BLOCKED/NOT RUN，不得由 Agent 虚报通过。
- TSDuck 报告与自研 parser 结果进行字段对照；分歧作为测试失败或明确的 analyzer disagreement 记录。

## 12. 验收标准

- `REQ-TS-108-001`：typed config 校验完整，非法配置明确拒绝。
- `REQ-TS-108-002`：能生成固定 188-byte TS Packet 序列。
- `REQ-TS-108-003`：输出 PAT/PMT/PES/PCR 结构可由自研 Parser 回读。
- `REQ-TS-108-004`：CBR/Mux packet slot 与目标配置一致。
- `REQ-TS-108-005`：相同 config/seed 产生字节级确定性结果。
- `REQ-TS-108-006`：Generator 与 Fault Injector 职责分离。
- `REQ-TS-108-007`：`analysis_only` 与 playback-ready 的能力边界清晰。
- `REQ-TS-108-008`：TSDuck 集成验证有真实命令、版本、退出码和报告证据。

## 13. 与外部模块集成

- `Simulation Runtime` 调用 `iter_packets()` 或 `generate_to()`；TS Core 不管理 Run 生命周期。
- `Artifact Storage` 提供 sink 并记录 Artifact 元数据、SHA-256、config hash。
- `Fault Injector` 接收正常 Packet 流/Artifact，产生单独 faulted 输出和 mutation log。MVP 语义级故障走流式过滤器（ADR-0007：Generator→sink 之间的语义包流过滤器，位于 faults 包）；Artifact 通道保留给 TSDuck 传输级路由。
- `TSDuck Adapter` 对生成 Artifact 执行分析；TS Core 不启动 TSDuck。

## 14. 交付要求

建议文件：`ts/generator/config.py`、`ts/generator/validator.py`、`ts/generator/generator.py`、`ts/generator/sources.py`。提供示例配置、正常 TS fixture、GenerationSummary 和 SHA-256 重复生成报告。
