import { existsSync } from "node:fs";
import path from "node:path";

export function resolveBuildPython({
  projectRoot,
  platform = process.platform,
  environment = process.env,
  exists = existsSync,
} = {}) {
  const configured = String(environment.DESIGNDNA_BUILD_PYTHON || "").trim();
  if (configured) return configured;

  const projectPython = platform === "win32"
    ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
    : path.join(projectRoot, ".venv", "bin", "python");
  if (exists(projectPython)) return projectPython;

  return platform === "win32" ? "python" : "python3";
}
