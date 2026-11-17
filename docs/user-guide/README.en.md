# DVB-Nexus User Guide (English)

English | [简体中文](README.zh-CN.md)

> **Status**: this guide grows with the software. It currently covers every
> user-visible feature of the MVP (TS-first eight-step closed loop) and of
> Phase 2, the advanced encapsulation layer (T2-MI three-level
> encapsulation, BISS scrambling/descrambling).
> Domain vocabulary is authoritative in [`CONTEXT.md`](../../CONTEXT.md);
> this guide is about *how to use it*, not a re-statement of definitions.

## Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Installation & Startup](#3-installation--startup)
   - 3.1 [Start the backend](#31-start-the-backend)
   - 3.2 [Start the frontend](#32-start-the-frontend)
4. [UI Tour](#4-ui-tour)
   - 4.1 [Topologies — link topology editor](#41-topologies--link-topology-editor)
   - 4.2 [Monitor — stream monitoring](#42-monitor--stream-monitoring)
   - 4.3 [Lab — training range](#43-lab--training-range)
5. [Core Workflow: the Eight-Step Closed Loop](#5-core-workflow-the-eight-step-closed-loop)
6. [Training Scenarios](#6-training-scenarios)
7. [REST API & WebSocket](#7-rest-api--websocket)
8. [Environment Variables](#8-environment-variables)
9. [FAQ](#9-faq)
10. [Documentation Roadmap](#10-documentation-roadmap)

---

## 1. Overview

DVB-Nexus (DVB Sandbox) is a single-machine engineering platform combining
**real-time stream troubleshooting** with **interactive protocol drills**:

- **Sandbox mode**: no real hardware or live feeds — a simulation engine
  produces link state on its own. The MVP focuses on the MPEG-TS transport
  layer: 188-byte packets and the `analysis_only` generation profile
  (structurally compliant, parseable, analyzable; payload is deterministic
  synthetic data — playback is explicitly not promised). Phase 2 adds the
  advanced encapsulation layer: T2-MI → BBFrame → Inner TS three-level
  encapsulation and BISS Mode 1 / Mode E scrambling/descrambling.
- **Eight-step closed loop**: Create → Generate → Inject → Analyze →
  Diagnose → Inspect → Recover → Verify, with real data and traceable
  evidence at every step.
- **Training range (Lab)**: preset fault scenarios (SC-01 ~ SC-09). After a
  fault is injected, the learner repairs it and the experiment is judged on
  the evidence of the new post-repair run (PASS / FAIL / INCONCLUSIVE).

Single machine, single user, no authentication (localhost `127.0.0.1`
posture). Not intended for multi-user or public exposure.

## 2. Requirements

| Component | Version | Notes |
|---|---|---|
| Python | ≥ 3.10 | backend runtime |
| Node.js | ≥ 22.12 | frontend build & dev server |
| npm | ≥ 11 | frontend package manager |
| websockets (Python pkg) | ≥ 14, < 16 | required for WebSocket push — see [FAQ](#9-faq) |
| TSDuck CLI (optional) | any local install | cross validation, transport-level fault injection, generation fallback; without it those features are unavailable, everything else works |

Windows-first runtime (ADR-0004): other platforms can run it, but
troubleshooting and CI target Windows first.

## 3. Installation & Startup

Run from the repository root (Git Bash examples for Windows).

### 3.1 Start the backend

```bash
# 1) Create and activate a virtual environment (optional but recommended)
python -m venv .venv
source .venv/Scripts/activate        # Git Bash / Windows
# source .venv/bin/activate          # Linux / macOS

# 2) Install the backend (editable mode, convenient for development)
pip install -e .

# 3) Install WebSocket serving support (uvicorn refuses all WS handshakes without it)
pip install "websockets>=14,<16"

# 4) Start the API server (the SQLite DB path is mandatory)
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" \
python -m uvicorn bootstrap.asgi:app --host 127.0.0.1 --port 8765
```

Equivalent convenience entry (reads `DVBNEXUS_HOST` / `DVBNEXUS_PORT`,
defaults to `127.0.0.1:8765`):

```bash
DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db" python -m bootstrap.asgi
```

Key points:

- `DVBNEXUS_DB_PATH` **must be provided explicitly**; without it the backend
  refuses to start (an explicit contract beats silently creating a database).
- The artifact store is derived from the DB path:
  `artifacts/` inside the database's parent directory.
- On success, `GET http://127.0.0.1:8765/api/v1/version` returns version info.

### 3.2 Start the frontend

```bash
cd frontend
npm install
npm run dev          # Vite dev server, default http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to the backend at
`http://127.0.0.1:8765` (keeps the SPA same-origin, so no CORS handling is
needed). If your backend listens elsewhere, override the proxy target:

```bash
DVBNEXUS_BACKEND_ORIGIN="http://127.0.0.1:9000" npm run dev
```

Open `http://localhost:5173` in a browser. Production build: `npm run build`;
preview the built bundle locally: `npm run preview` (fixed port 4173, same
proxy).

## 4. UI Tour

Three pages in the top navigation: **Topologies** → **Monitor** → **Lab**.

### 4.1 Topologies — link topology editor

A React Flow canvas for link topology editing:

- **Node palette**: node types —
  | Node type | Description |
  |---|---|
  | `ts_generator` | produces an MPEG-TS stream per its GeneratorConfig; the Generate anchor of the closed loop |
  | `ts_mux` | muxes multiple TS inputs into one output |
  | `ts_demux` | splits one TS input into two outputs (receive-side split) |
  | `ts_monitor` | passive observation endpoint where Analyze/Inspect evidence lands |
  | `t2mi_encapsulator` (T2-MI encapsulator) | packs Inner TS into a T2-MI packet stream via BBFrame framing (Phase 2) |
  | `t2mi_demux` (T2-MI demux) | T2-MI packet stream → BBFrame parsing → Inner TS reconstruction (Phase 2) |

- **Wiring**: ports have direction (input/output) and max-connection
  constraints; illegal connections are rejected up front. Enabled signal
  planes: `MPEG_TS` and `T2MI` (since Phase 2; RF / SEC_CONTROL / IP planes
  are reserved extension slots). A three-level encapsulation subgraph =
  generator → encapsulator → demux → monitor.
- **Validation**: the submitted topology is validated by the backend; the
  violation panel lists every issue (missing monitor, port mismatch, …) —
  fix and resubmit.
- After saving, the topology enters a session and its lifecycle is driven
  from the Monitor page.

### 4.2 Monitor — stream monitoring

A session-scoped monitoring console (URL carries `?session=<id>`), with two
tabs:

**Stream tab** (the main surface of the closed loop):

- **Lifecycle control bar**: start / pause / resume / validate / stop /
  dispose (delete the session).
- **Overview card & run trigger**: session summary; trigger a new run
  (Generate).
- **Metrics panel**: PID-level observed metrics.
- **Alerts panel**: alerts produced by the rule engine.
- **Diagnosis list**: root-cause candidates (ranked by static rule
  confidence: high / medium / low), each optionally carrying evidence links.
- **Packet inspector**: one-click drill-down from an observation/diagnosis to
  the raw stream — located by the PID + packet index + Artifact triple, with
  188-byte packet and table decode details. A `view=t2mi|bbframe|ts`
  parameter switches between three views (6-byte T2-MI header field by field
  + CRC-32, 10-byte BBHEADER field by field + UP boundaries, Inner TS
  structure); the default is `ts`.
- **Journal tail**: the event journal (journal-seq stamped), throttled
  real-time refresh; since Phase 2, `gen.*` (construction stages and sampled
  packets) and `t2mi.*` / `bbframe.*` / `biss.*` (encapsulation and
  scrambling events) render registry-driven — keys appear only as
  fingerprints.
- **Verify form & result card**: submit the repair claim; the verdict
  (PASS / FAIL / INCONCLUSIVE) is decided on the new run's evidence.

**CLI Console tab**: records of TSDuck subprocess invocations (command line,
state, output) for auditing cross validation and transport-level injection.

### 4.3 Lab — training range

The interactive training area for preset scenarios:

- **Scenario library**: nine built-in scenarios (see
  [Section 6](#6-training-scenarios)) with difficulty tiers, objectives and
  initial topologies.
- **Experiment console**: enter an experiment in two hops from the scenario
  library; session and fault plan are assembled automatically.
- **Eight-step stepper**: the closed loop mapped onto a trackable step bar.
- **Generation fold-out**: a read-only panel showing per-stage progress of
  the layered pipeline (Inner TS / BBFrame / T2-MI) plus sampled-packet
  cards; clicking one jumps to the packet inspector with a `view` parameter.
- **Hints ladder**: stuck? Reveal hints one rung at a time — try diagnosing
  yourself first.
- **Solution panel**: unlocked only when verification returns **PASS** — a
  repair action or a green UI is not evidence of recovery.

## 5. Core Workflow: the Eight-Step Closed Loop

One full experiment walks all eight steps:

| Step | Action | Page | Output |
|---|---|---|---|
| 1 Create | create a session bound to a topology | Topologies / Lab | Session |
| 2 Generate | trigger a run to produce the baseline stream | Monitor | baseline TS artifact |
| 3 Inject | inject a fault (slot-preserving substitution; no packets added/removed) | Monitor / Lab | faulted TS artifact |
| 4 Analyze | structural analysis of the stream | Monitor | observations + alerts |
| 5 Diagnose | produce root-cause candidates | Monitor | diagnosis list (confidence tiers) |
| 6 Inspect | drill into the raw stream to verify evidence | Monitor | PID + packet index + Artifact |
| 7 Recover | apply the fix (topology/config change, regenerate) | Monitor / Lab | new post-repair run |
| 8 Verify | judge the recovery on the new run's evidence | Monitor / Lab | PASS / FAIL / INCONCLUSIVE |

Two disciplines apply throughout (see `CONTEXT.md`):

- **Observations are never mislabeled**: every observation carries a source
  (generator / internal_parser / tsduck / …) and a confidence
  (simulated / parsed / measured / inferred); SIM_STATE output is never
  marked `parsed`.
- **Recovery is judged on evidence**: verdicts come from the new
  post-repair run's evidence, not from UI state; "no alerts" does not mean
  "clean".

## 6. Training Scenarios

Built-in scenarios come in two packs (`scenarios/` directory):

**Lab Pack v1 (TS-layer basics)**:

| Scenario | Title | Difficulty | Focus |
|---|---|---|---|
| SC-01 | 认识闭环：PAT 缺失 (Meet the loop: missing PAT) | introductory | walk the eight-step loop; locate a missing PSI root table behind "no services" |
| SC-02 | CRC 防线：PMT 校验和失效 (CRC defense: invalid PMT CRC) | introductory | symptoms and evidence of a failed table CRC check |
| SC-03 | 声明失配：PMT PID 重指向 (Declaration mismatch: PMT PID retarget) | intermediate | locating declared-vs-actual PID drift |
| SC-04 | 连续性破坏：CC 相对偏移 (Continuity broken: CC offset) | intermediate | continuity-counter anomalies and loss symptoms |
| SC-05 | 双故障靶场：组合症状 (Double fault: combined symptoms) | advanced | diagnosing two stacked faults |

**Lab Pack v2 (Phase 2 advanced encapsulation)**:

| Scenario | Title | Difficulty | Focus |
|---|---|---|---|
| SC-06 | 封装错位：T2MI PLP 映射 (Encapsulation misaligned: T2-MI PLP mapping) | intermediate | expected-vs-actual PLP drift — outer layer green but Inner TS carries no business ("missing ≠ zero") |
| SC-07 | 封装错位：BBHEADER 同步 (Encapsulation misaligned: BBHEADER sync) | intermediate | locating a SYNCD bit-distance mismatch ("SYNCD is a bit distance, not a sync byte") |
| SC-08 | 加扰错位：BISS 密钥 (Scrambling misaligned: BISS key) | intermediate | the descramble-evidence chain for a wrong session word ("descramble failure ≠ corrupted stream"; keys show only as fingerprints) |
| SC-09 | 时序错位：PMT 版本更新后 PID 漂移 (Timing misaligned: PID drift after a PMT version bump) | advanced | locating drift when a PMT version changes but the demux filter table lags |

Practice SC-01 → SC-05 for TS-layer basics (loop first, then single faults,
then combined faults), then move on to SC-06 → SC-09 for the advanced
encapsulation layer.

## 7. REST API & WebSocket

- Base prefix: `/api/v1` (additive-only version policy).
- Interactive docs: `http://127.0.0.1:8765/docs` (Swagger UI generated from
  OpenAPI; frontend types are synced from `/openapi.json`).
- Version probe: `GET /api/v1/version`.
- Resource groups: `sessions` (lifecycle), `topologies` (CRUD + validation),
  `runs` (generation), `scenarios` (range scenarios), `artifacts` (artifact
  metadata & content, plus
  `GET /artifacts/{id}/structure?view=t2mi|bbframe|ts` structural views),
  the observation group (metrics / alerts / snapshot / diagnoses /
  verification), `tsduck_calls` (CLI call records).
- WebSocket: `/ws/v1/sessions/{session_id}` — per-session event push
  (journal / hints). Note `/ws/v1` sits outside the `/api/v1` prefix.

Single-machine single-user posture: no authentication, fixed local tenant —
do not expose it to the public internet.

## 8. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DVBNEXUS_DB_PATH` | none (required) | SQLite database path; artifact store derived as `artifacts/` in its parent directory |
| `DVBNEXUS_HOST` | `127.0.0.1` | bind host for the convenience entry |
| `DVBNEXUS_PORT` | `8765` | bind port for the convenience entry (matches the Vite proxy default) |
| `DVBNEXUS_PUMP_INTERVAL_MS` | `50` | pump tick interval in server mode (journal commits / WS fan-out) |
| `DVBNEXUS_BACKEND_ORIGIN` | `http://127.0.0.1:8765` | backend origin the frontend Vite proxy targets |

## 9. FAQ

**Q1: No real-time events in the frontend, and the backend logs WS
handshake 404s?**
uvicorn refuses every WebSocket handshake (404) when the WS serving library
is missing. Install and restart: `pip install "websockets>=14,<16"`.

**Q2: The backend fails with "DVBNEXUS_DB_PATH is required".**
The DB path is an explicit contract with no default. Set it before starting,
e.g. `DVBNEXUS_DB_PATH="D:/dvbnexus-data/dvbnexus.db"`. Missing directories
are created; artifacts land under `artifacts/` beside the database.

**Q3: The frontend proxy can't reach the backend.**
Confirm the backend is on `127.0.0.1:8765`; if you changed the port, set
`DVBNEXUS_BACKEND_ORIGIN` accordingly before starting the frontend.

**Q4: What happens without TSDuck installed?**
The core loop (the in-house TS Core semantic layer) is unaffected; cross
validation, transport-level fault injection and generation fallback are
unavailable and the related tests skip explicitly. Install TSDuck
(≥ 3.40 recommended) and those features enable automatically.

**Q5: Can I play the generated TS?**
No. The MVP only promises `analysis_only`: structurally compliant and
parseable, with deterministic synthetic payloads. The `playback_ready`
profile lives on the long-term roadmap.

**Q6: Why isn't my experiment passing even though I fixed the issue?**
The verdict is judged on the **new post-repair run's evidence**: you must
complete Recover (regenerate) and Verify (submit). A green UI or vanishing
alerts is not evidence.

## 10. Documentation Roadmap

This guide evolves with the software; it covers all user-visible MVP and
Phase 2 features. Planned follow-up sections:

- Example configuration walkthrough (field-by-field for
  `examples/ts-generator-minimal.json`)
- Scenario authoring guide (`scenarios/*.json` schema and fault-plan syntax)
- Artifacts & the evidence chain (SHA-256, config hash, fault archive)
- Advanced TSDuck integration (reading cross-validation results, analyzing
  CLI console output)

Found a gap or an error? Please open a
[GitHub issue](https://github.com/BingChaoLiu/DVB-Nexus/issues).
