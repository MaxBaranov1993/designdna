import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

/* Claude как провайдер генерации — через локальный Claude Code CLI.
 *
 * Подписочный OAuth живёт внутри самого Claude Code (его собственный `/login`),
 * поэтому DesignDNA никогда не видит и не хранит секрет: мы только проверяем,
 * что CLI установлен и залогинен, и запускаем одноразовый headless-запрос
 * (`claude -p`). Текстовые запросы выполняются без tools; изображения
 * передаются временными файлами с доступом только через Read. Codex
 * передаёт изображения нативными входами app-server image/localImage.
 */

const CLAUDE_MODEL = "opus";
/* Модели, которые принимает headless CLI. Неизвестное значение тихо падает
 * в дефолт: адаптер не должен ронять запрос из-за опечатки в маршруте. */
const CLAUDE_MODELS = new Set(["opus", "sonnet", "haiku"]);

export function claudeModel(value) {
  const model = String(value || "").trim().toLowerCase();
  return CLAUDE_MODELS.has(model) ? model : CLAUDE_MODEL;
}

/* Усилие → бюджет extended thinking. Claude не знает про medium|high|max —
 * это продуктовый контракт DesignDNA, поэтому маппинг живёт в одном месте. */
const THINKING_BUDGETS = { medium: 0, high: 8_000, max: 24_000 };

export function claudeEffortBudget(effort) {
  return Object.hasOwn(THINKING_BUDGETS, effort) ? THINKING_BUDGETS[effort] : THINKING_BUDGETS.medium;
}

/** Subscription chat must not inherit API credentials, gateway endpoints or
 * cloud-provider selectors. Match case-insensitively for Windows env keys.
 * This only builds the child environment; it never changes stored credentials
 * or CLI settings. OAuth remains available from env, app storage or CLI login. */
export function claudeSubscriptionEnvironment(environment, storedOAuthToken = null) {
  const env = {};
  let inheritedOAuthToken;
  for (const [key, value] of Object.entries(environment)) {
    const name = key.toUpperCase();
    if (name === "CLAUDE_CODE_OAUTH_TOKEN") {
      inheritedOAuthToken ??= value;
      continue;
    }
    if (name.startsWith("ANTHROPIC_")
      || name === "BASE_URL"
      || name === "AWS_BEARER_TOKEN_BEDROCK"
      || /^CLAUDE_CODE_(?:USE_(?:BEDROCK|VERTEX|FOUNDRY|ANTHROPIC_AWS)|SKIP_(?:BEDROCK|VERTEX|FOUNDRY)_AUTH)$/.test(name)) {
      continue;
    }
    env[key] = value;
  }
  const token = storedOAuthToken || inheritedOAuthToken;
  if (token) env.CLAUDE_CODE_OAUTH_TOKEN = token;
  return env;
}

function pathApiForPlatform(platform) {
  return platform === "win32" ? path.win32 : path.posix;
}

/* Официальный установщик Claude Code кладёт бинарь в ~/.local/bin, который
 * НЕ добавляется в PATH процесса Electron. Ищем сначала там, потом по PATH:
 * иначе на машине с установленным CLI запуск падал в cmd.exe с «"claude" не
 * является внутренней или внешней командой».
 *
 * platform вычисляется отдельно от host OS: desktop tests эмулируют Windows
 * на Linux/macOS, и discovery обязан строить Windows-пути в этой ситуации. */
export function claudeInstallPaths(
  environment = process.env,
  platform = environment.USERPROFILE && !environment.HOME ? "win32" : process.platform,
) {
  const home = environment.USERPROFILE || environment.HOME || "";
  if (!home) return [];
  const pathApi = pathApiForPlatform(platform);
  return [
    pathApi.join(home, ".local", "bin", "claude.exe"),
    pathApi.join(home, ".local", "bin", "claude"),
    pathApi.join(home, "AppData", "Local", "Programs", "claude", "claude.exe"),
  ];
}

function findClaudeBinary(environment, fileExists = existsSync, platform = process.platform) {
  const pathApi = pathApiForPlatform(platform);
  for (const candidate of claudeInstallPaths(environment, platform)) {
    if (fileExists(candidate)) return candidate;
  }
  const delimiter = platform === "win32" ? ";" : ":";
  for (const directory of String(environment.PATH || environment.Path || "").split(delimiter)) {
    if (!directory) continue;
    for (const candidate of [
      pathApi.join(directory, "claude.exe"),
      pathApi.join(directory, "claude"),
    ]) {
      if (fileExists(candidate)) return candidate;
    }
  }
  return null;
}

/* cmd.exe печатает собственные ошибки в OEM-кодировке (cp866), а не в UTF-8,
 * даже после chcp 65001 — из-за этого сообщение приходило кракозябрами. */
function decodeProcessOutput(buffer) {
  if (!Buffer.isBuffer(buffer)) return String(buffer || "");
  const utf8 = buffer.toString("utf8");
  if (!utf8.includes("�")) return utf8;
  for (const encoding of ["cp866", "windows-1251"]) {
    try {
      const decoded = new TextDecoder(encoding).decode(buffer);
      if (!decoded.includes("�")) return decoded;
    } catch { /* кодировка недоступна в этой сборке Node */ }
  }
  return utf8;
}

/** Спека запуска CLI. На Windows npm-шимы (.cmd) не резолвятся execFile —
 *  как и для Codex, падаем в cmd.exe с явной кодовой страницей UTF-8. */
export function claudeProcessSpec({
  platform = process.platform,
  environment = process.env,
  args = [],
  fileExists = existsSync,
} = {}) {
  if (environment.DESIGNDNA_CLAUDE) {
    return { command: environment.DESIGNDNA_CLAUDE, args, resolved: true };
  }
  const binary = findClaudeBinary(environment, fileExists, platform);
  if (binary) return { command: binary, args, resolved: true };
  if (platform === "win32") {
    const quoted = args.map((arg) => (!arg || /[\s"&|<>^]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg)).join(" ");
    return {
      command: environment.ComSpec || environment.COMSPEC || "cmd.exe",
      args: ["/d", "/s", "/c", `chcp 65001>nul && claude ${quoted}`],
      resolved: false,
    };
  }
  return { command: "claude", args, resolved: false };
}

/** Путь к файлу учётных данных Claude Code. */
export function claudeCredentialPaths(environment = process.env) {
  const home = environment.USERPROFILE || environment.HOME || "";
  if (!home) return [];
  return [
    path.join(home, ".claude", ".credentials.json"),
    path.join(home, ".config", "claude", ".credentials.json"),
  ];
}

/** Файл кредов может существовать с ПУСТЫМИ токенами (logout оставляет
 *  каркас) — «залогинен» значит непустой accessToken, а не наличие файла. */
export function claudeCredentialsValid(environment = process.env, readFile = readFileSync, fileExists = existsSync) {
  for (const file of claudeCredentialPaths(environment)) {
    if (!fileExists(file)) continue;
    try {
      const oauth = JSON.parse(String(readFile(file, "utf8")))?.claudeAiOauth;
      if (oauth && String(oauth.accessToken || "").length > 0) return true;
    } catch { /* битый файл = не залогинен */ }
  }
  return false;
}

const PROFILE_INSTRUCTIONS = {
  chat: "You are a design assistant. Answer the user in their language.",
  generator: "Generate the requested Design IR. The SYSTEM section below is the complete, authoritative design specification — follow it exactly, including the design craft rules and any locked Style DNA tokens: token colors (primary for CTAs and key accents, alternating background/surface sections) are mandatory, a plain white-and-grey wireframe is a failure.",
  quality_judge: "Evaluate the supplied Design IR exactly as requested.",
  quality_repair: "Repair the supplied Design IR exactly as requested.",
  editor: "Apply the requested visual edit to the supplied Design IR scope. The SYSTEM section below defines the exact output contract - follow it precisely and return only the JSON object it specifies. Do not generate a full page, do not restructure anything outside the selected scope.",
};

export class ClaudeAgentServer {
  constructor({ cwd, spawnProcess = spawn, environment = process.env, fileExists = existsSync, readFile = readFileSync, getStoredToken = null, imageTempRoot = tmpdir() } = {}) {
    this.cwd = cwd;
    this.spawnProcess = spawnProcess;
    this.environment = environment;
    this.fileExists = fileExists;
    this.readFile = readFile;
    this.imageTempRoot = path.resolve(imageTempRoot);
    // Долгоживущий OAuth-токен из safeStorage приложения (claude setup-token):
    // секрет живёт в main-процессе и уходит только в env спауна CLI.
    this.getStoredToken = getStoredToken;
  }

  #storedToken() {
    try { return String(this.getStoredToken?.() || "").trim() || null; } catch { return null; }
  }

  /** Статус подключения: бинарь найден + OAuth приложения, окружения или CLI. */
  account() {
    const spec = claudeProcessSpec({ environment: this.environment, fileExists: this.fileExists });
    const installed = Boolean(spec.resolved);
    const viaApp = Boolean(this.#storedToken());
    const viaEnv = Boolean(String(claudeSubscriptionEnvironment(this.environment).CLAUDE_CODE_OAUTH_TOKEN || "").trim());
    const loggedIn = viaApp || viaEnv || claudeCredentialsValid(this.environment, this.readFile, this.fileExists);
    const ready = installed && loggedIn;
    return {
      provider: "claude",
      installed,
      loggedIn,
      viaApp,
      viaEnv,
      ready,
      model: CLAUDE_MODEL,
      binary: installed ? spec.command : null,
      // Наличие файла кредов ещё не значит, что бинарь доступен: сообщаем
      // именно то, чего не хватает, а не общее «не подключён».
      hint: ready ? null
        : !installed ? "Claude CLI не найден. Установите Claude Code — бинарь ожидается в ~/.local/bin — либо задайте путь в DESIGNDNA_CLAUDE."
          : "Нажмите «Подключить Claude» — приложение проведёт вход само.",
    };
  }

  /** Вход из приложения: CLI-логин — интерактивный TUI, поэтому открываем
   *  НАСТОЯЩЕЕ окно терминала с `claude /login` (браузерный OAuth ведёт сам
   *  CLI и сам сохраняет креды). Приложению остаётся дождаться валидных
   *  кредов через waitForLogin(). */
  loginStart() {
    const spec = claudeProcessSpec({ environment: this.environment, fileExists: this.fileExists });
    if (!spec.resolved) throw new Error("Claude CLI не найден — установите Claude Code, затем подключайте.");
    const platform = this.environment.USERPROFILE && !this.environment.HOME ? "win32" : process.platform;
    if (platform === "win32") {
      const comspec = this.environment.ComSpec || this.environment.COMSPEC || "cmd.exe";
      // start: первый аргумент в кавычках — заголовок окна; /k держит окно
      // открытым, чтобы пользователь видел результат входа.
      // windowsVerbatimArguments обязателен: без него Node экранирует кавычки
      // (\"Claude Login\") и start принимал заголовок за имя файла — кнопка
      // «Подключить Claude» падала диалогом «Не удаётся найти "Claude Login"».
      const child = this.spawnProcess(comspec,
        ["/d", "/s", "/c", `start "Claude Login" ${comspec} /k "${spec.command}" /login`],
        { cwd: this.cwd, env: this.environment, stdio: "ignore", detached: true,
          windowsHide: false, windowsVerbatimArguments: true });
      child.unref?.();
    } else {
      const child = this.spawnProcess(spec.command, ["/login"],
        { cwd: this.cwd, env: this.environment, stdio: "ignore", detached: true });
      child.unref?.();
    }
    return { opened: true };
  }

  /** Дождаться завершения входа: креды становятся валидными, когда CLI
   *  сохранит OAuth после браузера. Poll — файловый, секретов не читаем. */
  async waitForLogin({ timeoutMs = 300_000, intervalMs = 3_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (claudeCredentialsValid(this.environment, this.readFile, this.fileExists)) return this.account();
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error("Вход не завершён за 5 минут. Завершите /login в окне терминала и нажмите «Проверить».");
  }

  /** Одноразовый headless-запрос. messages — тот же формат, что у Codex.
   *
   * Мультимодальные сообщения (content-массив с image_url data:-частями,
   * стандарт ChatRequestEnvelope) транспортируются файлами: CLI текстовый,
   * поэтому каждое изображение пишется во временный PNG, в промпт попадает
   * его путь, и ровно для таких запросов разрешается ОДИН инструмент Read.
   * Без изображений контракт прежний: без tools и файловых операций. */
  async chat(messages, { timeoutMs = 180_000, profile = "generator", effort = "medium", signal = null, model = null } = {}) {
    if (!Object.hasOwn(PROFILE_INSTRUCTIONS, profile)) {
      throw new Error(`Unsupported Claude chat profile: ${profile}`);
    }
    const status = this.account();
    if (!status.installed) throw new Error(status.hint);
    if (!status.loggedIn) {
      throw new Error("Claude не подключён. Требуется существующий OAuth-вход по подписке. Откройте Agents → Connections и нажмите «Подключить Claude».");
    }
    const { lines, imageFiles, cleanup } = this.materializeMessages(messages);
    const toolRule = imageFiles.length
      ? "Use the Read tool ONLY to view the image files listed in the messages. Do not run commands or use any other tool."
      : "Do not inspect files, run commands, or call tools.";
    const prompt = [
      `${PROFILE_INSTRUCTIONS[profile]} ${toolRule}${profile === "chat" ? "" : " Return only the JSON object."}`,
      ...lines,
      ...(profile === "chat" ? [] : ["Final response: return only the complete JSON object required above. No introduction, explanation, or Markdown fences."]),
    ].join("\n\n");

    const budget = claudeEffortBudget(effort);
    // Do not reload API keys, apiKeyHelper or cloud selectors from user,
    // project or local settings after sanitizing env. This preserves the
    // global OAuth credential location; --bare would disable OAuth entirely.
    const args = ["-p", "--output-format", "json", "--model", claudeModel(model), "--setting-sources", ""];
    if (imageFiles.length) args.push("--allowedTools", "Read");
    const spec = claudeProcessSpec({
      environment: this.environment, args, fileExists: this.fileExists,
    });
    const env = claudeSubscriptionEnvironment(this.environment, this.#storedToken());
    if (budget > 0) env.MAX_THINKING_TOKENS = String(budget);

    try {
      const raw = await this.#run(spec, { prompt, timeoutMs, env, signal });
      return this.#extract(raw);
    } finally {
      cleanup();
    }
  }

  /** Сообщения → строки промпта; image_url data:-части → временные PNG.
   *  Возвращает cleanup, удаляющий каталог с изображениями целиком. */
  materializeMessages(messages) {
    const lines = [];
    const imageFiles = [];
    let tempDir = null;
    const cleanup = () => {
      if (tempDir) { try { rmSync(tempDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 }); } catch { /* already removed or unavailable */ } }
    };
    try {
      for (const message of messages || []) {
        const role = String(message.role || "user").toUpperCase();
        const content = message.content;
        if (!Array.isArray(content)) {
          lines.push(`${role}:\n${String(content || "")}`);
          continue;
        }
        const pieces = [];
        for (const part of content) {
          if (part?.type === "image_url") {
            const url = String(part.image_url?.url || "");
            const match = /^data:image\/([a-z0-9.+-]+);base64,(.+)$/i.exec(url);
            if (!match) {
              // https-картинку CLI прочитать не может — честный отказ вместо
              // молчаливой потери визуального входа.
              throw new Error("Claude CLI transports only data:image base64 parts");
            }
            if (!tempDir) tempDir = mkdtempSync(path.join(this.imageTempRoot, "ddna-claude-img-"));
            const ext = match[1] === "jpeg" ? "jpg" : match[1];
            const file = path.join(tempDir, `image-${imageFiles.length + 1}.${ext}`);
            writeFileSync(file, Buffer.from(match[2], "base64"));
            imageFiles.push(file);
            pieces.push(`IMAGE FILE (view it with the Read tool): ${file}`);
          } else {
            pieces.push(String(part?.text || ""));
          }
        }
        lines.push(`${role}:\n${pieces.join("\n")}`);
      }
      return { lines, imageFiles, cleanup };
    } catch (error) {
      // chat() cannot run its finally until this method has returned cleanup.
      cleanup();
      throw error;
    }
  }

  #run(spec, { prompt, timeoutMs, env, signal }) {
    return new Promise((resolve, reject) => {
      const child = this.spawnProcess(spec.command, spec.args, {
        cwd: this.cwd,
        env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
      const stdoutChunks = [];
      const stderrChunks = [];
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

      child.stdout.on("data", (chunk) => { stdoutChunks.push(Buffer.from(chunk)); });
      child.stderr.on("data", (chunk) => { stderrChunks.push(Buffer.from(chunk)); });
      child.once("error", (error) => finish(new Error(`Claude CLI недоступен: ${error.message}`)));
      child.once("exit", (code) => {
        const stdout = decodeProcessOutput(Buffer.concat(stdoutChunks));
        if (code === 0) { finish(null, stdout); return; }
        // CLI кладёт настоящую причину в JSON-конверт на stdout (is_error+result),
        // а stderr при этом пуст — без разбора stdout пользователь видел голое
        // «завершился с кодом 1» вместо «выполните /login».
        let envelopeReason = "";
        try {
          const envelope = JSON.parse(stdout.trim());
          if (envelope && typeof envelope.result === "string") envelopeReason = envelope.result;
        } catch { /* не JSON — остаёмся со stderr */ }
        const detail = (envelopeReason
          || decodeProcessOutput(Buffer.concat(stderrChunks))).trim().slice(-1_000);
        if (/not recognized|не является|не найден|command not found|ENOENT/i.test(detail)) {
          finish(new Error("Claude CLI не найден в PATH. Установите Claude Code или задайте путь в DESIGNDNA_CLAUDE."));
          return;
        }
        finish(new Error(
          /login|authenticat|credential|unauthor/i.test(detail)
            ? "Claude не подключён. Откройте Agents → Connections и нажмите «Подключить Claude»."
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
