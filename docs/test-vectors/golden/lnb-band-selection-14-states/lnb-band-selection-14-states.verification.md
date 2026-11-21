# lnb-band-selection-14-states · 独立验证注记

- **vector_id**: `lnb-band-selection-14-states`（kind `state_eval`，#172 登记，2026-11）
- **规格权威**: SPEC-621 appendix A — 14 态真值表（normative，逐格 verbatim）。
- **数据文件**: `lnb-band-selection-14-states.ts` = 向量表的 canonical JSON 序列化
  （`json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` + 尾随换行；UTF-8）。
  sha256 即身份（manifest）；字节冻结，变更 = 重新登记 + 批准。

## 独立验证路径（SPEC-506 §5 红线）

1. **规格表权威推导（L1，无 src 参与）**：14 行 × (voltage, tone_actual,
   tone_composite) → (band_selected, lo_frequency_khz, polarization_delivered)
   逐格转录自 SPEC-621 appendix A 印刷表。转录发生在实现写入**之前**的同一张表
   已被四源一致核验（#146 research 票：SPEC-621 appendix A 原文 / ETSI TS 101 964
   表 A.1 / 教科书通例 / 实现票 #161 的独立预推导——四源逐格一致）。
2. **实现无关的双向转录对拍**：#161 的向量测试常量（`tests/unit/simulation/state/
   evaluators/test_lnb_evaluator_vectors.py::ALL_14_ROWS`）是**另一次独立转录**
   （向量先钉纪律：先写测试常量后写实现）；本 golden 表与其逐格一致即两份独立
   转录互证，再由 conformance 测试驱动生产 `select_band` 纯函数对拍 golden——
   生产实现对拍的不是自己的输出，是规格表转录。
3. **TSDuck 交叉**：不适用（state 域无码流；L2 TSDuck 交叉对状态域向量无意义）。

## 同源自证排除声明

- 本向量**不是**「同一实现解析自身输出」：golden 表 ← 规格表转录（#146 四源）；
  conformance 断言 ← 生产纯函数。两条链在 golden 处汇合，无循环。
- #161 向量测试常量与 golden 表逐格一致是**第二独立转录**的一致性证据，非验收
  依据本身（验收依据 = 规格表 + conformance 生产对拍）。

## 单位与编码钉扎（#161 REPORT 冻结的调和）

- appendix A `lo_frequency_khz` 列印刷 `9750`/`10600`（MHz 语气）——落 `*_khz`
  字段的全 kHz 值 `9750000`/`10600000`（与 `LoFrequenciesDTO` 及 IF 窗口算术一致）。
- 复合态（行 13/14）编码 = `tone_actual="data_burst"`（寻址 burst）+
  `tone_composite="continuous_plus_data_burst"`（持续载波分量）；band 随持续分量。
- 行 1–4（0V 语义）：band `none` / LO `null` / polarization `none`——tone 无载体。

## 登记校验

- `tools/validate_golden_registration.py` PASS（三件套/sha/事件类型合法性/索引一致）。
- conformance 门：`tests/conformance/test_state_eval_golden_vectors.py` 驱动生产
  `select_band("universal", …)` 14 态逐格对拍 + canonical 序列化往返稳定。
