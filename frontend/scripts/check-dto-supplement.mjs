// DTO supplement shrink-only check (SPEC-400 §7.1 drift lock, step c).
//
// The supplement (src/api/dto-supplement.ts) hand-writes the response models
// that are NOT reachable from today's OpenAPI. When the backend wires a model
// into OpenAPI (M5 companion ticket scope), the supplement entry MUST be
// deleted and the generated type used instead. This script fails with the
// exact names to delete when the intersection is non-empty.
//
// Usage: node scripts/check-dto-supplement.mjs <openapi-dump.json>
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dumpPath = process.argv[2];
if (!dumpPath) {
  console.error("usage: node scripts/check-dto-supplement.mjs <openapi-dump.json>");
  process.exit(2);
}

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dump = JSON.parse(readFileSync(dumpPath, "utf8"));
const schemaNames = new Set(Object.keys(dump?.components?.schemas ?? {}));
if (schemaNames.size === 0) {
  console.error("check-dto-supplement: dump has no components.schemas — bad dump?");
  process.exit(2);
}

const supplementSource = readFileSync(
  path.join(frontendRoot, "src", "api", "dto-supplement.ts"),
  "utf8",
);
const exported = [...supplementSource.matchAll(/^export type (\w+)/gm)].map((m) => m[1]);
if (exported.length === 0) {
  console.error("check-dto-supplement: no `export type` declarations found — parse drift?");
  process.exit(2);
}

const nowReachable = exported.filter((name) => schemaNames.has(name));
if (nowReachable.length > 0) {
  console.error(
    "DTO supplement drift: the following models are now reachable from OpenAPI " +
      "and MUST be deleted from src/api/dto-supplement.ts (use the generated " +
      "components['schemas'] types instead):\n  " +
      nowReachable.join("\n  "),
  );
  process.exit(1);
}
console.log(
  `dto-supplement OK: ${exported.length} supplement entries, none reachable from ` +
    `OpenAPI (${schemaNames.size} schemas).`,
);
