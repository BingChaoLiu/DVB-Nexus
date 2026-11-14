# Implementation dispatch — 并行实现票调度配方

milestone 票图 / implement-spec 流水里 orchestrator 的调度纪律。提炼自 M0
会话（#20~#25：7 次合并零冲突、零 allowlist 违规；两处双实现收拢教训；
CI 首跑红一轮）。

## 调度步骤

1. **Frontier 取票**：原生 Blocked-by 边定 frontier，blockers-first；并列时
   先做能解阻塞下游的票（域模型先于依赖它的持久化）。
2. **接口契约先行**：派发前为并行票切好互斥 OWN / NOT-TOUCH 文件面；
   同一文件的不同 section（pyproject 的运行时依赖 vs 测试配置）也须唯一
   归属。票面与派发词冲突时，orchestrator 裁定并留档。
3. **并行度**：按操作者指令设上限（M0 = 2）；一票完成即补位下一 frontier
   票，槽位全留给实现 work。合并由 orchestrator 顺序执行（merge → 全量
   复验 pytest + lint-imports → 绿了才补位），不单开 merger subagent。
4. **CI 早开 draft PR**：首个影响 CI 的票合入后，立即推集成分支开 draft
   PR——CI-only 路径（winget 安装、runner 差异、新 workflow 门）只有真
   runner 能验，攒到期末首跑 = 把环境风险攒到期末（M0 教训：windows job
   首跑即红，回修一轮才绿）。此后每次合并 CI 持续跑。

## Seam 所有权（单一实现）

- test-support（tests/_support 等）从第一天就 **import 生产实现**，禁止
  平行实现副本等"以后收拢"——收拢不会自动发生，review 必抓，白付一个
  修复票（M0：迁移 runner 与 TSDuck probe 双份均由此来）。
- 生产代码尚未存在的票，support 侧只写薄委托缝并注明归属票，归属票合入
  时接上。

## 真环境测试

实机 / CI 真环境测试断言**形状**，禁钉环境字面值（版本号、盘符、绝对
路径、盘上 casing）；字面钉扎只属于合成 fixture（锁定基线）。细则见
`tests/README.md` §6。
