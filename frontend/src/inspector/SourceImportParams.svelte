<script lang="ts">
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { useFlowStore } from "../flow/store";
  import type { SourceImportNodeData, SourceViewport } from "../flow/types";

  let { id, data }: { id: number; data: SourceImportNodeData } = $props();
  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];
  const PREVIEW_MODES = ["reference", "ir", "compare"] as const;
  let busy = $derived(!!$flowBusy[id]);
  let desktopAuth = $derived(typeof window !== "undefined" ? window.designDNA?.sourceAuth : undefined);

  const openAuthenticatedSession = async () => {
    const rawUrl = (data.url || "").trim();
    if (!rawUrl || !desktopAuth) return;
    const url = /^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    await desktopAuth.open(url);
  };
  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(id, { activeViewport: viewport });
    queueMicrotask(() => $flow.propagate(id));
  };
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Источник</div>
    <div class="dna-insp-seg">
      <button class:active={data.mode === "url"} onclick={() => $flow.setNodeData(id, { mode: "url" })}>URL</button>
      <button class:active={data.mode === "screenshot"} onclick={() => $flow.setNodeData(id, { mode: "screenshot" })}>Скриншот</button>
    </div>
  </div>
  {#if data.mode === "url"}
    <label class="dna-insp-check" title="Импортируйте только свои страницы или страницы, на которые есть право">
      <input type="checkbox" checked={data.mine} onchange={(e) => $flow.setNodeData(id, { mine: e.currentTarget.checked })} />
      <span>Это мой сайт / есть право</span>
    </label>
    {#if desktopAuth}
      <label class="dna-insp-check" title="Cookies остаются в изолированной памяти desktop-приложения">
        <input type="checkbox" checked={data.authenticatedSession} onchange={(e) => $flow.setNodeData(id, { authenticatedSession: e.currentTarget.checked })} />
        <span>Авторизованная сессия</span>
      </label>
      {#if data.authenticatedSession}
        <button class="dna-btn-ghost" onclick={openAuthenticatedSession}>Открыть вход в браузере</button>
      {/if}
    {/if}
  {/if}
  {#if desktopAuth}
    <div class="dna-field">
      <div class="dna-field-cap">AI-уточнение · чей аккаунт</div>
      <ProviderPicker
        provider={data.aiProvider || "openai"}
        effort={data.aiEffort || "high"}
        onChange={(next) => $flow.setNodeData(id, { aiProvider: next.provider, aiEffort: next.effort as "medium" | "high" | "max" })}
      />
    </div>
  {/if}
  <div class="dna-field">
    <div class="dna-field-cap">Вьюпорт превью · снимаются все три</div>
    <div class="dna-insp-seg">
      {#each VIEWPORTS as viewport (viewport)}
        <button class:active={data.activeViewport === viewport} onclick={() => setViewport(viewport)}>{viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}</button>
      {/each}
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Режим превью блока</div>
    <div class="dna-insp-seg">
      {#each PREVIEW_MODES as mode (mode)}
        <button class:active={(data.previewMode || "reference") === mode} onclick={() => $flow.setNodeData(id, { previewMode: mode })}>{mode === "reference" ? "Reference" : mode === "ir" ? "IR" : "Compare"}</button>
      {/each}
    </div>
  </div>
  {#if data.importedUrl && data.blocks.length}
    <div class="dna-insp-row">
      <button class="dna-btn-ghost" disabled={busy} title="Повторно загрузить страницу" onclick={() => { $flow.setNodeData(id, { importedUrl: null }); queueMicrotask(() => $flow.runNode(id)); }}>Обновить импорт</button>
      <button class="dna-btn-ghost" disabled={busy} title="Собрать UI Kit и дизайн-систему из этого Source" onclick={() => void useFlowStore.getState().createDesignSystemFromSource(id)}>◈ UI Kit &amp; ДС</button>
    </div>
  {/if}
  {#if data.lastRun}
    <div class="dna-field">
      <div class="dna-field-cap">Последний импорт</div>
      <div class="dna-field-value"><span>{data.lastRun.cached ? "из кэша" : "измерен"}</span><span class="dna-out-kind">{(data.lastRun.totalMs / 1000).toFixed(1)}s</span></div>
    </div>
  {/if}
</div>
