import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

/* Claude как провайдер генерации — через локальный Claude Code CLI.
 *
 * Подписочный OAuth живёт внутри самого Claude Code (его собственный `/login`),
 * поэтому DesignDNA никогда не видит и не хранит секрет: мы только проверяем,
 * что CLI установлен и залогинен, и запускаем одноразовый headless-запрос
 * (`claude -p`). Это тот же контракт, что у Codex: текстовый вход/выход,
 * без tools и без файловых операций.
 */

const CLAUDE_MODEL = "opus";

/* Усилие → бюджет extended thinking. Claude не знает про medium|high|max —
 * это продуктовый контракт DesignDNA, поэтому маппинг живёт в одном месте. */
const THINKING_BUDGETS = { medium: 0, high: 8_000, max: 24_000 };

export function claudeEffortBudget(effort) {
  return Object.hasOwn(THINKING_BUDGETS, effort) ? THINKING_BUDGETS[effort] : THINKING_BUDGETS.medium;
}

function findWindowsClaudeBinary(environment) {
  for (const directory of String(environment.PATH || environment.Path || "").split(path.delimiter)) {
    if (!directory) continue;
    for (const candidate of [
      path.join(directory, "claude.exe"),
      path.join(directory, "node_modules", "@anthropic-ai", "claude-code", "cli.js"),
      path.resolve(directory, "..", "@anthropic-ai", "claude-code", "cli.js"),
    ]) {
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

/** Спека запуска CLI. На Windows npm-шимы (.cmd) не резолвятся execFile —
 *  как и для Codex, падаем в cmd.exe с явной кодовой страницей UTF-8. */
export function claudeProcessSpec({
  platform = process.platform,
  environment = process.env,
  args = [],
} = {}) {
  if (environment.DESIGNDNA_CLAUDE) return { command: environment.DESIGNDNA_CLAUDE, args };
  if (platform === "win32") {
    const nativeBinary = findWindowsClaudeBinary(environment);
    if (nativeBinary && nativeBinary.endsWith(".exe")) return { command: nativeBinary, args };
    const quoted = args.map((arg) => (/[\s"&|<>^]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg)).join(" ");
    return {
      command: environment.ComSpec || environment.COMSPEC || "cmd.exe",
      args: ["/d", "/s", "/c", `chcp 65001>nul && claude ${quoted}`],
    };
  }
  return { command: "claude", args };
}

/** Путь к файлу учётных данных Claude Code (наличие = пользователь залогинен). */
export function claudeCredentialPaths(environment = process.env) {
  const home = environment.USERPROFILE || environment.HOME || "";
  if (!home) return [];
  return [
    path.join(home, ".claude", ".credentials.json"),
    path.join(home, ".config", "claude", ".credentials.json"),
  ];
}

const PROFILE_INSTRUCTIONS = {
  generator: "Generate the requested Design IR. The SYSTEM section below is the complete, authoritative design specification — follow it exactly, including the design craft rules and any locked Style DNA tokens: token colors (primary for CTAs and key accents, alternating background/surface sections) are mandatory, a plain white-and-grey wireframe is a failure.",
  quality_judge: "Evaluate the supplied Design IR exactly as requested.",
  quality_repair: "Repair the supplied Design IR exactly as requested.",
};

export class ClaudeAgentServer {
  constructor({ cwd, spawnProcess = spawn, environment = process.env, fileExists = existsSync } = {}) {
    this.cwd = cwd;
    this.spawnProcess = spawnProcess;
    this.environment = environment;
    this.fileExists = fileExists;
  }

  /** Статус подключения: бинарь найден + креды Claude Code на месте.
   *  Интерактивный вход из приложения не ведём — это работа самого CLI. */
  account() {
    const spec = claudeProcessSpec({ environment: this.environment });
    const usesShim = spec.command !== this.environment.DESIGNDNA_CLAUDE && !spec.command.endsWith("claude.exe");
    const installed = Boolean(this.environment.DESIGNDNA_CLAUDE)
      || !usesShim
      || Boolean(findWindowsClaudeBinary(this.environment))
      || process.platform !== "win32";
    const loggedIn = claudeCredentialPaths(this.environment).some((file) => this.fileExists(file));
    return {
      provider: "claude",
      installed,
      loggedIn,
      model: CLAUDE_MODEL,
      hint: loggedIn ? null : "Запустите `claude` в терминале и выполните /login, затем нажмите «Проверить».",
    };
  }

  /** Одноразовый headless-запрос. messages — тот же формат, что у Codex. */
  async chat(messages, { timeoutMs = 180_000, profile = "generator", effort = "medium", signal = null } = {}) {
    if (!Object.hasOwn(PROFILE_INSTRUCTIONS, profile)) {
      throw new Error(`Unsupported Claude chat profile: ${profile}`);
    }
    const prompt = [
      `${PROFILE_INSTRUCTIONS[profile]} Do not inspect files, run commands, or call tools. Return only the JSON object.`,
      ...messages.map((message) => `${String(message.role || "user").toUpperCase()}:\n${String(message.content || "")}`),
    ].join("\n\n");

    const budget = claudeEffortBudget(effort);
    const args = ["-p", "--output-format", "json", "--model", CLAUDE_MODEL];
    const spec = claudeProcessSpec({ environment: this.environment, args });
    const env = { ...this.environment };
    if (budget > 0) env.MAX_THINKING_TOKENS = String(budget);

    const raw = await this.#run(spec, { prompt, timeoutMs, env, signal });
    return this.#extract(raw);
  }

  #run(spec, { prompt, timeoutMs, env, signal }) {
    return new Promise((resolve, reject) => {
      const child = this.spawnProcess(spec.command, spec.args, {
        cwd: this.cwd,
        env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
      let stdout = "";
      let stderr = "";
      let settled = false;
      const finish = (error, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener?.("abort", onAbort);
        if (error) reject(error); else resolve(value);
      };
      const onAbort = () => { child.kill(); finish(new Error("Claude request cancelled")); };
      const timer = setTimeout(() => { child.kill(); finish(new Error("Claude generator timed out")); }, timeoutMs);
      signal?.addEventListener?.("abort", onAbort, { once: true });

      child.stdout.on("data", (chunk) => { stdout += chunk; });
      child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-4_000); });
      child.once("error", (error) => finish(new Error(`Claude CLI недоступен: ${error.message}`)));
      child.once("exit", (code) => {
        if (code === 0) { finish(null, stdout); return; }
        const detail = stderr.trim();
        finish(new Error(
          /login|authenticat|credential/i.test(detail)
            ? "Claude не подключён. Запустите `claude` в терминале и выполните /login."
            : `Claude CLI завершился с кодом ${code}${detail ? `: ${detail}` : ""}`,
        ));
      });
      child.stdin.end(prompt);
    });
  }

  /** `claude -p --output-format json` отдаёт конверт с полем result. */
  #extract(raw) {
    const text = String(raw || "").trim();
    if (!text) throw new Error("Claude generator returned an empty response");
    let envelope;
    try {
      envelope = JSON.parse(text);
    } catch {
      // Совместимость: если CLI отдал сырой текст, отдаём как есть.
      return text;
    }
    if (envelope && envelope.is_error === true) {
      throw new Error(String(envelope.result || "Claude generator failed"));
    }
    const output = typeof envelope?.result === "string"
      ? envelope.result
      : Array.isArray(envelope?.content)
        ? envelope.content.map((part) => String(part?.text || "")).join("")
        : "";
    if (!output.trim()) throw new Error("Claude generator returned an empty response");
    return output;
  }
}
