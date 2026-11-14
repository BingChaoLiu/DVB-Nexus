---
spec_id: SPEC-105
title: MPEG Media Clock, PCR and PTS/DTS Primitives
version: 0.4.0
status: DRAFT
phase: MVP
owner: TS Core
priority: P0
depends_on: [SPEC-003, SPEC-004]
requirements: [REQ-TS-105-001, REQ-TS-105-002, REQ-TS-105-003, REQ-TS-105-004, REQ-TS-105-005, REQ-TS-105-006]
---

# SPEC-105 — PCR / Media Clock

## 1. 目标

提供与 MPEG 时间戳相关的纯整数时基、PCR 42-bit 编码/解码、PTS/DTS 33-bit 编码/解码、回绕和精确换算。该模块是协议媒体时钟原语，不负责 Session 的现实时间或 Simulation Runtime 的 pause/speed 控制。

## 2. 三种时间必须分离

| 时间域 | 单位 | 所属模块 |
|---|---|---|
| Wall Clock | UTC Unix ms/ns | Application/Observation |
| Simulation Clock | 虚拟 tick | SPEC-201 |
| MPEG Media Clock | PCR 27 MHz ticks / PTS 90 kHz ticks | 本 Spec |

不得用 `datetime.now()` 填充 PCR/PTS。

## 3. PCR 编码

PCR 由 33-bit `program_clock_reference_base`、6-bit reserved（必须为 `111111`）和 9-bit `program_clock_reference_extension` 构成，共 42 significant bits / 6 bytes。`PCR.base` 使用 90 kHz 计数；`extension` 使用 27 MHz sub-tick，合法范围为 0..299。组合 27 MHz tick 为：

`pcr_27mhz_ticks = base * 300 + extension`

回绕模数为 `2^33 * 300` 个 27 MHz ticks；base 自身按 `2^33` 回绕。

## 4. PTS/DTS 编码

- PTS/DTS 是 33-bit、90 kHz 单位的时间戳。
- PTS/DTS 在 PES Header 中按指定 prefix 与 marker-bit 分段编码，共 5 bytes。
- PTS only 与 PTS+DTS 两种组合必须编码正确；DTS 必须使用 DTS prefix。
- Parser 必须校验 marker bits、prefix 和 33-bit 范围。
- PTS/DTS 与 PCR 的时间关系需由上层 Analyzer/Diagnosis 检查；本模块只做编码和数值转换。

## 5. 数据模型

```python
PCR_MODULUS = (1 << 33) * 300
PTS_MODULUS = 1 << 33

@dataclass(frozen=True)
class PCR:
    base: int
    extension: int

    @property
    def ticks_27mhz(self) -> int: ...

@dataclass(frozen=True)
class MediaClock:
    ticks_27mhz: int

    def pcr(self) -> PCR: ...
    def pts90k(self) -> int: ...
```

`MediaClock` 只接受非负整数 tick；是否允许超过单次回绕范围，按内部绝对时间计数保存，再在编码边界取模。不要在运行期间过早丢失 wrap count。

## 6. 公共接口

```python
def encode_pcr(pcr: PCR) -> bytes: ...
def decode_pcr(data: bytes) -> PCR: ...

def encode_pts(value_90khz: int, *, prefix: int = 0b0010) -> bytes: ...
def decode_pts(data: bytes, *, expected_prefix: int | None = None) -> int: ...

def pcr_to_27mhz_ticks(pcr: PCR) -> int: ...
def pcr_from_27mhz_ticks(ticks: int) -> PCR: ...
def ticks27_to_pts90(ticks: int, *, rounding: str = "floor") -> int: ...
def pts90_to_ticks27(pts: int) -> int: ...
def modular_delta(current: int, previous: int, modulus: int) -> int: ...
```

`prefix` 仅允许标准定义的 PTS/DTS prefix；调用方不得传任意 nibble。`modular_delta` 需定义“前向差值”范围并提供歧义说明；通常差值为 `(current-previous) % modulus`，但无法仅凭两个模值判断超过半周期的实际方向。

## 7. 计算和边界规则

- PCR 字段序列化按 H.222.0 位布局，reserved 6 bits 必须写 1。
- PCR extension 输入 300..511 视为非法；不能自动对 300 取模。
- base、PTS、DTS 超过各自范围时，公共编码 API 拒绝；若要处理绝对媒体 tick，则由专用转换函数按 modulus 映射。
- PTS/DTS 5-byte 中所有 marker bit 必须为 1；错误 marker 返回 `InvalidTimestampError`。
- 不使用 float 进行 MHz/90kHz 转换。27MHz→90kHz 是除以 300，按指定 rounding policy 执行。
- `floor` 是默认向下取整；其他 rounding 方式需枚举支持并测试。
- 时间戳 wrap-around 要保留原始模值；比较需使用 modular delta 及调用方可配置的最大可判定窗口。

## 8. PCR 与 Mux 的职责边界

- 本模块负责 PCR 值本身的编码/解码与时间转换。
- PCR 的插入位置、重复周期和是否创建 adaptation-only Packet 由 SPEC-107。
- PCR repetition/accuracy 的测量和诊断属于后续 SPEC-301/304 / Conformance Profile。
- 不在 `encode_pcr()` 中硬编码 DVB TR 101 290 的检测阈值。

## 9. 错误码

- `PCR_INPUT_LENGTH_INVALID`（不是 6 bytes）
- `PCR_RESERVED_BITS_INVALID`
- `PCR_EXTENSION_OUT_OF_RANGE`
- `PCR_BASE_OUT_OF_RANGE`
- `PTS_INPUT_LENGTH_INVALID`（不是 5 bytes）
- `PTS_MARKER_BIT_INVALID`
- `PTS_PREFIX_INVALID`
- `PTS_VALUE_OUT_OF_RANGE`
- `CLOCK_NEGATIVE_TICKS`
- `CLOCK_ROUNDING_MODE_UNSUPPORTED`

## 10. 测试规格

- PCR base=0/ext=0 编码。
- PCR base=2^33-1/ext=299 最大合法值。
- PCR ext 0、1、299 合法；300/511 拒绝。
- reserved bits 被破坏时 decode 拒绝。
- PCR round-trip 与 combined ticks round-trip。
- PTS/DTS 0、1、2^33-1；拒绝 -1、2^33。
- PTS only / PTS+DTS prefix 验证。
- marker bit 每个位置分别翻转，Parser 必须报错。
- 27MHz→90kHz→27MHz 的整数舍入边界。
- PTS wrap：`2^33-1 → 0` 的 modular delta 为 1。
- 固定 seed property tests 与 test-vectors/PCR-PTS.md。

## 11. 验收标准

- `REQ-TS-105-001`：PCR 6-byte 位编码/解码准确。
- `REQ-TS-105-002`：reserved bits 与 extension 范围校验正确。
- `REQ-TS-105-003`：PTS/DTS 33-bit 时间戳编码/解码正确。
- `REQ-TS-105-004`：27 MHz / 90 kHz 换算仅使用精确整数运算。
- `REQ-TS-105-005`：wrap-around 和 modular delta 行为符合约定。
- `REQ-TS-105-006`：本模块不依赖或混淆 wall-clock/Simulation Clock。

## 12. 交付要求

建议文件：`clock.py`、`pcr.py`、`timestamp.py`；如果拆为多个文件，应保持公开接口集中导出。不得依赖系统时间或第三方 TS 工具。

## 13. 参考

- ITU-T H.222.0 (04/2025), PCR、PTS、DTS syntax。
- ETSI TR 101 290 用于后续测量规范参考；PCR repetition 与 accuracy 检查不是此模块的编码逻辑。
