import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/ui/button";
import "./agent-workspace.css";

type TimelineItem = { id: string; type: string; text?: string; status?: string; command?: string; aggregatedOutput?: string; changes?: Array<{ path?: string; kind?: string }> };

export function AgentWorkspace() {
  const desktop = window.designDNA;
  const [threadId, setThreadId] = useState("");
  const [turnId, setTurnId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [stream, setStream] = useState("");
  const [items, setItems] = useState<Record<string, TimelineItem>>({});
  const [requests, setRequests] = useState<Array<{ id: string | number; method: string; params: Record<string, any> }>>([]);
  const [mcpApproval, setMcpApproval] = useState<Record<string, any> | null>(null);
  const [mcpConfig, setMcpConfig] = useState("[]");
  const [mcpStatus, setMcpStatus] = useState<Array<Record<string, any>>>([]);
  const [tools, setTools] = useState<Array<Record<string, any>>>([]);
  const [providerState, setProviderState] = useState<Record<string, any>>({});
  const [codexAccount, setCodexAccount] = useState<Record<string, any> | null>(null);
  const [openaiKey, setOpenaiKey] = useState("");
  const [kimiKey, setKimiKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!desktop) return;
    void desktop.mcp.list().then((servers) => setMcpConfig(JSON.stringify(servers, null, 2)));
    void desktop.providers.status().then(setProviderState);
    void desktop.codex.account().then(setCodexAccount).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    const offEvent = desktop.codex.onEvent(({ method, params }) => {
      if (method === "turn/started") setTurnId(String(params.turn?.id || ""));
      if (method === "turn/completed") setTurnId("");
      if (method === "item/agentMessage/delta") setStream((value) => value + String(params.delta || ""));
      if ((method === "item/started" || method === "item/completed") && params.item?.id) {
        setItems((value) => ({ ...value, [params.item.id]: params.item }));
      }
      if (method === "desktop/error" || method === "error") setError(String(params.message || params.error?.message || "Codex error"));
      if (method === "account/updated" || method === "account/login/completed") {
        void desktop.codex.account().then(setCodexAccount).catch(() => undefined);
      }
    });
    const offRequest = desktop.codex.onRequest((request) => setRequests((value) => [...value, request]));
    const offMcp = desktop.mcp.onApproval((request) => setMcpApproval(request));
    return () => { offEvent(); offRequest(); offMcp(); };
  }, [desktop]);

  const timeline = useMemo(() => Object.values(items), [items]);

  async function ensureThread() {
    if (threadId) return threadId;
    if (!desktop) throw new Error("Desktop bridge unavailable");
    const response = await desktop.codex.startThread({});
    const id = String(response.thread?.id || "");
    if (!id) throw new Error("Codex did not return a thread id");
    setThreadId(id);
    return id;
  }

  async function send() {
    if (!desktop || !prompt.trim()) return;
    setBusy(true); setError(""); setStream(""); setItems({});
    try {
      const id = await ensureThread();
      const response = await desktop.codex.startTurn({ threadId: id, input: [{ type: "text", text: prompt.trim() }] });
      setTurnId(String(response.turn?.id || "")); setPrompt("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }

  async function answer(request: (typeof requests)[number], decision: "accept" | "acceptForSession" | "decline" | "cancel") {
    if (!desktop) return;
    await desktop.codex.respond(request.id, { decision });
    setRequests((value) => value.filter((item) => item.id !== request.id));
  }

  async function saveMcp() {
    if (!desktop) return;
    setError("");
    try {
      const result = await desktop.mcp.save(JSON.parse(mcpConfig));
      setMcpStatus(result.statuses || []); setTools(await desktop.mcp.tools());
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  async function saveKey(provider: "openai" | "kimi", value: string) {
    if (!desktop || !value.trim()) return;
    await desktop.providers.setCredential(provider, value.trim());
    if (provider === "openai") setOpenaiKey(""); else setKimiKey("");
    setProviderState(await desktop.providers.status());
  }

  async function loginWithChatGPT() {
    if (!desktop) return;
    setBusy(true); setError("");
    try {
      await desktop.codex.login("chatgpt");
      setCodexAccount(await desktop.codex.account());
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  }

  if (!desktop) return <div className="agent-empty">Agents доступны в desktop-приложении.</div>;

  return (
    <section className="agent-shell">
      <aside className="agent-sidebar">
        <div><span className="agent-eyebrow">Local agent runtime</span><h1>Codex + MCP</h1><p>Streaming, approvals и локальные инструменты без отдельного сервера.</p></div>
        <Button variant="outline" onClick={() => { setThreadId(""); setStream(""); setItems({}); }}>Новая сессия</Button>
        <div className="agent-connections">
          <h2>Connections</h2>
          <Button variant="outline" onClick={() => void loginWithChatGPT()} disabled={busy}>
            {codexAccount?.account?.type === "chatgpt" ? "ChatGPT подключён" : "Войти через ChatGPT"}
          </Button>
          {codexAccount?.account ? <span className="agent-connection-status">Codex: {codexAccount.account.email || codexAccount.account.type}{codexAccount.account.planType ? ` · ${codexAccount.account.planType}` : ""}</span> : null}
          <label><span>OpenAI API key {providerState.credentials?.openai ? "· saved" : ""}</span><input type="password" value={openaiKey} onChange={(event) => setOpenaiKey(event.target.value)} placeholder="sk-…" /></label>
          <Button variant="outline" onClick={() => void saveKey("openai", openaiKey)}>Сохранить OpenAI key</Button>
          <label><span>Kimi API key {providerState.credentials?.kimi ? "· saved" : ""}</span><input type="password" value={kimiKey} onChange={(event) => setKimiKey(event.target.value)} placeholder="Moonshot key" /></label>
          <Button variant="outline" onClick={() => void saveKey("kimi", kimiKey)}>Сохранить Kimi key</Button>
        </div>
        <div className="agent-thread"><span>Thread</span><code>{threadId || "not started"}</code></div>
        <h2>MCP servers</h2>
        <textarea className="agent-config" value={mcpConfig} onChange={(event) => setMcpConfig(event.target.value)} spellCheck={false} />
        <Button variant="outline" onClick={() => void saveMcp()}>Сохранить и подключить</Button>
        <div className="agent-mcp-list">
          {mcpStatus.map((server) => <span key={server.id} className={server.connected ? "ok" : "bad"}>{server.name}: {server.connected ? `${server.tools} tools` : server.error}</span>)}
          {tools.map((tool) => <code key={tool.qualifiedName}>{tool.serverName}/{tool.name}</code>)}
        </div>
      </aside>
      <main className="agent-main">
        {error ? <div className="agent-error">{error}</div> : null}
        <div className="agent-timeline">
          {!stream && timeline.length === 0 ? <div className="agent-welcome"><h2>Рабочая сессия DesignDNA</h2><p>Попросите Codex проанализировать проект, изменить код или использовать подключённый MCP-инструмент.</p></div> : null}
          {timeline.map((item) => <Timeline key={item.id} item={item} />)}
          {stream ? <article className="agent-message"><span>Codex</span><div>{stream}</div></article> : null}
        </div>
        <div className="agent-composer">
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Что нужно сделать в DesignDNA?" onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send(); }} />
          {turnId ? <Button variant="outline" onClick={() => void desktop.codex.interruptTurn(threadId, turnId)}>Стоп</Button> : null}
          <Button onClick={() => void send()} disabled={busy || !prompt.trim()}>Отправить</Button>
        </div>
      </main>
      {requests[0] ? <Approval request={requests[0]} onDecision={(decision) => void answer(requests[0], decision)} /> : null}
      {mcpApproval ? <McpApproval request={mcpApproval} onDecision={(accepted) => { void desktop.mcp.respondToApproval(String(mcpApproval.id), accepted); setMcpApproval(null); }} /> : null}
    </section>
  );
}

function Timeline({ item }: { item: TimelineItem }) {
  if (item.type === "agentMessage" || item.type === "reasoning" || item.type === "userMessage") return null;
  return <article className="agent-event"><header><strong>{item.type}</strong><span>{item.status || "running"}</span></header>{item.command ? <code>{item.command}</code> : null}{item.aggregatedOutput ? <pre>{item.aggregatedOutput}</pre> : null}{item.changes?.map((change) => <code key={change.path}>{change.kind}: {change.path}</code>)}</article>;
}

function Approval({ request, onDecision }: { request: { method: string; params: Record<string, any> }; onDecision: (decision: "accept" | "acceptForSession" | "decline" | "cancel") => void }) {
  const network = request.params.networkApprovalContext;
  return <div className="agent-modal"><div><span className="agent-eyebrow">Codex approval</span><h2>{network ? "Доступ к сети" : request.method.includes("fileChange") ? "Изменение файлов" : "Выполнение команды"}</h2><p>{request.params.reason || (network ? `${network.protocol || "https"}://${network.host}` : request.params.command || request.params.cwd)}</p><div className="agent-modal-actions"><Button variant="outline" onClick={() => onDecision("decline")}>Отклонить</Button><Button variant="outline" onClick={() => onDecision("accept")}>Разрешить один раз</Button><Button onClick={() => onDecision("acceptForSession")}>На сессию</Button></div></div></div>;
}

function McpApproval({ request, onDecision }: { request: Record<string, any>; onDecision: (accepted: boolean) => void }) {
  return <div className="agent-modal"><div><span className="agent-eyebrow">MCP tool approval</span><h2>{request.server} / {request.tool}</h2><pre>{JSON.stringify(request.arguments || {}, null, 2)}</pre><div className="agent-modal-actions"><Button variant="outline" onClick={() => onDecision(false)}>Отклонить</Button><Button onClick={() => onDecision(true)}>Выполнить</Button></div></div></div>;
}
