# features/ — route-region ownership (裁定 C, SPEC-400 §4.2)

Each subdirectory is ONE route region, owned by its implementing ticket from
its own merge onward:

| Directory | Route | Owner | Shared-face rules |
|---|---|---|---|
| `topologies/` | `/topologies` | #62 (SPEC-401), #63 inside it (SPEC-402 node inspector) | OWN everything below the dir |
| `monitor/` | `/monitor` | #64 (SPEC-403), #65 evidence drill-down + #66 CLI console enter from here | OWN everything below the dir |
| `lab/` | `/lab` | #67 (SPEC-406) | OWN everything below the dir |

Shared faces (route registry `src/app/routes.tsx`, dto barrel `src/api/`,
query key vocabulary `src/query/keys.ts`, CI workflows, E2E config) are
**additive-only** across tickets: adding a route = one registry entry + one
import; adding an API surface = one endpoint module + barrel export line.

- Cross-area reuse goes through explicit imports (SPEC-18 Q5: SPEC-403 owns
  the diagnosis/verify presentation components; SPEC-406 overlays scenario
  context on top of them).
- Each region owns its own api/dto feature files and its own query hooks;
  the hint→invalidation bridge (`src/query/invalidation.ts`) and the WS
  client (`src/ws/`) stay shared — never fork a second channel.
