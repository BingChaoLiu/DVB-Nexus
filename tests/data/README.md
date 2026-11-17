# tests/data/ — 静态测试数据（checked-in 资产区）

SPEC-505 §6：静态数据入 `tests/data/`。本目录只收**入库资产**（文件形式的
测试数据），不收、也不允许代替程序化构造：

- TS/位级字节资产必须来自 SPEC-506 登记 golden（仓库级
  `docs/test-vectors/golden/`，经 `golden_loader` 消费）或确定性场景生成器
  （`tests/_support/deterministic.py`，固定 seed）——**禁手拼字节**
  （SPEC-505 §6、#14 裁决延伸；可执行检测见 `tests/_support/data_rules.py`，
  CI 必绿组合内扫描全 tests/ 树）。
- 每个资产必须能回答三问：来源（生成脚本/golden 登记/实测捕获锚点）、
  身份（sha256）、消费方（哪层哪些测试）。

## 当前布局

- `malformed/` — 畸形输入集（#14 Q2：畸形输入**不入 golden**，expectations
  机制只承载正向观测断言；畸形资产由 unit 层测试消费——SPEC-102 错误码、
  SPEC-308 JSON 内容门）。资产入库时在此 README 登记：文件名、来源、sha256、
  构造方式。
- `t2mi/` — T2-MI 链 checked-in 资产（#125，SPEC-603 §11；research 分支
  只读取材，非手拼字节——来源为外部独立生成器实测捕获锚点）。资产三问：

  | 文件 | 来源 | sha256 | 消费方 |
  |---|---|---|---|
  | `t2mi/inner_ts_roundtrip_input.bin` | `research/ffmpeg-t2mi-demuxer` @ `2935ab68683247dbdf58ee007e1d919e89a60684` 的 `docs/research/phase2/ffmpeg-t2mi-data/raw_t2mi.bin`（外部 stdlib 生成器 `gen_t2mi_sample.py`，N_UPS=3 N_T2MI=2，`git show` 原样提取）；配套 expected 侧 = 登记 golden `inner-ts-roundtrip`（`docs/test-vectors/golden/inner-ts-roundtrip/`） | `b215c997fc515463b44476208889fc2a80b1f42f276eac788c71416de6921985` | `tests/conformance/test_inner_ts_golden_vector.py`（demux 链输入，逐字节对 golden）、`tests/integration/ts/test_t2mi_inner_ts_chain.py`（链 → artifact kind=inner_ts → 消费面） |
  | `t2mi/inner_ts_roundtrip_outer.ts` | 同上分支的 `t2mi_in_ts.ts`（PAT/PMT/T2MI_descriptor 信号化，T2-MI 承载于 PID 0x64，section 式 pointer_field 打包） | `8c1a282961742a3b7435b9b4addd775b5d54dbdbf95043fd9bfa155fc8c0876d` | `tests/conformance/test_inner_ts_golden_vector.py` 的 `tsduck`-marked live cross（`tsp -P t2mi --extract` 外层输入） |

  完整性证明：链输入任何字节漂移都会使 `reconstruct(parse(input))` 偏离
  sha256 冻结的 golden 期望侧（conformance 断言），无需另行字面钉扎。
