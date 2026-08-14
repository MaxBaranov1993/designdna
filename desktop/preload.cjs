const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("designDNA", Object.freeze({
  app: Object.freeze({ info: () => ipcRenderer.invoke("app:info") }),
  api: Object.freeze({ request: (request) => ipcRenderer.invoke("api:request", request) }),
  repoCanvas: Object.freeze({
    snapshot: () => ipcRenderer.invoke("repo-canvas:snapshot"),
    check: () => ipcRenderer.invoke("repo-canvas:check"),
    refresh: (options = {}) => ipcRenderer.invoke("repo-canvas:refresh", options),
  }),
  providers: Object.freeze({
    status: () => ipcRenderer.invoke("providers:status"),
    credentials: () => ipcRenderer.invoke("providers:credentials"),
    setCredential: (provider, value) => ipcRenderer.invoke("providers:set-credential", { provider, value }),
    deleteCredential: (provider) => ipcRenderer.invoke("providers:delete-credential", { provider }),
  }),
  codex: Object.freeze({
    account: () => ipcRenderer.invoke("codex:account"),
    login: (type = "chatgpt") => ipcRenderer.invoke("codex:login", { type }),
  }),
  mcp: Object.freeze({
    list: () => ipcRenderer.invoke("mcp:list"),
    save: (servers) => ipcRenderer.invoke("mcp:save", servers),
  }),
}));
