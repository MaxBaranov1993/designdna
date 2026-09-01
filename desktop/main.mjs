import { createHash } from "node:crypto";
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
import { chatWithProvider, resolveProvider } from "./services/provider-router.mjs";
import { ClaudeAgentServer } from "./services/claude-agent-server.mjs";
import { createEnvelope, EnvelopeValidationError, redactForLog, UnsupportedCapabilityError } from "./services/provider-envelope.mjs";
import { CodexAppServer } from "./services/codex-app-server.mjs";
import { McpManager } from "./services/mcp-manager.mjs";
import { canonicalMcpSpec, createMcpActivationApprover } from "./services/mcp-activation-approval.mjs";
import { ApiScheduler } from "./services/api-scheduler.mjs";
import { attachSourceAuthCookies, sourceAuthIntent, validateSourceAuthUrl } from "./services/source-auth.mjs";
import { putContentAddressedBlob, readBlobBatch, readBlobObject, safeBlobName } from "./services/blob-store.mjs";
import { LiveCommandRegistry } from "./services/live-command-registry.mjs";
import { LiveProjectApiSync } from "./services/live-project-api-sync.mjs";
import { assertBaseRevision, classifyActionAccess } from "./services/live-command-contract.mjs";
import { RendererCommandBridge } from "./services/renderer-command-bridge.mjs";
import { LiveCommandPipeServer } from "./services/live-command-pipe-server.mjs";

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
let claude;
let credentials;
let settings;
let mcp;
let mcpActivation;
let liveCommands;
let liveProjects;
let rendererCommands;
let liveCommandPipe;
let approvalSequence = 0;
const mcpApprovals = new Map();
const codexRequests = new Map();
/* Активные provider-чаты по requestId: отмена (providers:cancel) гасит
 * HTTP-запрос и CLI-процессы через AbortController. */
const providerChats = new Map();
const pythonApiQueue = new SerialRequestQueue();
const pythonInteractiveQueue = new SerialRequestQueue();
const repoCanvasQueue = new SerialRequestQueue();
const liveMutationQueue = new SerialRequestQueue();
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

/* Keep provider credentials inside the trusted main/sidecar boundary.
 * Reconfigure only when the fingerprint (credentials + worker restart)
 * changed. Fingerprint несёт ВЕРСИЮ ключа (короткий sha256), а не только
 * наличие: ротация credentials без смены набора провайдеров обязана
 * переконфигурировать воркер, иначе он останется со старым ключом. */
async function ensureWorkerConfigured(worker) {
  let queue = configureQueues.get(worker);
  if (!queue) {
    queue = new SerialRequestQueue();
    configureQueues.set(worker, queue);
  }
  await queue.run(async () => {
    const key = credentials.get("openai");
    const openrouterKey = credentials.get("openrouter");
    const keyTag = key ? createHash("sha256").update(String(key)).digest("hex").slice(0, 12) : "-";
    const openrouterTag = openrouterKey
      ? createHash("sha256").update(String(openrouterKey)).digest("hex").slice(0, 12)
      : "-";
    const fingerprint = `${worker.spawnCount}:${keyTag}:${openrouterTag}`;
    if (configureFingerprints.get(worker) === fingerprint) return;
    await worker.request("runtime.configure", {
      openaiApiKey: key || "",
      openrouterApiKey: openrouterKey || "",
    });
    configureFingerprints.set(worker, fingerprint);
  });
}
const LIVE_COMMAND_TOOL_NAME = "designdna_live_command";
const LIVE_COMMAND_TOOL = Object.freeze({
  serverId: "designdna-live",
  serverName: "DesignDNA Live",
  name: LIVE_COMMAND_TOOL_NAME,
  qualifiedName: LIVE_COMMAND_TOOL_NAME,
  description: "Read or change the open DesignDNA project through the revision-safe Live Command Bus.",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["commandId", "idempotencyKey", "projectId", "intent", "scope", "action", "arguments", "mode", "correlationId", "timeoutMs"],
    properties: {
      commandId: { type: "string" }, idempotencyKey: { type: "string" }, projectId: { type: "string" },
      pageId: { type: ["string", "null"] }, baseRevision: { type: "string" }, intent: { type: "string" },
      scope: { type: "object" }, action: { type: "string" }, arguments: { type: "object" },
      mode: { type: "string", enum: ["preview", "apply"] }, correlationId: { type: "string" }, timeoutMs: { type: "integer" },
    },
  },
  annotations: { readOnlyHint: false },
});

function liveCommandDynamicTool() {
  return { name: LIVE_COMMAND_TOOL.qualifiedName, description: LIVE_COMMAND_TOOL.description, inputSchema: LIVE_COMMAND_TOOL.inputSchema };
}

async function executeLiveCommandRequest(request, { source = "agent" } = {}) {
  const access = classifyActionAccess(request?.action);
  const session = liveProjects?.get("local-user", request?.projectId);
  if (access === "mutation") {
    if (!session) throw new Error(`Live project ${String(request?.projectId || "")} is not loaded`);
    return request.mode === "preview"
      ? session.beginPreview(request, { approvalContext: { source } })
      : liveCommands.execute(request, { currentRevision: session.currentRevision(), approvalContext: { source } });
  }
  return liveCommands.execute(request, { approvalContext: { source } });
}

async function callLiveCommandTool(arguments_, { source = "agent" } = {}) {
  const request = arguments_ || {};
  const result = await executeLiveCommandRequest(request, { source });
  return {
    content: [{ type: "text", text: JSON.stringify(result) }],
    structuredContent: result,
    isError: false,
  };
}

/* Быстрые routes уходят на интерактивный воркер: они обязаны отвечать за десятки
 * миллисекунд даже когда длинный воркер минутами держит Source Import / reproduce.
 * project/* целиком на интерактивном — projects.db остаётся single-writer. */
/* Тяжёлые capture-конвейеры: минутные Playwright/LLM-прогоны. Идут в
 * эксклюзивную полосу — не параллелятся друг с другом (Chromium×viewports
 * дорого), но больше не блокируют лёгкие запросы UI (воркер многопоточный). */
const EXCLUSIVE_API_PATHS = new Set([
  "/api/block-parse",
]);
/* Три полосы вместо одного мьютекса: exclusive (block-parse) и /api/project/*
 * серийные, остальной трафик — параллельно с семафором на воркер. Раньше все
 * не-exclusive запросы шли через один SerialRequestQueue, и любой долгий
 * запрос замораживал весь API-трафик UI. */
const apiScheduler = new ApiScheduler({ exclusivePaths: EXCLUSIVE_API_PATHS });
/* runtime.configure под маленьким мьютексом на воркер: параллельные запросы
 * не гоняют configure наперегонки; сам http.request идёт вне мьютекса. */
const configureQueues = new Map();

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
const MAX_BLOB_BATCH_BYTES = 256 * 1024 * 1024;

/* Блобы (inline data:image в node.data) исторически раздували localStorage до
 * десятков МБ: каждый бут парсит блоб целиком, каждый автосейв сериализует.
 * Десктоп выносит их в userData/data/blobs и кладёт в LS короткие ссылки
 * ddna://blobs/<name>; рендерер грузит их через тот же протокол. */
function blobsDir() {
  return path.join(app.getPath("userData"), "data", "blobs");
}

function registerFontsProtocol() {
  const fontsDir = path.join(app.getPath("userData"), "data", "fonts");
  protocol.handle("ddna", async (request) => {
    const url = new URL(request.url);
    if (url.host !== "fonts" && url.host !== "blobs") return new Response("not found", { status: 404 });
    const name = safeBlobName(decodeURIComponent(url.pathname.replace(/^\/+/, "")));
    if (!name) return new Response("bad name", { status: 400 });
    const ext = path.extname(name).toLowerCase();
    try {
      const object = url.host === "fonts"
        ? { data: await readFile(path.join(fontsDir, name)), mime: FONT_MIME[ext] || "application/octet-stream" }
        : await readBlobObject(blobsDir(), name);
      return new Response(object.data, {
        headers: {
          "Content-Type": object.mime,
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

async function requestLiveCommandApproval({ request, context }) {
  const action = String(request?.action || "unknown");
  const intent = String(request?.intent || "").slice(0, 500);
  const source = String(context?.source || "agent");
  const window = BrowserWindow.getAllWindows()[0];
  const options = {
    type: "question",
    buttons: ["Apply", "Cancel"],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
    title: "DesignDNA Live Command",
    message: `Allow ${source} to run ${action}?`,
    detail: intent || "This command will change the open project.",
  };
  const result = window ? await dialog.showMessageBox(window, options) : await dialog.showMessageBox(options);
  return result.response === 0;
}

function waitForPersistedRevision(session, baseRevision, timeoutMs) {
  let settled = false;
  let unsubscribe = () => {};
  let timer;
  const promise = new Promise((resolve, reject) => {
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      unsubscribe();
      callback(value);
    };
    unsubscribe = session.subscribe((event) => {
      if (event.type === "session.persisted" && event.baseRevision === baseRevision) finish(resolve, event);
    });
    timer = setTimeout(() => finish(reject, Object.assign(new Error("The renderer changed state but persistence acknowledgement timed out"), { code: "PERSIST_TIMEOUT" })), Math.min(Number(timeoutMs) || 30_000, 120_000));
  });
  return { promise, cancel: () => { if (!settled) { settled = true; clearTimeout(timer); unsubscribe(); } } };
}

async function executeRendererMutation(request) {
  const session = liveProjects?.get("local-user", request.projectId);
  if (!session) throw new Error(`Live project ${String(request.projectId || "")} is not loaded`);
  assertBaseRevision(request, session.currentRevision());
  if (request.mode === "preview") return rendererCommands.request(request, request.timeoutMs);
  const persisted = waitForPersistedRevision(session, request.baseRevision, request.timeoutMs);
  try {
    const acknowledgement = await rendererCommands.request(request, request.timeoutMs);
    const event = await persisted.promise;
    return {
      newRevision: event.newRevision,
      inverseCommand: acknowledgement.inverseCommand,
      undoEntry: acknowledgement.undoEntry,
      affectedObjects: acknowledgement.affectedObjects,
      qualityReport: acknowledgement.qualityReport,
    };
  } catch (error) {
    persisted.cancel();
    throw error;
  }
}

function createLiveCommandRegistry() {
  const registry = new LiveCommandRegistry({ approve: requestLiveCommandApproval });
  registry.register("session.get", async () => {
    const [window] = BrowserWindow.getAllWindows();
    return {
      appVersion: app.getVersion(),
      packaged: app.isPackaged,
      rendererReady: Boolean(window && !window.isDestroyed() && !window.webContents.isLoading()),
      windowVisible: Boolean(window && !window.isDestroyed() && window.isVisible()),
      activeProject: liveProjects?.getSnapshot() || null,
    };
  });
  registry.register("command.list", async () => ({ actions: registry.actionInventory() }));
  registry.register("project.get", async (request) => ({
    available: Boolean(liveProjects?.getSnapshot("local-user", request.projectId)),
    snapshot: liveProjects?.getSnapshot("local-user", request.projectId) || null,
  }));
  registry.register("pages.list", async (request) => {
    const snapshot = liveProjects?.getSnapshot("local-user", request.projectId);
    const pages = Array.isArray(snapshot?.project?.pages) ? snapshot.project.pages : [];
    return {
      revision: snapshot?.revision || null,
      pages: pages.map((page) => ({ id: page?.id || null, title: page?.title || page?.name || "" })),
    };
  });
  registry.register("graph.get", async (request) => {
    const snapshot = liveProjects?.getSnapshot("local-user", request.projectId);
    const pages = Array.isArray(snapshot?.project?.pages) ? snapshot.project.pages : [];
    const page = pages.find((candidate) => candidate?.id === request.pageId) || null;
    return {
      revision: snapshot?.revision || null,
      pageId: request.pageId,
      nodes: Array.isArray(page?.nodes) ? page.nodes : [],
      edges: Array.isArray(page?.edges) ? page.edges : [],
    };
  });
  registry.register("changes.since", async (request) => {
    const cursor = request.arguments?.cursor ?? 0;
    return registry.changesSince(cursor);
  });
  const serializedRendererMutation = (request) => liveMutationQueue.run(() => executeRendererMutation(request));
  registry.register("graph.node.create", serializedRendererMutation);
  registry.register("graph.node.delete", serializedRendererMutation);
  registry.register("graph.node.move", serializedRendererMutation);
  registry.register("editor.style.patch", serializedRendererMutation);
  registry.register("history.undo", serializedRendererMutation);
  registry.subscribe((event) => broadcast("live-command:event", event));
  return registry;
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
    // Интерактивные вызовы короткие: таймаут = мёртвый канал. Авто-респаун
    // вместо «перезапустите приложение» (симптом: все /api/generate и
    // editor/assist виснут по 120с при живом и свободном воркере).
    restartOnTimeout: true,
  });
  // Лимиты параллельной полосы = размер ThreadPoolExecutor воркера (3);
  // интерактивному оставляем слот под серийную project-полосу.
  apiScheduler.registerWorker(pythonWorker, 3);
  apiScheduler.registerWorker(pythonInteractiveWorker, 2);
  repoCanvasWorker = new JsonlProcess({
    name: "Repo Canvas runtime",
    command: process.execPath,
    args: [repoCanvasWorkerEntry, repositoryRoot],
    cwd: repositoryRoot,
    env: { DESIGNDNA_PROJECT_ROOT: repositoryRoot, ELECTRON_RUN_AS_NODE: "1" },
    timeoutMs: 180_000,
  });
  // Claude — headless-запуск Claude Code CLI. Вход ведёт само приложение
  // (`claude setup-token`); долгоживущий токен лежит в safeStorage и уходит
  // только в env спауна CLI — renderer секрета не видит.
  claude = new ClaudeAgentServer({
    cwd: repositoryRoot,
    getStoredToken: () => { try { return credentials?.get("claude"); } catch { return null; } },
  });
  codex = new CodexAppServer({ cwd: repositoryRoot });
  codex.on("notification", (message) => broadcast("codex:event", message));
  codex.on("request", async (message) => {
    if (message.method === "item/tool/call") {
      try {
        const toolResult = message.params.tool === LIVE_COMMAND_TOOL_NAME
          ? await callLiveCommandTool(message.params.arguments, { source: "codex" })
          : await mcp.callTool(message.params.tool, message.params.arguments, { source: "codex" });
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
  // v2: тело — Uint8Array (structured clone без base64); length — в байтах.
  // Строковые тела legacy-рендереров проверяются по длине строки.
  const bodyLength = request?.body instanceof Uint8Array
    ? request.body.byteLength
    : String(request?.body || "").length;
  if (bodyLength > 96 * 1024 * 1024) throw new Error("Desktop API request is too large");
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
  // Первый безопасный vertical slice Live Command Bus. Пока наружу открыты
  // только зарегистрированные read-handlers. Mutations будут подключены после
  // появления authoritative Live Project Session, а не с revision из renderer.
  handleTrusted("live-command:list", () => liveCommands.actionInventory());
  handleTrusted("live-command:execute", (_event, request) => executeLiveCommandRequest(request, { source: "renderer" }));
  handleTrusted("live-command:preview-get", (_event, { previewId } = {}) => liveCommands.getPreview(String(previewId || "")));
  handleTrusted("live-command:response", (event, payload) => rendererCommands.respond(String(event.sender.id), payload));
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
  handleTrusted("api:cancel", (_event, payload) => {
    // scope "long" (по умолчанию) рестартует длинный воркер; "interactive"
    // трогает интерактивный только по явной просьбе — он держит project-полосу
    // и не должен рестартоваться заодно с отменой импорта.
    const scope = String(payload?.scope || "long");
    if (scope === "interactive") {
      pythonInteractiveWorker.abort("cancelled by user");
    } else {
      pythonWorker.abort("cancelled by user");
    }
    return { cancelled: true, scope };
  });
  // Вынос inline-блобов из localStorage: рендерер кладёт содержимое, LS хранит
  // только ddna://blobs/<name>. getMany возвращает ПОЛНЫЕ data:-URL обратно —
  // мост разворачивает их в исходящие /api-тела (кроме project/save), чтобы
  // серверный рендер (fidelity/QA) продолжал видеть картинки.
  handleTrusted("blobs:put", async (_event, { mime, base64 }) => {
    return putContentAddressedBlob(blobsDir(), { mime, base64 });
  });
  handleTrusted("blobs:getMany", async (_event, { names }) => {
    const batch = await readBlobBatch(blobsDir(), names, { maxItems: 500, maxTotalBytes: MAX_BLOB_BATCH_BYTES });
    const out = {};
    for (const [name, object] of Object.entries(batch.objects)) {
      out[name] = `data:${object.mime};base64,${object.data.toString("base64")}`;
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
    let liveProjectContext = null;
    try {
      liveProjectContext = liveProjects.prepare(validatedRequest);
    } catch (error) {
      const stale = error?.code === "STALE_REVISION";
      return {
        status: stale ? 409 : 400,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          ok: false,
          stale,
          error: error?.code || "PROJECT_REQUEST_INVALID",
          revision: error?.currentRevision || null,
        }),
        encoding: "utf8",
      };
    }
    const requestPath = validatedRequest.path.split("?", 1)[0];
    const interactive = INTERACTIVE_API_PATHS.has(requestPath);
    const worker = interactive ? pythonInteractiveWorker : pythonWorker;
    // Полосы: exclusive (block-parse) и /api/project/* — серийные (Chromium
    // дорог; projects.db single-writer + монотонные ревизии Live Project
    // Session), остальное — параллельно с семафором на воркер.
    return apiScheduler.run(requestPath, worker, async () => {
      let preparedRequest = validatedRequest;
      const authIntent = sourceAuthIntent(validatedRequest);
      if (authIntent) {
        const cookies = await sourceAuthSession().cookies.get({ url: authIntent.url });
        preparedRequest = attachSourceAuthCookies(validatedRequest, cookies, authIntent.url);
      }
      await ensureWorkerConfigured(worker);
      // Source Import / generation pipelines legitimately take minutes
      // (Playwright captures multiple viewports, font downloads, LLM steps),
      // so the HTTP call gets a wider budget than the default worker timeout.
      // Тело уходит бинарным фреймом (bodyBytes), ответ приходит так же:
      // bodyBytes — уже Uint8Array для structured clone в рендерер.
      const requestParams = { ...preparedRequest };
      if (requestParams.body instanceof Uint8Array) {
        requestParams.bodyBytes = requestParams.body;
        delete requestParams.body;
        delete requestParams.encoding;
      }
      const response = await worker.request("http.request", requestParams, interactive ? 120_000 : 600_000);
      liveProjects.synchronize(liveProjectContext, response);
      if (response && response.bodyBytes instanceof Uint8Array) {
        return { ...response, body: response.bodyBytes, encoding: "raw" };
      }
      // legacy-строчные ответы (base64) — конвертируем один раз в Uint8Array
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
    encryptedStorage: credentials.available(),
  }));
  handleTrusted("providers:credentials", () => ({ configured: credentials.status(), encryptedStorage: credentials.available() }));
  handleTrusted("providers:set-credential", (_event, { provider, value }) => credentials.set(provider, value));
  handleTrusted("providers:delete-credential", (_event, { provider }) => credentials.delete(provider));
  // Provider chat: единый типизированный envelope (см. provider-envelope.mjs).
  // Legacy-форма {provider, messages, temperature, profile, tools} продолжает
  // работать: поля собираются в envelope с correlation id. Все отказы
  // валидации/возможностей — структурные ошибки с кодом, dropped-параметры
  // возвращаются в result.transport (явно, не молча).
  const structuredProviderError = (error) => {
    if (error instanceof EnvelopeValidationError || error instanceof UnsupportedCapabilityError) {
      // Электрон сериализует только Error-инстансы: код и issues — полями
      const structured = new Error(error.message);
      structured.code = error.code;
      structured.issues = error.issues;
      console.warn(`[providers:chat] ${JSON.stringify(redactForLog({ code: error.code, issues: error.issues }))}`);
      return structured;
    }
    return error;
  };
  const runProviderChat = async (payload) => {
    const request = payload?.request && typeof payload.request === "object" ? payload.request : payload;
    const requestedEffort = typeof request?.reasoning === "string"
      ? request.reasoning
      : request?.reasoning?.effort;
    // Провайдер выбирается пользователем в ноде; ретро-значения мигрируют
    // на дефолт внутри resolveProvider. Envelope остаётся Sol-типизированным:
    // Codex и Claude — текстовые CLI-транспорты и читают из него messages.
    const provider = resolveProvider(request?.provider);
    const envelope = createEnvelope({
      ...request,
      provider: "openai",
      model: "gpt-5.6-sol",
      reasoning: { effort: new Set(["medium", "high", "max"]).has(requestedEffort) ? requestedEffort : "medium" },
      id: request?.id || `chat-${++approvalSequence}-${Date.now().toString(36)}`,
    });
    const abort = new AbortController();
    providerChats.set(envelope.id, abort);
    try {
      const result = await chatWithProvider({
        provider,
        envelope: { ...envelope, provider },
        profile: payload?.profile,
        signal: abort.signal,
        codex,
        claude,
        credentials,
      });
      return { ...result, requestId: envelope.id };
    } finally {
      providerChats.delete(envelope.id);
    }
  };
  handleTrusted("providers:chat", (_event, payload) => runProviderChat(payload).catch((error) => {
    throw structuredProviderError(error);
  }));
  handleTrusted("providers:chat-request", (_event, request) => runProviderChat(request).catch((error) => {
    throw structuredProviderError(error);
  }));
  handleTrusted("providers:cancel", (_event, { requestId } = {}) => {
    const id = String(requestId || "");
    const abort = providerChats.get(id);
    if (!abort) return { cancelled: false };
    abort.abort();
    providerChats.delete(id);
    return { cancelled: true, requestId: id };
  });
  handleTrusted("claude:status", () => claude.account());
  // Вход Claude из приложения: открываем окно терминала с `claude /login`
  // (OAuth и сохранение кредов ведёт сам CLI), затем ждём валидные креды.
  handleTrusted("claude:login-start", () => claude.loginStart());
  handleTrusted("claude:login-wait", () => claude.waitForLogin());
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
    return codex.startThread({ cwd: repositoryRoot, ...params, dynamicTools: [...mcp.dynamicTools(), liveCommandDynamicTool()] });
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
  handleTrusted("mcp:tools", async () => [...await mcp.listTools(), LIVE_COMMAND_TOOL]);
  handleTrusted("mcp:call", (_event, { name, arguments: args, timeoutMs, correlationId }) => (
    String(name) === LIVE_COMMAND_TOOL_NAME
      ? callLiveCommandTool(args, { source: "user" })
      : mcp.callTool(String(name), args || {}, {
        source: "user",
        timeoutMs: Number(timeoutMs) || null,
        correlationId: correlationId ? String(correlationId).slice(0, 128) : null,
      })
  ));
  handleTrusted("mcp:cancel", (_event, { correlationId } = {}) => ({ cancelled: mcp.cancelByCorrelation(String(correlationId || "")) }));
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
  const rendererId = String(window.webContents.id);
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
    rendererCommands?.detach(rendererId);
    console.error(`Renderer gone (${details.reason}): ${details.exitCode}`);
    // Белое окно без воркеров хуже перезагрузки страницы: перезагружаем
    if (!window.isDestroyed()) window.webContents.reload();
  });
  window.webContents.on("unresponsive", () => console.warn("Renderer unresponsive"));
  // Ошибки рендерера иначе не видны нигде: окно просто «ничего не делает».
  // Warning/error уходят в stdout main-процесса и в лог запуска.
  window.webContents.on("console-message", (event) => {
    // Electron 43: единый объект события вместо позиционных аргументов.
    const level = String(event?.level || "");
    if (level !== "error" && level !== "warning") return;
    const where = event?.sourceId ? ` (${event.sourceId}:${event.lineNumber})` : "";
    console.error(`[renderer] ${event?.message || ""}${where}`);
  });
  // Devtools по требованию: DESIGNDNA_DEVTOOLS=1 npm start
  if (process.env.DESIGNDNA_DEVTOOLS === "1") window.webContents.openDevTools({ mode: "detach" });
  window.on("closed", () => rendererCommands?.detach(rendererId));
  if (rendererDevUrl) void window.loadURL(rendererDevUrl);
  else void window.loadFile(rendererEntry);
}

app.whenReady().then(async () => {
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
  rendererCommands = new RendererCommandBridge({
    getTarget: () => {
      const [window] = BrowserWindow.getAllWindows();
      if (!window || window.isDestroyed() || window.webContents.isLoading()) return null;
      return { id: String(window.webContents.id), send: (channel, payload) => window.webContents.send(channel, payload) };
    },
  });
  liveCommands = createLiveCommandRegistry();
  liveProjects = new LiveProjectApiSync({
    registry: liveCommands,
    onEvent: (event) => broadcast("live-project:event", event),
  });
  liveCommandPipe = new LiveCommandPipeServer({
    dataDirectory: path.join(app.getPath("userData"), "data"),
    execute: (command) => executeLiveCommandRequest(command, { source: "external-mcp" }),
  });
  await liveCommandPipe.start().catch((error) => console.error(`Live command pipe unavailable: ${error.message}`));
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
const allowDevelopmentMultiInstance = !app.isPackaged && process.env.DESIGNDNA_ALLOW_MULTI_INSTANCE === "1";
const gotSingleInstanceLock = allowDevelopmentMultiInstance || app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  // Быстрый перезапуск после закрытия: прежний экземпляр ещё освобождает
  // lock, и молчаливый quit выглядел как «приложение не открылось».
  // Перезапускаемся с ограниченным числом попыток — к следующему старту
  // lock обычно уже свободен; настоящий второй экземпляр (живое окно)
  // получает second-instance-фокус в старом процессе и здесь не зациклится.
  const restartFlag = "--ddna-restart-attempt=";
  const attempt = Number((process.argv.find((arg) => arg.startsWith(restartFlag)) || "").slice(restartFlag.length) || 0);
  if (attempt < 5) {
    app.relaunch({
      args: process.argv.slice(1).filter((arg) => !arg.startsWith(restartFlag))
        .concat([restartFlag + String(attempt + 1)]),
    });
  }
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
  liveCommands?.dispose();
  liveProjects?.dispose();
  rendererCommands?.dispose();
  const stops = Promise.allSettled([
    liveCommandPipe?.stop(),
    pythonWorker?.stop(),
    pythonInteractiveWorker?.stop(),
    repoCanvasWorker?.stop(),
  ]);
  const forceExit = new Promise((resolve) => setTimeout(resolve, 3_000));
  void Promise.race([stops, forceExit]).then(() => app.exit(0));
});
