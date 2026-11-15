// SPEC-402 §7.4 / §11 (TV-402-02) 口径 A: 400 REQUEST_BODY_INVALID loc-chain
// → FieldError[] mapping. Envelope shape = SPEC-500 §6 path-addressed chain
// ({"errors":[{loc,msg,type},...]}, FastAPI default 422 overridden to 400 —
// brief §2.3). Wire names are asserted verbatim.
import { describe, expect, it } from "vitest";

import { mapLocChain } from "./locChain";

const NODES = ["gen-0", "gen-1", "mux-0"];

function chain(errors: unknown): unknown {
  return { errors };
}

describe("mapLocChain (SPEC-402 §7.4, TV-402-02)", () => {
  it("maps a node-addressed config loc to that node's form-root banner", () => {
    const errors = mapLocChain(
      chain([{ loc: ["body", "nodes", 1, "config"], msg: "Input should be a valid object", type: "invalid_type" }]),
      NODES,
    );
    expect(errors).toEqual([{ nodeId: "gen-1", fieldPath: "config", message: "Input should be a valid object" }]);
  });

  it("resolves deeper known descriptor paths (group)", () => {
    const errors = mapLocChain(
      chain([{ loc: ["body", "nodes", 0, "config", "program"], msg: "Field required", type: "missing" }]),
      NODES,
    );
    expect(errors).toEqual([{ nodeId: "gen-0", fieldPath: "program", message: "Field required" }]);
  });

  it("resolves concrete stream-row locs to the row-field descriptor path", () => {
    const errors = mapLocChain(
      chain([{ loc: ["body", "nodes", 0, "config", "program", "streams", 0, "pid"], msg: "Input should be a valid integer", type: "int_type" }]),
      NODES,
    );
    expect(errors).toEqual([
      { nodeId: "gen-0", fieldPath: "program.streams[].pid", message: "Input should be a valid integer" },
    ]);
  });

  it("loc stopping at the node index is node-level (fieldPath null)", () => {
    const errors = mapLocChain(chain([{ loc: ["body", "nodes", 2], msg: "Bad node", type: "value_error" }]), NODES);
    expect(errors).toEqual([{ nodeId: "mux-0", fieldPath: null, message: "Bad node" }]);
  });

  it("unmatched segments after config degrade to node-level (no invented fields)", () => {
    const errors = mapLocChain(
      chain([{ loc: ["body", "nodes", 0, "config", "something_unknown"], msg: "Unknown key", type: "extra_forbidden" }]),
      NODES,
    );
    expect(errors).toEqual([{ nodeId: "gen-0", fieldPath: null, message: "Unknown key" }]);
  });

  it("out-of-range node index degrades to graph level (mapper returns nothing — the page banner carries the envelope)", () => {
    const errors = mapLocChain(chain([{ loc: ["body", "nodes", 9, "config"], msg: "x", type: "y" }]), NODES);
    expect(errors).toEqual([]);
  });

  it("non-numeric node index degrades to graph level", () => {
    const errors = mapLocChain(chain([{ loc: ["body", "nodes", "zero", "config"], msg: "x", type: "y" }]), NODES);
    expect(errors).toEqual([]);
  });

  it("loc without a nodes segment degrades to graph level", () => {
    const errors = mapLocChain(chain([{ loc: ["body", "topology"], msg: "x", type: "y" }]), NODES);
    expect(errors).toEqual([]);
  });

  it("malformed details degrade entirely (never throws, never fabricates)", () => {
    expect(mapLocChain(null, NODES)).toEqual([]);
    expect(mapLocChain(undefined, NODES)).toEqual([]);
    expect(mapLocChain({}, NODES)).toEqual([]);
    expect(mapLocChain({ errors: "not-an-array" }, NODES)).toEqual([]);
    expect(mapLocChain(chain([{ no_loc: true }]), NODES)).toEqual([]);
    expect(mapLocChain(chain([{ loc: "flat-string", msg: "x" }]), NODES)).toEqual([]);
    expect(mapLocChain(chain("nope"), NODES)).toEqual([]);
  });

  it("maps every error entry in order; message is the verbatim msg (type only as fallback)", () => {
    const errors = mapLocChain(
      chain([
        { loc: ["body", "nodes", 0, "config"], msg: "first", type: "t1" },
        { loc: ["body", "nodes", 1], type: "t2" }, // no msg → type fallback
        { loc: ["body", "nodes", 2, "config"] }, // neither → empty message, still mapped
      ]),
      NODES,
    );
    expect(errors).toEqual([
      { nodeId: "gen-0", fieldPath: "config", message: "first" },
      { nodeId: "gen-1", fieldPath: null, message: "t2" },
      { nodeId: "mux-0", fieldPath: "config", message: "" },
    ]);
  });
});
