<script lang="ts">
  import { onMount } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import { serializeToolResult } from "./tool-result";
  import "./agent-workspace.css";

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
  let prompt = $state("");
  let mcpApproval = $state<Record<string, any> | null>(null);
  let mcpConfig = $state("[]");
  let mcpStatus = $state<Array<Record<string, any>>>([]);
  let tools = $state<Array<Record<string, any>>>([]);
  let providerState = $state<Record<string, any>>({});
  let openaiKey = $state("");
  let openrouterKey = $state("");
  /* Claude подключается своим CLI (`claude` → /login): приложение только
   * читает статус, секрет к нам не попадает. */
  let claudeStatus = $state<{ installed: boolean; loggedIn: boolean; hint: string | null } | null>(null);
  let agentEffort = $state<"medium" | "high" | "max">("medium");
  let agentHistory = $state<AgentMessage[]>([]);
  let agentRunning = $state(false);
  let activeCorrelationId = $state<string | null>(null);
  let error = $state("");
  let busy = $state(false);

  onMount(() => {
    if (!desktop) return;
    void desktop.mcp.list().then((servers) => (mcpConfig = JSON.stringify(servers, null, 2)));
    void desktop.mcp.tools().then((list) => (tools = list)).catch(() => undefined);
    void desktop.providers.status().then((state) => (providerState = state));
    void refreshClaude();
    const offMcp = desktop.mcp.onApproval((request: Record<string, any>) => (mcpApproval = request));
    return () => { offMcp(); };
  });

  function generateId() {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  }

  async function send() {
    if (!desktop || !prompt.trim()) return;
    error = "";
    await sendAgent();
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
    const selectedBackend = "openai" as const;
    const selectedEffort = agentEffort;
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
          model: "gpt-5.6-sol",
          reasoning: { effort: selectedEffort },
          messages: agentHistory,
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

  async function saveMcp() {
    if (!desktop) return;
    error = "";
    try {
      const result = await desktop.mcp.save(JSON.parse(mcpConfig));
      mcpStatus = result.statuses || []; tools = await desktop.mcp.tools();
    } catch (reason) { error = reason instanceof Error ? reason.message : String(reason); }
  }

  async function refreshClaude() {
    if (!desktop?.claude) return;
    try {
      claudeStatus = await desktop.claude.status();
    } catch {
      claudeStatus = { installed: false, loggedIn: false, hint: "Claude CLI не найден в PATH." };
    }
  }

  /* Вход Claude из приложения: открывается окно терминала с `claude /login`,
   * приложение ждёт, пока CLI сохранит креды, и обновляет статус само. */
  let claudeLoginActive = $state(false);
  let claudeLoginError = $state("");

  async function startClaudeLogin() {
    if (!desktop?.claude?.loginStart) return;
    claudeLoginError = "";
    try {
      await desktop.claude.loginStart();
      claudeLoginActive = true;
      claudeStatus = await desktop.claude.loginWait();
      claudeLoginActive = false;
    } catch (reason) {
      claudeLoginActive = false;
      claudeLoginError = reason instanceof Error ? reason.message : String(reason);
    }
  }

  async function saveKey(provider: "openai" | "openrouter", value: string) {
    if (!desktop || !value.trim()) return;
    await desktop.providers.setCredential(provider, value.trim());
    if (provider === "openai") openaiKey = "";
    else openrouterKey = "";
    providerState = await desktop.providers.status();
  }

</script>

{#if !desktop}
  <div class="agent-empty">Agents available in the desktop app.</div>
{:else}
  <section class="agent-shell">
    <aside class="agent-sidebar">
      <div><span class="agent-eyebrow">GPT-5.6 Sol</span><h1>Agent + MCP</h1><p>One model, three explicit reasoning profiles.</p></div>
      <div class="agent-backend">
        <button class:active={agentEffort === "medium"} onclick={() => (agentEffort = "medium")} disabled={busy || agentRunning}>Medium</button>
        <button class:active={agentEffort === "high"} onclick={() => (agentEffort = "high")} disabled={busy || agentRunning}>High</button>
        <button class:active={agentEffort === "max"} onclick={() => (agentEffort = "max")} disabled={busy || agentRunning}>Max</button>
      </div>
      <Button variant="outline" onclick={() => { agentHistory = []; }} disabled={busy || agentRunning}>New session</Button>
      <div class="agent-connections">
        <h2>Connections</h2>
        <label><span>OpenAI API key {providerState.credentials?.openai ? "· saved" : ""}</span><input type="password" bind:value={openaiKey} placeholder="sk-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("openai", openaiKey)}>Save OpenAI key</Button>
        <label><span>OpenRouter video key {providerState.credentials?.openrouter ? "· saved" : ""}</span><input type="password" bind:value={openrouterKey} placeholder="sk-or-v1-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("openrouter", openrouterKey)}>Save OpenRouter key</Button>
        <div class="agent-runtime" data-provider="claude">
          <span class={claudeStatus?.loggedIn ? "ok" : "bad"}>
            Claude Opus: {claudeStatus === null
              ? "проверяю…"
              : claudeStatus.loggedIn
                ? "подключён по подписке"
                : claudeStatus.installed
                  ? "не выполнен вход"
                  : "CLI не установлен"}
          </span>
          {#if claudeStatus && !claudeStatus.loggedIn}
            <p class="agent-runtime-hint">{claudeStatus.hint || "Установите Claude Code и выполните вход."}</p>
          {/if}
          {#if claudeLoginActive}
            <p class="agent-runtime-hint">Открыто окно терминала — завершите вход там (браузер откроется сам). Статус обновится автоматически.</p>
          {:else if claudeStatus?.installed && !claudeStatus.loggedIn}
            <Button variant="outline" onclick={() => void startClaudeLogin()}>Подключить Claude</Button>
          {/if}
          {#if claudeLoginError}<p class="agent-runtime-hint">{claudeLoginError}</p>{/if}
          <Button variant="outline" onclick={() => void refreshClaude()}>Проверить Claude</Button>
        </div>
      </div>
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
        {#if agentHistory.length === 0}
          <div class="agent-welcome"><h2>DesignDNA working session</h2><p>Ask the agent to analyze the project, change code, or use a connected MCP tool.</p></div>
        {/if}
        {#each agentHistory as message, index (index)}
          <article class="agent-message" class:agent-tool-message={message.role === "tool"}>
            <span>{message.role === "user" ? "You" : message.role === "tool" ? `MCP · ${message.toolName || message.toolCallId || ""}` : `GPT-5.6 Sol · ${agentEffort}`}</span>
            <div>{message.content}</div>
          </article>
        {/each}
        {#if agentRunning}
          <article class="agent-message"><span>GPT-5.6 Sol · {agentEffort}</span><div>thinking… {tools.length ? `· ${tools.length} MCP tools` : ""}</div></article>
        {/if}
      </div>
      <div class="agent-composer">
        <textarea bind:value={prompt} placeholder="What should DesignDNA do?" onkeydown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send(); }}></textarea>
        {#if agentRunning}<Button variant="outline" onclick={() => void cancelAgent()}>Cancel</Button>{/if}
        <Button onclick={() => void send()} disabled={busy || agentRunning || !prompt.trim()}>Send</Button>
      </div>
    </main>
    {#if mcpApproval}
      {@const request = mcpApproval}
      <div class="agent-modal"><div><span class="agent-eyebrow">MCP tool approval</span><h2>{request.server} / {request.tool}</h2><pre>{JSON.stringify(request.arguments || {}, null, 2)}</pre><div class="agent-modal-actions"><Button variant="outline" onclick={() => { void desktop.mcp.respondToApproval(String(request.id), false); mcpApproval = null; }}>Decline</Button><Button onclick={() => { void desktop.mcp.respondToApproval(String(request.id), true); mcpApproval = null; }}>Execute</Button></div></div></div>
    {/if}
  </section>
{/if}
