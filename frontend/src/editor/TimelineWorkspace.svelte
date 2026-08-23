<script lang="ts">
  /* TimelineWorkspace — полноэкранный видеоредактор (After Effects lite).
   *
   * Дисциплина рендера: содержимое дизайна рендерится ОДИН раз (IRRenderer),
   * во время проигрывания/скраба меняются только композитные свойства
   * (transform/opacity/visibility) на обёртках слоёв — превью и headless-рендер
   * используют один солвер (engine/timeline.ts), ролик совпадает с превью.
   *
   * Ручные правки мутируют локальную копию и проходят серверную валидацию
   * контракта (дебаунс-синхронизация); ИИ-правки приходят через
   * timeline-change-set (preview → atomic apply → undo). */
  import { TimelineEngine, Timeline } from "../engine/timeline";
  import { IRRenderer } from "../engine/renderer";
  import { flow } from "../flow/state";
  import { api, apiGet } from "../flow/api";
  import { toast } from "../flow/toast";
  import type { TimelineNodeData } from "../flow/types";

  let { nodeId, data, onClose }: { nodeId: number; data: TimelineNodeData; onClose: () => void } = $props();

  type AnyDoc = Record<string, any>;

  let doc = $state<AnyDoc | null>(data.timeline ? structuredClone(data.timeline) : null);
  let selectedLayerId = $state<string | null>(null);
  let selectedProp = $state<string>("opacity");
  let playhead = $state(0);
  let playing = $state(false);
  let pxPerMs = $state(0.12);
  let aiPrompt = $state("");
  let busy = $state(false);
  let message = $state("");
  let renderState = $state<AnyDoc | null>(null);

  // снапшот-история ручных правок (паттерн snapshot-before-mutation, лимит 25)
  const history: AnyDoc[] = [];
  let lastChangeSet = $state<AnyDoc | null>(null);

  let irHost: HTMLDivElement | null = $state(null);
  let boxW = $state(800);
  let boxH = $state(450);

  const designIr = $derived(data.ir as AnyDoc | null);
  const composition = $derived((doc?.composition || {}) as AnyDoc);
  const duration = $derived(Number(composition.duration || 0));
  const fps = $derived(Number(composition.fps || 30));
  const width = $derived(Number(composition.width || 1920));
  const height = $derived(Number(composition.height || 1080));
  const layers = $derived(((doc?.layers || []) as AnyDoc[]));
  const groups = $derived(((doc?.groups || []) as AnyDoc[]));
  const selectedLayer = $derived(layers.find((l) => l.id === selectedLayerId) || null);
  const fitScale = $derived(Math.min(boxW / width, boxH / height) * 0.96);

  const engine = $derived(doc ? new TimelineEngine(doc as any) : null);
  const solved = $derived(engine ? engine.seek(playhead) : {});

  function say(text: string) { message = text; }

  /* ---------- рендер контента (один раз) + привязка слоёв ---------- */

  $effect(() => {
    const host = irHost;
    const ir = designIr;
    if (!host || !ir || !doc) return;
    IRRenderer.renderIR(host, ir as any, { viewport: "desktop" });
    // секции рендерера помечены data-ir-sec="<i>"; связываем со слоями по ref
    const keysToIndex = new Map<string, number>();
    const tree = Array.isArray(ir.tree) ? ir.tree : [];
    tree.forEach((sec: AnyDoc, i: number) => {
      if (sec?.sourceKey) keysToIndex.set(String(sec.sourceKey), i);
      if (sec?.id) keysToIndex.set(String(sec.id), i);
    });
    host.querySelectorAll("[data-timeline-layer]").forEach((el) => el.removeAttribute("data-timeline-layer"));
    for (const layer of (doc.layers || []) as AnyDoc[]) {
      if (layer.type !== "component" || !layer.ref) continue;
      const index = keysToIndex.get(String(layer.ref));
      if (index === undefined) continue;
      const el = host.querySelector(`[data-ir-sec="${index}"]`);
      if (el) {
        el.setAttribute("data-timeline-layer", layer.id);
        (el as HTMLElement).style.willChange = "transform, opacity";
      }
    }
  });

  /* ---------- применение решённого состояния на каждый тик ---------- */

  $effect(() => {
    const host = irHost;
    const state = solved;
    if (!host || !state) return;
    Timeline.applySolvedToDom(host, state);
  });

  /* ---------- плейбек ---------- */

  $effect(() => {
    if (!playing || !duration) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      playhead = Math.min(duration, playhead + dt);
      if (playhead >= duration) { playing = false; return; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  });

  function togglePlay() {
    if (!duration) return;
    if (!playing && playhead >= duration) playhead = 0;
    playing = !playing;
  }

  /* ---------- синхронизация локальных правок с контрактом ---------- */

  let syncTimer: ReturnType<typeof setTimeout> | null = null;

  function snapshot() {
    if (!doc) return;
    history.push(structuredClone(doc));
    if (history.length > 25) history.shift();
  }

  function mutate(fn: (d: AnyDoc) => void) {
    if (!doc) return;
    fn(doc);
    doc = { ...doc };
    scheduleSync();
  }

  function scheduleSync() {
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(() => void sync(), 400);
  }

  async function sync() {
    if (!doc) return;
    try {
      const resp = await api<{ errors?: string[] }>("/api/timeline/validate", { timeline: doc });
      const errors = resp.errors || [];
      if (errors.length) {
        say("Правки не прошли валидацию: " + errors[0]);
        return;
      }
      snapshot();
      $flow.setNodeData(nodeId, { timeline: structuredClone(doc) });
      say("");
    } catch (error) {
      say(error instanceof Error ? error.message : String(error));
    }
  }

  function undo() {
    const prev = history.pop();
    if (!prev) { say("История пуста"); return; }
    doc = prev;
    $flow.setNodeData(nodeId, { timeline: structuredClone(doc) });
    say("Отменено");
  }

  /* ---------- операции таймлайна ---------- */

  function selectLayer(id: string) { selectedLayerId = id; }

  function setLayerTiming(layerId: string, key: "in" | "out", value: number) {
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      if (!layer) return;
      layer[key] = Math.max(0, Math.min(duration, Math.round(value)));
      if (layer.in >= layer.out) layer[key === "in" ? "out" : "in"] = layer[key] + (key === "in" ? 1 : -1);
    });
  }

  function addKeyframe(layerId: string, prop: string) {
    const state = solved[layerId];
    if (!state) return;
    const value = prop === "x" ? state.x : prop === "y" ? state.y : prop === "scale" ? state.scale
      : prop === "rotation" ? state.rotation : state.opacity;
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      if (!layer) return;
      const props = layer.transform.properties;
      const track = props[prop] || (props[prop] = { keyframes: [] });
      const t = Math.round(playhead);
      track.keyframes = track.keyframes.filter((k: AnyDoc) => k.t !== t);
      track.keyframes.push({ t, value: Number(value.toFixed(4)), easing: "ease-in-out" });
      track.keyframes.sort((a: AnyDoc, b: AnyDoc) => a.t - b.t);
    });
    say(`Кейфрейм ${prop} @ ${(playhead / 1000).toFixed(2)}s`);
  }

  function removeKeyframe(layerId: string, prop: string, t: number) {
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      const track = layer?.transform?.properties?.[prop];
      if (!track) return;
      track.keyframes = track.keyframes.filter((k: AnyDoc) => k.t !== t);
      if (!track.keyframes.length) delete layer.transform.properties[prop];
    });
  }

  function setKeyframeT(layerId: string, prop: string, oldT: number, newT: number) {
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      const track = layer?.transform?.properties?.[prop];
      if (!track) return;
      const kf = track.keyframes.find((k: AnyDoc) => k.t === oldT);
      if (!kf) return;
      kf.t = Math.max(0, Math.min(duration, Math.round(newT)));
      track.keyframes.sort((a: AnyDoc, b: AnyDoc) => a.t - b.t);
    });
  }

  function setKeyframeEasing(layerId: string, prop: string, t: number, easing: string) {
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      const kf = layer?.transform?.properties?.[prop]?.keyframes.find((k: AnyDoc) => k.t === t);
      if (kf) kf.easing = easing;
    });
  }

  /* ---------- ИИ-режиссёр: промпт -> change-set -> preview/apply ---------- */

  async function runAiDirector() {
    if (!doc || !aiPrompt.trim() || busy) return;
    busy = true;
    say("ИИ-режиссёр готовит монтаж...");
    try {
      const resp = await api<{ timeline?: AnyDoc; changeSet?: AnyDoc; error?: string }>(
        "/api/timeline/assist", { timeline: doc, prompt: aiPrompt.trim() });
      if (resp.error || !resp.timeline) throw new Error(resp.error || "пустой ответ");
      snapshot();
      doc = resp.timeline;
      lastChangeSet = resp.changeSet || null;
      $flow.setNodeData(nodeId, { timeline: structuredClone(doc) });
      say(`Готово: ${resp.changeSet?.intent || aiPrompt.trim()}`);
      aiPrompt = "";
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      say("ИИ-режиссёр: " + msg);
      toast("ИИ-режиссёр: " + msg, "error");
    } finally {
      busy = false;
    }
  }

  async function undoAi() {
    if (!doc || !lastChangeSet) return;
    busy = true;
    try {
      const resp = await api<{ timeline?: AnyDoc }>("/api/timeline/revert", {
        timeline: doc, changeSet: lastChangeSet });
      if (resp.timeline) {
        snapshot();
        doc = resp.timeline;
        lastChangeSet = null;
        $flow.setNodeData(nodeId, { timeline: structuredClone(doc) });
        say("ИИ-патч откатан");
      }
    } finally {
      busy = false;
    }
  }

  /* ---------- рендер ролика и экспорт веб-анимации ---------- */

  function downloadText(filename: string, text: string, mime: string) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  async function exportCss() {
    if (!doc || busy) return;
    busy = true;
    try {
      const resp = await api<{ files?: Record<string, string>; error?: string }>(
        "/api/timeline/export", { timeline: doc, mode: "css" });
      if (resp.error || !resp.files?.["timeline.css"]) throw new Error(resp.error || "пустой экспорт");
      downloadText("timeline.css", resp.files["timeline.css"], "text/css");
      say("CSS-анимация выгружена: подключите файл и разметку с data-timeline-layer");
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      say("Экспорт: " + msg);
    } finally {
      busy = false;
    }
  }

  async function renderVideo(format: string) {
    if (!doc || busy) return;
    if (!designIr) { say("Нет входного Design IR для рендера"); return; }
    busy = true;
    renderState = { status: "starting" };
    say("Рендер запущен...");
    try {
      const resp = await api<{ renderId?: string; error?: string }>(
        "/api/timeline/render", { timeline: doc, ir: designIr, format });
      if (resp.error || !resp.renderId) throw new Error(resp.error || "нет renderId");
      const renderId = resp.renderId;
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const st = await apiGet<AnyDoc>(`/api/timeline/render/${renderId}`);
        renderState = st;
        if (st.status === "done" || st.status === "error") break;
      }
      if (renderState?.status === "done") say("Ролик готов — скачайте файл");
      else say("Рендер: " + (renderState?.error || renderState?.status || "неизвестно"));
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      renderState = { status: "error", error: msg };
      say("Рендер: " + msg);
    } finally {
      busy = false;
    }
  }

  /* ---------- перетаскивание ---------- */

  let drag: { kind: "playhead" | "key" | "trim-in" | "trim-out"; layerId?: string; prop?: string; t?: number; startX: number; origin: number } | null = null;

  function onRulerDown(e: PointerEvent) {
    drag = { kind: "playhead", startX: e.clientX, origin: playhead };
    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function onKeyDown(e: PointerEvent, layerId: string, prop: string, t: number) {
    e.stopPropagation();
    drag = { kind: "key", layerId, prop, t, startX: e.clientX, origin: t };
    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function onTrimDown(e: PointerEvent, layerId: string, edge: "trim-in" | "trim-out") {
    e.stopPropagation();
    const layer = layers.find((l) => l.id === layerId);
    drag = { kind: edge, layerId, startX: e.clientX, origin: Number(layer?.[edge === "trim-in" ? "in" : "out"] || 0) };
    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function onDragMove(e: PointerEvent) {
    if (!drag) return;
    const dx = e.clientX - drag.startX;
    const dms = dx / pxPerMs;
    if (drag.kind === "playhead") {
      playhead = Math.max(0, Math.min(duration, drag.origin + dms));
    } else if (drag.kind === "key" && drag.layerId && drag.prop && drag.t !== undefined) {
      const frameMs = 1000 / fps;
      const newT = Math.round((drag.origin + dms) / frameMs) * frameMs;
      if (Math.abs(newT - drag.t) >= frameMs / 2) {
        setKeyframeT(drag.layerId, drag.prop, drag.t, newT);
        drag.t = newT;
      }
    } else if ((drag.kind === "trim-in" || drag.kind === "trim-out") && drag.layerId) {
      setLayerTiming(drag.layerId, drag.kind === "trim-in" ? "in" : "out", drag.origin + dms);
    }
  }

  function onDragEnd() { drag = null; }

  const PROPS = ["x", "y", "scale", "rotation", "opacity"] as const;
  const PROP_COLORS: Record<string, string> = {
    x: "#5aa9ff", y: "#67d98f", scale: "#f2c14e", rotation: "#c792ea", opacity: "#ff8a80",
  };
  const FORMATS = [
    { label: "16:9 · 1920×1080", width: 1920, height: 1080 },
    { label: "9:16 · 1080×1920", width: 1080, height: 1920 },
    { label: "1:1 · 1080×1080", width: 1080, height: 1080 },
  ];

  function setFormat(widthValue: number, heightValue: number) {
    mutate((d) => {
      d.composition.width = widthValue;
      d.composition.height = heightValue;
      d.composition.aspect = widthValue === heightValue ? "1:1" : widthValue > heightValue ? "16:9" : "9:16";
    });
  }

  function setDuration(value: number) {
    mutate((d) => {
      d.composition.duration = Math.max(250, Math.min(600000, Math.round(value)));
      for (const layer of d.layers) {
        if (layer.out > d.composition.duration) layer.out = d.composition.duration;
        if (layer.in >= layer.out) layer.in = Math.max(0, layer.out - 250);
      }
    });
  }

  function timeLabel(ms: number) {
    const s = Math.max(0, ms) / 1000;
    return s.toFixed(2) + "s";
  }
</script>

<div class="tlw-root" onpointermove={onDragMove} onpointerup={onDragEnd}>
  <div class="tlw-top">
    <button class="tlw-btn" onclick={onClose}>← Граф</button>
    <span class="tlw-title">Video Editor</span>
    <button class="tlw-btn primary" onclick={togglePlay} disabled={!duration}>{playing ? "❚❚" : "▶"}</button>
    <span class="tlw-time">{timeLabel(playhead)} / {timeLabel(duration)}</span>
    <select class="tlw-select" value={FORMATS.find((f) => f.width === width && f.height === height)?.label || "custom"}
      onchange={(e) => {
        const f = FORMATS.find((x) => x.label === (e.currentTarget as HTMLSelectElement).value);
        if (f) setFormat(f.width, f.height);
      }}>
      {#each FORMATS as f (f.label)}<option value={f.label}>{f.label}</option>{/each}
      {#if !FORMATS.some((f) => f.width === width && f.height === height)}<option value="custom">{width}×{height}</option>{/if}
    </select>
    <label class="tlw-inline">Длительность, с
      <input class="tlw-input" type="number" min="0.25" step="0.5" value={(duration / 1000).toFixed(2)}
        onchange={(e) => setDuration(Number(e.currentTarget.value) * 1000)} />
    </label>
    <span class="tlw-spacer"></span>
    <button class="tlw-btn" onclick={undo}>Undo</button>
    {#if lastChangeSet}<button class="tlw-btn" onclick={() => void undoAi()}>Откатить ИИ-патч</button>{/if}
    <button class="tlw-btn" disabled={busy || !doc} onclick={() => void renderVideo("mp4")}>Рендер MP4</button>
    <button class="tlw-btn" disabled={busy || !doc} onclick={() => void exportCss()}>Экспорт CSS</button>
  </div>

  <div class="tlw-ai">
    <input class="tlw-ai-input" placeholder="ИИ-режиссёр: «интро снизу, наезд на hero, пульс на кнопке в конце»"
      bind:value={aiPrompt} disabled={busy || !doc}
      onkeydown={(e) => { if (e.key === "Enter") void runAiDirector(); }} />
    <button class="tlw-btn primary" disabled={busy || !doc || !aiPrompt.trim()} onclick={() => void runAiDirector()}>
      {busy ? "..." : "Применить"}
    </button>
  </div>

  <div class="tlw-body">
    <div class="tlw-layers">
      <div class="tlw-panel-title">Слои и группы</div>
      {#if !doc}
        <div class="tlw-empty">Соберите таймлайн из входного Design IR</div>
      {:else}
        {#each groups as group (group.id)}
          <div class="tlw-group">{group.name}</div>
          {#each layers.filter((l) => l.parent === group.id) as layer (layer.id)}
            <button class="tlw-layer" class:active={selectedLayerId === layer.id} onclick={() => selectLayer(layer.id)}>
              <span class="tlw-layer-name">{layer.name}</span>
              <span class="tlw-layer-time">{(layer.in / 1000).toFixed(1)}–{(layer.out / 1000).toFixed(1)}s</span>
              {#if layer.locked}<span title="locked raster layer">🔒</span>{/if}
            </button>
          {/each}
        {/each}
      {/if}
    </div>

    <div class="tlw-stage" bind:clientWidth={boxW} bind:clientHeight={boxH}>
      <div class="tlw-artboard" style="width:{width}px; height:{height}px; transform:scale({fitScale}); background:{composition.background || '#111116'}">
        <div class="tlw-irhost" bind:this={irHost}></div>
      </div>
    </div>

    <div class="tlw-inspector">
      <div class="tlw-panel-title">Инспектор</div>
      {#if selectedLayer}
        <div class="tlw-insp-name">{selectedLayer.name}</div>
        <label class="tlw-inline">in, с
          <input class="tlw-input" type="number" step="0.1" value={(selectedLayer.in / 1000).toFixed(2)}
            onchange={(e) => setLayerTiming(selectedLayer.id, "in", Number(e.currentTarget.value) * 1000)} />
        </label>
        <label class="tlw-inline">out, с
          <input class="tlw-input" type="number" step="0.1" value={(selectedLayer.out / 1000).toFixed(2)}
            onchange={(e) => setLayerTiming(selectedLayer.id, "out", Number(e.currentTarget.value) * 1000)} />
        </label>
        <div class="tlw-prop-pick">
          {#each PROPS as prop (prop)}
            <button class="tlw-prop-chip" class:active={selectedProp === prop} style="--pc:{PROP_COLORS[prop]}"
              onclick={() => (selectedProp = prop)}>{prop}</button>
          {/each}
        </div>
        <button class="tlw-btn primary wide" onclick={() => addKeyframe(selectedLayer.id, selectedProp)}>
          ◆ Кейфрейм {selectedProp} @ {timeLabel(playhead)}
        </button>
        <div class="tlw-kf-list">
          {#each (selectedLayer.transform?.properties?.[selectedProp]?.keyframes || []) as kf (kf.t)}
            <div class="tlw-kf-row">
              <span style="color:{PROP_COLORS[selectedProp]}">◆</span>
              <span>{timeLabel(kf.t)} → {Number(kf.value).toFixed(2)}</span>
              <select class="tlw-select small" value={kf.easing || "linear"}
                onchange={(e) => setKeyframeEasing(selectedLayer.id, selectedProp, kf.t, (e.currentTarget as HTMLSelectElement).value)}>
                {#each ["linear", "ease", "ease-in", "ease-out", "ease-in-out"] as ez (ez)}<option value={ez}>{ez}</option>{/each}
              </select>
              <button class="tlw-btn danger small" onclick={() => removeKeyframe(selectedLayer.id, selectedProp, kf.t)}>✕</button>
            </div>
          {/each}
        </div>
      {:else}
        <div class="tlw-empty">Выберите слой слева</div>
      {/if}
    </div>
  </div>

  <div class="tlw-timeline">
    <div class="tlw-ruler" onpointerdown={onRulerDown}>
      <div class="tlw-ruler-track" style="width:{duration * pxPerMs}px">
        {#each Array.from({ length: Math.ceil(duration / 1000) + 1 }) as _, sec}
          <div class="tlw-ruler-mark" style="left:{sec * 1000 * pxPerMs}px">{sec}s</div>
        {/each}
        <div class="tlw-playhead" style="left:{playhead * pxPerMs}px"></div>
      </div>
    </div>
    <div class="tlw-tracks">
      {#each layers as layer (layer.id)}
        <div class="tlw-track" class:active={selectedLayerId === layer.id} onclick={() => selectLayer(layer.id)}>
          <div class="tlw-track-name">{layer.name}</div>
          <div class="tlw-track-lane" style="width:{duration * pxPerMs}px">
            <div class="tlw-clip" style="left:{layer.in * pxPerMs}px; width:{Math.max(4, (layer.out - layer.in) * pxPerMs)}px">
              <div class="tlw-trim" onpointerdown={(e) => onTrimDown(e, layer.id, "trim-in")}></div>
              {#each PROPS as prop (prop)}
                {#each (layer.transform?.properties?.[prop]?.keyframes || []) as kf (prop + ":" + kf.t)}
                  <div class="tlw-key" title="{prop} {timeLabel(kf.t)}"
                    style="left:{(kf.t - layer.in) * pxPerMs}px; top:{2 + PROPS.indexOf(prop) * 7}px; background:{PROP_COLORS[prop]}"
                    onpointerdown={(e) => onKeyDown(e, layer.id, prop, kf.t)}
                    ondblclick={() => removeKeyframe(layer.id, prop, kf.t)}></div>
                {/each}
              {/each}
              <div class="tlw-trim right" onpointerdown={(e) => onTrimDown(e, layer.id, "trim-out")}></div>
            </div>
            <div class="tlw-playhead" style="left:{playhead * pxPerMs}px"></div>
          </div>
        </div>
      {/each}
    </div>
    <div class="tlw-status">
      {#if message}<span>{message}</span>{/if}
      {#if renderState?.status === "done" && renderState?.downloadUrl}
        <a class="tlw-download" href={renderState.downloadUrl} download>Скачать ролик</a>
      {/if}
      <span class="tlw-hint">клик по линейке — скраб · ◆ — кейфрейм (тянуть мышью, двойной клик — удалить)</span>
    </div>
  </div>
</div>

<style>
  .tlw-root { position: fixed; inset: 0; z-index: 80; display: flex; flex-direction: column;
    background: #101216; color: #d7dae0; font-size: 13px; }
  .tlw-top, .tlw-ai { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    border-bottom: 1px solid #23262d; flex-wrap: wrap; }
  .tlw-title { font-weight: 600; margin-right: 8px; }
  .tlw-time { font-variant-numeric: tabular-nums; color: #9aa0ab; min-width: 120px; }
  .tlw-spacer { flex: 1; }
  .tlw-btn { background: #1b1e24; color: #d7dae0; border: 1px solid #2c3038; border-radius: 7px;
    padding: 5px 10px; cursor: pointer; font-size: 12px; }
  .tlw-btn:hover:not(:disabled) { background: #23262d; }
  .tlw-btn:disabled { opacity: 0.45; cursor: default; }
  .tlw-btn.primary { background: #3366ff; border-color: #3366ff; color: #fff; }
  .tlw-btn.primary:hover:not(:disabled) { background: #4a78ff; }
  .tlw-btn.danger { color: #ff8a80; }
  .tlw-btn.small { padding: 2px 6px; }
  .tlw-btn.wide { width: 100%; margin: 6px 0; }
  .tlw-select { background: #1b1e24; color: #d7dae0; border: 1px solid #2c3038; border-radius: 6px; padding: 4px 6px; }
  .tlw-select.small { padding: 1px 4px; font-size: 11px; }
  .tlw-input { width: 72px; background: #1b1e24; color: #d7dae0; border: 1px solid #2c3038; border-radius: 6px; padding: 4px 6px; }
  .tlw-inline { display: flex; align-items: center; gap: 6px; color: #9aa0ab; }
  .tlw-ai-input { flex: 1; background: #15171c; color: #e8eaee; border: 1px solid #2c3038; border-radius: 8px; padding: 7px 10px; }
  .tlw-body { flex: 1; display: grid; grid-template-columns: 230px 1fr 260px; min-height: 0; }
  .tlw-layers, .tlw-inspector { border-right: 1px solid #23262d; overflow-y: auto; padding: 8px; }
  .tlw-inspector { border-right: none; border-left: 1px solid #23262d; }
  .tlw-panel-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #7c828d; margin: 4px 0 8px; }
  .tlw-group { margin: 10px 0 4px; color: #8b909a; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .tlw-layer { display: flex; align-items: center; gap: 6px; width: 100%; background: transparent; border: none;
    color: #cfd3da; padding: 5px 6px; border-radius: 6px; cursor: pointer; text-align: left; }
  .tlw-layer:hover { background: #1b1e24; }
  .tlw-layer.active { background: #24304d; color: #fff; }
  .tlw-layer-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tlw-layer-time { color: #7c828d; font-size: 11px; font-variant-numeric: tabular-nums; }
  .tlw-stage { display: flex; align-items: center; justify-content: center; overflow: hidden; background: #0b0d10; }
  .tlw-artboard { position: relative; transform-origin: center center; box-shadow: 0 0 0 1px #2c3038; flex: none; }
  .tlw-irhost { position: absolute; inset: 0; overflow: hidden; }
  .tlw-empty { color: #7c828d; padding: 12px 6px; }
  .tlw-insp-name { font-weight: 600; margin-bottom: 8px; }
  .tlw-prop-pick { display: flex; gap: 4px; flex-wrap: wrap; margin: 8px 0; }
  .tlw-prop-chip { border: 1px solid var(--pc); color: var(--pc); background: transparent; border-radius: 6px;
    padding: 2px 8px; cursor: pointer; font-size: 11px; }
  .tlw-prop-chip.active { background: var(--pc); color: #101216; }
  .tlw-kf-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
  .tlw-kf-row { display: flex; align-items: center; gap: 6px; background: #15171c; border-radius: 6px; padding: 4px 6px; }
  .tlw-kf-row span:nth-child(2) { flex: 1; font-variant-numeric: tabular-nums; }
  .tlw-timeline { border-top: 1px solid #23262d; background: #121418; max-height: 38vh; overflow: auto; }
  .tlw-ruler { padding: 6px 8px 0 148px; cursor: ew-resize; }
  .tlw-ruler-track { position: relative; height: 22px; }
  .tlw-ruler-mark { position: absolute; top: 0; font-size: 10px; color: #7c828d; border-left: 1px solid #2c3038; padding-left: 3px; height: 100%; }
  .tlw-tracks { padding: 4px 8px 8px 0; }
  .tlw-track { display: flex; align-items: center; }
  .tlw-track.active .tlw-track-name { color: #fff; }
  .tlw-track-name { width: 140px; flex: none; padding: 4px 8px; font-size: 11px; color: #9aa0ab;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tlw-track-lane { position: relative; height: 40px; background: #15171c; border-radius: 6px; margin: 2px 0; }
  .tlw-clip { position: absolute; top: 2px; bottom: 2px; background: #20263a; border: 1px solid #33415e; border-radius: 6px; }
  .tlw-trim { position: absolute; top: 0; bottom: 0; width: 7px; left: 0; cursor: ew-resize; }
  .tlw-trim.right { left: auto; right: 0; }
  .tlw-trim:hover { background: #3366ff66; }
  .tlw-key { position: absolute; width: 8px; height: 5px; transform: rotate(45deg); cursor: ew-resize; border-radius: 1px; }
  .tlw-playhead { position: absolute; top: 0; bottom: 0; width: 1px; background: #ff5f56; pointer-events: none; }
  .tlw-status { display: flex; align-items: center; gap: 12px; padding: 6px 12px; border-top: 1px solid #23262d; color: #9aa0ab; }
  .tlw-status .tlw-hint { margin-left: auto; font-size: 11px; color: #666c77; }
  .tlw-download { color: #67d98f; text-decoration: underline; }
</style>
