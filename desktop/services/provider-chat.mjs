import { getValidToken } from "./kimi-account.mjs";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  adaptEnvelopeForProvider,
  assertEnvelopeSupported,
  buildOpenAiCompatiblePayload,
  canonicalToolArguments,
  createEnvelope,
  ToolArgumentsError,
} from "./provider-envelope.mjs";

const KIMI_URL = "https://api.kimi.com/coding/v1/chat/completions";
const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
const GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions";
const GROK_URL = "https://api.x.ai/v1/chat/completions";
// Direct Z.AI GLM: общий OpenAI-совместимый v4 endpoint и (только по явному
// opt-in) coding-plan endpoint. Ключ Z.AI никогда не уходит на другой хост
// молча: coding-plan выбирается только через DESIGNDNA_ZAI_ENDPOINT=coding,
// произвольный override — только через DESIGNDNA_ZAI_URL.
const ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions";
const ZAI_CODING_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions";

function zaiUrl(environment) {
  const explicit = String(environment.DESIGNDNA_ZAI_URL || "").trim();
  if (explicit) return explicit;
  return String(environment.DESIGNDNA_ZAI_ENDPOINT || "").trim() === "coding" ? ZAI_CODING_URL : ZAI_URL;
}

const DEFAULT_TIMEOUT_MS = 180_000;

/* Все адаптеры принимают типизированный request envelope (см.
 * provider-envelope.mjs). Legacy-вызовы {messages, temperature, tools}
 * оборачиваются в envelope автоматически — параметры идут через одну точку
 * валидации, и ни одно поле не теряется молча: всё, что провайдер не
 * принимает, возвращается в result.transport.dropped с причиной.
 *
 * Отмена: внешний AbortSignal (signal) + envelope.timeoutMs объединяются в
 * один abort-сигнал; гонки отмены и таймаута дают структурную ошибку
 * {code: "PROVIDER_CANCELLED" | "PROVIDER_TIMEOUT"}. */

function envelopeFromCall(input) {
  if (input?.envelope) return input.envelope;
  return createEnvelope({
    ...(input || {}),
    messages: input?.messages,
    temperature: input?.temperature,
    tools: input?.tools ?? null,
  });
}

function abortSignalFor({ signal, timeoutMs }, timeoutLabel) {
  const timeout = timeoutMs || DEFAULT_TIMEOUT_MS;
  const signals = [AbortSignal.timeout(timeout)];
  if (signal) signals.push(signal);
  if (typeof AbortSignal.any === "function") return AbortSignal.any(signals);
  return signals[0];
}

function providerError(label, code, cause) {
  const error = new Error(`${label}: ${cause?.message || cause}`);
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}

function isAbort(signal, error) {
  return signal?.aborted || error?.name === "AbortError";
}

/** Привести envelope к провайдеру и собрать wire-payload. Единая точка,
 *  из которой возвращаются dropped-поля (явно, не молча). */
function preparePayload({ envelope, provider, defaultModel, jsonMode = false, environment, modelEnv }) {
  assertEnvelopeSupported(envelope, provider);
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, provider);
  const model = adapted.model || environment[modelEnv] || defaultModel;
  const built = buildOpenAiCompatiblePayload({ ...adapted, model }, provider, { defaultModel: model, jsonMode });
  return { adapted: { ...adapted, model }, payload: built.payload, dropped: [...dropped, ...built.dropped] };
}

async function postJson(url, body, { headers, signal, fetchImpl = fetch }) {
  const response = await fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
    error.status = response.status;
    error.body = data;
    throw error;
  }
  return data;
}

const MAX_TOOL_CALLS_PER_RESPONSE = 32;
const MAX_TOOL_CALL_FIELD_BYTES = 128;
const TOOL_FIELD_UTF8 = new TextEncoder();

function toolArgsError(label, field, reason) {
  const error = new Error(`${label}: invalid tool_call at ${field}: ${reason}`);
  error.code = "PROVIDER_TOOL_ARGS";
  error.field = field;
  return error;
}

function extractContent(data, label) {
  const message = data.choices?.[0]?.message || {};
  const content = String(message.content || "");
  let toolCalls = null;
  if (message.tool_calls != null && !Array.isArray(message.tool_calls)) {
    throw toolArgsError(label, "tool_calls", "must be an array");
  }
  if (Array.isArray(message.tool_calls) && message.tool_calls.length) {
    if (message.tool_calls.length > MAX_TOOL_CALLS_PER_RESPONSE) {
      throw toolArgsError(label, "tool_calls", `more than ${MAX_TOOL_CALLS_PER_RESPONSE} calls in one response`);
    }
    const seenIds = new Set();
    try {
      // Z.AI GLM-5.3 возвращает function.arguments ОБЪЕКТОМ — канонизируем в
      // deterministic JSON-строку; строки (OpenAI/xAI) проходят дословно.
      // Битые значения — громкая структурная ошибка ДО MCP-вызовов.
      toolCalls = message.tool_calls.map((call, callIndex) => {
        const at = `${label} tool_calls[${callIndex}]`;
        if (!call || typeof call !== "object" || Array.isArray(call)) {
          throw toolArgsError(label, `${at}`, "tool_call must be an object");
        }
        if (call.type != null && call.type !== "function") {
          throw toolArgsError(label, `${at}.type`, `unsupported tool_call type "${call.type}"`);
        }
        const fn = call.function;
        if (!fn || typeof fn !== "object" || Array.isArray(fn)) {
          throw toolArgsError(label, `${at}.function`, "must be an object");
        }
        for (const [key, value] of [["id", call.id], ["function.name", fn.name]]) {
          if (typeof value !== "string" || !value || TOOL_FIELD_UTF8.encode(value).length > MAX_TOOL_CALL_FIELD_BYTES) {
            throw toolArgsError(label, `${at}.${key}`, "must be a non-empty string ≤ 128 UTF-8 bytes");
          }
        }
        if (seenIds.has(call.id)) {
          throw toolArgsError(label, `${at}.id`, `duplicate tool_call id "${call.id}"`);
        }
        seenIds.add(call.id);
        return {
          id: call.id,
          name: fn.name,
          arguments: canonicalToolArguments(fn.arguments, `${at}.function.arguments`),
        };
      });
    } catch (error) {
      if (error instanceof ToolArgumentsError) {
        throw toolArgsError(label, error.field, error.message);
      }
      throw error;
    }
  }
  if (!content.trim() && !toolCalls) throw new Error(`${label} вернул пустой ответ`);
  return { content, toolCalls };
}

export async function chatWithKimi({ credentials, envelope = null, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env, signal }) {
  const request = envelope || envelopeFromCall({ messages, temperature });
  const token = await getValidToken(credentials, { fetchImpl });
  const { adapted, payload, dropped } = preparePayload({
    envelope: request, provider: "kimi", defaultModel: "k3",
    // kimi/k3 отвергает response_format (см. KIMI_LIMITS): JSON запрошен
    // самим промптом, форсировать его на wire нельзя — иначе каждый запрос
    // рискует HTTP 400 без recovery.
    jsonMode: false,
    environment, modelEnv: "DESIGNDNA_KIMI_MODEL",
  });
  let response;
  try {
    response = await postJson(environment.DESIGNDNA_KIMI_URL || KIMI_URL, payload, {
      headers: { Authorization: `Bearer ${token}` },
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }), fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) throw providerError("Kimi", signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    throw providerError("Kimi", "PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractContent(response, "Kimi");
  return { content, toolCalls, transport: { provider: "kimi", model: payload.model, dropped } };
}

export async function chatWithOpenAI({ credentials, envelope = null, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env, signal }) {
  const key = credentials.get("openai");
  if (!key) throw new Error("Нет OpenAI API key: добавьте его в Agents → Connections");
  const request = envelope || envelopeFromCall({ messages, temperature });
  const { adapted, payload, dropped } = preparePayload({
    envelope: request, provider: "openai", defaultModel: "gpt-5.6-sol", jsonMode: true,
    environment, modelEnv: "DESIGNDNA_OPENAI_MODEL",
  });
  let response;
  try {
    response = await postJson(environment.DESIGNDNA_OPENAI_URL || OPENAI_URL, payload, {
      headers: { Authorization: `Bearer ${key}` },
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }), fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) throw providerError("OpenAI", signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    throw providerError("OpenAI", "PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractContent(response, "OpenAI");
  return { content, toolCalls, transport: { provider: "openai", model: payload.model, dropped } };
}

/** GLM (Zhipu) — OpenAI-совместимый v4 endpoint. Поддерживает function
 *  calling: при tools возвращает tool_calls модели (arguments остаются
 *  JSON-строкой, как в протоколе OpenAI) — на этом строится MCP-цикл
 *  Agent Workspace. reasoning.effort → thinking enabled + reasoning_effort
 *  (GLM-5.3: low|high|max; legacy-значения нормализуются явно). */
export async function chatWithGlm({ credentials, envelope = null, messages, temperature = 0.8, tools = null, returnToolCalls = false, fetchImpl = fetch, environment = process.env, signal }) {
  const key = credentials.get("glm");
  if (!key) throw new Error("Нет GLM API key: добавьте его в Agents → Connections");
  const request = envelope || envelopeFromCall({ messages, temperature, tools });
  const { adapted, payload, dropped } = preparePayload({
    envelope: request, provider: "glm", defaultModel: "glm-5.3",
    // в tool-режиме JSON-режим ответа не запрашиваем: модель должна звать инструменты
    jsonMode: !(Array.isArray(request.tools) && request.tools.length),
    environment, modelEnv: "DESIGNDNA_GLM_MODEL",
  });
  let response;
  try {
    response = await postJson(environment.DESIGNDNA_GLM_URL || GLM_URL, payload, {
      headers: { Authorization: `Bearer ${key}` },
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }), fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) throw providerError("GLM", signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    throw providerError("GLM", "PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractContent(response, "GLM");
  return { content, toolCalls, transport: { provider: "glm", model: payload.model, dropped } };
}

/** Grok (xAI) — OpenAI-совместимый v1 endpoint, default grok-4.6.
 *  reasoning_effort: low|medium|high|xhigh (reasoning cannot be disabled);
 *  legacy canonical значения нормализуются явно в payload-builder'е.
 *  x-grok-conv-id: стабильный id конверсации (envelope/correlation id) для
 *  cache affinity — безопасно: это UUID запроса, не секрет. */
export async function chatWithGrok({ credentials, envelope = null, messages, temperature = 0.8, fetchImpl = fetch, environment = process.env, signal }) {
  const key = credentials.get("grok");
  if (!key) throw new Error("Нет Grok API key: добавьте его в Agents → Connections");
  const request = envelope || envelopeFromCall({ messages, temperature });
  const { adapted, payload, dropped } = preparePayload({
    envelope: request, provider: "grok", defaultModel: "grok-4.6", jsonMode: true,
    environment, modelEnv: "DESIGNDNA_GROK_MODEL",
  });
  const headers = { Authorization: `Bearer ${key}` };
  const convId = String(request.id || "").replace(/[^A-Za-z0-9-]/g, "").slice(0, 64);
  if (convId) headers["x-grok-conv-id"] = convId;
  let response;
  try {
    response = await postJson(environment.DESIGNDNA_GROK_URL || GROK_URL, payload, {
      headers,
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }), fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) throw providerError("Grok", signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    throw providerError("Grok", "PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractContent(response, "Grok");
  return { content, toolCalls, transport: { provider: "grok", model: payload.model, dropped } };
}

/** Direct Z.AI GLM — OpenAI-совместимый v4 endpoint на api.z.ai. Отдельный
 *  провайдер и отдельный креденшел от Zhipu (bigmodel.cn): ключи и хосты не
 *  смешиваются. Coding-plan endpoint — только явный opt-in
 *  (DESIGNDNA_ZAI_ENDPOINT=coding); reasoning.effort → thinking enabled +
 *  reasoning_effort (GLM-5.3: low|high|max; legacy-значения нормализуются явно). */
export async function chatWithZai({ credentials, envelope = null, messages, temperature = 0.8, tools = null, fetchImpl = fetch, environment = process.env, signal }) {
  const key = credentials.get("zai");
  if (!key) throw new Error("Нет Z.AI API key: добавьте его в Agents → Connections");
  const request = envelope || envelopeFromCall({ messages, temperature, tools });
  const { adapted, payload, dropped } = preparePayload({
    envelope: request, provider: "zai", defaultModel: "glm-5.3",
    // в tool-режиме JSON-режим ответа не запрашиваем: модель должна звать инструменты
    jsonMode: !(Array.isArray(request.tools) && request.tools.length),
    environment, modelEnv: "DESIGNDNA_ZAI_MODEL",
  });
  let response;
  try {
    response = await postJson(zaiUrl(environment), payload, {
      headers: { Authorization: `Bearer ${key}` },
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }), fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) throw providerError("Z.AI", signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    throw providerError("Z.AI", "PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractContent(response, "Z.AI");
  return { content, toolCalls, transport: { provider: "zai", model: payload.model, dropped } };
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

// Локальный ZCode CLI — ТОЛЬКО явный opt-in через ZCODE_CLI. Автоматический
// поиск установленного приложения (resources/glm/zcode.cjs) удалён: это
// приватный внутренний entry point GUI без стабильного CLI-контракта.
export function zcodeCliPath(environment = process.env) {
  const override = String(environment.ZCODE_CLI || "").trim();
  if (override && existsSync(override)) return override;
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

function runZcode(cli, args, { cwd, timeoutMs, environment = process.env, spawnImpl = spawn, signal }) {
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
    let settled = false;
    const settle = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      fn(value);
    };
    const timer = setTimeout(() => settle(reject, providerError("zcode", "PROVIDER_TIMEOUT", new Error(`таймаут ${timeoutMs}ms`))), timeoutMs);
    const onAbort = () => {
      child.kill();
      settle(reject, providerError("zcode", "PROVIDER_CANCELLED", new Error("cancelled")));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout?.on("data", (chunk) => { stdout += chunk.toString("utf-8"); });
    child.stderr?.on("data", (chunk) => { stderr += chunk.toString("utf-8"); });
    child.on("error", (error) => settle(reject, error));
    child.on("close", (code) => {
      const content = stdout.trim();
      if (code !== 0 || !content) {
        settle(reject, new Error(`zcode: exit ${code}: ${(stderr.trim() || "пустой ответ").slice(-300)}`));
        return;
      }
      settle(resolve, content);
    });
  });
}

/** Генерация через локальный ZCode CLI (учётка ZCode, без API-ключей).
 *  Промпт уходит в TASK.md во временной папке, ответ — stdout CLI.
 *  Параметры, которые CLI-транспорт не умеет (tools/response_format/...),
 *  отсекаются ЯВНО: hard-поля падают ошибкой, temperature — со ссылкой в
 *  transport.dropped. */
export async function chatWithZcode({ envelope = null, messages, timeoutMs = 180_000, environment = process.env, spawnImpl = spawn, ensureConfig = zcodeEnsureConfig, signal }) {
  const cli = ensureConfig(environment);
  if (!cli) throw new Error("ZCode CLI не найден или не включён: автоматический поиск установленного приложения удалён — задайте ZCODE_CLI с полным путём к zcode.cjs и выполните login Z.AI");
  const request = envelope || envelopeFromCall({ messages });
  assertEnvelopeSupported(request, "zcode");
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(request, "zcode");
  const dir = await mkdtemp(path.join(os.tmpdir(), "zcode-task-"));
  try {
    const task = wireTaskMarkdown(adapted);
    await writeFile(path.join(dir, "TASK.md"), task, "utf-8");
    const content = await runZcode(cli, ["--prompt", ZCODE_TASK_PROMPT, "--cwd", dir, "--disallowed-tools", ZCODE_DENY_TOOLS], {
      cwd: dir,
      timeoutMs: Math.max(adapted.timeoutMs || timeoutMs, ZCODE_MIN_TIMEOUT_MS) + ZCODE_BOOT_GRACE_MS,
      environment, spawnImpl, signal,
    });
    return { content, toolCalls: null, transport: { provider: "zcode", model: null, dropped } };
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}

/** TASK.md из envelope: system отдельной секцией, мультимодальные части —
 *  текстом (CLI-транспорт текстовый). */
function wireTaskMarkdown(envelope) {
  const parts = [];
  if (envelope.system) parts.push(`### SYSTEM\n${envelope.system}`);
  for (const message of envelope.messages) {
    const text = (message.content || [])
      .map((part) => (part.type === "text" ? part.text : part.type === "image_url" ? "[image attached]" : ""))
      .filter(Boolean)
      .join("\n");
    if (text.trim()) parts.push(`### ${message.role.toUpperCase()}\n${text}`);
  }
  return parts.join("\n\n");
}
