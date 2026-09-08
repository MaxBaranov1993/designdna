<script lang="ts">
  import VideoModelPicker from "../editor/VideoModelPicker.svelte";
  import { flow, flowBusy } from "../flow/state";
  import type { TimelineNodeData } from "../flow/types";

  let { id, data }: { id: number; data: TimelineNodeData } = $props();
  let busy = $derived(!!$flowBusy[id]);
  const inputs = $derived(data.inputs || ["ir"]);

  function renamePage(port: string, name: string) {
    const pageNames = { ...data.pageNames, [port]: name.slice(0, 120) };
    const sourcePages = (data.sourcePages || []).map((p) => ({ ...p, name: pageNames[p.id] || p.name }));
    const next = data.timeline ? JSON.parse(JSON.stringify(data.timeline)) : null;
    if (next?.story) next.story.pages = next.story.pages.map((p: any) => ({ ...p, name: pageNames[p.id] || p.name }));
    $flow.setNodeData(id, { pageNames, sourcePages, ...(next ? { timeline: next } : {}) });
  }
  const patchSettings = (patch: Partial<TimelineNodeData["settings"]>) => $flow.setNodeData(id, { settings: { ...data.settings, ...patch } });
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Что должно происходить в ролике</div>
    <textarea rows="4" value={data.prompt || ""} disabled={busy}
      placeholder="На странице «Форма» заполни поля, нажми «Разместить» и перейди к странице «Готово»"
      oninput={(event) => $flow.setNodeData(id, { prompt: event.currentTarget.value })}></textarea>
  </div>
  <div class="dna-field" inert={busy}>
    <div class="dna-field-cap">Модель</div>
    <VideoModelPicker model={data.model} provider={data.provider === "claude" ? "claude" : "codex"} effort={data.effort || "medium"}
      onChange={(choice) => $flow.setNodeData(id, choice)} />
  </div>
  <div class="dna-insp-row three">
    <div class="dna-field">
      <div class="dna-field-cap">FPS</div>
      <select value={String(data.settings.fps)} onchange={(e) => patchSettings({ fps: Number(e.currentTarget.value) })}>
        <option value="24">24</option><option value="30">30</option><option value="60">60</option>
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Секунд</div>
      <input type="number" min="1" max="120" step="0.5" value={(data.settings.duration / 1000).toFixed(1)} onchange={(e) => patchSettings({ duration: Math.max(1000, Math.round(Number(e.currentTarget.value) * 1000)) })} />
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Кадр</div>
      <select value={`${data.settings.width}x${data.settings.height}`} onchange={(e) => { const [w, h] = e.currentTarget.value.split("x").map(Number); patchSettings({ width: w, height: h }); }}>
        <option value="1920x1080">16:9</option><option value="1080x1920">9:16</option><option value="1080x1080">1:1</option>
      </select>
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Страницы-источники</div>
    <div class="nrow-merge">
      {#each inputs as port, index (port)}
        <div class="merge-row" data-port={port} data-kind="ir">
          <span class="merge-n">{index + 1}</span>
          <input aria-label={`Название страницы ${index + 1}`} value={data.pageNames?.[port] || `Страница ${index + 1}`} maxlength="120"
            style="flex: 1; min-width: 0; padding: 4px 6px; font-size: 11.5px"
            onchange={(event) => renamePage(port, event.currentTarget.value.trim() || `Страница ${index + 1}`)} />
          {#if port !== "ir"}<span class="merge-ctl"><button title="Удалить вход" onclick={() => $flow.removeVideoInput(id, port)}>✕</button></span>{/if}
        </div>
      {/each}
    </div>
    <button class="dna-btn-ghost" disabled={inputs.length >= 8 || busy} onclick={() => $flow.addVideoInput(id)}>+ Страница</button>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Версии</div>
    <div class="dna-field-value"><span>{data.revisions?.length || 0} версий монтажа</span><span class="dna-out-kind">без звука</span></div>
  </div>
</div>
