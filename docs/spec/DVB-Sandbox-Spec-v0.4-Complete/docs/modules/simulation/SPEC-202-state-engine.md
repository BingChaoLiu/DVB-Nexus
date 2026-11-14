# SPEC-202 — L0 State Engine and Topology Evaluation
Version 0.4.0 | DRAFT_FOR_REVIEW | Phase MVP

## Purpose
Evaluate logical topology and propagate state without generating TS bytes.

## Graph contract
Nodes have stable IDs, types, config and named ports. Connections identify `from_node/from_port` and `to_node/to_port`; a simple node-to-node pair is insufficient for multi-port components. Ports declare direction, media type and max connections.

## Validation
Reject duplicate IDs, missing endpoints/ports, output-to-output or input-to-input links, incompatible media types, cardinality violations, self-loops and cycles (MVP). Disconnected nodes are allowed and reported idle. Validation is non-mutating and returns path-addressed errors.

## Evaluation
Node evaluator is a pure function from node + input states + context to health, output states, metrics and causes. It performs no I/O, wall-clock reads, random operations or mutation of other nodes. Deterministic topological order uses node ID as tie-breaker. Severity precedence: error > warn > idle > ok. Downstream errors retain causal references to upstream root causes.

## Incremental mode
Full graph reevaluation is acceptable for MVP. If incremental evaluation is added, canonical output must equal full evaluation for identical input.

## Acceptance
- AC-202-01 endpoint, port, direction, type and cardinality validation.
- AC-202-02 cycle rejection and deterministic ordering.
- AC-202-03 same graph/config yields same state excluding operational timestamps.
- AC-202-04 downstream state carries causal references.
- AC-202-05 incremental and full evaluation equivalence if incremental mode exists.
