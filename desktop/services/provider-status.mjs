const PROVIDERS = [{ id: "openai", auth: "api-key", model: "gpt-5.6-sol" }];

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

export async function getProviderStatus() {
  return PROVIDERS.map((provider) => ({ ...provider, installed: true }));
}
