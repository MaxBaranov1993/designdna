import path from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, ipcMain, safeStorage, shell } from "electron";
import { JsonlProcess } from "./lib/jsonl-process.mjs";
import { pythonWorkerEnvironment, pythonWorkerSpec } from "./lib/runtime-paths.mjs";
import { CredentialStore } from "./services/credential-store.mjs";
import { SettingsStore } from "./services/settings-store.mjs";
import { getProviderStatus } from "./services/provider-status.mjs";
import { CodexAppServer } from "./services/codex-app-server.mjs";
import { McpManager } from "./services/mcp-manager.mjs";

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
let approvalSequence = 0;
const mcpApprovals = new Map();
const codexRequests = new Map();

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
  ipcMain.handle("app:info", () => ({
    name: "DesignDNA",
    version: app.getVersion(),
    platform: process.platform,
    productionTransport: "ipc+stdio",
  }));
  ipcMain.handle("api:request", (_event, request) => pythonWorker.request("http.request", validateApiRequest(request)));
  ipcMain.handle("repo-canvas:snapshot", () => repoCanvasWorker.request("snapshot"));
  ipcMain.handle("repo-canvas:check", () => repoCanvasWorker.request("check"));
  ipcMain.handle("repo-canvas:refresh", (_event, options) => repoCanvasWorker.request("architect.refresh", options || {}));
  ipcMain.handle("providers:status", async () => ({
    runtimes: await getProviderStatus(),
    credentials: credentials.status(),
    encryptedStorage: credentials.available(),
  }));
  ipcMain.handle("providers:credentials", () => ({ configured: credentials.status(), encryptedStorage: credentials.available() }));
  ipcMain.handle("providers:set-credential", (_event, { provider, value }) => credentials.set(provider, value));
  ipcMain.handle("providers:delete-credential", (_event, { provider }) => credentials.delete(provider));
  ipcMain.handle("codex:account", () => codex.account());
  ipcMain.handle("codex:login", (_event, { type }) => codex.login({ type, apiKey: type === "apiKey" ? credentials.get("openai") : undefined }));
  ipcMain.handle("codex:threads", (_event, params) => codex.listThreads(params || {}));
  ipcMain.handle("codex:start-thread", async (_event, params) => {
    await mcp.refresh();
    return codex.startThread({ cwd: repositoryRoot, ...params, dynamicTools: mcp.dynamicTools() });
  });
  ipcMain.handle("codex:resume-thread", (_event, { threadId }) => codex.resumeThread(String(threadId)));
  ipcMain.handle("codex:start-turn", (_event, params) => codex.startTurn(params));
  ipcMain.handle("codex:steer-turn", (_event, params) => codex.steerTurn(params));
  ipcMain.handle("codex:interrupt-turn", (_event, { threadId, turnId }) => codex.interruptTurn(String(threadId), String(turnId)));
  ipcMain.handle("codex:respond", (_event, { id, result }) => {
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
  ipcMain.handle("mcp:list", () => settings.listMcpServers());
  ipcMain.handle("mcp:save", async (_event, servers) => { const saved = settings.saveMcpServers(servers); return { servers: saved, statuses: await mcp.refresh() }; });
  ipcMain.handle("mcp:refresh", () => mcp.refresh());
  ipcMain.handle("mcp:tools", () => mcp.listTools());
  ipcMain.handle("mcp:call", (_event, { name, arguments: args }) => mcp.callTool(String(name), args || {}, { source: "user" }));
  ipcMain.handle("mcp:approval-response", (_event, { id, accepted }) => {
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
  window.webContents.on("will-navigate", (event, url) => {
    const current = window.webContents.getURL();
    if (url !== current && !url.startsWith("file:")) event.preventDefault();
  });
  window.once("ready-to-show", () => window.show());
  const devUrl = process.env.DESIGNDNA_RENDERER_URL;
  if (devUrl) void window.loadURL(devUrl);
  else void window.loadFile(rendererEntry);
}

app.whenReady().then(() => {
  credentials = new CredentialStore({ userDataPath: app.getPath("userData"), safeStorage });
  settings = new SettingsStore(app.getPath("userData"));
  mcp = new McpManager({ settings, credentials, cwd: repositoryRoot, approve: requestMcpApproval });
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
