import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFile } from "node:fs/promises";
import { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, session, shell } from "electron";
import { JsonlProcess } from "./lib/jsonl-process.mjs";
import { isAllowedRendererUrl } from "./lib/renderer-policy.mjs";
import { pythonWorkerEnvironment, pythonWorkerSpec } from "./lib/runtime-paths.mjs";
import { SerialRequestQueue } from "./lib/serial-request-queue.mjs";
import { CredentialStore } from "./services/credential-store.mjs";
import { SettingsStore } from "./services/settings-store.mjs";
import { getProviderStatus } from "./services/provider-status.mjs";
import { chatWithProvider } from "./services/provider-router.mjs";
import { getValidToken, importFromCli, kimiAccountStatus } from "./services/kimi-account.mjs";
import { CodexAppServer } from "./services/codex-app-server.mjs";
import { McpManager } from "./services/mcp-manager.mjs";
import { canonicalMcpSpec, createMcpActivationApprover } from "./services/mcp-activation-approval.mjs";
import { attachSourceAuthCookies, sourceAuthIntent, validateSourceAuthUrl } from "./services/source-auth.mjs";

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.resolve(desktopDirectory, "..");
const runtimeRoot = app.isPackaged ? process.resourcesPath : sourceRoot;
const repositoryRoot = path.resolve(process.env.DESIGNDNA_PROJECT_ROOT || (app.isPackaged ? app.getPath("documents") : sourceRoot));
const rendererEntry = path.join(runtimeRoot, "app", "static", "flow", "index.html");
const preload = path.join(desktopDirectory, "preload.cjs");
const repoCanvasWorkerEntry = app.isPackaged
  ? path.join(`${app.getAppPath()}.unpacked`, "workers", "repo-canvas-worker.mjs")
  : path.join(desktopDirectory, "workers", "repo-canvas-worker.mjs");

let pythonWorker;
let pythonInteractiveWorker;
let repoCanvasWorker;
let codex;
let credentials;
let settings;
let mcp;
let mcpActivation;
let approvalSequence = 0;
const mcpApprovals = new Map();
const codexRequests = new Map();
const pythonApiQueue = new SerialRequestQueue();
const pythonInteractiveQueue = new SerialRequestQueue();
const repoCanvasQueue = new SerialRequestQueue();
let prewarmed = false;

/* Прогрев: холодный старт Python-воркера (импорт FastAPI-стека) стоит ~1.5 с;
 * гоняем health-запрос обоим воркерам сразу после показа окна, чтобы первый
 * реальный вызов не платил этот тариф. Через очереди — чтобы не спорить с
 * пользовательскими запросами. */
function prewarmWorkers() {
  if (prewarmed) return;
  prewarmed = true;
  void pythonInteractiveQueue.run(() => pythonInteractiveWorker.request("health", {}, 30_000))
    .catch(() => undefined);
  void pythonApiQueue.run(() => pythonWorker.request("health", {}, 30_000))
    .catch(() => undefined);
}
const SOURCE_AUTH_PARTITION = "designdna-source-auth";
let sourceAuthWindow = null;
let quitting = false;

/* Кэш runtime.configure: одинаковые credentials не гоняем лишним JSONL-раундтрипом
 * перед каждым API-вызовом; spawnCount отличает перезапущенный воркер. */
const configureFingerprints = new Map();

/* Быстрые routes уходят на интерактивный воркер: они обязаны отвечать за десятки
 * миллисекунд даже когда длинный воркер минутами держит Source Import / reproduce.
 * project/* целиком на интерактивном — projects.db остаётся single-writer. */
const INTERACTIVE_API_PATHS = new Set([
  "/api/editor/assist",
  "/api/project/save",
  "/api/project/load",
  "/api/project/taste",
  "/api/config",
  "/api/cache/stats",
  "/api/quality-pass/codex-step",
  "/api/generate", // desktop-поток — это быстрые prepareOnly/rawOutputs-шаги
]);

// Captured source fonts live in userData/data/fonts and are unreachable from a
// file:// renderer ('/fonts/...' would resolve to the filesystem root). A
// privileged scheme serves them cross-origin with an explicit CORS header.
protocol.registerSchemesAsPrivileged([
  { scheme: "ddna", privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true } },
]);

const FONT_MIME = { ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf" };
const BLOB_MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webm": "video/webm" };

/* Блобы (inline data:image в node.data) исторически раздували localStorage до
 * десятков МБ: каждый бут парсит блоб целиком, каждый автосейв сериализует.
 * Десктоп выносит их в userData/data/blobs и кладёт в LS короткие ссылки
 * ddna://blobs/<name>; рендерер грузит их через тот же протокол. */
function blobsDir() {
  return path.join(app.getPath("userData"), "data", "blobs");
}

function safeBlobName(raw) {
  const name = path.basename(String(raw || ""));
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(name) ? name : null;
}

function registerFontsProtocol() {
  const fontsDir = path.join(app.getPath("userData"), "data", "fonts");
  protocol.handle("ddna", async (request) => {
    const url = new URL(request.url);
    if (url.host !== "fonts" && url.host !== "blobs") return new Response("not found", { status: 404 });
    const name = safeBlobName(decodeURIComponent(url.pathname.replace(/^\/+/, "")));
    if (!name) return new Response("bad name", { status: 400 });
    const dir = url.host === "fonts" ? fontsDir : blobsDir();
    const ext = path.extname(name).toLowerCase();
    try {
      const data = await readFile(path.join(dir, name));
      return new Response(data, {
        headers: {
          "Content-Type": (url.host === "fonts" ? FONT_MIME : BLOB_MIME)[ext] || "application/octet-stream",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "immutable",
        },
      });
    } catch {
      return new Response("not found", { status: 404 });
    }
  });
}

/* Точная политика доверенного renderer-URL: dev-сервер (когда задан
 * DESIGNDNA_RENDERER_URL) или ровно файл собранного renderer'а. Используется и
 * will-navigate, и проверкой IPC-отправителя — обе проверяют один список. */
const rendererDevUrl = process.env.DESIGNDNA_RENDERER_URL || "";
const rendererPolicy = { devUrl: rendererDevUrl, rendererEntry };

/* IPC принимаем только от главного фрейма нашего окна с доверенным URL:
 * iframe/гостевой фрейм или подменённая страница не должны дёргать привилегированные
 * каналы (mcp/codex/providers/api). */
function isTrustedSender(event) {
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window) return false;
  const frame = event.senderFrame;
  if (!frame || frame !== window.webContents.mainFrame) return false;
  return isAllowedRendererUrl(frame.url, rendererPolicy);
}

function handleTrusted(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!isTrustedSender(event)) throw new Error(`Untrusted IPC sender: ${channel}`);
    return handler(event, ...args);
  });
}

function broadcast(channel, payload) {
  for (const window of BrowserWindow.getAllWindows()) window.webContents.send(channel, payload);
}

function requestMcpApproval(payload) {
  const id = `mcp-${++approvalSequence}`;
  return new Promise((resolve) => {
    const timer = setTimeout(() => { mcpApprovals.delete(id); resolve(false); }, 120_000);
    mcpApprovals.set(id, { resolve, timer });
    broadcast("mcp:approval-requested", { id, ...payload });
  });
}

function createWorkers() {
  const python = pythonWorkerSpec({
    isPackaged: app.isPackaged,
    platform: process.platform,
    resourcesPath: process.resourcesPath,
    sourceRoot,
    pythonOverride: process.env.DESIGNDNA_PYTHON,
  });
  pythonWorker = new JsonlProcess({
    name: "DesignDNA Python runtime",
    command: python.command,
    args: python.args,
    cwd: repositoryRoot,
    env: pythonWorkerEnvironment({ isPackaged: app.isPackaged, runtimeRoot, userDataPath: app.getPath("userData") }),
    timeoutMs: 120_000,
  });
  // Editor Assist has a short prepare/finalize round-trip around the external
  // provider call. Keep it independent from multi-minute Source Import jobs;
  // the JSONL Python worker processes one request at a time.
  pythonInteractiveWorker = new JsonlProcess({
    name: "DesignDNA interactive Python runtime",
    command: python.command,
    args: python.args,
    cwd: repositoryRoot,
    env: pythonWorkerEnvironment({ isPackaged: app.isPackaged, runtimeRoot, userDataPath: app.getPath("userData") }),
    timeoutMs: 120_000,
  });
  repoCanvasWorker = new JsonlProcess({
    name: "Repo Canvas runtime",
    command: process.execPath,
    args: [repoCanvasWorkerEntry, repositoryRoot],
    cwd: repositoryRoot,
    env: { DESIGNDNA_PROJECT_ROOT: repositoryRoot, ELECTRON_RUN_AS_NODE: "1" },
    timeoutMs: 180_000,
  });
  codex = new CodexAppServer({ cwd: repositoryRoot });
  codex.on("notification", (message) => broadcast("codex:event", message));
  codex.on("request", async (message) => {
    if (message.method === "item/tool/call") {
      try {
        const toolResult = await mcp.callTool(message.params.tool, message.params.arguments, { source: "codex" });
        codex.respond(message.id, { contentItems: toolResult.content || [], success: toolResult.isError !== true });
      } catch (error) {
        codex.respond(message.id, { contentItems: [{ type: "text", text: error.message }], success: false });
      }
      return;
    }
    // Гигиена map'а: записи, на которые renderer не ответил (закрытый диалог),
    // не должны копиться вечно; рестарт codex-сервера обнуляет всё.
    if (codexRequests.size > 200) codexRequests.clear();
    codexRequests.set(String(message.id), message.method);
    broadcast("codex:request", message);
  });
  codex.on("serverError", () => codexRequests.clear());
  codex.on("serverError", (error) => broadcast("codex:event", { method: "desktop/error", params: { message: error.message } }));
}

function validateApiRequest(request) {
  const method = String(request?.method || "GET").toUpperCase();
  const rawPath = String(request?.path || "");
  const pathname = rawPath.split("?", 1)[0];
  if (!new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]).has(method)) throw new Error(`Unsupported API method: ${method}`);
  if (!pathname.startsWith("/api/") || pathname.includes("..")) throw new Error("Desktop bridge only accepts DesignDNA API paths");
  if (String(request?.body || "").length > 96 * 1024 * 1024) throw new Error("Desktop API request is too large");
  return { ...request, method, path: rawPath };
}

function sourceAuthSession() {
  return session.fromPartition(SOURCE_AUTH_PARTITION, { cache: false });
}

function openSourceAuthWindow(rawUrl) {
  const url = validateSourceAuthUrl(rawUrl);
  if (sourceAuthWindow && !sourceAuthWindow.isDestroyed()) {
    sourceAuthWindow.show();
    sourceAuthWindow.focus();
    void sourceAuthWindow.loadURL(url);
    return { opened: true };
  }
  sourceAuthWindow = new BrowserWindow({
    width: 1120,
    height: 820,
    title: "Source Login — DesignDNA",
    webPreferences: {
      partition: SOURCE_AUTH_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  const allowHttpNavigation = (event, nextUrl) => {
    try { validateSourceAuthUrl(nextUrl); } catch { event.preventDefault(); }
  };
  sourceAuthWindow.webContents.on("will-navigate", allowHttpNavigation);
  sourceAuthWindow.webContents.on("will-redirect", allowHttpNavigation);
  sourceAuthWindow.webContents.setWindowOpenHandler(({ url: popupUrl }) => {
    try { validateSourceAuthUrl(popupUrl); } catch { return { action: "deny" }; }
    return {
      action: "allow",
      overrideBrowserWindowOptions: {
        parent: sourceAuthWindow,
        webPreferences: {
          partition: SOURCE_AUTH_PARTITION,
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: true,
          webSecurity: true,
        },
      },
    };
  });
  sourceAuthWindow.on("closed", () => { sourceAuthWindow = null; });
  void sourceAuthWindow.loadURL(url);
  return { opened: true };
}

function registerIpc() {
  let mcpSaveQueue = Promise.resolve();
  handleTrusted("app:info", () => ({
    name: "DesignDNA",
    version: app.getVersion(),
    platform: process.platform,
    productionTransport: "ipc+stdio",
  }));
  handleTrusted("source-auth:open", (_event, { url }) => openSourceAuthWindow(url));
  handleTrusted("source-auth:clear", async () => {
    await sourceAuthSession().clearStorageData();
    return { cleared: true };
  });
  // Скачать бинарник (видео Motion и т.п.): в desktop нет HTTP, якорь href
  // "/api/.../download" под file:// не работает — сохраняем через диалог.
  // Отмена длинных задач (Source Import / reproduce минутами держат серийный
  // Python-воркер). Воркер stateless: честная отмена = рестарт процесса — все
  // ожидающие запросы длинной очереди отклоняются как cancelled, кэш и проект
  // живут в SQLite/файлах и переживают рестарт. configure-фингерпринт
  // сбрасывается автоматически через spawnCount.
  handleTrusted("api:cancel", () => {
    pythonWorker.abort("cancelled by user");
    return { cancelled: true };
  });
  // Вынос inline-блобов из localStorage: рендерер кладёт содержимое, LS хранит
  // только ddna://blobs/<name>. getMany возвращает ПОЛНЫЕ data:-URL обратно —
  // мост разворачивает их в исходящие /api-тела (кроме project/save), чтобы
  // серверный рендер (fidelity/QA) продолжал видеть картинки.
  handleTrusted("blobs:put", async (_event, { name, base64 }) => {
    const safe = safeBlobName(name);
    if (!safe) throw new Error("Invalid blob name");
    const { writeFile, mkdir } = await import("node:fs/promises");
    await mkdir(blobsDir(), { recursive: true });
    await writeFile(path.join(blobsDir(), safe), Buffer.from(String(base64 || ""), "base64"));
    return { stored: true, name: safe };
  });
  handleTrusted("blobs:getMany", async (_event, { names }) => {
    const out = {};
    for (const raw of Array.isArray(names) ? names.slice(0, 500) : []) {
      const safe = safeBlobName(raw);
      if (!safe) continue;
      try {
        const data = await readFile(path.join(blobsDir(), safe));
        const ext = path.extname(safe).toLowerCase();
        const mime = BLOB_MIME[ext] || "application/octet-stream";
        out[safe] = `data:${mime};base64,${data.toString("base64")}`;
      } catch {
        // отсутствующий блоб не должен ронять весь запрос
      }
    }
    return out;
  });
  handleTrusted("files:save", async (_event, { name, base64 }) => {
    const safeName = path.basename(String(name || "file")).replace(/[\\/:*?"<>|]/g, "_") || "file";
    const window = BrowserWindow.getAllWindows()[0];
    const result = await (window
      ? dialog.showSaveDialog(window, { defaultPath: safeName })
      : dialog.showSaveDialog({ defaultPath: safeName }));
    if (result.canceled || !result.filePath) return { saved: false };
    const { writeFile } = await import("node:fs/promises");
    await writeFile(result.filePath, Buffer.from(String(base64 || ""), "base64"));
    return { saved: true, path: result.filePath };
  });
  handleTrusted("api:request", (_event, request) => {
    const validatedRequest = validateApiRequest(request);
    const interactive = INTERACTIVE_API_PATHS.has(validatedRequest.path.split("?", 1)[0]);
    const queue = interactive ? pythonInteractiveQueue : pythonApiQueue;
    const worker = interactive ? pythonInteractiveWorker : pythonWorker;
    return queue.run(async () => {
      let preparedRequest = validatedRequest;
      const authIntent = sourceAuthIntent(validatedRequest);
      if (authIntent) {
        const cookies = await sourceAuthSession().cookies.get({ url: authIntent.url });
        preparedRequest = attachSourceAuthCookies(validatedRequest, cookies, authIntent.url);
      }
      // Keep provider credentials inside the trusted main/sidecar boundary.
      // Reconfigure only when the fingerprint (credentials + worker restart)
      // changed: identical configure round-trips before every call added ~30ms
      // of latency to each request.
      let kimiApiKey = "";
      if (credentials.has("kimi")) {
        // Best-effort: a token refresh failure must not break the API request;
        // the worker just runs without a Kimi key until re-import/re-login.
        try {
          kimiApiKey = await getValidToken(credentials);
        } catch (error) {
          console.warn(`Kimi token unavailable for api:request: ${error.message}`);
        }
      }
      const fingerprint = `${worker.spawnCount}:${kimiApiKey ? "kimi" : "-"}:${credentials.has("openai") ? "oa" : "-"}`;
      if (configureFingerprints.get(worker) !== fingerprint) {
        await worker.request("runtime.configure", {
          openaiApiKey: credentials.get("openai") || "",
          kimiApiKey,
        });
        configureFingerprints.set(worker, fingerprint);
      }
      // Source Import / generation pipelines legitimately take minutes
      // (Playwright captures multiple viewports, font downloads, LLM steps),
      // so the HTTP call gets a wider budget than the default worker timeout.
      const response = await worker.request("http.request", preparedRequest, interactive ? 120_000 : 600_000);
      // Бинарные тела отдаём как Uint8Array: structured clone переносит их
      // без base64, и рендерер не платит посимвольный atob-декод на мегабайтах
      if (response && response.encoding === "base64" && typeof response.body === "string") {
        return { ...response, body: Buffer.from(response.body, "base64") };
      }
      return response;
    });
  });
  handleTrusted("repo-canvas:snapshot", () => repoCanvasQueue.run(() => repoCanvasWorker.request("snapshot")));
  handleTrusted("repo-canvas:check", () => repoCanvasQueue.run(() => repoCanvasWorker.request("check")));
  // LLM-обновление архитектора занимает минуты — без очереди оно блокировало
  // снапшоты Project Map напрямую
  handleTrusted("repo-canvas:refresh", (_event, options) => repoCanvasQueue.run(() => repoCanvasWorker.request("architect.refresh", options || {}, 180_000)));
  handleTrusted("providers:status", async () => ({
    runtimes: await getProviderStatus(),
    credentials: credentials.status(),
    kimiAccount: kimiAccountStatus(credentials),
    encryptedStorage: credentials.available(),
  }));
  handleTrusted("providers:credentials", () => ({ configured: credentials.status(), encryptedStorage: credentials.available() }));
  handleTrusted("providers:set-credential", (_event, { provider, value }) => credentials.set(provider, value));
  handleTrusted("providers:delete-credential", (_event, { provider }) => credentials.delete(provider));
  // Import OAuth tokens from the Kimi CLI; returns account status only, never the tokens.
  handleTrusted("providers:import-kimi-cli", (_event) => importFromCli(credentials));
  handleTrusted("providers:chat", async (_event, { provider, messages, temperature, profile }) => {
    return chatWithProvider({ provider, messages, temperature, profile, codex, credentials });
  });
  handleTrusted("codex:account", () => codex.account());
  handleTrusted("codex:login", async (_event, { type }) => {
    const result = await codex.login({ type, apiKey: type === "apiKey" ? credentials.get("openai") : undefined });
    if (type === "chatgpt" && result?.authUrl) {
      const authUrl = new URL(result.authUrl);
      if (authUrl.protocol !== "https:") throw new Error("Codex returned an unsafe authentication URL");
      await shell.openExternal(authUrl.toString());
    }
    return result;
  });
  handleTrusted("codex:threads", (_event, params) => codex.listThreads(params || {}));
  handleTrusted("codex:start-thread", async (_event, params) => {
    await mcp.refresh();
    return codex.startThread({ cwd: repositoryRoot, ...params, dynamicTools: mcp.dynamicTools() });
  });
  handleTrusted("codex:resume-thread", (_event, { threadId }) => codex.resumeThread(String(threadId)));
  handleTrusted("codex:start-turn", (_event, params) => codex.startTurn(params));
  handleTrusted("codex:steer-turn", (_event, params) => codex.steerTurn(params));
  handleTrusted("codex:interrupt-turn", (_event, { threadId, turnId }) => codex.interruptTurn(String(threadId), String(turnId)));
  handleTrusted("codex:respond", (_event, { id, result }) => {
    const method = codexRequests.get(String(id));
    if (!method) throw new Error("Unknown or resolved Codex request");
    if (method.endsWith("requestApproval")) {
      const decision = result?.decision;
      if (!new Set(["accept", "acceptForSession", "decline", "cancel"]).has(decision)) throw new Error("Invalid approval decision");
    }
    codexRequests.delete(String(id));
    codex.respond(id, result);
    return { ok: true };
  });
  handleTrusted("mcp:list", () => settings.listMcpServers());
  handleTrusted("mcp:save", (_event, servers) => {
    const save = async () => {
    // Нативный approval ДО persist/запуска: диалог показывает канонический спек
    // исполняемого конфига (команды/args), и сохраняется ровно одобренное.
    const normalized = settings.validateMcpServers(servers);
    const accepted = await mcpActivation.ensureApproved(canonicalMcpSpec(normalized));
    if (!accepted) throw new Error("MCP configuration save declined by user");
    const saved = settings.saveMcpServers(normalized);
    return { servers: saved, statuses: await mcp.refresh() };
    };
    const pending = mcpSaveQueue.then(save, save);
    mcpSaveQueue = pending.catch(() => undefined);
    return pending;
  });
  handleTrusted("mcp:refresh", () => mcp.refresh());
  handleTrusted("mcp:tools", () => mcp.listTools());
  handleTrusted("mcp:call", (_event, { name, arguments: args }) => mcp.callTool(String(name), args || {}, { source: "user" }));
  handleTrusted("mcp:approval-response", (_event, { id, accepted }) => {
    const pending = mcpApprovals.get(String(id));
    if (!pending) return { ok: false };
    clearTimeout(pending.timer); mcpApprovals.delete(String(id)); pending.resolve(accepted === true); return { ok: true };
  });
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1500,
    height: 960,
    minWidth: 1080,
    minHeight: 700,
    title: "DesignDNA",
    backgroundColor: "#09090b",
    show: false,
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (new Set(["https:", "http:"]).has(new URL(url).protocol)) void shell.openExternal(url);
    return { action: "deny" };
  });
  const enforceRendererNavigation = (event, url) => {
    // Точная политика: разрешена только навигация на доверенный renderer-URL
    // (dev-сервер или файл entry); любые прочие file:/http(s) переходы блокируем.
    if (!isAllowedRendererUrl(url, rendererPolicy)) event.preventDefault();
  };
  window.webContents.on("will-navigate", enforceRendererNavigation);
  window.webContents.on("will-redirect", enforceRendererNavigation);
  window.once("ready-to-show", () => {
    window.show();
    prewarmWorkers();
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    console.error(`Renderer gone (${details.reason}): ${details.exitCode}`);
    // Белое окно без воркеров хуже перезагрузки страницы: перезагружаем
    if (!window.isDestroyed()) window.webContents.reload();
  });
  window.webContents.on("unresponsive", () => console.warn("Renderer unresponsive"));
  if (rendererDevUrl) void window.loadURL(rendererDevUrl);
  else void window.loadFile(rendererEntry);
}

app.whenReady().then(() => {
  registerFontsProtocol();
  credentials = new CredentialStore({ userDataPath: app.getPath("userData"), safeStorage });
  settings = new SettingsStore(app.getPath("userData"));
  mcpActivation = createMcpActivationApprover({
    showMessageBox: (options) => {
      const window = BrowserWindow.getAllWindows()[0];
      return window ? dialog.showMessageBox(window, options) : dialog.showMessageBox(options);
    },
  });
  mcp = new McpManager({ settings, credentials, cwd: repositoryRoot, approve: requestMcpApproval, approveActivation: (spec) => mcpActivation.ensureApproved(spec) });
  createWorkers();
  registerIpc();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Второй запуск фокусирует существующее окно вместо второго набора воркеров
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [window] = BrowserWindow.getAllWindows();
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
}

// await-завершение вместо fire-and-forget: отброшенные stop()-промисы не убивали
// детей на Windows и оставляли зомби-процессы python/repo-canvas после выхода
app.on("before-quit", (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault();
  codex?.stop();
  mcp?.stop();
  const stops = Promise.allSettled([
    pythonWorker?.stop(),
    pythonInteractiveWorker?.stop(),
    repoCanvasWorker?.stop(),
  ]);
  const forceExit = new Promise((resolve) => setTimeout(resolve, 3_000));
  void Promise.race([stops, forceExit]).then(() => app.exit(0));
});
