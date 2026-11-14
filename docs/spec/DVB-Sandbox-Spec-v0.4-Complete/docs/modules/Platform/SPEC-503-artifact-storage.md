---
spec_id: SPEC-503
title: Artifact Storage
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-003, SPEC-502]
requirements: [REQ-PLT-503-001, REQ-PLT-503-002, REQ-PLT-503-003, REQ-PLT-503-004, REQ-PLT-503-005, REQ-PLT-503-006]
---

# SPEC-503 — Artifact Storage

## 1. 目标

定义文件系统资产仓契约：目录布局、SHA-256 内容寻址、**tee 双写落点协议**（[ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 2 条）与路径安全。Artifact 的索引权威在 SPEC-502 `artifacts` 表，本模块负责物理文件与写入协议。

## 2. 范围

### 2.1 In Scope

- 目录布局与内容寻址规则。
- 写入协议（含 tee 双写、原子提交、崩溃恢复）。
- 去重（baseline SHA-256 引用）与读取边界。
- 路径安全。

### 2.2 Out of Scope

- Artifact 索引与查询（SPEC-502）。
- HTTP 下载端点与 Range 语义（SPEC-500）。
- Evidence 语义（定位/引用归 SPEC-206/305）。
- 自动保留/清理策略（roadmap；单文件上限配置随 OPEN-006 定档 [#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16) 回填）。

## 3. 目录布局与内容寻址

```
<root>/artifacts/<sha256[:2]>/<sha256>.<ext>   # 内容寻址平铺（ticket #13 Q-A-①）
<root>/tmp/                                    # in-flight 写入，原子 rename 提交
<root>/exports/<export_id>/                    # SPEC-305 导出产物
```

- 文件名 = 内容 SHA-256；`<ext>` 按 kind 取 `ts` / `json` / `log` / `bin`。
- 同内容天然单文件：**去重 = 引用不复制**——register 时按 sha256 查 SPEC-502 已有行，命中则新增索引行指向同文件。
- MVP **无引用计数、无自动删除**；清理为手动操作（按 session/run 查索引行后删文件须一致性校验）。

## 4. 写入协议（tee 双写落点）

每个 sink（baseline / faulted / mutation log）走同一流程：

1. 在 `tmp/` 创建临时文件，流式写入。
2. 关闭后计算 SHA-256 与 byte_size；对照 `max_bytes` 上限（超限即失败，不留文件）。
3. `os.replace` 原子 rename 到 `artifacts/<aa>/<sha256>.<ext>`。
4. 注册 SPEC-502 索引行（`relative_path` = 布局相对路径）。

- **tee 双写**：带 fault plan 的 run 中，过滤器前流 → baseline sink，过滤器后流 → faulted sink + mutation log sink（kind=`generated_ts` / `faulted_ts` / `log`，ADR-0007 第 2 条）；重复 baseline 按 SHA-256 命中去重。
- **崩溃恢复**：启动时清扫 `tmp/` 孤儿文件（无索引行即删）。
- 写入顺序固定"先文件后索引"：索引行存在即文件必在；反向缺失（文件在、索引无）由清扫与手动一致性校验兜底。

## 5. 读取边界

- 按 `artifact_id` → SPEC-502 索引行 → `relative_path` → 流式读取。
- HTTP 下载、Range 请求、MIME 归 SPEC-500；本模块只提供本地流接口。
- 读取时可选 `verify=True`：重算 SHA-256 与索引行比对，不匹配按损坏处理（503 存储不可用语义 + 日志）。

## 6. 路径安全

- `relative_path` 白名单正则：`^[a-z0-9][a-z0-9/_.-]*$`；禁 `..` 段、禁绝对路径、禁反斜杠。
- 解析后（`resolve()`）必须仍在 `<root>` 内——防符号链接逃逸；`artifacts/` 内禁符号链接。
- API 层永不返回绝对路径（SPEC-003 §2.7 既有禁令）。

## 7. 错误处理

| 场景 | 语义 |
|---|---|
| 磁盘满 / 权限拒绝 | 存储不可用——HTTP 503（对齐 SPEC-305 §7） |
| 写入后 SHA 校验失败 / 超 `max_bytes` | 写入失败，拒绝注册，临时文件即删 |
| 未知 `artifact_id` | 404 |
| 读取 verify 不匹配 | 损坏处理（503 + 告警记录，供 SPEC-304 `OBS_STORAGE_WRITE_FAILURE` 类规则消费） |

## 8. 资源约束

- 单 artifact `max_bytes` 可配置，默认值随 OPEN-006 定档（[#16](https://github.com/BingChaoLiu/DVB-Nexus/issues/16)）回填；写入超限即失败。
- 流式写入不整载内存；SHA-256 边写边算。
- 并发写同内容：`os.replace` 原子性保证最终一致，临时文件名含 uuid 防碰撞。

## 9. 测试规格

- 写入→读取往返字节一致；SHA-256 与索引行一致。
- 去重：同内容二次注册复用同文件（文件系统 inode/路径断言）。
- tee 双写：带 plan run 产出 generated_ts + faulted_ts + log 三 kind；baseline 重复 run 命中去重。
- 崩溃恢复：`tmp/` 孤儿清扫；"先文件后索引"顺序断言。
- 路径安全矩阵：`..` / 绝对路径 / 反斜杠 / 符号链接逃逸全部拒绝。
- 超限与磁盘错误路径。

## 10. 验收标准

- `REQ-PLT-503-001`：内容寻址布局落地，文件名 = SHA-256。
- `REQ-PLT-503-002`：tee 双写三 kind 产物齐备，baseline 重复按 SHA-256 去重（ADR-0007 第 2 条）。
- `REQ-PLT-503-003`：原子提交 + 启动清扫，无半写状态可被索引引用。
- `REQ-PLT-503-004`：路径安全矩阵全绿；API 不暴露绝对路径。
- `REQ-PLT-503-005`：错误语义与 HTTP 映射一致（503 / 404）。
- `REQ-PLT-503-006`：`max_bytes` 上限生效且可配置。

## 11. 非目标与风险

- 不做自动清理、引用计数、压缩、远程对象存储。
- 风险：孤儿文件（文件在、索引无）——MVP 接受，启动清扫 + 手动校验兜底；磁盘空间监控归 SPEC-304 健康规则。

## 12. 交付要求

建议文件：`app/adapters/storage/`（`artifact_store.py` / `paths.py`）；与 SPEC-502 共享 `db.py` 配置。契约测试与 SPEC-203（tee 双写集成）共享 fixture。

## 13. 参考

- SPEC-003 §2.7（TSArtifact 模型与 relativePath 禁令）、SPEC-502 §4（索引表）。
- [ADR-0007](../../../../adr/0007-fault-injection-pipeline-contract.md) 第 2/4 条（tee 双写、等位替换去重）、[ADR-0005](../../../../adr/0005-architecture-baseline.md) 决策 4。
- SPEC-203（Generator/TSRuntime artifacts 关联）、SPEC-305 §4（导出端点）。
