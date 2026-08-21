import { getValidToken } from "./kimi-account.mjs";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const KIMI_URL = "https://api.kimi.com/coding/v1/chat/completions";
const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
const GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions";

function cleanMessages(messages) {
  if (!Array.isArray(messages) || !messages.length) throw new Error("Provider messages are required");
  return messages.map((message) => {
    const role = String(message?.role || "");
    const content = String(message?.content || "");
    if (!new Set(["system", "user", "assistant"]).has(role) || !content.trim()) {
      throw new Error("Invalid provider message");
    }
    return { role, content };
  });
}

export async function chatWithKimi({ credentials, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env }) {
  // Resolves a plain API key as-is or a fresh OAuth access token (refreshing
  // and persisting rotated tokens when needed).
  const token = await getValidToken(credentials, { fetchImpl });
  const payload = {
    model: environment.DESIGNDNA_KIMI_MODEL || "k3",
    messages: cleanMessages(messages),
    // K3 on the managed coding endpoint rejects any temperature other than 1
    // ("only 1 is allowed for this model") — let the server default apply.
    response_format: { type: "json_object" },
  };
  const url = environment.DESIGNDNA_KIMI_URL || KIMI_URL;
  const post = (body) => fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  });
  let response = await post(payload);
  if (response.status === 400) {
    // Some models reject response_format — retry once without it.
    const { response_format, ...withoutFormat } = payload;
    response = await post(withoutFormat);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Kimi HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const content = String(data.choices?.[0]?.message?.content || "");
  if (!content.trim()) throw new Error("Kimi вернул пустой ответ");
  return content;
}

export async function chatWithOpenAI({ credentials, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env }) {
  const key = credentials.get("openai");
  if (!key) throw new Error("Нет OpenAI API key: добавьте его в Agents → Connections");
  const payload = {
    model: environment.DESIGNDNA_OPENAI_MODEL || "gpt-5.6-sol",
    messages: cleanMessages(messages),
    temperature: Math.max(0, Math.min(1, Number(temperature) || 0)),
    response_format: { type: "json_object" },
  };
  const response = await fetchImpl(environment.DESIGNDNA_OPENAI_URL || OPENAI_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180_000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`OpenAI HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const content = String(data.choices?.[0]?.message?.content || "");
  if (!content.trim()) throw new Error("OpenAI вернул пустой ответ");
  return content;
}

/** GLM (Zhipu) — OpenAI-совместимый v4 endpoint. Поддерживает function
 *  calling: при tools + returnToolCalls возвращает tool_calls модели
 *  (arguments остаются JSON-строкой, как в протоколе OpenAI) — на этом
 *  строится MCP-цикл Agent Workspace. */
export async function chatWithGlm({ credentials, messages, temperature = 0.8, tools = null, returnToolCalls = false, fetchImpl = fetch, environment = process.env }) {
  const key = credentials.get("glm");
  if (!key) throw new Error("Нет GLM API key: добавьте его в Agents → Connections");
  // в tool-режиме JSON-режим ответа не запрашиваем: модель должна уметь звать инструменты
  const wantsTools = Array.isArray(tools) && tools.length > 0;
  const payload = {
    model: environment.DESIGNDNA_GLM_MODEL || "glm-5.3",
    messages: cleanMessages(messages),
    temperature: Math.max(0, Math.min(1, Number(temperature) || 0)),
    ...(wantsTools ? { tools } : { response_format: { type: "json_object" } }),
  };
  const post = (body) => fetchImpl(environment.DESIGNDNA_GLM_URL || GLM_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  });
  let response = await post(payload);
  if (response.status === 400 && payload.response_format) {
    const { response_format, ...withoutFormat } = payload;
    response = await post(withoutFormat);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`GLM HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
  const message = data.choices?.[0]?.message || {};
  const content = String(message.content || "");
  const toolCalls = Array.isArray(message.tool_calls) && message.tool_calls.length
    ? message.tool_calls.map((call) => ({
      id: String(call.id || ""),
      name: String(call.function?.name || ""),
      arguments: String(call.function?.arguments || "{}"),
    }))
    : null;
  if (!content.trim() && !toolCalls) throw new Error("GLM вернул пустой ответ");
  if (returnToolCalls) return { content, toolCalls };
  if (toolCalls) throw new Error(`GLM запросил инструменты (${toolCalls.map((c) => c.name).join(", ")}), но этот вызов их не поддерживает`);
  return content;
}

// --- ZCode CLI (без ключа): локальный авторизованный ZCode, coding plan Z.AI ---

// Полный промпт лежит в TASK.md: командная строка Windows ограничена ~32К.
const ZCODE_TASK_PROMPT = [
  "Read the file TASK.md in the current working directory and complete",
  "the task it describes. Output only the final answer the task requires,",
  "nothing else. Do not read, create or modify any other files.",
].join(" ");

// Чистая генерация текста: гасим все инструменты, кроме Read (TASK.md/вложения).
const ZCODE_DENY_TOOLS = [
  "Bash Edit Write Glob Grep Agent Task WebFetch WebSearch TodoWrite Skill",
  "SendMessage CronCreate CronDelete CronList CronUpdate TaskOutput TaskStop",
  "EnterPlanMode ExitPlanMode AskUserQuestion",
].join(" ");

const ZCODE_MODEL_PREFERENCE = ["GLM-5.3", "GLM-5.2", "GLM-5-Turbo"];
const ZCODE_BOOT_GRACE_MS = 45_000;
// Пол agent-цикла CLI медленнее прямого API и высоковариативен (60–285с на
// полную генерацию IR) — не даём коротким таймаутам ролей убивать генерации.
const ZCODE_MIN_TIMEOUT_MS = 420_000;

export function zcodeCliPath(environment = process.env) {
  const override = String(environment.ZCODE_CLI || "").trim();
  if (override && existsSync(override)) return override;
  const localappdata = String(environment.LOCALAPPDATA || "");
  if (localappdata) {
    const candidate = path.join(localappdata, "Programs", "ZCode", "resources", "glm", "zcode.cjs");
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** HOME для файлов ZCode: env (USERPROFILE/HOME) → os.homedir(). */
function zcodeHomeDir(environment = process.env) {
  return String(environment.USERPROFILE || environment.HOME || os.homedir());
}

/** CLI на месте и login Z.AI есть; идемпотентно бутстрапит
 *  ~/.zcode/cli/config.json из v2-конфига (там лежит подключённый план). */
export function zcodeEnsureConfig(environment = process.env) {
  const cli = zcodeCliPath(environment);
  if (!cli) return null;
  const home = zcodeHomeDir(environment);
  if (!existsSync(path.join(home, ".zcode", "v2", "credentials.json"))) return null;
  const configPath = path.join(home, ".zcode", "cli", "config.json");
  if (existsSync(configPath)) return cli;
  const v2Path = path.join(home, ".zcode", "v2", "config.json");
  if (!existsSync(v2Path)) return null;
  try {
    const v2 = JSON.parse(readFileSync(v2Path, "utf-8"));
    const ranked = Object.entries(v2.provider || {})
      .filter(([, provider]) => Object.keys(provider.models || {}).length && provider.options?.baseURL)
      .sort((a, b) => {
        const rank = ([id, provider]) => (id.includes("coding-plan") && provider.enabled ? 0 : 1);
        return rank(a) - rank(b) || a[0].localeCompare(b[0]);
      });
    if (!ranked.length) return null;
    const [providerId, provider] = ranked[0];
    const models = Object.keys(provider.models);
    const model = ZCODE_MODEL_PREFERENCE.find((candidate) => models.includes(candidate)) || models[0];
    const config = { provider: { [providerId]: provider }, model: { main: `${providerId}/${model}` } };
    mkdirSync(path.dirname(configPath), { recursive: true });
    writeFileSync(configPath, JSON.stringify(config, null, 2), "utf-8");
    return cli;
  } catch {
    return null;
  }
}

function runZcode(cli, args, { cwd, timeoutMs, environment = process.env, spawnImpl = spawn }) {
  return new Promise((resolve, reject) => {
    const node = String(environment.ZCODE_NODE || "").trim() || "node";
    let child;
    try {
      child = spawnImpl(node, [cli, ...args], { cwd, windowsHide: true });
    } catch (error) {
      reject(error);
      return;
    }
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`zcode: таймаут ${timeoutMs}ms`));
    }, timeoutMs);
    child.stdout?.on("data", (chunk) => { stdout += chunk.toString("utf-8"); });
    child.stderr?.on("data", (chunk) => { stderr += chunk.toString("utf-8"); });
    child.on("error", (error) => { clearTimeout(timer); reject(error); });
    child.on("close", (code) => {
      clearTimeout(timer);
      const content = stdout.trim();
      if (code !== 0 || !content) {
        reject(new Error(`zcode: exit ${code}: ${(stderr.trim() || "пустой ответ").slice(-300)}`));
        return;
      }
      resolve(content);
    });
  });
}

/** Генерация через локальный ZCode CLI (учётка ZCode, без API-ключей).
 *  Промпт уходит в TASK.md во временной папке, ответ — stdout CLI. */
export async function chatWithZcode({ messages, timeoutMs = 180_000, environment = process.env, spawnImpl = spawn, ensureConfig = zcodeEnsureConfig }) {
  const cli = ensureConfig(environment);
  if (!cli) throw new Error("ZCode CLI не найден или не авторизован: выполните вход в приложение ZCode");
  const cleaned = cleanMessages(messages);
  const dir = await mkdtemp(path.join(os.tmpdir(), "zcode-task-"));
  try {
    const task = cleaned
      .map((message) => `### ${message.role.toUpperCase()}\n${message.content}`)
      .join("\n\n");
    await writeFile(path.join(dir, "TASK.md"), task, "utf-8");
    return await runZcode(cli, ["--prompt", ZCODE_TASK_PROMPT, "--cwd", dir, "--disallowed-tools", ZCODE_DENY_TOOLS],
      { cwd: dir, timeoutMs: Math.max(timeoutMs, ZCODE_MIN_TIMEOUT_MS) + ZCODE_BOOT_GRACE_MS, environment, spawnImpl });
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}
