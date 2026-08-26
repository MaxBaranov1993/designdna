import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PROVIDERS = [
  { id: "codex", command: "codex", args: ["--version"], auth: "chatgpt-or-api-key" },
  { id: "kimi", command: "kimi", args: ["--version"], auth: "account-or-api-key" },
];

export function providerCommand(definition, {
  platform = process.platform,
  environment = process.env,
} = {}) {
  if (platform !== "win32") return { command: definition.command, args: definition.args };
  // npm/global CLIs on Windows are commonly .cmd shims. execFile("codex")
  // does not resolve those shims, while cmd.exe does. Definitions are a fixed
  // internal allowlist, so no user-provided command reaches the shell.
  const shell = environment.ComSpec || environment.COMSPEC || "cmd.exe";
  const versionCommand = `${definition.command} ${definition.args.join(" ")}`;
  return { command: shell, args: ["/d", "/s", "/c", `chcp 65001>nul && ${versionCommand}`] };
}

async function inspect(definition) {
  const spec = providerCommand(definition);
  try {
    const { stdout, stderr } = await execFileAsync(spec.command, spec.args, {
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
