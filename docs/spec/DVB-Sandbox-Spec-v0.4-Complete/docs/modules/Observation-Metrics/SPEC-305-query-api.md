# SPEC-305 — Observation Query API

## 1. Purpose

Define read-only service contracts consumed by the frontend, Diagnosis Engine, report generator and test harness.

## 2. API principles

- Read-only; no simulation mutation endpoints.
- All requests scoped by tenant and session authorization.
- Bounded time range, page size and response size.
- Explicit clock domain.
- Stable error envelope.
- Cursor pagination for event/timeline/alert collections.
- Metric queries return bounded point counts.

## 3. Logical endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/sessions/{session_id}/observation/summary` | Session observation summary |
| GET | `/api/v1/sessions/{session_id}/events` | Event journal query |
| GET | `/api/v1/sessions/{session_id}/timeline` | Timeline query |
| POST | `/api/v1/sessions/{session_id}/metrics/query` | Metric series query |
| GET | `/api/v1/sessions/{session_id}/alerts` | Alert list |
| GET | `/api/v1/sessions/{session_id}/health` | Health roll-up |
| GET | `/api/v1/sessions/{session_id}/exports/{export_id}` | Export status/manifest |
| POST | `/api/v1/sessions/{session_id}/exports` | Request export |

The export POST creates an Observation export job only; it MUST NOT create or alter a simulation session.

## 4. Common query parameters

- `start`, `end`: integer nanoseconds or documented ISO-8601 wall time; never mix.
- `clock_domain`: REQUIRED for simulation-time query.
- `limit`: default 100; hard max 2000.
- `cursor`: opaque token.
- `sort`: `journal_asc|journal_desc|time_asc|time_desc`.
- filters are allow-listed per endpoint.

## 5. Response envelope

```json
{
  "request_id": "req-001",
  "scope": {"tenant_id": "local", "session_id": "sess-001"},
  "data": {},
  "meta": {
    "schema_version": "1.0",
    "next_cursor": null,
    "truncated": false,
    "clock_domain": "sim:sess-001"
  }
}
```

## 6. Error envelope

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

HTTP mapping:
- 400 invalid query/envelope.
- 401 unauthenticated.
- 403 scope forbidden.
- 404 unknown session/record.
- 409 cursor/filter conflict or export conflict.
- 413 request too large.
- 422 semantically invalid time domain/range.
- 429 rate limited.
- 500 unexpected internal error.
- 503 storage unavailable or service not ready.

## 7. WebSocket integration

This module publishes notifications only; the API/WebSocket module owns transport connections and authentication.

Logical topics:
- `observation.event_appended`
- `observation.metric_updated`
- `observation.alert_changed`
- `observation.health_changed`
- `observation.export_progress`

Notifications are hints. Clients MUST fetch canonical records through REST after reconnect; WebSocket is not a durable event store.

## 8. Limits and safety

- Maximum request body and query range are configurable with conservative defaults.
- Server-side filtering occurs before pagination.
- No arbitrary SQL, expression strings or user-provided Python.
- No secret-bearing payload fields.
- Export jobs are rate-limited and scoped.

## 9. Acceptance tests

- Scope enforcement for every endpoint.
- Time-domain validation.
- Cursor pagination consistency.
- Range/point limits.
- Error envelope consistency.
- WebSocket notification loss/reconnect recovery via REST.
