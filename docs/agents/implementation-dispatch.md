# Implementation dispatch — 并行实现票调度配方

milestone 票图 / implement-spec 流水里 orchestrator 的调度纪律。提炼自 M0
会话（#20~#25：7 次合并零冲突、零 allowlist 违规；两处双实现收拢教训；
CI 首跑红一轮）。

## 调度步骤

1. **Frontier 取票**：原生 Blocked-by 边定 frontier，blockers-first；并列时
   先做能解阻塞下游的票（域模型先于依赖它的持久化）。
2. **探索摊销（milestone 级）**：≥6 张实现票的 milestone 先跑一次
   exploration subagent 产出共享简报（implement-spec skill step 2 的
   exploration notes 机制），票词指向简报文件而非各自重读语料——M3
   实测每票 subagent 自读 SPEC/ADR/CONTEXT/tests-README 花 10–15M
   tokens（#47 达 15.7M），11 票重复摊销远贵于一次前置；简报顺带固化
   环境纪律（worktree 检查姿势、house 测试惯用法）与 seam 图，供接口
   契约切分（下一步）直接引用。小票图（<6 票）跳过，sparse pointers
   直读权威源即可。落点约定（M4 retro finding B5）：仓库同级
   `dvb-nexus-m<N>-brief/BRIEF.md`（M4 先例
   `D:\Document\Project\dvb-nexus-m4-brief\BRIEF.md`，790 行一次
   21.5M 摊销九票）；milestone 收尾后保留作历史，不进 repo。
3. **接口契约先行**：派发前为并行票切好互斥 OWN / NOT-TOUCH 文件面；
   同一文件的不同 section（pyproject 的运行时依赖 vs 测试配置）也须唯一
   归属。票面与派发词冲突时，orchestrator 裁定并留档；派发词中关于
   允许 import 边的断言先对 pyproject `[tool.importlinter]` 合约核对
   （M3 retro：#40 派工词笔误与冻结合约相悖，靠 implementer 回注才收拢）。
4. **并行度**：按操作者指令设上限（M0 = 2）；一票完成即补位下一 frontier
   票，槽位全留给实现 work。合并由 orchestrator 顺序执行（merge → 全量
   复验 pytest + lint-imports → 绿了才补位），不单开 merger subagent。
5. **CI 早开 draft PR**：首个影响 CI 的票合入后，立即推集成分支开 draft
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

## 实现票收尾纪律

- IMPLEMENTATION_REPORT 必须**同时以 comment 贴到票上**：报告只活在
  派发会话上下文时，fresh reviewer / orchestrator 不可达，已申报偏差
  会被当新发现重审（M3 retro：spec 轴四处检索找不到任何 REPORT）。
  分支 commit 与报告内容一致；orchestrator 的汇总留档归 tracking
  issue。
- **下游接口清单交接**（M4 retro finding B7）：IMPLEMENTATION_REPORT
  首节固定「下游接口清单」（类/函数签名 + payload/fixture 键契约 +
  组合根绑定姿势）；orchestrator 派下游票时把上游清单**原文贴进派工
  词**并明示「不重读上游全报告」——M4 实测：带现成清单的后票
  （#55 13.7M/#58 32.6M）显著低于中途链票自行检索的（#53 65M/
  #56 57M）。
- worktree 内跑检查：pytest 经 pyproject `pythonpath` 自愈；
  `lint-imports` 必须 `PYTHONPATH=$PWD/src`（见
  `docs/agents/windows-shell.md`「Worktree 内跑检查」）。
