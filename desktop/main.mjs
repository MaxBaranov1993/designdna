import path from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, ipcMain, safeStorage, shell } from "electron";
import { JsonlProcess } from "./lib/jsonl-process.mjs";
import { CredentialStore } from "./services/credential-store.mjs";
import { SettingsStore } from "./services/settings-store.mjs";
import { getProviderStatus } from "./services/provider-status.mjs";
import { CodexAppServer } from "./services/codex-app-server.mjs";

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(desktopDirectory, "..");
const rendererEntry = path.join(repositoryRoot, "app", "static", "flow", "index.html");
const preload = path.join(desktopDirectory, "preload.cjs");

let pythonWorker;
let repoCanvasWorker;
let codex;
let credentials;
let settings;

function pythonCommand() {
  return process.env.DESIGNDNA_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function createWorkers() {
  pythonWorker = new JsonlProcess({
    name: "DesignDNA Python runtime",
    command: pythonCommand(),
    args: [path.join(repositoryRoot, "app", "desktop_worker.py")],
    cwd: repositoryRoot,
    env: { PYTHONUNBUFFERED: "1" },
    timeoutMs: 120_000,
  });
  repoCanvasWorker = new JsonlProcess({
    name: "Repo Canvas runtime",
    command: process.execPath,
    args: [path.join(desktopDirectory, "workers", "repo-canvas-worker.mjs"), repositoryRoot],
    cwd: repositoryRoot,
    env: { DESIGNDNA_PROJECT_ROOT: repositoryRoot, ELECTRON_RUN_AS_NODE: "1" },
    timeoutMs: 180_000,
  });
  codex = new CodexAppServer({ cwd: repositoryRoot });
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
  ipcMain.handle("mcp:list", () => settings.listMcpServers());
  ipcMain.handle("mcp:save", (_event, servers) => settings.saveMcpServers(servers));
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
});
