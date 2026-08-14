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

declare global {
  interface Window {
    designDNA?: {
      app: { info(): Promise<Record<string, unknown>> };
      api: { request(request: Record<string, unknown>): Promise<Record<string, unknown>> };
      repoCanvas: { snapshot(): Promise<RepoCanvasSnapshot>; check(): Promise<Record<string, unknown>>; refresh(options?: Record<string, unknown>): Promise<Record<string, unknown>> };
      providers: {
        status(): Promise<Record<string, any>>; credentials(): Promise<Record<string, any>>;
        setCredential(provider: "openai" | "kimi", value: string): Promise<Record<string, unknown>>;
        deleteCredential(provider: "openai" | "kimi"): Promise<Record<string, unknown>>;
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
