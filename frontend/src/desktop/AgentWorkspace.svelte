<script lang="ts">
  import { onMount } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import { serializeToolResult } from "./tool-result";
  import "./agent-workspace.css";

  type TimelineItem = { id: string; type: string; text?: string; status?: string; command?: string; aggregatedOutput?: string; changes?: Array<{ path?: string; kind?: string }> };
  type ToolCall = { id: string; name: string; arguments: string };
  type AgentMessage = {
    role: "user" | "assistant" | "tool";
    content: string;
    provider?: string;
    toolCalls?: ToolCall[];
    toolCallId?: string;
    toolName?: string;
  };

  const desktop = window.designDNA;
  let threadId = $state("");
  let turnId = $state("");
  let prompt = $state("");
  let stream = $state("");
  let items = $state<Record<string, TimelineItem>>({});
  let requests = $state<Array<{ id: string | number; method: string; params: Record<string, any> }>>([]);
  let mcpApproval = $state<Record<string, any> | null>(null);
  let mcpConfig = $state("[]");
  let mcpStatus = $state<Array<Record<string, any>>>([]);
  let tools = $state<Array<Record<string, any>>>([]);
  let providerState = $state<Record<string, any>>({});
  let codexAccount = $state<Record<string, any> | null>(null);
  let openaiKey = $state("");
  let kimiKey = $state("");
  let glmKey = $state("");
  let zaiKey = $state("");
  let grokKey = $state("");
  // Agent backend. "codex" keeps the native thread/turn flow; everything else
  // uses the typed chatRequest/cancel envelope + MCP tool loop.
  // GLM-5.3-first chain: по умолчанию агент идёт через GLM (Zhipu) с MCP-циклом;
  // Codex — переключаемый вариант.
  let agentBackend = $state<"codex" | "openai" | "kimi" | "glm" | "zai" | "grok" | "zcode">("glm");
  let agentHistory = $state<AgentMessage[]>([]);
  let agentRunning = $state(false);
  let activeCorrelationId = $state<string | null>(null);
  let kimiImportError = $state("");
  let error = $state("");
  let busy = $state(false);

  onMount(() => {
    if (!desktop) return;
    void desktop.mcp.list().then((servers) => (mcpConfig = JSON.stringify(servers, null, 2)));
    void desktop.mcp.tools().then((list) => (tools = list)).catch(() => undefined);
    void desktop.providers.status().then((state) => (providerState = state));
    void desktop.codex.account().then((account) => (codexAccount = account)).catch((reason) => (error = reason instanceof Error ? reason.message : String(reason)));
    const offEvent = desktop.codex.onEvent(({ method, params }: { method: string; params: any }) => {
      if (method === "turn/started") turnId = String(params.turn?.id || "");
      if (method === "turn/completed") turnId = "";
      if (method === "item/agentMessage/delta") stream = stream + String(params.delta || "");
      if ((method === "item/started" || method === "item/completed") && params.item?.id) {
        items = { ...items, [params.item.id]: params.item };
      }
      if (method === "desktop/error" || method === "error") error = String(params.message || params.error?.message || "Codex error");
      if (method === "account/updated" || method === "account/login/completed") {
        void desktop.codex.account().then((account) => (codexAccount = account)).catch(() => undefined);
      }
    });
    const offRequest = desktop.codex.onRequest((request: { id: string | number; method: string; params: Record<string, any> }) => (requests = [...requests, request]));
    const offMcp = desktop.mcp.onApproval((request: Record<string, any>) => (mcpApproval = request));
    return () => { offEvent(); offRequest(); offMcp(); };
  });

  let timeline = $derived(Object.values(items));

  function generateId() {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  async function ensureThread() {
    if (threadId) return threadId;
    if (!desktop) throw new Error("Desktop bridge unavailable");
    const response = await desktop.codex.startThread({});
    const id = String(response.thread?.id || "");
    if (!id) throw new Error("Codex did not return a thread id");
    threadId = id;
    return id;
  }

  async function send() {
    if (!desktop || !prompt.trim()) return;
    error = "";
    if (agentBackend === "codex") { await sendCodex(); return; }
    await sendAgent();
  }

  async function sendCodex() {
    if (!desktop) return;
    busy = true; stream = ""; items = {};
    try {
      const id = await ensureThread();
      const response = await desktop.codex.startTurn({ threadId: id, input: [{ type: "text", text: prompt.trim() }] });
      turnId = String((response as { turn?: { id?: string } }).turn?.id || ""); prompt = "";
    } catch (reason) { error = reason instanceof Error ? reason.message : String(reason); }
    finally { busy = false; }
  }

  function toolDefinitions() {
    return tools.map((tool) => ({
      type: "function",
      function: {
        // qualifiedName уходит ДОСЛОВНО: McpManager генерирует provider-safe
        // детерминированные имена (≤128 байт, hash-сuffix при коллизиях) —
        // replace/slice здесь разорвали бы связь с исходным инструментом.
        name: String(tool.qualifiedName || tool.name || ""),
        // description тоже дословно: envelope громко отвергнет >1024 UTF-8
        // байт, а скрытый slice искажал бы промпт без ведома вызывающего.
        description: `[${tool.serverName || "mcp"}] ${String(tool.description || tool.name || "")}`,
        parameters: tool.inputSchema && typeof tool.inputSchema === "object" ? tool.inputSchema : { type: "object", properties: {} },
      },
    }));
  }

  /** Provider-agnostic agent loop using the typed chatRequest/cancel envelope.
   *  - Preserves complete tool history: assistant tool_calls + tool role
   *    tool_call_id/name/content for every round.
   *  - Uses a correlation id for cancellation and MCP audit.
   *  - Surfaces adapter errors and dropped parameters to the user. */
  async function sendAgent() {
    if (!desktop || !prompt.trim() || agentRunning) return;
    agentRunning = true; error = "";
    const question = prompt.trim();
    prompt = "";
    const correlationId = generateId();
    const selectedBackend = agentBackend;
    activeCorrelationId = correlationId;
    agentHistory.push({ role: "user", content: question });
    agentHistory = [...agentHistory];
    try {
      const toolDefs = toolDefinitions();
      for (let round = 0; round < 8; round++) {
        if (activeCorrelationId !== correlationId) return; // cancelled before this round
        const envelope = {
          id: correlationId,
          provider: selectedBackend,
          messages: agentHistory,
          temperature: 0.4,
          tools: toolDefs.length ? toolDefs : null,
        };
        let answer;
        try {
          answer = await desktop.providers.chatRequest(envelope);
        } catch (reason) {
          throw new Error(reason instanceof Error ? reason.message : String(reason));
        }
        const calls = answer.toolCalls || [];
        const assistantMessage: AgentMessage = {
          role: "assistant",
          content: answer.content || "",
          provider: selectedBackend,
          toolCalls: calls.length ? calls : undefined,
        };
        agentHistory.push(assistantMessage);
        agentHistory = [...agentHistory];
        if (answer.transport?.dropped?.length) {
          const dropped = answer.transport.dropped.map((d: any) => `${d.field}: ${d.reason}`).join("; ");
          agentHistory.push({ role: "assistant", provider: selectedBackend, content: `[parameters dropped by ${answer.provider || selectedBackend}] ${dropped}` });
          agentHistory = [...agentHistory];
        }
        if (!calls.length) return;
        for (const call of calls) {
          let resultText = "";
          try {
            const args = JSON.parse(call.arguments || "{}");
            const result = await desktop.mcp.call(call.name, args, { correlationId });
            // Никогда не режем JSON молча: oversize → явный структурный
            // маркер ошибки (см. tool-result.ts), history остаётся валидной.
            resultText = serializeToolResult(result).text;
          } catch (reason) {
            resultText = `tool error: ${reason instanceof Error ? reason.message : String(reason)}`;
          }
          agentHistory.push({
            role: "tool",
            content: resultText,
            toolCallId: call.id,
            toolName: call.name,
          });
          agentHistory = [...agentHistory];
        }
      }
      agentHistory.push({ role: "assistant", provider: selectedBackend, content: "(tool round limit reached — rephrase the task)" });
      agentHistory = [...agentHistory];
    } catch (reason) {
      // A user-initiated cancel rejects the in-flight request with
      // PROVIDER_CANCELLED — that is a neutral stop, not an error banner.
      if (activeCorrelationId === correlationId) {
        error = reason instanceof Error ? reason.message : String(reason);
      }
    } finally {
      // A cancelled request may settle after the user has already started a
      // new one. Never let the old finally block clear the new correlation id.
      if (activeCorrelationId === correlationId) activeCorrelationId = null;
      agentRunning = activeCorrelationId !== null;
    }
  }

  async function cancelAgent() {
    if (!desktop || !activeCorrelationId) return;
    const correlationId = activeCorrelationId;
    // Clear first so the loop's cancel checks trip even if the aborted
    // chatRequest rejects before the IPC calls below return.
    activeCorrelationId = null;
    agentRunning = false;
    try {
      await desktop.providers.cancel(correlationId);
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
    }
    try {
      // Abort an in-flight MCP tool call too — providers.cancel only covers
      // the chat request, the tool call would otherwise run to completion.
      await desktop.mcp.cancel(correlationId);
    } catch {
      // no in-flight MCP call for this correlation id — nothing to cancel
    }
  }

  async function answer(request: (typeof requests)[number], decision: "accept" | "acceptForSession" | "decline" | "cancel") {
    if (!desktop) return;
    await desktop.codex.respond(request.id, { decision });
    requests = requests.filter((item) => item.id !== request.id);
  }

  async function saveMcp() {
    if (!desktop) return;
    error = "";
    try {
      const result = await desktop.mcp.save(JSON.parse(mcpConfig));
      mcpStatus = result.statuses || []; tools = await desktop.mcp.tools();
    } catch (reason) { error = reason instanceof Error ? reason.message : String(reason); }
  }

  async function saveKey(provider: "openai" | "kimi" | "glm" | "zai" | "grok", value: string) {
    if (!desktop || !value.trim()) return;
    await desktop.providers.setCredential(provider, value.trim());
    if (provider === "openai") openaiKey = "";
    else if (provider === "kimi") kimiKey = "";
    else if (provider === "zai") zaiKey = "";
    else if (provider === "grok") grokKey = "";
    else glmKey = "";
    providerState = await desktop.providers.status();
  }

  async function importKimiCli() {
    if (!desktop) return;
    busy = true; error = ""; kimiImportError = "";
    try {
      await desktop.providers.importKimiCli();
      providerState = await desktop.providers.status();
    } catch (reason) { kimiImportError = reason instanceof Error ? reason.message : String(reason); }
    finally { busy = false; }
  }

  async function loginWithChatGPT() {
    if (!desktop) return;
    busy = true; error = "";
    try {
      await desktop.codex.login("chatgpt");
      codexAccount = await desktop.codex.account();
    } catch (reason) { error = reason instanceof Error ? reason.message : String(reason); }
    finally { busy = false; }
  }
</script>

{#if !desktop}
  <div class="agent-empty">Agents available in the desktop app.</div>
{:else}
  <section class="agent-shell">
    <aside class="agent-sidebar">
      <div><span class="agent-eyebrow">Local agent runtime</span><h1>Agents + MCP</h1><p>Streaming, approvals and local tools without a separate server.</p></div>
      <div class="agent-backend">
        <button class:active={agentBackend === "codex"} onclick={() => (agentBackend = "codex")} disabled={busy || agentRunning}>Codex</button>
        <button class:active={agentBackend === "openai"} onclick={() => (agentBackend = "openai")} disabled={busy || agentRunning}>OpenAI</button>
        <button class:active={agentBackend === "kimi"} onclick={() => (agentBackend = "kimi")} disabled={busy || agentRunning}>Kimi</button>
        <button class:active={agentBackend === "glm"} onclick={() => (agentBackend = "glm")} disabled={busy || agentRunning}>GLM-5.3 · Zhipu</button>
        <button class:active={agentBackend === "zai"} onclick={() => (agentBackend = "zai")} disabled={busy || agentRunning}>GLM-5.3 · Z.AI</button>
        <button class:active={agentBackend === "grok"} onclick={() => (agentBackend = "grok")} disabled={busy || agentRunning}>Grok</button>
        <button class:active={agentBackend === "zcode"} onclick={() => (agentBackend = "zcode")} disabled={busy || agentRunning}>ZCode</button>
      </div>
      <Button variant="outline" onclick={() => { threadId = ""; stream = ""; items = {}; agentHistory = []; }} disabled={busy || agentRunning}>New session</Button>
      <div class="agent-connections">
        <h2>Connections</h2>
        <Button variant="outline" onclick={() => void loginWithChatGPT()} disabled={busy}>
          {codexAccount?.account?.type === "chatgpt" ? "ChatGPT connected" : "Sign in with ChatGPT"}
        </Button>
        {#if codexAccount?.account}
          <span class="agent-connection-status">Codex: {codexAccount.account.email || codexAccount.account.type}{codexAccount.account.planType ? ` · ${codexAccount.account.planType}` : ""}</span>
        {/if}
        <label><span>OpenAI API key {providerState.credentials?.openai ? "· saved" : ""}</span><input type="password" bind:value={openaiKey} placeholder="sk-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("openai", openaiKey)}>Save OpenAI key</Button>
        <label><span>Kimi API key {providerState.credentials?.kimi ? "· saved" : ""}</span><input type="password" bind:value={kimiKey} placeholder="Moonshot key" /></label>
        <Button variant="outline" onclick={() => void saveKey("kimi", kimiKey)}>Save Kimi key</Button>
        <label><span>GLM API key (Zhipu) {providerState.credentials?.glm ? "· saved" : ""}</span><input type="password" bind:value={glmKey} placeholder="Zhipu bigmodel.cn key" /></label>
        <Button variant="outline" onclick={() => void saveKey("glm", glmKey)}>Save GLM key</Button>
        <label><span>Z.AI API key (direct GLM) {providerState.credentials?.zai ? "· saved" : ""}</span><input type="password" bind:value={zaiKey} placeholder="api.z.ai key" /></label>
        <Button variant="outline" onclick={() => void saveKey("zai", zaiKey)}>Save Z.AI key</Button>
        <label><span>Grok API key {providerState.credentials?.grok ? "· saved" : ""}</span><input type="password" bind:value={grokKey} placeholder="xai-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("grok", grokKey)}>Save Grok key</Button>
        <Button variant="outline" onclick={() => void importKimiCli()} disabled={busy}>Import from Kimi CLI</Button>
        {#if providerState.kimiAccount?.connected}
          <span class="agent-connection-status">
            Kimi CLI: {providerState.kimiAccount.kind === "oauth" ? "OAuth" : "API key"}
            {providerState.kimiAccount.expiresAt ? ` · token until ${new Date(providerState.kimiAccount.expiresAt * 1000).toLocaleDateString("en-US")}` : ""}
          </span>
        {/if}
        {#if kimiImportError}<span class="agent-connection-status">{kimiImportError}</span>{/if}
      </div>
      <div class="agent-thread"><span>Thread</span><code>{threadId || "not started"}</code></div>
      <h2>MCP servers</h2>
      <textarea class="agent-config" bind:value={mcpConfig} spellcheck="false"></textarea>
      <Button variant="outline" onclick={() => void saveMcp()}>Save and connect</Button>
      <div class="agent-mcp-list">
        {#each mcpStatus as server (server.id)}
          <span class={server.connected ? "ok" : "bad"}>{server.name}: {server.connected ? `${server.tools} tools` : server.error}</span>
        {/each}
        {#each tools as tool (tool.qualifiedName)}
          <code>{tool.serverName}/{tool.name}</code>
        {/each}
      </div>
    </aside>
    <main class="agent-main">
      {#if error}<div class="agent-error">{error}</div>{/if}
      <div class="agent-timeline">
        {#if !stream && timeline.length === 0 && agentHistory.length === 0}
          <div class="agent-welcome"><h2>DesignDNA working session</h2><p>Ask the agent to analyze the project, change code, or use a connected MCP tool.</p></div>
        {/if}
        {#each timeline as item (item.id)}
          {@render timelineRow(item)}
        {/each}
        {#each agentHistory as message, index (index)}
          <article class="agent-message" class:agent-tool-message={message.role === "tool"}>
            <span>{message.role === "user" ? "You" : message.role === "tool" ? `MCP · ${message.toolName || message.toolCallId || ""}` : message.provider || agentBackend}</span>
            <div>{message.content}</div>
          </article>
        {/each}
        {#if stream}
          <article class="agent-message"><span>Codex</span><div>{stream}</div></article>
        {/if}
        {#if agentRunning}
          <article class="agent-message"><span>{agentBackend}</span><div>thinking… {tools.length ? `· ${tools.length} MCP tools` : ""}</div></article>
        {/if}
      </div>
      <div class="agent-composer">
        <textarea bind:value={prompt} placeholder="What should DesignDNA do?" onkeydown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send(); }}></textarea>
        {#if turnId}<Button variant="outline" onclick={() => void desktop.codex.interruptTurn(threadId, turnId)}>Stop</Button>{/if}
        {#if agentRunning}<Button variant="outline" onclick={() => void cancelAgent()}>Cancel</Button>{/if}
        <Button onclick={() => void send()} disabled={busy || agentRunning || !prompt.trim()}>Send</Button>
      </div>
    </main>
    {#if requests[0]}
      {@const request = requests[0]}
      {@const network = request.params.networkApprovalContext}
      <div class="agent-modal"><div><span class="agent-eyebrow">Codex approval</span><h2>{network ? "Network access" : request.method.includes("fileChange") ? "File change" : "Command execution"}</h2><p>{request.params.reason || (network ? `${network.protocol || "https"}://${network.host}` : request.params.command || request.params.cwd)}</p><div class="agent-modal-actions"><Button variant="outline" onclick={() => void answer(request, "decline")}>Decline</Button><Button variant="outline" onclick={() => void answer(request, "accept")}>Allow once</Button><Button onclick={() => void answer(request, "acceptForSession")}>Allow session</Button></div></div></div>
    {/if}
    {#if mcpApproval}
      {@const request = mcpApproval}
      <div class="agent-modal"><div><span class="agent-eyebrow">MCP tool approval</span><h2>{request.server} / {request.tool}</h2><pre>{JSON.stringify(request.arguments || {}, null, 2)}</pre><div class="agent-modal-actions"><Button variant="outline" onclick={() => { void desktop.mcp.respondToApproval(String(request.id), false); mcpApproval = null; }}>Decline</Button><Button onclick={() => { void desktop.mcp.respondToApproval(String(request.id), true); mcpApproval = null; }}>Execute</Button></div></div></div>
    {/if}
  </section>
{/if}

{#snippet timelineRow(item: TimelineItem)}
  {#if item.type !== "agentMessage" && item.type !== "reasoning" && item.type !== "userMessage"}
    <article class="agent-event"><header><strong>{item.type}</strong><span>{item.status || "running"}</span></header>{#if item.command}<code>{item.command}</code>{/if}{#if item.aggregatedOutput}<pre>{item.aggregatedOutput}</pre>{/if}{#each item.changes || [] as change (change.path)}<code>{change.kind}: {change.path}</code>{/each}</article>
  {/if}
{/snippet}
