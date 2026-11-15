// E2E backend server (SPEC-400 §7.3): uvicorn over the tree's ASGI entry.
// The interpreter resolves via scripts/lib/python.mjs (env override → tree
// .venv → main-repo shared .venv → PATH) and PYTHONPATH is forced to THIS
// tree's src — the shared-venv editable install points at the MAIN repo src
// and would silently serve the wrong tree without it.
// Playwright owns the lifecycle (webServer url: /api/v1/version readiness).
//
// WS serving prerequisite: uvicorn's ws="auto" needs `websockets` (or
// wsproto) INSTALLED or every WS handshake is refused with 404 — the
// in-process TestClient never exercised real WS handshakes, so the project
// venv historically lacked it (SPEC-501 serving face). This script fails
// fast with the exact fix; CI installs it as a declared workflow step.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { envWithTreeSrc, resolvePython, TREE_ROOT } from "./lib/python.mjs";

const python = resolvePython();
const wsCheck = spawnSync(python, ["-I", "-c", "import websockets"], { encoding: "utf8" });
if (wsCheck.status !== 0) {
  console.error(
    `[start-backend] WS serving library missing: \`${python} -c "import websockets"\` failed.\n` +
      "uvicorn refuses all WebSocket handshakes (404) without it.\n" +
      `Fix: ${python} -m pip install "websockets>=14,<16"  (CI does this as a declared workflow step;\n` +
      " pinned <16 because uvicorn 0.54's websockets impl imports the legacy API removed in 16)",
  );
  process.exit(2);
}

const host = process.env.DVBNEXUS_HOST ?? "127.0.0.1";
const port = process.env.DVBNEXUS_PORT ?? "8765";
const dbPath =
  process.env.DVBNEXUS_DB_PATH ??
  path.join(mkdtempSync(path.join(tmpdir(), "dvbnexus-e2e-")), "dvbnexus.db");

const child = spawn(
  python,
  ["-m", "uvicorn", "bootstrap.asgi:app", "--host", host, "--port", port, "--log-level", "warning"],
  {
    cwd: TREE_ROOT,
    env: envWithTreeSrc({ DVBNEXUS_DB_PATH: dbPath, DVBNEXUS_PORT: port, DVBNEXUS_HOST: host }),
    stdio: "inherit",
  },
);

const shutdown = () => {
  child.kill();
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
child.on("exit", (code) => process.exit(code ?? 0));
