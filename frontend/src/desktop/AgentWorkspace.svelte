<script lang="ts">
  import { onMount } from "svelte";
  import Button from "../components/ui/Button.svelte";
  import "./agent-workspace.css";

  type TimelineItem = { id: string; type: string; text?: string; status?: string; command?: string; aggregatedOutput?: string; changes?: Array<{ path?: string; kind?: string }> };

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
  let kimiImportError = $state("");
  let error = $state("");
  let busy = $state(false);

  onMount(() => {
    if (!desktop) return;
    void desktop.mcp.list().then((servers) => (mcpConfig = JSON.stringify(servers, null, 2)));
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
    busy = true; error = ""; stream = ""; items = {};
    try {
      const id = await ensureThread();
      const response = await desktop.codex.startTurn({ threadId: id, input: [{ type: "text", text: prompt.trim() }] });
      turnId = String(response.turn?.id || ""); prompt = "";
    } catch (reason) { error = reason instanceof Error ? reason.message : String(reason); }
    finally { busy = false; }
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

  async function saveKey(provider: "openai" | "kimi", value: string) {
    if (!desktop || !value.trim()) return;
    await desktop.providers.setCredential(provider, value.trim());
    if (provider === "openai") openaiKey = "";
    else kimiKey = "";
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
  <div class="agent-empty">Agents доступны в desktop-приложении.</div>
{:else}
  <section class="agent-shell">
    <aside class="agent-sidebar">
      <div><span class="agent-eyebrow">Local agent runtime</span><h1>Codex + MCP</h1><p>Streaming, approvals и локальные инструменты без отдельного сервера.</p></div>
      <Button variant="outline" onclick={() => { threadId = ""; stream = ""; items = {}; }}>Новая сессия</Button>
      <div class="agent-connections">
        <h2>Connections</h2>
        <Button variant="outline" onclick={() => void loginWithChatGPT()} disabled={busy}>
          {codexAccount?.account?.type === "chatgpt" ? "ChatGPT подключён" : "Войти через ChatGPT"}
        </Button>
        {#if codexAccount?.account}
          <span class="agent-connection-status">Codex: {codexAccount.account.email || codexAccount.account.type}{codexAccount.account.planType ? ` · ${codexAccount.account.planType}` : ""}</span>
        {/if}
        <label><span>OpenAI API key {providerState.credentials?.openai ? "· saved" : ""}</span><input type="password" bind:value={openaiKey} placeholder="sk-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("openai", openaiKey)}>Сохранить OpenAI key</Button>
        <label><span>Kimi API key {providerState.credentials?.kimi ? "· saved" : ""}</span><input type="password" bind:value={kimiKey} placeholder="Moonshot key" /></label>
        <Button variant="outline" onclick={() => void saveKey("kimi", kimiKey)}>Сохранить Kimi key</Button>
        <Button variant="outline" onclick={() => void importKimiCli()} disabled={busy}>Импорт из Kimi CLI</Button>
        {#if providerState.kimiAccount?.connected}
          <span class="agent-connection-status">
            Kimi CLI: {providerState.kimiAccount.kind === "oauth" ? "OAuth" : "API key"}
            {providerState.kimiAccount.expiresAt ? ` · токен до ${new Date(providerState.kimiAccount.expiresAt * 1000).toLocaleDateString("ru-RU")}` : ""}
          </span>
        {/if}
        {#if kimiImportError}<span class="agent-connection-status">{kimiImportError}</span>{/if}
      </div>
      <div class="agent-thread"><span>Thread</span><code>{threadId || "not started"}</code></div>
      <h2>MCP servers</h2>
      <textarea class="agent-config" bind:value={mcpConfig} spellcheck="false"></textarea>
      <Button variant="outline" onclick={() => void saveMcp()}>Сохранить и подключить</Button>
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
        {#if !stream && timeline.length === 0}
          <div class="agent-welcome"><h2>Рабочая сессия DesignDNA</h2><p>Попросите Codex проанализировать проект, изменить код или использовать подключённый MCP-инструмент.</p></div>
        {/if}
        {#each timeline as item (item.id)}
          {@render timelineRow(item)}
        {/each}
        {#if stream}
          <article class="agent-message"><span>Codex</span><div>{stream}</div></article>
        {/if}
      </div>
      <div class="agent-composer">
        <textarea bind:value={prompt} placeholder="Что нужно сделать в DesignDNA?" onkeydown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send(); }}></textarea>
        {#if turnId}<Button variant="outline" onclick={() => void desktop.codex.interruptTurn(threadId, turnId)}>Стоп</Button>{/if}
        <Button onclick={() => void send()} disabled={busy || !prompt.trim()}>Отправить</Button>
      </div>
    </main>
    {#if requests[0]}
      {@const request = requests[0]}
      {@const network = request.params.networkApprovalContext}
      <div class="agent-modal"><div><span class="agent-eyebrow">Codex approval</span><h2>{network ? "Доступ к сети" : request.method.includes("fileChange") ? "Изменение файлов" : "Выполнение команды"}</h2><p>{request.params.reason || (network ? `${network.protocol || "https"}://${network.host}` : request.params.command || request.params.cwd)}</p><div class="agent-modal-actions"><Button variant="outline" onclick={() => void answer(request, "decline")}>Отклонить</Button><Button variant="outline" onclick={() => void answer(request, "accept")}>Разрешить один раз</Button><Button onclick={() => void answer(request, "acceptForSession")}>На сессию</Button></div></div></div>
    {/if}
    {#if mcpApproval}
      {@const request = mcpApproval}
      <div class="agent-modal"><div><span class="agent-eyebrow">MCP tool approval</span><h2>{request.server} / {request.tool}</h2><pre>{JSON.stringify(request.arguments || {}, null, 2)}</pre><div class="agent-modal-actions"><Button variant="outline" onclick={() => { void desktop.mcp.respondToApproval(String(request.id), false); mcpApproval = null; }}>Отклонить</Button><Button onclick={() => { void desktop.mcp.respondToApproval(String(request.id), true); mcpApproval = null; }}>Выполнить</Button></div></div></div>
    {/if}
  </section>
{/if}

{#snippet timelineRow(item: TimelineItem)}
  {#if item.type !== "agentMessage" && item.type !== "reasoning" && item.type !== "userMessage"}
    <article class="agent-event"><header><strong>{item.type}</strong><span>{item.status || "running"}</span></header>{#if item.command}<code>{item.command}</code>{/if}{#if item.aggregatedOutput}<pre>{item.aggregatedOutput}</pre>{/if}{#each item.changes || [] as change (change.path)}<code>{change.kind}: {change.path}</code>{/each}</article>
  {/if}
{/snippet}
