// Dump the live OpenAPI document (SPEC-400 §7.1 drift lock, step a).
//
// The dump is performed IN THIS TREE at run time — never from a committed
// snapshot (M5 brief §11 J10: the snapshot is an exploration artifact).
// The python side uses the exact brief §3.1 command shape (`python -I -c`
// with a cwd-relative sys.path.insert, which self-heals in any checkout);
// PYTHONPATH is additionally prepended with this tree's src (shared-venv
// trap, scripts/lib/python.mjs).
//
// Usage: node scripts/dump-openapi.mjs [output.json]   (default: stdout)
import { writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { envWithTreeSrc, resolvePython, TREE_ROOT } from "./lib/python.mjs";

const output = process.argv[2] ?? null;

// Keep this string in sync with the M5 brief §3.1 verified command.
// ensure_ascii stays at its True default: the dump travels through a spawned
// pipe whose encoding is locale-dependent (Windows cp936 vs CI UTF-8) — pure
// ASCII JSON is byte-identical on every platform, so the drift lock compares
// semantics, not console encodings (PR #81 dto-drift-lock red, 2026-11-15).
const DUMP_CODE = [
  "import json,sys",
  "sys.path.insert(0,'src')",
  "from api.app import create_app",
  "from api.routes import build_spec500_routers",
  "app = create_app(*build_spec500_routers(sessions_port=None, runs_port=None, artifacts_port=None))",
  "json.dump(app.openapi(), sys.stdout, indent=2)",
].join("; ");

const result = spawnSync(resolvePython(), ["-I", "-c", DUMP_CODE], {
  cwd: TREE_ROOT,
  encoding: "utf8",
  env: envWithTreeSrc({ PYTHONUTF8: "1" }),
});

if (result.status !== 0 || result.error) {
  console.error("dump-openapi: python failed:", result.stderr ?? result.error);
  process.exit(1);
}
try {
  JSON.parse(result.stdout);
} catch {
  console.error("dump-openapi: stdout is not valid JSON — interpreter or tree mismatch");
  console.error((result.stderr ?? "").slice(0, 2000));
  process.exit(1);
}
if (output) {
  writeFileSync(output, result.stdout, "utf8");
} else {
  process.stdout.write(result.stdout);
}
