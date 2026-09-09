<script lang="ts">
  import { flow, flowBusy, flowEdges, flowNodes } from "../flow/state";
  import { resolveDesignSystemAiProvider } from "../flow/store";
  import type { DesignSystemAiProvider, DesignSystemNodeData } from "../flow/types";

  let { id, data }: { id: number; data: DesignSystemNodeData & Record<string, any> } = $props();
  const nodeId = $derived(String(id));
  let busy = $derived(!!$flowBusy[id] || !!data._dsFinishing);
  let fileInput: HTMLInputElement | null = $state(null);
  let resolvedProvider = $derived.by(() => {
    const node = $flowNodes.find((n) => n.id === nodeId);
    return node ? resolveDesignSystemAiProvider($flowNodes, $flowEdges, node) : "openai";
  });
  let canBuild = $derived.by(() => {
    const edge = $flowEdges.find((e) => e.target === nodeId && e.targetHandle === "artifact");
    const source = $flowNodes.find((n) => n.id === edge?.source);
    return source?.type === "sourceimport" && source.data.blocks.some((b) => !!b.ir && !b.error);
  });

  async function onFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    let payload: unknown;
    try {
      payload = JSON.parse(await file.text());
    } catch {
      $flow.setNodeData(id, { lastError: `«${file.name}» не разбирается как JSON` });
      return;
    }
    await $flow.importDesignSystemDocument(id, payload, file.name);
  }
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Система</div>
    <div class="dna-field-value"><span>{data.name || "Без имени"}</span><span class="dna-out-kind">{data.status === "published" ? `v${data.revision}` : data.status}</span></div>
    {#if data.defaultSet}<div class="dna-field-hint">Система проекта по умолчанию.</div>{/if}
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" checked={data.autoPublish !== false} onchange={(event) => $flow.setNodeData(id, { autoPublish: event.currentTarget.checked })} />
    <span>Автопубликация после сборки</span>
  </label>
  <div class="dna-field">
    <div class="dna-field-cap">AI для всех действий</div>
    <select data-ds-ai-provider value={data.aiProvider || "inherit"} disabled={busy} onchange={(event) => $flow.setNodeData(id, { aiProvider: event.currentTarget.value as DesignSystemAiProvider })}>
      <option value="inherit">Из Source · {resolvedProvider}</option>
      <option value="codex">Codex</option>
      <option value="claude">Claude Opus</option>
      <option value="openai">GPT-5.6 Sol</option>
      <option value="astra">GPT-6 Astra</option>
    </select>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Источник системы</div>
    {#if !data.systemId}
      <button class="dna-btn-ghost" data-ds-action="build" disabled={!canBuild || busy} onclick={() => $flow.rebuildDesignSystemFromSource(id)}>Собрать из Source</button>
    {/if}
    <input class="ds-file" type="file" accept=".json,application/json" hidden bind:this={fileInput} onchange={onFile} />
    <button class="dna-btn-ghost" data-ds-action="import" disabled={busy} title="Документ DesignDNA, W3C / Tokens Studio JSON или карта shadcn" onclick={() => fileInput?.click()}>Загрузить JSON</button>
  </div>
  {#if data.lastError}
    <div class="dna-insp-log err">{String(data.lastError)}</div>
  {/if}
  {#each Object.entries(data.pipelineStatus || {}) as [stage, result]}
    {#if result.timings}
      <details class="dna-field" data-ds-timings={stage}>
        <summary>{stage}: {Math.round(result.timings.elapsedMs / 1000)} с · запросов {result.timings.requests}</summary>
        <div class="dna-field-hint">Подготовка снимков: {Math.round(result.timings.prepareMs / 1000)} с. Серверная проверка: {Math.round(result.timings.applyMs / 1000)} с. AI суммарно по запросам: {Math.round(result.timings.providerMs / 1000)} с. Повторов из-за сети: {result.timings.retries}.</div>
      </details>
    {/if}
  {/each}
</div>
