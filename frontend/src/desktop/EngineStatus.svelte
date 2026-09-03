<script lang="ts">
  import { onMount } from "svelte";
  import { getConfig, type ConfigResp } from "../flow/api";

  /* Индикатор состояния Python-движка десктопа: точка + подпись по
   * engine:status из main.mjs. В браузере (нет window.designDNA) — «Browser mode». */
  type EngineState = Awaited<ReturnType<NonNullable<Window["designDNA"]>["engine"]["status"]>>;
  type Overall = "browser" | "starting" | "ready" | "busy" | "dead";

  const desktop = typeof window !== "undefined" ? window.designDNA : undefined;
  let engine = $state<EngineState | null>(null);
  let restarting = $state(false);
  let error = $state("");

  // Сводный статус двух полос: dead важнее всего, потом starting, потом busy.
  let overall: Overall = $derived.by(() => {
    if (!desktop) return "browser";
    if (!engine) return "starting";
    const statuses = [engine.interactive, engine.long];
    if (statuses.includes("dead")) return "dead";
    if (statuses.includes("starting")) return "starting";
    if (statuses.includes("busy")) return "busy";
    return "ready";
  });

  let lastError = $derived(engine?.lastError || "");
  let showRestart = $derived(overall === "dead" || (overall !== "browser" && Boolean(lastError)));

  /* Браузерный режим: сервер отвечает через ключ OpenAI или консольный аккаунт
   * (Codex CLI / Claude Code) — показываем, через что именно, а не «Browser mode». */
  let providers = $state<ConfigResp["providers"] | null>(null);
  let providerLabel = $derived.by(() => {
    if (!providers) return "Browser mode";
    if (providers.default === "openai") return "OpenAI API";
    if (providers.default === "codex") return "Codex CLI";
    if (providers.default === "claude") return "Claude Code";
    return "Нет AI-аккаунта";
  });
  let providerConnected = $derived(!!providers?.default);

  let label = $derived.by(() => {
    if (overall === "browser") return providerLabel;
    if (overall === "dead") return `Движок упал${lastError ? `: ${truncate(lastError)}` : ""}`;
    if (overall === "starting") return "Запуск…";
    if (overall === "busy") return "Занят";
    return "Движок готов";
  });

  let details = $derived.by(() => {
    if (!desktop) {
      if (!providers) return "";
      const rows = [
        `OpenAI API-ключ: ${providers.openaiKey ? "есть" : "нет"}`,
        `Codex CLI: ${providers.codexCli ? "найден" : "нет"}`,
        `Claude Code: ${providers.claudeCli ? "найден" : "нет"}`,
      ];
      if (!providers.default) rows.push("Войдите: codex login или claude /login, либо задайте OPENAI_API_KEY");
      return rows.join("\n");
    }
    const current = engine;
    if (!current) return "";
    const rows = (["interactive", "long"] as const).map((scope) => {
      const info = current.workers[scope];
      return `${scope}: ${info.status}${info.pending ? ` (${info.pending} в работе)` : ""}${info.pid ? ` pid ${info.pid}` : ""}`;
    });
    if (current.restartCount) rows.push(`перезапусков: ${current.restartCount}`);
    if (lastError) rows.push(`ошибка: ${lastError}`);
    return rows.join("\n");
  });

  function truncate(text: string, max = 90): string {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  const restart = async () => {
    if (!desktop || restarting) return;
    restarting = true;
    error = "";
    try {
      const result = await desktop.engine.restart("all");
      engine = result.state;
    } catch (reason) {
      error = reason instanceof Error ? reason.message : String(reason);
    } finally {
      restarting = false;
    }
  };

  onMount(() => {
    if (!desktop) {
      void getConfig().then((config) => { providers = config.providers ?? { default: null }; }).catch(() => { providers = { default: null }; });
      return;
    }
    const unsubscribe = desktop.engine.onStatus((next) => { engine = next; });
    desktop.engine.status().then((next) => { engine = next; }).catch((reason) => {
      error = reason instanceof Error ? reason.message : String(reason);
    });
    return unsubscribe;
  });
</script>

<div class="engine-status" data-status={overall} data-provider={overall === "browser" ? (providerConnected ? "connected" : providers ? "missing" : "loading") : undefined} title={details || label}>
  <span class="dot" aria-hidden="true"></span>
  <span class="label">{label}</span>
  {#if showRestart}
    <button type="button" class="restart" onclick={restart} disabled={restarting}>
      {restarting ? "Перезапуск…" : "Перезапустить"}
    </button>
  {/if}
  {#if error}
    <span class="error" title={error}>{truncate(error, 60)}</span>
  {/if}
</div>

<style>
  .engine-status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 11px;
    line-height: 1;
    color: var(--dna-muted);
    white-space: nowrap;
  }

  .dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--dna-faint-2);
  }

  .label {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .engine-status[data-status="ready"] .dot {
    background: var(--dna-success);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--dna-success) 22%, transparent);
  }

  .engine-status[data-status="ready"] .label { color: var(--dna-text-2); }

  .engine-status[data-status="busy"] .dot { background: var(--dna-amber); }
  .engine-status[data-status="busy"] .label { color: var(--dna-text-2); }

  .engine-status[data-status="starting"] .dot {
    background: var(--dna-violet-l);
    animation: engine-pulse 1.2s ease-in-out infinite;
  }

  .engine-status[data-status="dead"] .dot { background: var(--dna-danger); }
  .engine-status[data-status="dead"] .label { color: var(--dna-danger-text); }

  .engine-status[data-status="browser"] .label { color: var(--dna-dim); }
  .engine-status[data-provider="connected"] .dot {
    background: var(--dna-success);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--dna-success) 22%, transparent);
  }
  .engine-status[data-provider="connected"] .label { color: var(--dna-text-2); }
  .engine-status[data-provider="missing"] .dot { background: var(--dna-danger); }
  .engine-status[data-provider="missing"] .label { color: var(--dna-danger-text); }

  .restart {
    flex: none;
    padding: 3px 8px;
    border: 1px solid var(--dna-border-strong);
    border-radius: 6px;
    background: var(--dna-elevated);
    color: var(--dna-text-2);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
  }

  .restart:hover:not(:disabled) {
    background: var(--dna-hover);
    border-color: var(--dna-action);
    color: var(--dna-action-text);
  }

  .restart:disabled { opacity: 0.6; cursor: default; }

  .error {
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--dna-danger-text);
  }

  @keyframes engine-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.35; }
  }
</style>
