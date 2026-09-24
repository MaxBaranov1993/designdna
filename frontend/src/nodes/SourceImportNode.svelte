<script lang="ts">
  import { captureNodeUpload, sourceAiRepair, sourceCaptureViewports } from "../flow/store";
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import CompositionParts from "../components/CompositionParts.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import { useFlowStore } from "../flow/store";
  import type { SourceImportFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* Source Import — результат-первый: адрес или скриншот сверху, список
   * зажжённых блоков (= выходы) как основное содержимое, футер «Импорт».
   * Вьюпорт, режим превью, авторизованная сессия и AI-аккаунт — в инспекторе. */
  let { id, data, selected }: NodeProps<SourceImportFlowNode> = $props();

  const STAGE_LABELS: Record<string, string> = {
    renderDom: "DOM",
    detectBlocks: "Blocks",
    semanticRefine: "Labels",
    captureCompile: "Layers",
    assemble: "IR",
    fidelity: "Fidelity",
    cacheWrite: "Cache",
  };

  let busy = $derived(!!$flowBusy[Number(id)]);
  let previewMode = $derived(data.previewMode || "reference");
  let captureViewports = $derived(sourceCaptureViewports(data));
  let aiRepair = $derived(sourceAiRepair(data));
  let capturedViewports = $derived(new Set(Object.keys(((data.blocks?.find((block) => block.ir)?.ir as { responsive?: { viewports?: Record<string, unknown> } } | undefined)?.responsive?.viewports) || {})));
  const toggleViewport = (name: "tablet" | "mobile") => {
    const next = captureViewports.filter((item) => item !== "desktop" && item !== name) as ("tablet" | "mobile")[];
    if (!captureViewports.includes(name)) next.push(name);
    $flow.setNodeData(Number(id), { captureViewports: next, importedUrl: null });
  };
  const addViewport = (name: "tablet" | "mobile") => {
    toggleViewport(name);
    void $flow.runNode(Number(id));
  };
  let expandedBlock = $state<string | null>(null);
  let litCount = $derived(data.blocks.filter((b) => b.lit && !b.error).length);

  // Сбрасываем раскрытие только если блок исчез (напр. re-import).
  $effect(() => {
    if (expandedBlock && !data.blocks.some((block) => block.name === expandedBlock)) {
      expandedBlock = null;
    }
  });

  const onFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const applyUpload = captureNodeUpload(Number(id));
    const rd = new FileReader();
    rd.onload = () => applyUpload({ image: String(rd.result), fileName: f.name, mode: "screenshot" });
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

  const createDesignSystem = () => {
    void useFlowStore.getState().createDesignSystemFromSource(Number(id));
  };

  const refreshImport = () => {
    $flow.setNodeData(Number(id), { importedUrl: null });
    queueMicrotask(() => $flow.runNode(Number(id)));
  };
</script>

<NodeShell {id} type="sourceimport" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      {#if data.mode === "url" && data.importedUrl && data.blocks.length}
        <button class="btn-node small f-refresh nodrag" disabled={busy} onclick={refreshImport} title="Reload the page and refresh the local result">Refresh</button>
        <button class="btn-node small f-create-ds nodrag" disabled={busy || !data.blocks?.length} title="Build UI Kit and design system from this Source" onclick={createDesignSystem}>◈ UI Kit &amp; DS</button>
      {:else if data.blocks.length}
        <span>{litCount} of {data.blocks.length} output blocks</span>
      {/if}
    </div>
    <div class="foot-right">
      <button
        class="btn-node primary small f-run nodrag"
        disabled={busy || (data.mode === "url" && !data.mine)}
        onclick={() => $flow.runNode(Number(id))}
      >
        {#if busy}<span class="spinner"></span>{/if} Import
      </button>
    </div>
  {/snippet}
  <div class="seg-row n-seg grow nodrag" role="group" aria-label="Source">
    <button class={"seg-btn" + (data.mode === "url" ? " active" : "")} onclick={() => $flow.setNodeData(Number(id), { mode: "url" })}>URL</button>
    <button class={"seg-btn" + (data.mode === "screenshot" ? " active" : "")} onclick={() => $flow.setNodeData(Number(id), { mode: "screenshot" })}>Screenshot</button>
  </div>
  {#if data.mode === "url"}
    <input
      type="text"
      class="f-url nodrag"
      placeholder="https://site.com/page"
      value={data.url}
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`sourceimport:${id}:url`, () => $flow.setNodeData(Number(id), { url: value }));
      }}
      onblur={(e) => {
        flushNodeText(`sourceimport:${id}:url`);
        const value = e.currentTarget.value.trim();
        if (value && !/^[a-z][a-z\d+.-]*:\/\//i.test(value)) {
          $flow.setNodeData(Number(id), { url: value.startsWith("//") ? `https:${value}` : `https://${value}` });
        }
      }}
    />
    <label class="bp-mine nodrag" title="Only import pages you own or have permission to use">
      <input
        type="checkbox"
        class="f-mine"
        checked={data.mine}
        onchange={(e) => $flow.setNodeData(Number(id), { mine: e.currentTarget.checked })}
      />
      I own this site / have permission
    </label>
    {#if !data.mine}
      <div class="bp-hint">Confirm site ownership or permission to enable import</div>
    {/if}
  {:else}
    {#if data.image}
      <div class="n-hero nodrag"><img class="ref-img" alt="screenshot" src={data.image} /></div>
    {/if}
    <label class="ref-drop nodrag">
      {data.image ? (data.fileName || "screenshot") + " (replace)" : "Upload element screenshot"}
      <input type="file" accept="image/*" hidden onchange={onFile} />
    </label>
  {/if}
  {#if data.mode === "url"}
    <div class="seg-row n-seg grow nodrag source-viewports" role="group" aria-label="Viewports to capture">
      <button class="seg-btn active" disabled title="Desktop 1440 px is always captured" aria-pressed="true">Desktop</button>
      <button class={"seg-btn" + (captureViewports.includes("tablet") ? " active" : "")} disabled={busy}
        aria-pressed={captureViewports.includes("tablet")} title="Also capture tablet 768 px (about +20 s)"
        onclick={() => toggleViewport("tablet")}>+ Tablet</button>
      <button class={"seg-btn" + (captureViewports.includes("mobile") ? " active" : "")} disabled={busy}
        aria-pressed={captureViewports.includes("mobile")} title="Also capture mobile 390 px (about +20 s)"
        onclick={() => toggleViewport("mobile")}>+ Mobile</button>
    </div>
    <label class="bp-mine nodrag source-ai-repair" title="AI repairs blocks that fail the visual check (slower, uses your AI account)">
      <input type="checkbox" checked={aiRepair} disabled={busy}
        onchange={(e) => $flow.setNodeData(Number(id), { aiRepair: e.currentTarget.checked, importedUrl: null })} />
      AI repair
    </label>
    <div class="bp-hint">Exact page snapshot · {captureViewports.join(" + ")}{aiRepair ? " · AI repair" : ""}</div>
    {#if data.blocks?.length && !busy}
      {#each (["tablet", "mobile"] as const).filter((name) => !capturedViewports.has(name)) as name (name)}
        <button class="btn-node small nodrag source-add-viewport" onclick={() => addViewport(name)}
          title={`Capture the ${name} layout of the same page`}>+ Capture {name}</button>
      {/each}
    {/if}
  {/if}
  {#if data.lastRun}
    <div class="source-run-diagnostics" title={`Pipeline ${data.lastRun.pipelineVersion || "unknown"}`}>
      <div class="source-run-summary">
        <span>{data.lastRun.cached ? "From cache" : "Measured"}</span>
        <strong>{(data.lastRun.totalMs / 1000).toFixed(1)}s</strong>
      </div>
      <div class="source-run-stages">
        {#each Object.entries(data.lastRun.timingsMs).filter(([name]) => name !== "total" && name !== "prepare" && name !== "cacheLookup") as [name, duration] (name)}
          <span>{STAGE_LABELS[name] || name} {(duration / 1000).toFixed(duration >= 1000 ? 1 : 2)}s</span>
        {/each}
      </div>
    </div>
  {/if}
  {#if data.sourceArtifact}
    <div class="source-artifact-summary" title={data.sourceArtifact.version}>
      <strong>Source Artifact</strong>
      <span>{data.sourceArtifact.summary?.componentCount ?? 0} components</span>
      <span>{data.sourceArtifact.summary?.observedStateCount ?? 0} states</span>
      <span>{data.sourceArtifact.summary?.viewportCount ?? 0} viewports</span>
    </div>
  {/if}
  {#if data.blocks.length}
    <div class="bp-blocks nowheel">
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
              {#if b.cached}<span class="bp-cached">from cache</span>{/if}
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
                title={expandedBlock === b.name ? "Hide preview" : "Show preview"}
                onclick={() => expandedBlock = expandedBlock === b.name ? null : b.name}
              >
                {expandedBlock === b.name ? "Hide" : "Preview"}
              </button>
            {/if}
          </div>
          {#if b.error}
            <div class="bp-error">{b.error}</div>
          {:else if expandedBlock === b.name}
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
            <CompositionParts ir={b.ir || null} protectedRoot />
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
  <OutPorts {id} type="sourceimport" {data} />
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

<style>
  .n-hero .ref-img { display: block; width: 100%; max-height: 160px; object-fit: contain; object-position: top; border: 0; border-radius: 0; background: #fff; }
</style>
