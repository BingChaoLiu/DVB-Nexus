# unicable-frequency-formula · 独立验证注记

- **vector_id**: `unicable-frequency-formula`（kind `state_eval`，#172 登记，2026-11）
- **规格权威**: SPEC-623 §6 频率公式（normative）：
  - 公式 I（EN 50494）：`t = round((f_IF + f_UB + 2)/4) − 350`（接收端调
    `(t+350)×4 − f_IF ≈ f_UB + 2 MHz`；实现分歧记录 = minisatip 直接调 f_UB，
    取多数派并标注——非 normative 偏差，+2/−350 常数路径为 normative 路径）；
  - 公式 II（EN 50607）：`t = f_IF − 100`。
- **数据文件**: `unicable-frequency-formula.ts` = 向量表的 canonical JSON 序列化
  （indent=2 / sort_keys / ensure_ascii=False + 尾随换行；UTF-8）。sha256 即身份。

## 独立验证路径（SPEC-506 §5 红线）

1. **数值手推（L1，无 src 参与）**：每个 t 值手算自公式——公式 I 的取整四元组
   （(f_IF+f_UB+2) mod 4 = 0/1/2/3 → 整/下/上(half-up pin)/上）与常数路径
   （+2 / −350）、10-bit 上界 3448+2040→1023；公式 II 六例含最小 t=0 与
   11-bit 上界 2147→2047。手算先于实现（#162 向量先钉纪律）。
2. **第二独立转录互证**：#162 的 `TestFrequencyFormulas` 断言是另一次独立手推；
   本 golden 表与其数值一致即两份独立手推互证。conformance 测试驱动生产
   `en50494_t_value` / `en50607_t_value` 纯函数对拍 golden——实现对拍的是
   规格手算值，不是自身输出。
3. **TSDuck 交叉**：不适用（频率公式属 SCR 消息构造面，非码流域）。

## 数值对照表

公式 I（EN 50494，f_UB = 1210 MHz 除末行 2040）：

| f_IF (MHz) | (f_IF+1210+2) | /4 | t |
|---|---|---|---|
| 1000 | 2212 | 553 exact | 203 |
| 1001 | 2213 | 553.25 → 553 | 203 |
| 1002 | 2214 | 553.5 → 554 | 204（round-half-up 钉扎） |
| 1003 | 2215 | 553.75 → 554 | 204 |
| 1002（+2 路径） | 同上 | — | 204 |
| 1000（−350 路径） | 553 raw − 350 | — | 203 |
| 3448（f_UB=2040） | 5490 | 1372.5 → 1373 | 1023（10-bit 上界） |

公式 II（EN 50607）：

| f_IF (MHz) | t |
|---|---|
| 1000 | 900 |
| 1950 | 1850 |
| 100 | 0（最小可编码 t） |
| 2147 | 2047（11-bit 上界） |
| 1100 | 1000 |
| 1500 | 1400 |

## 登记校验

- `tools/validate_golden_registration.py` PASS。
- conformance 门：`tests/conformance/test_state_eval_golden_vectors.py` 逐例
  驱动生产 `en50494_t_value(f_if, f_ub)` / `en50607_t_value(f_if)` 对拍 t +
  canonical 序列化往返稳定。
