# golden 向量三件套目录

每个子目录 `golden/<vector_id>/` 三件套：`<vector_id>.ts` + `manifest.json` + `expectations.json`，另附 `<vector_id>.verification.md`（独立验证实测证据注记）。布局、登记格式、独立验证红线、CI 门与首批清单见 SPEC-506（Conformance Suite）0.6.0；权威索引见 ../TEST-VECTOR-INDEX.md。

当前已登记：首批 10 条目 / 14 文件（#14 决议，2026-11 全部 registered）：

- `packet-header-set`（bit_level，L1 位级手造）
- `pat-minimal` / `pat-pmt-multi`（tsduck-generate→self-parse）
- `cc-wrap` / `pcr-wrap` / `section-fragmentation`（script-construct→tsduck-analyze）
- `pat-missing` / `pmt-invalid-crc` / `cc-discontinuity` / `pmt-pid-mismatch`（faulted_ts，各配 `<id>-baseline` generated_ts 向量，`fault_plan_ref` 指向各自 baseline）

纪律（SPEC-506 §6）：sha256 即身份，字节冻结；变更 = 重新登记 + 批准（digest 冻结表在 `tests/conformance/test_first_batch_registry.py`）；构造/变换脚本确定性可重跑（`tools/`），CI 只验 sha 永不重新生成；登记校验器 `tools/validate_golden_registration.py` 必须对全树 PASS。
