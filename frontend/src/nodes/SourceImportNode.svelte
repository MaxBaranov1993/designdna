<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { useFlowStore } from "../flow/store";
  import type { SourceImportFlowNode, SourceViewport } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<SourceImportFlowNode> = $props();

  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];
  const PREVIEW_MODES = ["reference", "ir", "compare"] as const;

  let busy = $derived(!!$flow.busy[Number(id)]);
  let previewMode = $derived(data.previewMode || "reference");
  let desktopAuth = $derived(typeof window !== "undefined" ? window.designDNA?.sourceAuth : undefined);
  let expandedBlock = $state<string | null>(null);

  $effect(() => {
    if (!selected || (expandedBlock && !data.blocks.some((block) => block.name === expandedBlock))) {
      expandedBlock = null;
    }
  });

  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(Number(id), { activeViewport: viewport });
    queueMicrotask(() => $flow.propagate(Number(id)));
  };

  const onFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => $flow.setNodeData(Number(id), { image: String(rd.result), fileName: f.name, mode: "screenshot" });
    rd.readAsDataURL(f);
    input.value = "";
  };

  const toggleLit = (name: string, lit: boolean) => {
    $flow.setNodeData(Number(id), {
      blocks: data.blocks.map((b) => (b.name === name ? { ...b, lit } : b)),
    });
    if (!lit) {
      useFlowStore
        .getState()
        .edges.filter((e) => e.source === id && e.sourceHandle === name)
        .forEach((e) => $flow.deleteEdge(e.id));
      useFlowStore.getState().propagate(Number(id));
    }
  };

  const openAuthenticatedSession = async () => {
    const rawUrl = (data.url || "").trim();
    if (!rawUrl || !desktopAuth) return;
    const url = /^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    await desktopAuth.open(url);
  };

  const refreshImport = () => {
    $flow.setNodeData(Number(id), { importedUrl: null });
    queueMicrotask(() => $flow.runNode(Number(id)));
  };
</script>

<NodeShell {id} type="sourceimport" {selected}>
  <div class="seg-row nodrag">
    <button class={"seg-btn" + (data.mode === "url" ? " active" : "")} onclick={() => $flow.setNodeData(Number(id), { mode: "url" })}>
      URL
    </button>
    <button class={"seg-btn" + (data.mode === "screenshot" ? " active" : "")} onclick={() => $flow.setNodeData(Number(id), { mode: "screenshot" })}>
      screenshot
    </button>
  </div>
  {#if data.mode === "url"}
    <input
      type="text"
      class="f-url nodrag"
      placeholder="https://site.com/page"
      value={data.url}
      oninput={(e) => $flow.setNodeData(Number(id), { url: e.currentTarget.value })}
      onblur={(e) => {
        const value = e.currentTarget.value.trim();
        if (value && !/^[a-z][a-z\d+.-]*:\/\//i.test(value)) {
          $flow.setNodeData(Number(id), { url: value.startsWith("//") ? `https:${value}` : `https://${value}` });
        }
      }}
    />
    <label class="bp-mine nodrag" title="Импортируйте только свои страницы или страницы, на которые есть право">
      <input
        type="checkbox"
        class="f-mine"
        checked={data.mine}
        onchange={(e) => $flow.setNodeData(Number(id), { mine: e.currentTarget.checked })}
      />
      это мой сайт / есть право
    </label>
    {#if desktopAuth}
      <label class="bp-mine nodrag" title="Cookies остаются в изолированной памяти desktop-приложения и не сохраняются в графе">
        <input
          type="checkbox"
          class="f-auth-session"
          checked={data.authenticatedSession}
          onchange={(e) => $flow.setNodeData(Number(id), { authenticatedSession: e.currentTarget.checked })}
        />
        использовать авторизованную сессию
      </label>
      {#if data.authenticatedSession}
        <button class="btn-node small f-auth-open nodrag" onclick={openAuthenticatedSession}>Открыть вход</button>
      {/if}
    {/if}
    <div class="source-viewports nodrag" aria-label="Source viewport">
      {#each VIEWPORTS as viewport (viewport)}
        <button
          class={"source-viewport" + (data.activeViewport === viewport ? " active" : "")}
          onclick={() => setViewport(viewport)}
          title={viewport === "desktop" ? "1440 px" : viewport === "tablet" ? "768 px" : "390 px"}
        >
          {viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}
        </button>
      {/each}
    </div>
  {:else}
    {#if data.image}
      <img class="ref-img" alt="screenshot" src={data.image} style="max-height: 120px; object-fit: contain" />
    {/if}
    <label class="ref-drop nodrag">
      {data.image ? (data.fileName || "screenshot") + " (заменить)" : "загрузить скриншот элемента"}
      <input type="file" accept="image/*" hidden onchange={onFile} />
    </label>
  {/if}
  {#if data.mode === "url" && !data.mine}
    <div class="bp-hint">Запуск доступен после отметки «это мой сайт / есть право»</div>
  {/if}
  <div class="ctl-row">
    {#if data.mode === "url" && data.importedUrl && data.blocks.length}
      <button class="btn-node small f-refresh nodrag" disabled={busy} onclick={refreshImport} title="Повторно загрузить страницу и обновить локальный результат">
        Обновить
      </button>
    {/if}
    <button
      class="btn-node primary small f-run nodrag"
      style="margin-left: auto"
      disabled={busy || (data.mode === "url" && !data.mine)}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{/if} Import
    </button>
  </div>
  {#if data.blocks.length}
    <div class="bp-blocks">
      {#each data.blocks as b (b.name)}
        <div class="bp-block" data-block={b.name}>
          <div class="bp-block-head">
            <label class="bp-lit">
              <input
                type="checkbox"
                class="f-lit nodrag"
                disabled={!!b.error}
                checked={b.lit}
                onchange={(e) => toggleLit(b.name, e.currentTarget.checked)}
              />
              <span class="bp-name">{b.label || b.name}</span>
              {#if b.kind}<span class="bp-kind">{b.kind}</span>{/if}
              {#if b.cached}<span class="bp-cached">из кэша</span>{/if}
              {#if b.source}<span class="bp-cached">{b.source}{b.layers ? ` · ${b.layers} layers` : ""}</span>{/if}
              {#if b.repeat?.count && b.repeat.count > 1}
                <span class="bp-repeat">{b.repeat.count}× {b.repeat.kind || "item"} → 1 block</span>
              {/if}
            </label>
            {#if !b.error}
              <button
                class="bp-expand nodrag"
                class:active={expandedBlock === b.name}
                aria-expanded={expandedBlock === b.name}
                title={expandedBlock === b.name ? "Скрыть preview" : "Показать preview"}
                onclick={() => expandedBlock = expandedBlock === b.name ? null : b.name}
              >
                {expandedBlock === b.name ? "Скрыть" : "Preview"}
              </button>
            {/if}
          </div>
          {#if b.error}
            <div class="bp-error">{b.error}</div>
          {:else if expandedBlock === b.name}
            <div class="source-preview-mode nodrag" aria-label="Source preview mode">
              {#each PREVIEW_MODES as mode (mode)}
                <button class={previewMode === mode ? "active" : ""} onclick={() => $flow.setNodeData(Number(id), { previewMode: mode })}>
                  {mode === "reference" ? "Reference" : mode === "ir" ? "IR" : "Compare"}
                </button>
              {/each}
            </div>
            {#if previewMode === "reference"}
              {@render sourceReferencePreview(b.previews?.[data.activeViewport] || b.preview)}
            {:else if previewMode === "compare"}
              <div class="source-compare">
                {@render sourceReferencePreview(b.previews?.[data.activeViewport] || b.preview)}
                <IrPreview class="bp-preview" ir={b.ir || null} height={72} viewport={data.activeViewport} empty="" />
              </div>
            {:else}
              <IrPreview class="bp-preview" ir={b.ir || null} height={72} viewport={data.activeViewport} empty="" />
            {/if}
          {/if}
          {#if !b.error}
            {@const active = data.activeViewport}
            {@const editable = b.editableLayersByViewport?.[active] ?? b.layersByViewport?.[active] ?? b.layers ?? 0}
            {@const components = b.componentBoundariesByViewport?.[active] ?? 0}
            {@const paint = b.paintCoverage?.[active] ?? b.coverage?.[active] ?? 0}
            {@const fidelity = b.fidelity?.[active]}
            {@const p95 = b.p95LayoutError?.[active]}
            {@const dropped = (b.droppedByViewport?.[active] ?? []).filter((d) => d.visual)}
            <div class="source-health">
              <span>{editable} editable layers</span>
              <span>{components} components</span>
              <span>{Math.round(paint)}% paint coverage</span>
              {#if fidelity != null}<span>{Math.round(fidelity)}% fidelity</span>{/if}
              {#if p95 != null}<span>±{p95}px p95</span>{/if}
              {#if dropped.length}<span class="source-warning" title={dropped.map((d) => `${d.sourceKey}: ${d.reason}`).join("\n")}>{dropped.length} visual drop</span>{/if}
              {#if b.warnings?.length}<span class="source-warning">{b.warnings.length} warning</span>{/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="sourceimport" {data} />
</NodeShell>

{#snippet sourceReferencePreview(src?: string)}
  {#if !src}
    <div class="bp-preview source-reference-empty"></div>
  {:else}
    <div class="bp-preview source-reference-preview">
      <img alt="Source reference" src={src} loading="lazy" decoding="async" />
    </div>
  {/if}
{/snippet}
