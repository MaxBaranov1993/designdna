import { spawn } from "node:child_process";

/* Рантаймы провайдеров. openai — HTTP по API-ключу (бинарника нет: «установлен»
 * = ключ сохранён); codex/claude — CLI, доступность проверяется реальным
 * запуском `--version` с таймаутом и кэшем: раньше installed был захардкожен. */
const PROVIDERS = [
  { id: "openai", auth: "api-key", model: "gpt-5.6-sol" },
  { id: "codex", auth: "cli", model: "codex", command: "codex", args: ["--version"], overrideEnv: "DESIGNDNA_CODEX" },
  { id: "claude", auth: "cli", model: "claude", command: "claude", args: ["--version"], overrideEnv: "DESIGNDNA_CLAUDE" },
];

export const PROBE_TIMEOUT_MS = 5_000;
export const PROBE_CACHE_MS = 60_000;

export function providerCommand(definition, {
  platform = process.platform,
  environment = process.env,
} = {}) {
  // Явный путь к бинарнику (как у codex/claude-серверов) — без шима cmd.exe
  if (definition.overrideEnv && environment[definition.overrideEnv]) {
    return { command: environment[definition.overrideEnv], args: definition.args };
  }
  if (platform !== "win32") return { command: definition.command, args: definition.args };
  // npm/global CLIs on Windows are commonly .cmd shims. execFile("codex")
  // does not resolve those shims, while cmd.exe does. Definitions are a fixed
  // internal allowlist, so no user-provided command reaches the shell.
  const shell = environment.ComSpec || environment.COMSPEC || "cmd.exe";
  const versionCommand = `${definition.command} ${definition.args.join(" ")}`;
  return { command: shell, args: ["/d", "/s", "/c", `chcp 65001>nul && ${versionCommand}`] };
}

/** Запуск `<cli> --version` с таймаутом: {installed, version, error}. */
export function probeCommand(definition, {
  platform = process.platform,
  environment = process.env,
  spawnImpl = spawn,
  timeoutMs = PROBE_TIMEOUT_MS,
} = {}) {
  const spec = providerCommand(definition, { platform, environment });
  return new Promise((resolve) => {
    let settled = false;
    let stdout = "";
    let stderr = "";
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    let child;
    try {
      child = spawnImpl(spec.command, spec.args, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"], env: environment });
    } catch (error) {
      finish({ installed: false, version: null, error: error.message });
      return;
    }
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* уже завершился */ }
      finish({ installed: false, version: null, error: `timeout after ${timeoutMs}ms` });
    }, timeoutMs);
    child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
    child.once("error", (error) => finish({ installed: false, version: null, error: error.message }));
    child.once("exit", (code) => {
      const version = stdout.trim().split(/\r?\n/).filter(Boolean).pop() || null;
      if (code === 0) finish({ installed: true, version, error: null });
      else finish({ installed: false, version: null, error: (stderr.trim() || stdout.trim() || `exit ${code}`).slice(0, 300) });
    });
  });
}

/* Кэш проб: providers:status дёргается при каждом открытии панели, а запуск
 * CLI на Windows — сотни миллисекунд. */
const probeCache = new Map();

export function resetProviderStatusCache() {
  probeCache.clear();
}

export async function getProviderStatus({
  hasCredential = () => false,
  now = Date.now,
  cacheMs = PROBE_CACHE_MS,
  probe = probeCommand,
  platform = process.platform,
  environment = process.env,
} = {}) {
  return Promise.all(PROVIDERS.map(async (provider) => {
    const { command, args, overrideEnv, ...publicFields } = provider;
    if (!command) {
      const configured = Boolean(hasCredential(provider.id));
      return { ...publicFields, installed: configured, checkedAt: now(), reason: configured ? null : "API-ключ не задан" };
    }
    const cached = probeCache.get(provider.id);
    if (cached && now() - cached.at < cacheMs) return { ...publicFields, ...cached.result, cached: true };
    const result = await probe({ command, args, overrideEnv }, { platform, environment });
    const entry = { at: now(), result: { installed: result.installed, version: result.version, reason: result.error, checkedAt: now() } };
    probeCache.set(provider.id, entry);
    return { ...publicFields, ...entry.result, cached: false };
  }));
}
