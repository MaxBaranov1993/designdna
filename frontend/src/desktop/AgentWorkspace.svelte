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
    model?: string;
    effort?: string;
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
  let openrouterKey = $state("");
  /* Claude подключается своим CLI (`claude` → /login): приложение только
   * читает статус, секрет к нам не попадает. */
  let claudeStatus = $state<{ installed: boolean; loggedIn: boolean; hint: string | null } | null>(null);
  /* GPT (Sol / Astra) — тоже только по подписке: Codex CLI app-server,
   * вход через ChatGPT в браузере (`codex:login` → authUrl). Ключ OpenAI API
   * в этом окне не запрашивается. */
  type CodexStatus = { installed: boolean; loggedIn: boolean; mode: "chatgpt" | "apiKey" | null; email: string | null; hint: string | null };
  let codexStatus = $state<CodexStatus | null>(null);
  let codexLoginActive = $state(false);
  let codexLoginError = $state("");
  /* Самопроверка изоляции: Codex — thread/start без вызова модели, Claude —
   * один короткий запрос haiku по подписке. Только по кнопке пользователя. */
  type IsolationSelfTest = { provider: "claude" | "codex"; ok: boolean; isolated: boolean | null; error?: string;
    model?: string | null; elapsedMs: number; globalInstructionSources?: string[]; sample?: string };
  let isolation = $state<Record<string, IsolationSelfTest>>({});
  let isolationBusy = $state<"claude" | "codex" | null>(null);
  async function runIsolationCheck(provider: "claude" | "codex") {
    if (!desktop?.providers?.selfTest || isolationBusy) return;
    isolationBusy = provider;
    try {
      isolation = { ...isolation, [provider]: await desktop.providers.selfTest(provider) };
    } catch (reason) {
      isolation = { ...isolation, [provider]: { provider, ok: false, isolated: null, elapsedMs: 0,
        error: reason instanceof Error ? reason.message : String(reason) } };
    } finally {
      isolationBusy = null;
    }
  }
  const isolationLabel = (result: IsolationSelfTest | undefined): string => {
    if (!result) return "";
    if (result.error) return `Изоляция: ошибка · ${result.error}`;
    if (result.isolated === false) return "Изоляция: НЕ работает — инструкции с диска попадают в модель";
    if (result.isolated) {
      const globals = result.globalInstructionSources?.length || 0;
      return `Изоляция: работает${globals ? ` · глобальных файлов инструкций: ${globals}` : ""}${result.model ? ` · ${result.model}` : ""}`;
    }
    return "Изоляция: не проверена";
  };
  let agentModel = $state("gpt-5.6-sol");
  const modelLabel = (model: string) => model === "opus" ? "Claude Opus" : model === "gpt-6-astra" ? "GPT-6 Astra" : "GPT-5.6 Sol";
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
    void refreshCodex();
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
    // Оба бэкенда — подписки через локальные CLI: Codex (GPT) и Claude Code.
    const selectedBackend = agentModel === "opus" ? "claude" as const : "codex" as const;
    const selectedEffort = agentEffort;
    const selectedModel = agentModel;
    activeCorrelationId = correlationId;
    agentHistory.push({ role: "user", content: question });
    agentHistory = [...agentHistory];
    try {
      // CLI-транспорты отвечают текстом; вызов MCP-инструментов из этого чата
      // пока не поддерживается (toolDefinitions остаётся для API-бэкенда).
      const toolDefs: ReturnType<typeof toolDefinitions> = [];
      for (let round = 0; round < 8; round++) {
        if (activeCorrelationId !== correlationId) return; // cancelled before this round
        const envelope = {
          id: correlationId,
          provider: selectedBackend,
          model: selectedModel,
          profile: "chat",
          reasoning: { effort: selectedEffort },
          messages: agentHistory.map(({ model: _model, effort: _effort, provider: _provider, ...message }) => message),
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
          model: selectedModel,
          effort: selectedEffort,
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

  /* Статус Codex: account/read отдаёт { account: {type: "chatgpt"|"apiKey", email?} | null }.
   * Ошибка запроса — CLI не установлен или app-server не поднялся. */
  async function refreshCodex(): Promise<CodexStatus | null> {
    if (!desktop?.codex) return null;
    try {
      const result = await desktop.codex.account();
      const account = (result?.account ?? result?.data?.account ?? null) as { type?: string; email?: string } | null;
      const mode = account?.type === "chatgpt" ? "chatgpt" : account?.type === "apiKey" ? "apiKey" : null;
      codexStatus = {
        installed: true,
        loggedIn: mode === "chatgpt",
        mode,
        email: account?.email || null,
        hint: mode === "apiKey" ? "Codex вошёл по API-ключу — переподключите по подписке ChatGPT." : mode ? null : "Войдите в ChatGPT, чтобы GPT работал по подписке.",
      };
    } catch (reason) {
      codexStatus = { installed: false, loggedIn: false, mode: null, email: null, hint: reason instanceof Error ? reason.message : "Codex CLI не найден в PATH." };
    }
    return codexStatus;
  }

  /* Вход GPT по подписке: Codex открывает страницу ChatGPT в браузере, мы
   * опрашиваем account/read, пока CLI не сохранит креды (до 3 минут). */
  async function startCodexLogin() {
    if (!desktop?.codex?.login || codexLoginActive) return;
    codexLoginError = "";
    codexLoginActive = true;
    try {
      await desktop.codex.login("chatgpt");
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline && codexLoginActive) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        const status = await refreshCodex();
        if (status?.loggedIn) break;
      }
      if (!codexStatus?.loggedIn) codexLoginError = "Вход не подтверждён. Завершите вход в браузере и нажмите «Проверить GPT».";
    } catch (reason) {
      codexLoginError = reason instanceof Error ? reason.message : String(reason);
    } finally {
      codexLoginActive = false;
    }
  }

  async function saveKey(provider: "openrouter", value: string) {
    if (!desktop || !value.trim()) return;
    await desktop.providers.setCredential(provider, value.trim());
    openrouterKey = "";
    providerState = await desktop.providers.status();
  }

</script>

{#if !desktop}
  <div class="agent-empty">Агенты доступны в десктоп-приложении.</div>
{:else}
  <section class="agent-shell">
    <aside class="agent-sidebar">
      <div><span class="agent-eyebrow">AI workspace</span><h1>Агент + MCP</h1><p>GPT и Claude по подписке · три уровня усилия.</p></div>
      <label>Модель
        <select bind:value={agentModel} disabled={busy || agentRunning} aria-label="Модель агента">
          <option value="gpt-5.6-sol">GPT-5.6 Sol · Codex</option>
          <option value="gpt-6-astra">GPT-6 Astra · Codex</option>
          <option value="opus">Claude Opus · Claude Code</option>
        </select>
      </label>
      {#if agentModel !== "opus" && codexStatus && !codexStatus.loggedIn}
        <p>GPT работает по подписке ChatGPT через Codex CLI — подключите его ниже.</p>
      {:else if agentModel === "opus" && claudeStatus && !claudeStatus.loggedIn}
        <p>Claude работает по подписке через Claude Code — подключите его ниже.</p>
      {/if}
      <div class="agent-backend">
        <button class:active={agentEffort === "medium"} onclick={() => (agentEffort = "medium")} disabled={busy || agentRunning}>Среднее</button>
        <button class:active={agentEffort === "high"} onclick={() => (agentEffort = "high")} disabled={busy || agentRunning}>Высокое</button>
        <button class:active={agentEffort === "max"} onclick={() => (agentEffort = "max")} disabled={busy || agentRunning}>Макс</button>
      </div>
      <Button variant="outline" onclick={() => { agentHistory = []; }} disabled={busy || agentRunning}>Новая сессия</Button>
      <div class="agent-connections">
        <h2>Подключения</h2>
        <div class="agent-runtime" data-provider="codex">
          <span class={codexStatus?.loggedIn ? "ok" : "bad"}>
            GPT · Codex CLI: {codexStatus === null
              ? "проверяю…"
              : codexStatus.loggedIn
                ? `подключён по подписке${codexStatus.email ? ` · ${codexStatus.email}` : ""}`
                : codexStatus.mode === "apiKey"
                  ? "вошёл по API-ключу"
                  : codexStatus.installed
                    ? "не выполнен вход"
                    : "CLI не установлен"}
          </span>
          {#if codexStatus && !codexStatus.loggedIn && codexStatus.hint}
            <p class="agent-runtime-hint">{codexStatus.hint}</p>
          {/if}
          {#if codexLoginActive}
            <p class="agent-runtime-hint">Открыта страница входа ChatGPT в браузере — завершите вход там. Статус обновится сам.</p>
            <Button variant="outline" onclick={() => { codexLoginActive = false; }}>Отменить ожидание</Button>
          {:else if codexStatus && codexStatus.installed && !codexStatus.loggedIn}
            <Button variant="outline" onclick={() => void startCodexLogin()}>Подключить GPT по подписке</Button>
          {/if}
          {#if codexLoginError}<p class="agent-runtime-hint">{codexLoginError}</p>{/if}
          <Button variant="outline" onclick={() => void refreshCodex()}>Проверить GPT</Button>
          <Button variant="outline" onclick={() => void runIsolationCheck("codex")} disabled={isolationBusy !== null || !codexStatus?.loggedIn}>
            {isolationBusy === "codex" ? "Проверяю изоляцию…" : "Проверить изоляцию GPT"}
          </Button>
          {#if isolation.codex}<p class="agent-runtime-hint" data-isolation="codex">{isolationLabel(isolation.codex)}</p>{/if}
        </div>
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
          <Button variant="outline" onclick={() => void runIsolationCheck("claude")} disabled={isolationBusy !== null || !claudeStatus?.loggedIn}>
            {isolationBusy === "claude" ? "Проверяю изоляцию…" : "Проверить изоляцию Claude"}
          </Button>
          {#if isolation.claude}<p class="agent-runtime-hint" data-isolation="claude">{isolationLabel(isolation.claude)} · один короткий запрос haiku по подписке</p>{/if}
        </div>
        <label><span>Ключ OpenRouter (только видео Seedance) {providerState.credentials?.openrouter ? "· сохранён" : ""}</span><input type="password" bind:value={openrouterKey} placeholder="sk-or-v1-…" /></label>
        <Button variant="outline" onclick={() => void saveKey("openrouter", openrouterKey)}>Сохранить ключ OpenRouter</Button>
      </div>
      <h2>MCP-серверы</h2>
      <textarea class="agent-config" bind:value={mcpConfig} spellcheck="false"></textarea>
      <Button variant="outline" onclick={() => void saveMcp()}>Сохранить и подключить</Button>
      <div class="agent-mcp-list">
        {#each mcpStatus as server (server.id)}
          <span class={server.connected ? "ok" : "bad"}>{server.name}: {server.connected ? `инструментов: ${server.tools}` : server.error}</span>
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
          <div class="agent-welcome"><h2>Рабочая сессия DesignDNA</h2><p>Попросите агента проанализировать проект, изменить код или использовать подключённый MCP-инструмент.</p></div>
        {/if}
        {#each agentHistory as message, index (index)}
          <article class="agent-message" class:agent-tool-message={message.role === "tool"}>
            <span>{message.role === "user" ? "Вы" : message.role === "tool" ? `MCP · ${message.toolName || message.toolCallId || ""}` : `${modelLabel(message.model || "gpt-5.6-sol")} · ${message.effort || "medium"}`}</span>
            <div>{message.content}</div>
          </article>
        {/each}
        {#if agentRunning}
          <article class="agent-message"><span>{modelLabel(agentModel)} · {agentEffort}</span><div>думаю… {agentModel !== "opus" && tools.length ? `· MCP-инструментов: ${tools.length}` : ""}</div></article>
        {/if}
      </div>
      <div class="agent-composer">
        <textarea bind:value={prompt} placeholder="Что должен сделать DesignDNA?" onkeydown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send(); }}></textarea>
        {#if agentRunning}<Button variant="outline" onclick={() => void cancelAgent()}>Отменить</Button>{/if}
        <Button onclick={() => void send()} disabled={busy || agentRunning || !prompt.trim()}>Отправить</Button>
      </div>
    </main>
    {#if mcpApproval}
      {@const request = mcpApproval}
      <div class="agent-modal"><div><span class="agent-eyebrow">Подтверждение MCP-инструмента</span><h2>{request.server} / {request.tool}</h2><pre>{JSON.stringify(request.arguments || {}, null, 2)}</pre><div class="agent-modal-actions"><Button variant="outline" onclick={() => { void desktop.mcp.respondToApproval(String(request.id), false); mcpApproval = null; }}>Отклонить</Button><Button onclick={() => { void desktop.mcp.respondToApproval(String(request.id), true); mcpApproval = null; }}>Выполнить</Button></div></div></div>
    {/if}
  </section>
{/if}
