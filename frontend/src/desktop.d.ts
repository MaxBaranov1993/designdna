export {};

type RepoCanvasSummary = { areaCount: number; entityCount: number; activeWork: number; agents: string[] };
type RepoCanvasSnapshot = {
  revision: number;
  errors: Array<{ line?: number; message?: string } | string>;
  summary: RepoCanvasSummary;
  areas: Array<{ id: string; title?: string; note?: string }>;
  entities: Array<{ id: string; areaId?: string; label?: string; purpose?: string; path?: string; status?: string }>;
  work: Array<{ id: string; title?: string; task?: string; status?: string; actor?: string }>;
};

declare global {
  interface Window {
    designDNA?: {
      app: { info(): Promise<Record<string, unknown>> };
      api: { request(request: Record<string, unknown>): Promise<Record<string, unknown>> };
      repoCanvas: {
        snapshot(): Promise<RepoCanvasSnapshot>;
        check(): Promise<Record<string, unknown>>;
        refresh(options?: Record<string, unknown>): Promise<Record<string, unknown>>;
      };
      providers: {
        status(): Promise<Record<string, unknown>>;
        credentials(): Promise<Record<string, unknown>>;
        setCredential(provider: "openai" | "anthropic" | "kimi", value: string): Promise<Record<string, unknown>>;
        deleteCredential(provider: "openai" | "anthropic" | "kimi"): Promise<Record<string, unknown>>;
      };
      codex: { account(): Promise<Record<string, unknown>>; login(type?: "chatgpt" | "apiKey"): Promise<Record<string, unknown>> };
      mcp: { list(): Promise<Array<Record<string, unknown>>>; save(servers: Array<Record<string, unknown>>): Promise<Array<Record<string, unknown>>> };
    };
  }
}
