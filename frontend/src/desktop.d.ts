export {};

type DesktopUnsubscribe = () => void;
type DesktopMessage = { method: string; params: Record<string, any> };
type DesktopRequest = { id: string | number; method: string; params: Record<string, any> };
type LiveCommandEvent = {
  cursor: number;
  type: "command.applied";
  timestamp: string;
  commandId: string;
  correlationId: string;
  projectId: string;
  pageId: string | null;
  action: string;
  baseRevision: string;
  newRevision: string;
};
type LiveProjectEvent = {
  cursor: number;
  type: "session.hydrated" | "session.persisted" | "session.applied" | "renderer.attached";
  timestamp: string;
  userId: string;
  projectId: string;
  revision?: string;
  baseRevision?: string;
  newRevision?: string;
  dirty?: boolean;
};
type RepoCanvasSnapshot = {
  revision: number; errors: Array<{ line?: number; message?: string } | string>;
  summary: { areaCount: number; entityCount: number; activeWork: number; agents: string[] };
  areas: Array<{ id: string; title?: string; note?: string }>;
  entities: Array<{ id: string; areaId?: string; label?: string; purpose?: string; path?: string; status?: string }>;
  work: Array<{ id: string; title?: string; task?: string; status?: string; actor?: string }>;
};

type DesktopProvider = "openai" | "codex" | "claude";
type SolEffort = "medium" | "high" | "max";

type ChatRequestEnvelope = {
  id?: string;
  provider: DesktopProvider;
  model?: string | null;
  system?: string | null;
  messages: Array<{
    role: "system" | "user" | "assistant" | "tool";
    content: string | Array<{ type: string;[key: string]: any }>;
    tool_calls?: Array<{ id: string; type?: string; function: { name: string; arguments: string } }>;
    tool_call_id?: string;
    name?: string;
  }>;
  temperature?: number | null;
  topP?: number | null;
  maxOutputTokens?: number | null;
  reasoning?: { effort: SolEffort } | null;
  responseFormat?: { type: "json_object" | "json_schema" | "text"; jsonSchema?: { name: string; schema: Record<string, any> } } | null;
  stop?: string[] | null;
  seed?: number | null;
  stream?: boolean | null;
  toolChoice?: "auto" | "none" | "required" | { name: string } | null;
  parallelToolCalls?: boolean | null;
  tools?: Array<Record<string, any>> | null;
  providerOptions?: Record<string, Record<string, any>> | null;
  timeoutMs?: number | null;
  metadata?: Record<string, string> | null;
};

type ChatResponse = {
  content: string;
  toolCalls?: Array<{ id: string; name: string; arguments: string }>;
  provider: DesktopProvider;
  requestId: string;
  transport: {
    provider: string;
    model: string | null;
    requestId: string;
    dropped?: Array<{ field: string; reason: string }>;
    fallback?: string | null;
  };
};

declare global {
  interface Window {
    designDNA?: {
      app: { info(): Promise<Record<string, unknown>> };
      commands: {
        list(): Promise<Array<{ action: string; access: "read" | "preview" | "mutation"; approval: string }>>;
        execute(request: Record<string, unknown>): Promise<Record<string, unknown>>;
        getPreview(previewId: string): Promise<Record<string, unknown> | null>;
        onEvent(listener: (event: LiveCommandEvent) => void): DesktopUnsubscribe;
        onProjectEvent(listener: (event: LiveProjectEvent) => void): DesktopUnsubscribe;
        onRequest(listener: (request: { requestId: string; command: Record<string, unknown> }) => void): DesktopUnsubscribe;
        respond(requestId: string, response: { ok: boolean; result?: Record<string, unknown>; error?: { code: string; message: string } }): Promise<{ accepted: boolean }>;
      };
      api: { request(request: Record<string, unknown>): Promise<Record<string, unknown>>; cancel(scope?: "long" | "interactive"): Promise<{ cancelled: boolean; scope?: string }> };
      files: { save(name: string, base64: string): Promise<{ saved: boolean; path?: string }> };
      blobs: {
        put(mime: string, base64: string): Promise<{ stored: boolean; name: string; sha256: string; mime: string; bytes: number }>;
        getMany(names: string[]): Promise<Record<string, string>>;
      };
      sourceAuth: { open(url: string): Promise<{ opened: boolean }>; clear(): Promise<{ cleared: boolean }> };
      repoCanvas: { snapshot(): Promise<RepoCanvasSnapshot>; check(): Promise<Record<string, unknown>>; refresh(options?: Record<string, unknown>): Promise<Record<string, unknown>> };
      providers: {
        status(): Promise<{ runtimes: Array<Record<string, any>>; credentials: Record<"openai" | "openrouter", boolean>; encryptedStorage: boolean }>;
        credentials(): Promise<{ configured: Record<string, boolean>; encryptedStorage: boolean }>;
        setCredential(provider: "openai" | "openrouter", value: string): Promise<{ provider: string; configured: boolean }>;
        deleteCredential(provider: "openai" | "openrouter"): Promise<{ provider: string; configured: boolean }>;
        chat(provider: DesktopProvider, messages: Array<{ role: string; content: string }>, temperature?: number,
          profile?: "generator" | "quality_judge" | "quality_repair", tools?: Array<Record<string, unknown>> | null):
          Promise<{ content: string; toolCalls?: Array<{ id: string; name: string; arguments: string }> }>;
        chatRequest(request: ChatRequestEnvelope): Promise<ChatResponse>;
        cancel(requestId: string): Promise<{ cancelled: boolean; requestId?: string }>;
      };
      claude: {
        status(): Promise<{ provider: "claude"; installed: boolean; loggedIn: boolean; model: string; hint: string | null }>;
      };
      codex: {
        account(): Promise<Record<string, any>>; login(type?: "chatgpt" | "apiKey"): Promise<Record<string, any>>;
        threads(params?: Record<string, unknown>): Promise<Record<string, any>>;
        startThread(params?: Record<string, unknown>): Promise<Record<string, any>>;
        resumeThread(threadId: string): Promise<Record<string, any>>;
        startTurn(params: Record<string, unknown>): Promise<Record<string, unknown>>;
        steerTurn(params: Record<string, unknown>): Promise<Record<string, unknown>>;
        interruptTurn(threadId: string, turnId: string): Promise<Record<string, unknown>>;
        respond(id: string | number, result: Record<string, unknown>): Promise<Record<string, unknown>>;
        onEvent(listener: (message: DesktopMessage) => void): DesktopUnsubscribe;
        onRequest(listener: (message: DesktopRequest) => void): DesktopUnsubscribe;
      };
      mcp: {
        list(): Promise<Array<Record<string, any>>>; save(servers: Array<Record<string, unknown>>): Promise<Record<string, any>>;
        refresh(): Promise<Array<Record<string, any>>>; tools(): Promise<Array<Record<string, any>>>;
        call(name: string, args?: Record<string, unknown>, options?: { timeoutMs?: number; correlationId?: string }): Promise<Record<string, any>>;
        cancel(correlationId: string): Promise<{ cancelled: number }>;
        respondToApproval(id: string, accepted: boolean): Promise<Record<string, unknown>>;
        onApproval(listener: (request: Record<string, any>) => void): DesktopUnsubscribe;
      };
    };
  }
}
