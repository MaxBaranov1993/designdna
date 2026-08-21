export {};

type DesktopUnsubscribe = () => void;
type DesktopMessage = { method: string; params: Record<string, any> };
type DesktopRequest = { id: string | number; method: string; params: Record<string, any> };
type RepoCanvasSnapshot = {
  revision: number; errors: Array<{ line?: number; message?: string } | string>;
  summary: { areaCount: number; entityCount: number; activeWork: number; agents: string[] };
  areas: Array<{ id: string; title?: string; note?: string }>;
  entities: Array<{ id: string; areaId?: string; label?: string; purpose?: string; path?: string; status?: string }>;
  work: Array<{ id: string; title?: string; task?: string; status?: string; actor?: string }>;
};

type DesktopProvider = "openai" | "kimi";
type KimiAccountStatus = { connected: boolean; kind: "oauth" | "api-key" | null; expiresAt: number | null };

declare global {
  interface Window {
    designDNA?: {
      app: { info(): Promise<Record<string, unknown>> };
      api: { request(request: Record<string, unknown>): Promise<Record<string, unknown>> };
      sourceAuth: { open(url: string): Promise<{ opened: boolean }>; clear(): Promise<{ cleared: boolean }> };
      repoCanvas: { snapshot(): Promise<RepoCanvasSnapshot>; check(): Promise<Record<string, unknown>>; refresh(options?: Record<string, unknown>): Promise<Record<string, unknown>> };
      providers: {
        status(): Promise<{ runtimes: Array<Record<string, any>>; credentials: Record<DesktopProvider, boolean>; kimiAccount: KimiAccountStatus; encryptedStorage: boolean }>;
        credentials(): Promise<Record<string, any>>;
        setCredential(provider: DesktopProvider, value: string): Promise<Record<string, unknown>>;
        deleteCredential(provider: DesktopProvider): Promise<Record<string, unknown>>;
        importKimiCli(): Promise<KimiAccountStatus>;
        chat(provider: "auto" | "codex" | "kimi" | "openai", messages: Array<{ role: string; content: string }>, temperature?: number,
          profile?: "generator" | "quality_judge" | "quality_repair"): Promise<{ content: string }>;
      };
      codex: {
        account(): Promise<Record<string, any>>; login(type?: "chatgpt" | "apiKey"): Promise<Record<string, any>>;
        threads(params?: Record<string, unknown>): Promise<Record<string, any>>;
        startThread(params?: Record<string, unknown>): Promise<Record<string, any>>;
        resumeThread(threadId: string): Promise<Record<string, any>>;
        startTurn(params: Record<string, unknown>): Promise<Record<string, any>>;
        steerTurn(params: Record<string, unknown>): Promise<Record<string, any>>;
        interruptTurn(threadId: string, turnId: string): Promise<Record<string, any>>;
        respond(id: string | number, result: Record<string, unknown>): Promise<Record<string, unknown>>;
        onEvent(listener: (message: DesktopMessage) => void): DesktopUnsubscribe;
        onRequest(listener: (message: DesktopRequest) => void): DesktopUnsubscribe;
      };
      mcp: {
        list(): Promise<Array<Record<string, any>>>; save(servers: Array<Record<string, unknown>>): Promise<Record<string, any>>;
        refresh(): Promise<Array<Record<string, any>>>; tools(): Promise<Array<Record<string, any>>>;
        call(name: string, args?: Record<string, unknown>): Promise<Record<string, any>>;
        respondToApproval(id: string, accepted: boolean): Promise<Record<string, unknown>>;
        onApproval(listener: (request: Record<string, any>) => void): DesktopUnsubscribe;
      };
    };
  }
}
