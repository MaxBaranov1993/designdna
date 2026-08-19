import path from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } from "electron";
import { JsonlProcess } from "./lib/jsonl-process.mjs";
import { isAllowedRendererUrl } from "./lib/renderer-policy.mjs";
import { pythonWorkerEnvironment, pythonWorkerSpec } from "./lib/runtime-paths.mjs";
import { CredentialStore } from "./services/credential-store.mjs";
import { SettingsStore } from "./services/settings-store.mjs";
import { getProviderStatus } from "./services/provider-status.mjs";
import { chatWithProvider } from "./services/provider-router.mjs";
import { getValidToken, importFromCli, kimiAccountStatus } from "./services/kimi-account.mjs";
import { CodexAppServer } from "./services/codex-app-server.mjs";
import { McpManager } from "./services/mcp-manager.mjs";
import { canonicalMcpSpec, createMcpActivationApprover } from "./services/mcp-activation-approval.mjs";

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
let repoCanvasWorker;
let codex;
let credentials;
let settings;
let mcp;
let mcpActivation;
let approvalSequence = 0;
const mcpApprovals = new Map();
const codexRequests = new Map();

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
    codexRequests.set(String(message.id), message.method);
    broadcast("codex:request", message);
  });
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

function registerIpc() {
  let mcpSaveQueue = Promise.resolve();
  handleTrusted("app:info", () => ({
    name: "DesignDNA",
    version: app.getVersion(),
    platform: process.platform,
    productionTransport: "ipc+stdio",
  }));
  handleTrusted("api:request", async (_event, request) => {
    // Keep provider credentials inside the trusted main/sidecar boundary.
    // Reconfigure before every API call so credential rotation and worker
    // restarts take effect without exposing the secrets to the renderer.
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
    await pythonWorker.request("runtime.configure", {
      openaiApiKey: credentials.get("openai") || "",
      kimiApiKey,
    });
    // Source Import / generation pipelines legitimately take minutes
    // (Playwright captures × viewports, font downloads, LLM steps) — give the
    // HTTP call a wider budget than the default 120s worker timeout.
    return pythonWorker.request("http.request", validateApiRequest(request), 600_000);
  });
  handleTrusted("repo-canvas:snapshot", () => repoCanvasWorker.request("snapshot"));
  handleTrusted("repo-canvas:check", () => repoCanvasWorker.request("check"));
  handleTrusted("repo-canvas:refresh", (_event, options) => repoCanvasWorker.request("architect.refresh", options || {}));
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
  window.once("ready-to-show", () => window.show());
  if (rendererDevUrl) void window.loadURL(rendererDevUrl);
  else void window.loadFile(rendererEntry);
}

app.whenReady().then(() => {
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

app.on("before-quit", () => {
  void pythonWorker?.stop();
  void repoCanvasWorker?.stop();
  codex?.stop();
  mcp?.stop();
});
