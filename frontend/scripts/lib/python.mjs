// Shared Python interpreter resolution for the frontend engineering scripts
// (SPEC-400 §4.5 / plan R6). The shared .venv trap (docs/agents/windows-shell.md):
// the main repo's editable install points at the MAIN repo src, so any script
// that must import THIS tree's bootstrap must prepend <tree>/src to PYTHONPATH.
// Resolution order:
//   1. DVBNEXUS_PYTHON env (explicit override)
//   2. <this tree>/.venv/...      (worktree-local venv, if a ticket creates one)
//   3. main repo shared .venv     (via git rev-parse --git-common-dir)
//   4. bare "python" on PATH
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
/** The REPO root (frontend's parent) — cwd for python invocations and the
 * PYTHONPATH anchor: THIS tree's src, never the shared-venv editable target. */
export const TREE_ROOT = path.resolve(FRONTEND_ROOT, "..");
const SRC = path.join(TREE_ROOT, "src");

function venvPython(venvRoot) {
  return process.platform === "win32"
    ? path.join(venvRoot, "Scripts", "python.exe")
    : path.join(venvRoot, "bin", "python");
}

function gitOutput(args) {
  const result = spawnSync("git", args, { cwd: TREE_ROOT, encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : null;
}

function mainRepoRoot() {
  const commonDir = gitOutput(["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  if (!commonDir) return null;
  return path.basename(commonDir) === ".git" ? path.dirname(commonDir) : commonDir;
}

export function resolvePython() {
  if (process.env.DVBNEXUS_PYTHON) return process.env.DVBNEXUS_PYTHON;
  const candidates = [
    venvPython(path.join(TREE_ROOT, ".venv")),
    ...(mainRepoRoot() ? [venvPython(path.join(mainRepoRoot(), ".venv"))] : []),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return "python";
}

export function envWithTreeSrc(extra = {}) {
  const existing = process.env.PYTHONPATH;
  const prepended = existing ? `${SRC}${path.delimiter}${existing}` : SRC;
  return { ...process.env, PYTHONPATH: prepended, ...extra };
}

export function runPythonCapture(args, opts = {}) {
  return spawnSync(resolvePython(), args, {
    cwd: TREE_ROOT,
    encoding: "utf8",
    ...opts,
  });
}
