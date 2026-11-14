---
spec_id: SPEC-501
title: WebSocket
version: 0.5.0
status: APPROVED
phase: MVP
owner: Platform
priority: P0
depends_on: [SPEC-003, SPEC-301]
requirements: [REQ-WS-501-001, REQ-WS-501-002, REQ-WS-501-003, REQ-WS-501-004, REQ-WS-501-005]
---

# SPEC-501 — WebSocket

## 1. 目标

定义 WS 传输契约：连接模型、消息帧、订阅与重连恢复、背压。WS 是**best-effort 通知层**，不是持久事件存储——事实源始终是 SPEC-502 journal（SPEC-301 §5 既有裁决）。跨 WebSocket/持久化边界的字段兼容性归本文件（SPEC-003 §2.3 指针）。

## 2. 范围

### 2.1 In Scope

- 路由与连接模型。
- 下行消息帧（journal 帧 + hint 帧）与上行协议。
- 重连恢复协议（cursor 重放）。
- 背压与慢消费处置。

### 2.2 Out of Scope

- REST 拉取端点（SPEC-500/305）。
- 事件信封本身（SPEC-301 权威，本文件只管传输封装）。
- 通知主题语义（SPEC-305 §8）。

## 3. 连接模型

- 路由：`/ws/v1/sessions/{session_id}`；**单连接单 session**（ticket #13 Q4）。
- 无认证（Q4：bind 127.0.0.1）；连接即订阅该 session 的 journal 通知。
- 心跳：服务端周期 ping，客户端 pong 超时即断开（可配置，默认 30s）。

## 4. 消息帧模型（ticket #13 Q-C-②）

### 4.1 下行

**journal 帧**——完整 SPEC-301 信封（含已盖章 `journal_seq`）：

```json
{"type": "journal", "envelope": { /* SPEC-301 信封原样 */ }}
```

**hint 帧**——指向 REST 拉取的通知（SPEC-305 §8 五主题）：

```json
{"type": "hint", "topic": "observation.alert_changed", "data": {"session_id": "..."}}
```

- hint 主题：`observation.event_appended` / `observation.metric_updated` / `observation.alert_changed` / `observation.health_changed` / `observation.export_progress`。
- 两类帧并存的理由（domain 区分）：journal 帧承载**已是事件的事实**；alert/metric/export 是**记录型状态**（不进事件流，SPEC-304 §5 / SPEC-301 §4），只能提示去拉。

### 4.2 上行

```json
{"type": "subscribe", "session_id": "...", "last_journal_seq": 1234}
{"type": "ping"}
```

服务端：`{"type": "ready", "replayed_from": 1235}` / `{"type": "pong"}`。

## 5. 订阅与重连恢复（ticket #13 Q-C-③）

1. 客户端 `subscribe` 带 `last_journal_seq`（缺省 = 从当前起，不重放）。
2. 服务端从 SPEC-502 EventJournal **重放** `query(session_id, after_seq=last_journal_seq)`（journal 帧），序号连续无洞。
3. 重放追上实时流后发 `ready`，转实时投递。
4. 全量状态（节点/故障/拓扑视图）不经 WS——经 REST snapshot 拉取（SPEC-200 §4，带 cursor 参数）。

恢复协议 = snapshot + `journal_seq` cursor（SPEC-301 §5 / ADR-0006 第 2 条既有裁决的重放实现）。

## 6. 背压与慢消费

- per-client **有界队列**（深度可配置）。
- 合并限流（SPEC-301 §5 嫁接条款）：`run_progress` / metrics 类高扇出事件**可合并**（新值覆盖未投递旧值）；`fault.*` / `session_*` / terminal run / `recovery.verification_completed` **禁静默丢弃**。
- 持续慢消费（队列长期高位 + 重放落后）→ 服务端**主动断开**（close code 1013 try again later + 自定义 reason 带 `journal_seq`）→ 客户端带 cursor 重连重放。
- 断开期间不丢事实：journal 仍在，重放补齐——丢的只是重复提示。

## 7. 投递语义

- WS 为 **best-effort**：网络抖动可能丢 journal 帧，客户端不得以 WS 完整性为正确性依据。
- 客户端幂等要求（SPEC-301 §5 消费者必须幂等）：按 `journal_seq` 去重乱序/重放重复。
- 每帧 `type` 字段为传输封装字段，不进信封（信封松负载紧，ADR-0006 第 4 条——传输层不造第四方信封）。

## 8. 错误与关闭码

| 场景 | 处置 |
|---|---|
| session 不存在 / 已 DISPOSED | close 4404 |
| subscribe 的 session_id 与路由不一致 | close 4400 |
| 队列溢出持续慢消费 | close 1013（reason 含续传 cursor） |
| 服务端存储不可用 | close 1011（恢复重连后重放兜底） |

## 9. 测试规格

- 重放连续性：断线期间产生的事件，重连后 cursor 重放无洞无重。
- 合并限流：高频 run_progress 合并后序号跳跃（去重客户端可容忍）；禁丢类逐帧到达。
- 背压：慢消费者被断开且 reason 带正确 cursor；重连重放补齐。
- hint 主题与 SPEC-305 §8 五主题一致；alert hint 后 REST 拉取到记录。
- 心跳超时断开；close code 矩阵。

## 10. 验收标准

- `REQ-WS-501-001`：单连接单 session；路由与订阅校验（4400/4404）。
- `REQ-WS-501-002`：journal 帧承载完整信封 + 盖章序号；hint 帧五主题与 SPEC-305 一致。
- `REQ-WS-501-003`：cursor 重放恢复协议落地（无洞无重 + `ready` 信号）。
- `REQ-WS-501-004`：合并/禁丢背压矩阵生效，慢消费断开带续传 cursor。
- `REQ-WS-501-005`：传输封装不修改信封结构（无第四方信封）。

## 11. 非目标与风险

- 不做多 session 聚合连接、不做消息确认 ACK 协议（best-effort + 重放已覆盖）、不做服务端推送补传保证。
- 风险：客户端把 WS 当唯一数据源——规格与 UI 约定反复强调"journal + REST 为事实源，WS 为提示"。

## 12. 交付要求

建议文件：`app/api/ws/`（`gateway.py` / `frames.py` / `backpressure.py`）；与 SPEC-502 EventJournal、SPEC-305 通知主题共享 fixture。

## 13. 参考

- SPEC-301 §5（排序、投递与背压——本文件的语义权威）、SPEC-305 §8（通知主题）、SPEC-200 §4（snapshot + cursor）。
- [ADR-0006](../../../../adr/0006-canonical-event-envelope.md) 第 1/2/4 条（唯一信封、journal_seq、信封松负载紧）。
- chatgpt-v04 §9/§13.2（WS 底稿与背压策略：最新值合并、窗口聚合、packet 不进事件流）。
