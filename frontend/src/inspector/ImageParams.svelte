<script lang="ts">
  import { onMount } from "svelte";
  import { apiGet } from "../flow/api";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { ImageNodeData } from "../flow/types";

  /* GPT Image creates raster assets; legacy SVG remains an explicit mode. */
  let { id, data }: { id: number; data: ImageNodeData } = $props();
  let busy = $derived(!!$flowBusy[id]);
  type ModelChoice = { provider: string; id: string; label: string };
  let models = $state<ModelChoice[]>([]);
  let catalogHint = $state("Loading models…");
  let provider = $derived(data.engine === "raster" ? "codex" : data.provider || "codex");
  let selectedModel = $derived((data.engine === "raster" ? data.rasterModel : data.model) || "");
  let modelChoices = $derived(models.filter(model => model.provider === provider));
  onMount(() => {
    let alive = true;
    apiGet<{ models: ModelChoice[]; source: string }>("/api/timeline/models").then(result => {
      if (!alive) return;
      models = result.models || [];
      catalogHint = result.source === "codex-cache" ? "" : "Default model catalog";
    }).catch(() => { if (alive) catalogHint = "Catalog unavailable. You can use the default account model."; });
    return () => { alive = false; };
  });
  const SIZES: Array<[number, number, string]> = [
    [1024, 1024, "1024 × 1024 · square"], [1024, 576, "1024 × 576 · 16:9"], [576, 1024, "576 × 1024 · 9:16"],
    [512, 512, "512 × 512"], [2048, 1024, "2048 × 1024 · panorama"],
  ];
  let sizeKey = $derived(`${data.width}x${data.height}`);
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Generation</div>
    <select value={data.engine || "svg"} disabled={busy} onchange={(e) => $flow.setNodeData(id, { engine: e.currentTarget.value })}>
      <option value="raster">GPT Image · photos and images</option>
      <option value="svg">SVG · vector graphics</option>
    </select>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">What to draw</div>
    <textarea rows="5" value={data.prompt} disabled={busy}
      placeholder="For example: a seamless texture of matte steel panels with rivets and light wear"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`image:${id}:prompt`, () => $flow.setNodeData(id, { prompt: value }));
      }}
      onblur={() => flushNodeText(`image:${id}:prompt`)}></textarea>
    <div class="dna-field-hint">If a Prompt node is connected, its text is used. {data.engine === "raster" ? "GPT Image creates raster images through your Codex account." : "The model draws SVG: vector illustrations, icons, and procedural textures."}</div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Subscription account</div>
    {#if data.engine === "raster"}
      <div class="dna-field-value">GPT Image · Codex</div>
    {:else}
      <fieldset disabled={busy} style="border:0;padding:0;margin:0">
        <ProviderPicker provider={data.provider || "codex"} effort={data.effort || "medium"} accountsOnly
          onChange={(next) => $flow.setNodeData(id, { provider: next.provider, effort: next.effort,
            ...(next.provider !== data.provider ? { model: "" } : {}) })} />
      </fieldset>
    {/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Model</div>
    <select aria-label="Image model" value={selectedModel} disabled={busy}
      onchange={(e) => $flow.setNodeData(id, data.engine === "raster"
        ? { rasterModel: e.currentTarget.value } : { model: e.currentTarget.value })}>
      <option value="">Account default</option>
      {#if selectedModel && !modelChoices.some(model => model.id === selectedModel)}
        <option value={selectedModel} disabled>{selectedModel} · not in catalog</option>
      {/if}
      {#each modelChoices as model (model.id)}<option value={model.id}>{model.label}</option>{/each}
    </select>
    {#if data.engine === "raster"}<div class="dna-field-hint">The selected model runs the request through the GPT Image tool.</div>{/if}
    {#if catalogHint}<div class="dna-field-hint">{catalogHint}</div>{/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Format</div>
    <select value={data.outputFormat || "png"} disabled={busy} onchange={(e) => $flow.setNodeData(id, { outputFormat: e.currentTarget.value })}>
      <option value="png">PNG</option><option value="jpeg">JPEG</option>
    </select>
    {#if data.outputFormat === "jpeg"}<div class="dna-field-hint">Transparent areas are saved on a white background.</div>{/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">{data.engine === "raster" ? "Target size" : "Size"}</div>
    <select value={sizeKey} disabled={busy} onchange={(e) => { const [w, h] = e.currentTarget.value.split("x").map(Number); $flow.setNodeData(id, { width: w, height: h }); }}>
      {#if !SIZES.some(([w, h]) => `${w}x${h}` === sizeKey)}<option value={sizeKey}>{data.width} × {data.height}</option>{/if}
      {#each SIZES as [w, h, label] (label)}<option value={`${w}x${h}`}>{label}</option>{/each}
    </select>
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" checked={!!data.tileable} disabled={busy} onchange={(e) => $flow.setNodeData(id, { tileable: e.currentTarget.checked })} />
    <span>Seamless (tileable) texture</span>
  </label>
  {#if data.variants?.length}
    <div class="dna-field">
      <div class="dna-field-cap">Results</div>
      <div class="dna-field-value"><span>{data.variants.length} {data.variants.length === 1 ? "variant" : "variants"} · last 4 kept</span></div>
      <button class="dna-btn-ghost" disabled={busy} onclick={() => { $flow.setNodeData(id, { variants: [], active: 0 }); $flow.propagate(id); }}>Clear results</button>
    </div>
  {/if}
</div>
