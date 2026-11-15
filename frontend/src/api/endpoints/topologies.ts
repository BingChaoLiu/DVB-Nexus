// Topology face (SPEC-500 §4.1 topology routes, wired by ticket #80 over the
// SPEC-502 revision-row persistence; SPEC-401 §6.1 is the frontend consumer
// contract). Wire semantics pinned by the backend routes:
//
// - POST /topologies          → 201, server-assigned uuid4 topology_id, revision 1;
// - GET  /topologies?limit=   → id-ASC summaries (latest revision per id);
// - GET  /topologies/{id}?revision= → full DTO, default latest; 404
//   SIM_TOPOLOGY_NOT_FOUND on unknown id/revision;
// - PUT  /topologies/{id}     → 200, revision = latest + 1 (immutable append;
//   the client NEVER chooses the revision);
// - POST /topologies/{id}/validate?revision= → 200 {ok, violations[]} — a
//   path-addressed report over the STORED graph (ok=false reports; the
//   session VALIDATING stage is where rejection happens, SPEC-200 §6).
//
// Non-2xx throws ApiError (client core); errorCode HTTP_501 = the frozen
// "not wired" presentation branch.
import { client, unwrap } from "../client";
import type { components } from "../schema.gen";

export type TopologyNodeDTO = components["schemas"]["TopologyNodeDTO"];
export type TopologyPortDTO = components["schemas"]["TopologyPortDTO"];
export type TopologyConnectionDTO = components["schemas"]["TopologyConnectionDTO"];
export type TopologyCreateRequest = components["schemas"]["TopologyCreateRequest"];
export type TopologyDTO = components["schemas"]["TopologyDTO"];
export type TopologySummaryDTO = components["schemas"]["TopologySummaryDTO"];
export type TopologyValidationDTO = components["schemas"]["TopologyValidationDTO"];
export type TopologyViolationDTO = components["schemas"]["TopologyViolationDTO"];

export function createTopology(body: TopologyCreateRequest) {
  return unwrap<TopologyDTO>(client.POST("/api/v1/topologies", { body }));
}

export function listTopologies(limit?: number) {
  return unwrap<TopologySummaryDTO[]>(
    client.GET("/api/v1/topologies", {
      params: { query: limit === undefined ? {} : { limit } },
    }),
  );
}

export function getTopology(topologyId: string, revision?: number) {
  return unwrap<TopologyDTO>(
    client.GET("/api/v1/topologies/{topology_id}", {
      params: {
        path: { topology_id: topologyId },
        query: revision === undefined ? {} : { revision },
      },
    }),
  );
}

export function saveTopologyRevision(topologyId: string, body: TopologyCreateRequest) {
  return unwrap<TopologyDTO>(
    client.PUT("/api/v1/topologies/{topology_id}", {
      params: { path: { topology_id: topologyId } },
      body,
    }),
  );
}

export function validateTopology(topologyId: string, revision?: number) {
  return unwrap<TopologyValidationDTO>(
    client.POST("/api/v1/topologies/{topology_id}/validate", {
      params: {
        path: { topology_id: topologyId },
        query: revision === undefined ? {} : { revision },
      },
    }),
  );
}
