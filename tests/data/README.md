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

M0 骨架期本目录暂无字节资产（golden 向量实体产出归 #14 后续实现期工作，
见 `docs/test-vectors/TEST-VECTOR-INDEX.md` 流转状态）。
