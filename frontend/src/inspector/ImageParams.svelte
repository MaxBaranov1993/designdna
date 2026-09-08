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
  let catalogHint = $state("Загрузка моделей…");
  let provider = $derived(data.engine === "raster" ? "codex" : data.provider || "codex");
  let selectedModel = $derived((data.engine === "raster" ? data.rasterModel : data.model) || "");
  let modelChoices = $derived(models.filter(model => model.provider === provider));
  onMount(() => {
    let alive = true;
    apiGet<{ models: ModelChoice[]; source: string }>("/api/timeline/models").then(result => {
      if (!alive) return;
      models = result.models || [];
      catalogHint = result.source === "codex-cache" ? "" : "Базовый каталог моделей";
    }).catch(() => { if (alive) catalogHint = "Каталог недоступен. Можно использовать модель аккаунта по умолчанию."; });
    return () => { alive = false; };
  });
  const SIZES: Array<[number, number, string]> = [
    [1024, 1024, "1024 × 1024 · квадрат"], [1024, 576, "1024 × 576 · 16:9"], [576, 1024, "576 × 1024 · 9:16"],
    [512, 512, "512 × 512"], [2048, 1024, "2048 × 1024 · панорама"],
  ];
  let sizeKey = $derived(`${data.width}x${data.height}`);
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Генерация</div>
    <select value={data.engine || "svg"} disabled={busy} onchange={(e) => $flow.setNodeData(id, { engine: e.currentTarget.value })}>
      <option value="raster">GPT Image · фото и изображения</option>
      <option value="svg">SVG · векторная графика</option>
    </select>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Что нарисовать</div>
    <textarea rows="5" value={data.prompt} disabled={busy}
      placeholder="Например: бесшовная текстура матовых стальных панелей с заклёпками и лёгкой потёртостью"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`image:${id}:prompt`, () => $flow.setNodeData(id, { prompt: value }));
      }}
      onblur={() => flushNodeText(`image:${id}:prompt`)}></textarea>
    <div class="dna-field-hint">Если подключена нода Промпт, используется её текст. {data.engine === "raster" ? "GPT Image создаёт растровое изображение через аккаунт Codex." : "Модель рисует SVG: векторные иллюстрации, иконки, процедурные текстуры."}</div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Аккаунт по подписке</div>
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
    <div class="dna-field-cap">Модель</div>
    <select aria-label="Модель изображения" value={selectedModel} disabled={busy}
      onchange={(e) => $flow.setNodeData(id, data.engine === "raster"
        ? { rasterModel: e.currentTarget.value } : { model: e.currentTarget.value })}>
      <option value="">По умолчанию аккаунта</option>
      {#if selectedModel && !modelChoices.some(model => model.id === selectedModel)}
        <option value={selectedModel} disabled>{selectedModel} · нет в каталоге</option>
      {/if}
      {#each modelChoices as model (model.id)}<option value={model.id}>{model.label}</option>{/each}
    </select>
    {#if data.engine === "raster"}<div class="dna-field-hint">Выбранная модель выполняет запрос через инструмент GPT Image.</div>{/if}
    {#if catalogHint}<div class="dna-field-hint">{catalogHint}</div>{/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Формат</div>
    <select value={data.outputFormat || "png"} disabled={busy} onchange={(e) => $flow.setNodeData(id, { outputFormat: e.currentTarget.value })}>
      <option value="png">PNG</option><option value="jpeg">JPEG</option>
    </select>
    {#if data.outputFormat === "jpeg"}<div class="dna-field-hint">Прозрачные области сохраняются на белом фоне.</div>{/if}
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">{data.engine === "raster" ? "Желаемый размер" : "Размер"}</div>
    <select value={sizeKey} disabled={busy} onchange={(e) => { const [w, h] = e.currentTarget.value.split("x").map(Number); $flow.setNodeData(id, { width: w, height: h }); }}>
      {#if !SIZES.some(([w, h]) => `${w}x${h}` === sizeKey)}<option value={sizeKey}>{data.width} × {data.height}</option>{/if}
      {#each SIZES as [w, h, label] (label)}<option value={`${w}x${h}`}>{label}</option>{/each}
    </select>
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" checked={!!data.tileable} disabled={busy} onchange={(e) => $flow.setNodeData(id, { tileable: e.currentTarget.checked })} />
    <span>Бесшовная (тайловая) текстура</span>
  </label>
  {#if data.variants?.length}
    <div class="dna-field">
      <div class="dna-field-cap">Результаты</div>
      <div class="dna-field-value"><span>{data.variants.length} {data.variants.length === 1 ? "вариант" : "варианта"} · хранятся последние 4</span></div>
      <button class="dna-btn-ghost" disabled={busy} onclick={() => { $flow.setNodeData(id, { variants: [], active: 0 }); $flow.propagate(id); }}>Очистить результаты</button>
    </div>
  {/if}
</div>
