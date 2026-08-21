const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("designDNA", Object.freeze({
  app: Object.freeze({ info: () => ipcRenderer.invoke("app:info") }),
  api: Object.freeze({
    request: (request) => ipcRenderer.invoke("api:request", request),
    cancel: () => ipcRenderer.invoke("api:cancel"),
  }),
  blobs: Object.freeze({
    put: (name, base64) => ipcRenderer.invoke("blobs:put", { name, base64 }),
    getMany: (names) => ipcRenderer.invoke("blobs:getMany", { names }),
  }),
  files: Object.freeze({
    save: (name, base64) => ipcRenderer.invoke("files:save", { name, base64 }),
  }),
  sourceAuth: Object.freeze({
    open: (url) => ipcRenderer.invoke("source-auth:open", { url }),
    clear: () => ipcRenderer.invoke("source-auth:clear"),
  }),
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
    importKimiCli: () => ipcRenderer.invoke("providers:import-kimi-cli"),
    chat: (provider, messages, temperature = 0.8, profile = "generator", tools = null) =>
      ipcRenderer.invoke("providers:chat", { provider, messages, temperature, profile, tools }),
  }),
  codex: Object.freeze({
    account: () => ipcRenderer.invoke("codex:account"),
    login: (type = "chatgpt") => ipcRenderer.invoke("codex:login", { type }),
    threads: (params = {}) => ipcRenderer.invoke("codex:threads", params),
    startThread: (params = {}) => ipcRenderer.invoke("codex:start-thread", params),
    resumeThread: (threadId) => ipcRenderer.invoke("codex:resume-thread", { threadId }),
    startTurn: (params) => ipcRenderer.invoke("codex:start-turn", params),
    steerTurn: (params) => ipcRenderer.invoke("codex:steer-turn", params),
    interruptTurn: (threadId, turnId) => ipcRenderer.invoke("codex:interrupt-turn", { threadId, turnId }),
    respond: (id, result) => ipcRenderer.invoke("codex:respond", { id, result }),
    onEvent: (listener) => { const wrapped = (_event, payload) => listener(payload); ipcRenderer.on("codex:event", wrapped); return () => ipcRenderer.removeListener("codex:event", wrapped); },
    onRequest: (listener) => { const wrapped = (_event, payload) => listener(payload); ipcRenderer.on("codex:request", wrapped); return () => ipcRenderer.removeListener("codex:request", wrapped); },
  }),
  mcp: Object.freeze({
    list: () => ipcRenderer.invoke("mcp:list"),
    save: (servers) => ipcRenderer.invoke("mcp:save", servers),
    refresh: () => ipcRenderer.invoke("mcp:refresh"),
    tools: () => ipcRenderer.invoke("mcp:tools"),
    call: (name, args = {}) => ipcRenderer.invoke("mcp:call", { name, arguments: args }),
    respondToApproval: (id, accepted) => ipcRenderer.invoke("mcp:approval-response", { id, accepted }),
    onApproval: (listener) => { const wrapped = (_event, payload) => listener(payload); ipcRenderer.on("mcp:approval-requested", wrapped); return () => ipcRenderer.removeListener("mcp:approval-requested", wrapped); },
  }),
}));
