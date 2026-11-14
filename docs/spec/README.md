# docs/spec/ — 规格参考底稿

本目录存放 ChatGPT 生成的 v0.4 规格包及其来源文件，作为**只读参考资料**（ADR-0001）。权威来源是 GitHub Issues（map #1）、`docs/adr/` 与根目录 `CONTEXT.md`。

## 目录结构

```
docs/spec/
├── README.md                        ← 本文件
├── DVB-Sandbox-Spec-v0.4-Complete/  ← ChatGPT v0.4 规格包原样归档（69 文件）
│   ├── README.md                    ← 包内 README（含归档说明）
│   ├── docs/                        ← 项目级 SPEC-000~005 + 模块包（ts-core/simulation/Observation-Metrics）
│   ├── schemas/ · examples/         ← JSON Schema 与示例
│   └── ...
└── provenance/
    ├── v03.md                       ← 项目愿景 v0.3（案例库已按标准核查订正进 docs/roadmap.md）
    └── chatgpt-v04.md               ← ChatGPT 技术架构评审（M0~M5 里程碑、模块划分、API 设计的原始出处）
```

## 使用规则

1. **引用规格包内容时注明路径**（如 `docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/ts-core/SPEC-100-ts-packet.md`）。
2. 发现底稿缺陷**不要直接改底稿**——在对应 ticket 里提出，修订落到本仓库自己的文档（`docs/adr/`、新规格文件、roadmap）。
3. 底稿中的编号体系有已知双轨缺陷（SPEC-300~305），引用时以 [#10 编号体系重建](https://github.com/BingChaoLiu/DVB-Nexus/issues/10) 的裁决为准。
4. 独立调研报告在 `docs/research/`（TSDuck 环境、生态对比、Python 性能、标准核查）。
