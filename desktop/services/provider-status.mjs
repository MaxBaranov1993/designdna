import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PROVIDERS = [
  { id: "codex", command: "codex", args: ["--version"], auth: "chatgpt-or-api-key" },
  { id: "kimi", command: "kimi", args: ["--version"], auth: "account-or-api-key" },
];

async function inspect(definition) {
  try {
    const { stdout, stderr } = await execFileAsync(definition.command, definition.args, {
      timeout: 4_000,
      windowsHide: true,
    });
    return { ...definition, installed: true, version: String(stdout || stderr).trim().split("\n")[0] };
  } catch (error) {
    return { ...definition, installed: false, error: error.code === "ENOENT" ? "not-installed" : "unavailable" };
  }
}

export async function getProviderStatus() {
  return Promise.all(PROVIDERS.map(inspect));
}
