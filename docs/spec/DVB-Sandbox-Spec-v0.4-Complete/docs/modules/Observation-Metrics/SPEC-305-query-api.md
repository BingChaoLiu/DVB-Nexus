---
spec_id: SPEC-305
title: Observation Query API
version: 0.6.0
status: APPROVED
phase: MVP
owner: Observation
priority: P0
depends_on: [SPEC-300, SPEC-303]
requirements: [REQ-OBS-305-001, REQ-OBS-305-002, REQ-OBS-305-003, REQ-OBS-305-004, REQ-OBS-305-005, REQ-OBS-305-006]
---

# SPEC-305 — Observation 查询 API

## 1. 目标

定义前端、Diagnosis Engine、报告生成器与测试工具消费的**只读**服务契约。本文件是查询参数形状的**基准**（[缝合批准 #12] Q7 裁决）：全平台查询参数一律扁平标量。

## 2. 范围

### 2.1 In Scope

- 逻辑端点清单与查询语义。
- 通用查询参数（扁平形状基准）与响应/错误信封。
- WebSocket 通知主题（提示语义）。
- 限制与安全。

### 2.2 Out of Scope

- WS 传输连接与鉴权（SPEC-501）。
- REST 路由的对外冻结（SPEC-500 批准时与本文件对齐；本 spec 的"逻辑端点"是服务级契约）。
- 告警/指标的计算逻辑（SPEC-304/302）。

## 3. API 原则

- 只读：**无任何** simulation 突变端点。
- 全部请求按 tenant/session 授权划界。
- 时间范围、页大小与响应大小有界。
- 时钟域显式。
- 错误信封稳定（§6）。
- 事件/时间轴/告警集合用 cursor 分页。
- 指标查询返回有界点数。

## 4. 逻辑端点

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/sessions/{session_id}/observation/summary` | 会话观测摘要 |
| GET | `/api/v1/sessions/{session_id}/events` | 事件 journal 查询 |
| GET | `/api/v1/sessions/{session_id}/timeline` | 时间轴查询 |
| POST | `/api/v1/sessions/{session_id}/metrics/query` | 指标序列查询 |
| GET | `/api/v1/sessions/{session_id}/alerts` | 告警列表 |
| GET | `/api/v1/sessions/{session_id}/health` | 健康 roll-up |
| GET | `/api/v1/sessions/{session_id}/exports/{export_id}` | 导出状态/manifest |
| POST | `/api/v1/sessions/{session_id}/exports` | 请求导出 |

导出 POST 只创建 Observation 导出任务，**绝不**创建或改动 simulation session。路由前缀与 DTO 的对外冻结归 SPEC-500（REST 契约须与 SPEC-108 §4 JSON↔DTO 映射表对齐，500 系批准时统一）。

## 5. 通用查询参数（扁平形状基准）

- `start_ns` / `end_ns`：整数纳秒；`wall:utc` 域查询允许 ISO-8601 字符串——**同一请求内绝不混用**两种形状。
- `clock_domain`：仿真时间查询**必填**。
- `step_ns`：指标查询的桶步长（整数纳秒）。
- `limit`：默认 100；硬上限 2000。
- `cursor`：opaque token。
- `sort`：`journal_asc|journal_desc|time_asc|time_desc`。
- 过滤器按端点白名单。
- timepoint 对象形状（`{value_ns, clock_domain, clock_epoch, semantics}`）**只用于记录/响应体**，不用于查询参数（SPEC-302 §8 同源裁决）。

## 6. 响应信封

```json
{
  "request_id": "req-001",
  "scope": {"tenant_id": "local", "session_id": "0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"},
  "data": {},
  "meta": {
    "schema_version": "1.0",
    "next_cursor": null,
    "truncated": false,
    "clock_domain": "sim:0f0e8d1c-2b3a-4c5d-8e9f-0a1b2c3d4e5f"
  }
}
```

## 7. 错误信封

```json
{
  "error": {
    "error_code": "OBS_QUERY_RANGE_TOO_LARGE",
    "message": "Requested range exceeds configured maximum",
    "retryable": false,
    "details": {"max_range_ns": 3600000000000}
  },
  "request_id": "req-001"
}
```

HTTP 映射：400 查询/信封非法；401 未认证；403 scope 禁止；404 未知 session/记录；409 cursor/过滤器冲突或导出冲突；413 请求过大；422 时钟域/范围语义非法；429 限流；500 未分类内部错误；503 存储不可用或服务未就绪。错误码归 SPEC-300 §13。

## 8. WebSocket 集成（通知提示语义）

本模块只发布**通知提示**；传输连接与鉴权归 SPEC-501。

逻辑主题：

- `observation.event_appended`
- `observation.metric_updated`
- `observation.alert_changed`
- `observation.health_changed`
- `observation.export_progress`

通知是 hints：客户端重连后**必须**经 REST 拉取规范记录；恢复协议 = 拉取 snapshot + `journal_seq` cursor（SPEC-301 §5）；WS 不是持久事件存储。告警变化经 `observation.alert_changed` 提示后由 `GET .../alerts` 拉取（SPEC-304 §5 记录权威）。

## 9. 限制与安全

- 请求体与查询范围上限可配置，默认保守。
- 服务端过滤先于分页。
- 禁任意 SQL、表达式字符串、用户提供的 Python。
- 禁含密钥 payload 字段。
- 导出任务限流且限定 scope。

## 10. 测试规格

- 每端点的 scope 强制。
- 时钟域校验（缺 `clock_domain` 的仿真查询拒绝；混形状请求拒绝）。
- cursor 分页一致性（翻页无重复无遗漏）。
- 范围/点数限制。
- 错误信封一致性（错误码/HTTP 映射矩阵）。
- WS 通知丢失/重连后经 REST 恢复（提示语义验证）。
- 扁平查询形状与 `examples/metric-query-example.json` 互证。

## 11. 验收标准

- `REQ-OBS-305-001`：每端点 scope 强制且只读（无 simulation 突变路径）。
- `REQ-OBS-305-002`：时钟域校验与扁平查询形状基准落地。
- `REQ-OBS-305-003`：cursor 分页一致且过期语义正确。
- `REQ-OBS-305-004`：范围/点数限制生效。
- `REQ-OBS-305-005`：响应/错误信封稳定并与 HTTP 映射一致。
- `REQ-OBS-305-006`：WS 通知为提示语义，重连恢复走 snapshot + journal_seq cursor + REST。

## 12. 非目标与风险

- 不冻结对外 REST 细节（SPEC-500）。
- 不做服务端推送补传（提示语义 + 拉取兜底）。
- 风险：前端直接消费本 spec 逻辑端点而 SPEC-500 之后再改路由——500 系批准时以对齐评审收口，前端集成须待其落定。

## 13. 交付要求

建议文件：`app/observation/query/`（service.py / envelopes.py）；契约测试与 SPEC-501 集成测试共享 fixture。

## 14. 参考

- SPEC-300（组件与错误模型）、SPEC-302 §8（查询形状同源）、SPEC-304 §5（告警记录权威）。
- SPEC-301 §5（snapshot + journal_seq cursor 恢复协议）。

## Phase 3 定点修订（随落笔票 #156，DRAFT_FOR_REVIEW 0.6.0；依据：细裁 [#152](https://github.com/BingChaoLiu/DVB-Nexus/issues/152) / [#153](https://github.com/BingChaoLiu/DVB-Nexus/issues/153)）

- **查询面扩容**：Run 状态快照查询支持 `rf.*` / `sec.*` 事件过滤（namespace / 事件类型 / node_type 维度），承载前端节点详情面板与画布状态摘要读路径（[#153](https://github.com/BingChaoLiu/DVB-Nexus/issues/153) Q2：静态读走查询面、实时走既有事件订阅，零新前端数据通道）。
- 快照查询返回 JSON-safe metrics 全量（NodeEvalResult 形状）+ journal_seq cursor 恢复协议沿用（SPEC-301 §5）。
