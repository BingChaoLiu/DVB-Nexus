# SPEC-304 — Health & Alert Engine

## 1. Purpose

Provide transparent health summaries and rule-based alerts from observation data. Alerts are evidence-backed signals, not diagnosis conclusions.

## 2. Health dimensions

Initial health dimensions:
- `transport`: continuity, packet rate, bitrate, null/scrambled ratio.
- `timing`: PCR repetition and jitter.
- `service`: PAT/PMT/service presence and PSI/SI freshness.
- `topology`: node state and path availability from L0 snapshots.
- `simulation`: session/clock/consumer operational status.
- `observation`: ingest failures, consumer lag, storage state.

Health state enum: `unknown|healthy|degraded|critical`.

A health result MUST include `evaluated_at`, `clock_domain`, rule-set version, contributing evidence IDs and reason codes.

## 3. Rule model

A rule includes:
- `rule_id`, `version`, `name`, `description`.
- input metric/event selectors.
- condition and threshold with explicit unit.
- evaluation window and minimum sample count.
- severity and target health dimension.
- open/resolve hysteresis.
- missing-data behavior.
- evidence capture policy.
- enabled flag.

Rules are declarative and validated. Arbitrary Python expressions or eval are forbidden.

## 4. Alert lifecycle

```text
inactive -> pending -> firing -> resolving -> resolved
                    \-> inactive (condition cleared before pending threshold)
```

- `pending`: condition met but `for_duration` not reached.
- `firing`: condition met for required duration.
- `resolving`: condition cleared but resolve hold-down not reached.
- `resolved`: condition remains clear for resolve duration.
- Re-trigger after resolved creates a new alert instance unless deduplication policy explicitly reopens within a configured interval.

Each transition is persisted with timestamp, clock domain, rule version and evidence references.

## 5. Deduplication and grouping

Alert fingerprint is derived from rule ID plus configured stable dimensions. Do not include volatile values or raw payload text.

Grouping may use session, service, PID, node or fault ID. Grouping MUST respect tenant/session scope.

## 6. Health roll-up

Health roll-up is deterministic:
- `critical` if any required critical rule is firing.
- `degraded` if one or more degraded rules are firing and no critical rule is firing.
- `healthy` if required inputs are present and no rules are firing.
- `unknown` if required inputs are missing or stale beyond configured freshness.

The roll-up policy and rule-set version MUST be included in the response.

## 7. Default rule examples

- `TS_CC_ERROR_RATE_HIGH`: continuity errors above configured threshold per service/PID over window.
- `PCR_JITTER_HIGH`: PCR jitter p95 above threshold.
- `PSI_STALE`: PAT/PMT not refreshed within configured interval.
- `TOPOLOGY_PATH_DOWN`: required path unavailable in topology snapshot.
- `OBS_CONSUMER_LAG_HIGH`: consumer lag above configured event count.
- `OBS_STORAGE_WRITE_FAILURE`: journal append failure.

Threshold values are profile-specific and MUST NOT be hard-coded as universal DVB compliance limits.

## 8. Notifications

This module emits alert lifecycle events and exposes alert state. External notification delivery (email, webhook, push) is out of scope for this package and belongs to a notification adapter.

## 9. Safety

- No automatic fault clearing, topology repair or simulation state mutation.
- Alert messages MUST distinguish measured fact from inferred interpretation.
- Never expose key material or secrets in alert evidence.
- Suppressed alerts remain queryable with suppression metadata.

## 10. Acceptance tests

- Pending/firing/resolving/resolved transitions with virtual time.
- Hysteresis and missing data.
- Deterministic evaluation under replay.
- Fingerprint deduplication.
- Evidence references resolve to immutable source records.
- Health roll-up and unknown/stale behavior.
