<script lang="ts">
  /* TimelineWorkspace — полноэкранный видеоредактор (After Effects lite).
   *
   * Дисциплина рендера: содержимое дизайна рендерится ОДИН раз (IRRenderer),
   * во время проигрывания/скраба меняются только композитные свойства
   * (transform/opacity/visibility) на обёртках слоёв — превью и headless-рендер
   * используют один солвер (engine/timeline.ts), ролик совпадает с превью.
   *
   * Ручные правки мутируют локальную копию и проходят серверную валидацию
   * контракта (дебаунс-синхронизация с ревизией: устаревший ответ не затирает
   * более новые правки; при закрытии несинхронизированный остаток сбрасывается
   * немедленно). ИИ-правки приходят через timeline-change-set как ПРЕВЬЮ:
   * канонический таймлайн ноды не меняется до явного «Применить». */
  import { TimelineEngine, Timeline } from "../engine/timeline";
  import { IRRenderer } from "../engine/renderer";
  import { flow } from "../flow/state";
  import { api, apiGet } from "../flow/api";
  import { toast } from "../flow/toast";
  import { bodyPortal } from "../lib/bodyPortal";
  import type { TimelineNodeData } from "../flow/types";

  let { nodeId, data, onClose }: { nodeId: number; data: TimelineNodeData; onClose: () => void } = $props();

  type AnyDoc = Record<string, any>;

  /* Локальная редактируемая копия: снимок таймлайна ноды на момент открытия.
   * Инициализация в $effect.pre — намеренно разовый захват начального значения. */
  let doc = $state<AnyDoc | null>(null);
  let docInitialized = false;
  $effect.pre(() => {
    if (docInitialized) return;
    docInitialized = true;
    // JSON-клон безопасен и для plain-объектов, и для реактивных прокси
    doc = data.timeline ? JSON.parse(JSON.stringify(data.timeline)) : null;
  });

  let selectedLayerId = $state<string | null>(null);
  let selectedProp = $state<string>("opacity");
  let playhead = $state(0);
  let playing = $state(false);
  let pxPerMs = $state(0.12);
  let aiPrompt = $state("");
  let busy = $state(false);
  let aiBusy = $state(false);
  let message = $state("");
  let renderState = $state<AnyDoc | null>(null);
  let renderId = $state<string | null>(null);
  let historyDepth = $state(0);

  // снапшот-история ручных правок (snapshot ПЕРЕД мутацией, лимит 25)
  const HISTORY_LIMIT = 25;
  const history: AnyDoc[] = [];
  let lastChangeSet = $state<AnyDoc | null>(null);

  // Превью ИИ-монтажа: канонический документ не трогается до «Применить».
  type AiPreview = {
    timeline: AnyDoc;
    changeSet: AnyDoc;
    intent: string;
    planSource: string;
    warning: string | null;
    operations: number;
  };
  let preview = $state<AiPreview | null>(null);

  let irHost: HTMLDivElement | null = $state(null);
  let rulerTrack: HTMLDivElement | null = $state(null);
  let boxW = $state(800);
  let boxH = $state(450);

  let disposed = false;

  const designIr = $derived(data.ir as AnyDoc | null);
  /* При открытом превью сцена показывает предлагаемый монтаж, редактирование
   * при этом заблокировано до Применить/Отменить. */
  const activeDoc = $derived(preview ? preview.timeline : doc);
  const composition = $derived((activeDoc?.composition || {}) as AnyDoc);
  const duration = $derived(Number(composition.duration || 0));
  const fps = $derived(Number(composition.fps || 30));
  const width = $derived(Number(composition.width || 1920));
  const height = $derived(Number(composition.height || 1080));
  const layers = $derived(((activeDoc?.layers || []) as AnyDoc[]));
  const groups = $derived(((activeDoc?.groups || []) as AnyDoc[]));
  const selectedLayer = $derived(layers.find((l) => l.id === selectedLayerId) || null);
  const fitScale = $derived(Math.min(boxW / width, boxH / height) * 0.96);

  const engine = $derived(activeDoc ? new TimelineEngine(activeDoc as any) : null);
  const solved = $derived(engine ? engine.seek(playhead) : {});

  function say(text: string) { message = text; }

  /* structuredClone не умеет реактивные прокси Svelte 5 — снимки документа
   * берутся через $state.snapshot (плоская глубокая копия). */
  function cloneDoc(d: AnyDoc): AnyDoc {
    return $state.snapshot(d) as AnyDoc;
  }

  /* ---------- рендер контента (один раз) + привязка слоёв ---------- */

  $effect(() => {
    const host = irHost;
    const ir = designIr;
    const current = activeDoc;
    if (!host || !ir || !current) return;
    IRRenderer.renderIR(host, ir as any, { viewport: "desktop" });
    // секции рендерера помечены data-ir-sec="<i>"; связываем со слоями по ref
    const keysToIndex = new Map<string, number>();
    const tree = Array.isArray(ir.tree) ? ir.tree : [];
    tree.forEach((sec: AnyDoc, i: number) => {
      if (sec?.sourceKey) keysToIndex.set(String(sec.sourceKey), i);
      if (sec?.id) keysToIndex.set(String(sec.id), i);
    });
    host.querySelectorAll("[data-timeline-layer]").forEach((el) => el.removeAttribute("data-timeline-layer"));
    for (const layer of (current.layers || []) as AnyDoc[]) {
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

  /* ---------- история: снапшот ДО мутации, драги — одна запись ---------- */

  let coalescing = false;          // транзакция драга: снапшот один на весь жест
  let dragNeedsSnapshot = false;   // снимок при первой реальной мутации драга

  function snapshot() {
    if (!doc) return;
    history.push(cloneDoc(doc));
    if (history.length > HISTORY_LIMIT) history.shift();
    historyDepth = history.length;
  }

  function mutate(fn: (d: AnyDoc) => void) {
    if (!doc) return;
    if (preview) { say("Сначала примените или отмените превью ИИ"); return; }
    if (coalescing) {
      if (dragNeedsSnapshot) { snapshot(); dragNeedsSnapshot = false; }
    } else {
      snapshot();
    }
    fn(doc);
    doc = { ...doc };
    docSeq++;
    scheduleSync();
  }

  function undo() {
    if (preview) { say("Сначала примените или отмените превью ИИ"); return; }
    const prev = history.pop();
    historyDepth = history.length;
    if (!prev) { say("История пуста"); return; }
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    doc = prev;
    docSeq++;
    // восстановленный документ уже проходил валидацию раньше — канонически
    // сохраняем сразу; устаревшие ответы синхронизации отбрасываются ревизией
    lastValidSeq = docSeq;
    $flow.setNodeData(nodeId, { timeline: cloneDoc(doc) });
    say("Отменено");
  }

  /* ---------- синхронизация локальных правок с контрактом ---------- */

  const SYNC_DEBOUNCE_MS = 400;
  let syncTimer: ReturnType<typeof setTimeout> | null = null;
  let docSeq = 0;        // ревизия локального документа
  let lastValidSeq = 0;  // последняя ревизия, подтверждённая валидацией

  function scheduleSync() {
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { syncTimer = null; void syncNow(); }, SYNC_DEBOUNCE_MS);
  }

  async function syncNow() {
    if (!doc) return;
    const seq = docSeq;
    if (seq === lastValidSeq) return;
    const payload = cloneDoc(doc);
    try {
      const resp = await api<{ errors?: string[] }>("/api/timeline/validate", { timeline: payload });
      if (seq !== docSeq) return; // устаревший ответ: документ изменился, не затираем
      const errors = resp.errors || [];
      if (errors.length) {
        say("Правки не прошли валидацию: " + errors[0]);
        return; // канонический таймлайн остаётся на последнем валидном состоянии
      }
      lastValidSeq = seq;
      $flow.setNodeData(nodeId, { timeline: payload });
      say("");
    } catch (error) {
      if (seq !== docSeq) return;
      say(error instanceof Error ? error.message : String(error));
    }
  }

  /* При закрытии/размонтировании недособранный дебаунс сбрасывается сразу:
   * последний валидный результат правок не теряется. */
  function flushPendingSync() {
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    if (doc && docSeq !== lastValidSeq) void syncNow();
  }

  $effect(() => {
    return () => {
      disposed = true;
      removeDragListeners();
      flushPendingSync();
    };
  });

  function closeWorkspace() {
    flushPendingSync();
    onClose();
  }

  /* ---------- операции таймлайна ---------- */

  function selectLayer(id: string) { selectedLayerId = id; }

  function setLayerTiming(layerId: string, key: "in" | "out", value: number) {
    mutate((d) => {
      const layer = d.layers.find((l: AnyDoc) => l.id === layerId);
      if (!layer) return;
      // Инвариант 0 <= in < out <= duration сохраняется при ЛЮБОМ вводе
      // (мышь, клавиатура, числа в инспекторе): значение зажимается в допустимый
      // интервал относительно второго края, промежуточные невалидные состояния
      // не возникают и не попадают ни в историю, ни в канон ноды.
      const v = Math.max(0, Math.min(duration, Math.round(value)));
      if (key === "in") {
        layer.in = Math.min(v, Math.max(0, Number(layer.out || 0) - 1));
      } else {
        layer.out = Math.max(v, Math.min(duration, Number(layer.in || 0) + 1));
      }
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

  /* ---------- ИИ-режиссёр: промпт -> превью -> явные Применить/Отменить ---------- */

  async function runAiDirector() {
    const prompt = aiPrompt.trim();
    if (!doc || !prompt || aiBusy || busy || preview) return;
    aiBusy = true;
    say("ИИ-режиссёр готовит монтаж...");
    try {
      const resp = await api<{
        timeline?: AnyDoc; changeSet?: AnyDoc; planSource?: string; warning?: string | null; error?: string;
      }>("/api/timeline/assist", { timeline: doc, prompt });
      if (resp.error || !resp.timeline || !resp.changeSet) throw new Error(resp.error || "пустой ответ");
      preview = {
        timeline: resp.timeline,
        changeSet: resp.changeSet,
        intent: String(resp.changeSet.intent || prompt),
        planSource: String(resp.planSource || "deterministic"),
        warning: resp.warning || null,
        operations: Array.isArray(resp.changeSet.operations) ? resp.changeSet.operations.length : 0,
      };
      say("Превью готово — проверьте монтаж и примените или отмените");
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      say("ИИ-режиссёр: " + msg);
      toast("ИИ-режиссёр: " + msg, "error");
    } finally {
      aiBusy = false;
    }
  }

  async function applyPreview() {
    if (!preview || !doc || busy) return;
    const applied = preview;
    busy = true;
    say("Применение ИИ-монтажа...");
    try {
      const resp = await api<{ timeline?: AnyDoc; error?: string }>(
        "/api/timeline/apply", { timeline: doc, changeSet: applied.changeSet });
      if (resp.error || !resp.timeline) throw new Error(resp.error || "пустой ответ");
      snapshot();
      doc = resp.timeline;
      docSeq++;
      lastChangeSet = applied.changeSet;
      preview = null;
      aiPrompt = "";
      say("Применено: " + applied.intent);
      scheduleSync();
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      say("Применение: " + msg);
      toast("ИИ-режиссёр: " + msg, "error");
    } finally {
      busy = false;
    }
  }

  function cancelPreview() {
    preview = null;
    say("Превью отменено — таймлайн не изменён");
  }

  async function undoAi() {
    if (!doc || !lastChangeSet || busy) return;
    busy = true;
    try {
      const resp = await api<{ timeline?: AnyDoc }>("/api/timeline/revert", {
        timeline: doc, changeSet: lastChangeSet });
      if (resp.timeline) {
        snapshot();
        doc = resp.timeline;
        docSeq++;
        lastChangeSet = null;
        say("ИИ-патч откатан");
        scheduleSync();
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

  function publishRenderJob(id: string, state: AnyDoc, format: string) {
    const mapped = state.status === "done" ? "complete"
      : state.status === "running" ? "rendering"
        : state.status === "cancelled" ? "error"
          : state.status === "error" ? "error" : "queued";
    $flow.setNodeData(nodeId, {
      renderJob: {
        id,
        status: mapped,
        progress: Number(state.progress || 0),
        framesDone: Number(state.framesDone || 0),
        framesTotal: Number(state.framesTotal || 0),
        filename: state.filename || `designdna-timeline-${id.slice(0, 8)}.${format === "webm" ? "webm" : "mp4"}`,
        downloadUrl: state.downloadUrl,
        result: state.result,
        error: state.error || (state.status === "cancelled" ? "Render cancelled" : undefined),
      },
    });
    if (mapped === "complete") $flow.propagate(nodeId);
  }

  async function renderVideo(format: string) {
    if (!doc || busy) return;
    if (!designIr) { say("Нет входного Design IR для рендера"); return; }
    busy = true;
    renderState = { status: "starting" };
    renderId = null;
    say("Рендер запущен...");
    try {
      const resp = await api<{ renderId?: string; error?: string }>(
        "/api/timeline/render", { timeline: doc, ir: designIr, format });
      if (resp.error || !resp.renderId) throw new Error(resp.error || "нет renderId");
      renderId = resp.renderId;
      publishRenderJob(renderId, { status: "queued", progress: 0 }, format);
      for (let i = 0; i < 600 && !disposed; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        if (disposed) break;
        const st = await apiGet<AnyDoc>(`/api/timeline/render/${renderId}`);
        renderState = st;
        publishRenderJob(renderId, st, format);
        if (st.status === "done" || st.status === "error" || st.status === "cancelled") break;
      }
      if (renderState?.status === "done") say("Ролик готов — скачайте файл");
      else say("Рендер: " + (renderState?.error || renderState?.status || "неизвестно"));
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      renderState = { status: "error", error: msg };
      publishRenderJob(renderId || "failed", renderState, format);
      say("Рендер: " + msg);
    } finally {
      busy = false;
      renderId = null;
    }
  }

  async function cancelRender() {
    const id = renderId;
    if (!id) return;
    try {
      await api<{ status?: string }>(`/api/timeline/render/${id}/cancel`, {});
      say("Отмена рендера запрошена");
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      say("Отмена рендера: " + msg);
    }
  }

  /* ---------- перетаскивание (оконные слушатели, одна транзакция на жест) ---------- */

  type DragState = {
    kind: "playhead" | "key" | "trim-in" | "trim-out";
    layerId?: string; prop?: string; t?: number; startX: number; origin: number;
  };
  let drag: DragState | null = null;

  function addDragListeners() {
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
  }

  function removeDragListeners() {
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
  }

  function beginDrag(state: DragState, mutatesDoc: boolean) {
    if (preview) { say("Сначала примените или отмените превью ИИ"); return; }
    // скраб (mutatesDoc=false) не трогает документ — снапшот не нужен;
    // драг кейфрейма/клипа даёт один снапшот на весь жест
    coalescing = true;
    dragNeedsSnapshot = mutatesDoc;
    drag = state;
    addDragListeners();
  }

  function onDragEnd() {
    drag = null;
    coalescing = false;
    dragNeedsSnapshot = false;
    removeDragListeners();
  }

  function rulerTimeFromEvent(e: PointerEvent): number {
    const rect = (rulerTrack || (e.currentTarget as HTMLElement)).getBoundingClientRect();
    return Math.max(0, Math.min(duration, (e.clientX - rect.left) / pxPerMs));
  }

  function onRulerDown(e: PointerEvent) {
    if (!duration) return;
    playing = false;
    playhead = rulerTimeFromEvent(e);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    beginDrag({ kind: "playhead", startX: e.clientX, origin: playhead }, false);
  }

  function onKeyDown(e: PointerEvent, layerId: string, prop: string, t: number) {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    beginDrag({ kind: "key", layerId, prop, t, startX: e.clientX, origin: t }, true);
  }

  function onTrimDown(e: PointerEvent, layerId: string, edge: "trim-in" | "trim-out") {
    e.stopPropagation();
    const layer = layers.find((l) => l.id === layerId);
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    beginDrag({
      kind: edge, layerId, startX: e.clientX,
      origin: Number(layer?.[edge === "trim-in" ? "in" : "out"] || 0),
    }, true);
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

  /* ---------- клавиатурное управление ---------- */

  function onRulerKey(e: KeyboardEvent) {
    if (!duration) return;
    const step = e.shiftKey ? 1000 : 1000 / fps;
    if (e.key === "ArrowLeft") { playhead = Math.max(0, playhead - step); e.preventDefault(); }
    else if (e.key === "ArrowRight") { playhead = Math.min(duration, playhead + step); e.preventDefault(); }
    else if (e.key === "Home") { playhead = 0; e.preventDefault(); }
    else if (e.key === "End") { playhead = duration; e.preventDefault(); }
  }

  function onKeyframeKey(e: KeyboardEvent, layerId: string, prop: string, t: number) {
    selectedLayerId = layerId;
    selectedProp = prop;
    const frameMs = 1000 / fps;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      setKeyframeT(layerId, prop, t, t + (e.key === "ArrowRight" ? frameMs : -frameMs));
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      removeKeyframe(layerId, prop, t);
    }
  }

  function onTrimKey(e: KeyboardEvent, layerId: string, edge: "trim-in" | "trim-out") {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const layer = layers.find((l) => l.id === layerId);
    const current = Number(layer?.[edge === "trim-in" ? "in" : "out"] || 0);
    const delta = (e.key === "ArrowRight" ? 1 : -1) * (1000 / fps);
    setLayerTiming(layerId, edge === "trim-in" ? "in" : "out", current + delta);
  }

  /* ---------- композиция ---------- */

  const PROPS = ["x", "y", "scale", "rotation", "opacity"] as const;
  // Семантика свойств (x/y/scale/rotation/opacity) намеренно разноцветная —
  // сами значения объявлены в .tlw-root как --tlw-prop-*, здесь только ссылки.
  const PROP_COLORS: Record<string, string> = {
    x: "var(--tlw-prop-x)", y: "var(--tlw-prop-y)", scale: "var(--tlw-prop-scale)",
    rotation: "var(--tlw-prop-rotation)", opacity: "var(--tlw-prop-opacity)",
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

<div class="tlw-root" role="dialog" aria-modal="true" aria-label="Video Editor"
  aria-busy={busy || aiBusy} use:bodyPortal>
  <div class="tlw-top">
    <button class="tlw-btn" data-act="close" aria-label="Закрыть редактор и вернуться к графу"
      onclick={closeWorkspace}>← Граф</button>
    <span class="tlw-title">Video Editor</span>
    <button class="tlw-btn primary" data-act="play" disabled={!duration}
      aria-label={playing ? "Пауза" : "Проиграть"} aria-pressed={playing} onclick={togglePlay}>
      {playing ? "❚❚" : "▶"}
    </button>
    <span class="tlw-time">{timeLabel(playhead)} / {timeLabel(duration)}</span>
    <select class="tlw-select" aria-label="Формат кадра"
      value={FORMATS.find((f) => f.width === width && f.height === height)?.label || "custom"}
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
    <button class="tlw-btn" data-act="undo" disabled={busy || Boolean(preview) || !doc || historyDepth === 0}
      onclick={undo}>Undo</button>
    {#if lastChangeSet}
      <button class="tlw-btn" data-act="ai-revert" disabled={busy || Boolean(preview)} onclick={() => void undoAi()}>Откатить ИИ-патч</button>
    {/if}
    <button class="tlw-btn" data-act="render-mp4" disabled={busy || !doc || Boolean(preview)}
      onclick={() => void renderVideo("mp4")}>Рендер MP4</button>
    <button class="tlw-btn" data-act="export-css" disabled={busy || !doc || Boolean(preview)}
      onclick={() => void exportCss()}>Экспорт CSS</button>
  </div>

  <div class="tlw-ai">
    <input class="tlw-ai-input" data-act="ai-prompt"
      aria-label="Промпт ИИ-режиссёра"
      placeholder="ИИ-режиссёр: «интро снизу, наезд на hero, пульс на кнопке в конце»"
      bind:value={aiPrompt} disabled={aiBusy || busy || !doc || Boolean(preview)}
      onkeydown={(e) => { if (e.key === "Enter") void runAiDirector(); }} />
    <button class="tlw-btn primary" data-act="ai-run"
      disabled={aiBusy || busy || !doc || !aiPrompt.trim() || Boolean(preview)}
      onclick={() => void runAiDirector()}>
      {aiBusy ? "..." : "Составить монтаж"}
    </button>
  </div>

  {#if preview}
    <div class="tlw-preview" role="region" aria-label="Превью ИИ-монтажа" data-act="ai-preview">
      <span class="tlw-preview-main">
        Превью: {preview.intent} · операций: {preview.operations} ·
        план: {preview.planSource === "llm" ? "LLM" : "детерминированный"}
      </span>
      {#if preview.warning}<span class="tlw-preview-warn" role="alert">{preview.warning}</span>{/if}
      <span class="tlw-spacer"></span>
      <button class="tlw-btn primary" data-act="ai-apply" disabled={busy || aiBusy}
        onclick={() => void applyPreview()}>{busy ? "..." : "Применить"}</button>
      <button class="tlw-btn" data-act="ai-cancel" disabled={busy || aiBusy} onclick={cancelPreview}>Отменить</button>
    </div>
  {/if}

  <div class="tlw-body">
    <div class="tlw-layers">
      <div class="tlw-panel-title">Слои и группы</div>
      {#if !activeDoc}
        <div class="tlw-empty">Соберите таймлайн из входного Design IR</div>
      {:else}
        {#each groups as group (group.id)}
          <div class="tlw-group">{group.name}</div>
          {#each layers.filter((l) => l.parent === group.id) as layer (layer.id)}
            <button class="tlw-layer" data-act="layer" type="button"
              aria-pressed={selectedLayerId === layer.id} onclick={() => selectLayer(layer.id)}>
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
        <div class="tlw-prop-pick" role="group" aria-label="Свойство анимации">
          {#each PROPS as prop (prop)}
            <button class="tlw-prop-chip" type="button" style="--pc:{PROP_COLORS[prop]}"
              aria-pressed={selectedProp === prop}
              onclick={() => (selectedProp = prop)}>{prop}</button>
          {/each}
        </div>
        <button class="tlw-btn primary wide" data-act="add-keyframe" disabled={Boolean(preview)}
          onclick={() => addKeyframe(selectedLayer.id, selectedProp)}>
          ◆ Кейфрейм {selectedProp} @ {timeLabel(playhead)}
        </button>
        <div class="tlw-kf-list">
          {#each (selectedLayer.transform?.properties?.[selectedProp]?.keyframes || []) as kf (kf.t)}
            <div class="tlw-kf-row">
              <span style="color:{PROP_COLORS[selectedProp]}">◆</span>
              <span>{timeLabel(kf.t)} → {Number(kf.value).toFixed(2)}</span>
              <select class="tlw-select small" aria-label="Изинг кейфрейма {timeLabel(kf.t)}" value={kf.easing || "linear"}
                onchange={(e) => setKeyframeEasing(selectedLayer.id, selectedProp, kf.t, (e.currentTarget as HTMLSelectElement).value)}>
                {#each ["linear", "ease", "ease-in", "ease-out", "ease-in-out"] as ez (ez)}<option value={ez}>{ez}</option>{/each}
              </select>
              <button class="tlw-btn danger small" type="button" aria-label="Удалить кейфрейм {timeLabel(kf.t)}"
                onclick={() => removeKeyframe(selectedLayer.id, selectedProp, kf.t)}>✕</button>
            </div>
          {/each}
        </div>
      {:else}
        <div class="tlw-empty">Выберите слой слева</div>
      {/if}
    </div>
  </div>

  <div class="tlw-timeline">
    <div class="tlw-ruler" data-act="ruler" role="slider" tabindex="0"
      aria-label="Позиция воспроизведения"
      aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(playhead)}
      aria-valuetext="{timeLabel(playhead)} из {timeLabel(duration)}"
      onpointerdown={onRulerDown} onkeydown={onRulerKey}>
      <div class="tlw-ruler-track" bind:this={rulerTrack} style="width:{duration * pxPerMs}px">
        {#each Array.from({ length: Math.ceil(duration / 1000) + 1 }) as _, sec}
          <div class="tlw-ruler-mark" style="left:{sec * 1000 * pxPerMs}px">{sec}s</div>
        {/each}
        <div class="tlw-playhead" style="left:{playhead * pxPerMs}px"></div>
      </div>
    </div>
    <div class="tlw-tracks">
      {#each layers as layer (layer.id)}
        <div class="tlw-track" class:active={selectedLayerId === layer.id}>
          <button class="tlw-track-name" type="button" title={layer.name}
            aria-pressed={selectedLayerId === layer.id} onclick={() => selectLayer(layer.id)}>{layer.name}</button>
          <div class="tlw-track-lane" style="width:{duration * pxPerMs}px">
            <div class="tlw-clip" style="left:{layer.in * pxPerMs}px; width:{Math.max(4, (layer.out - layer.in) * pxPerMs)}px">
              <button class="tlw-trim" type="button" disabled={Boolean(layer.locked)}
                aria-label="Начало клипа: {layer.name}"
                onpointerdown={(e) => onTrimDown(e, layer.id, "trim-in")}
                onkeydown={(e) => onTrimKey(e, layer.id, "trim-in")}></button>
              {#each PROPS as prop (prop)}
                {#each (layer.transform?.properties?.[prop]?.keyframes || []) as kf (prop + ":" + kf.t)}
                  <button class="tlw-key" type="button" title="{prop} {timeLabel(kf.t)}"
                    aria-label="Кейфрейм {prop} слоя {layer.name} в {timeLabel(kf.t)}"
                    disabled={Boolean(layer.locked)}
                    style="left:{(kf.t - layer.in) * pxPerMs}px; top:{2 + PROPS.indexOf(prop) * 7}px; background:{PROP_COLORS[prop]}"
                    onpointerdown={(e) => onKeyDown(e, layer.id, prop, kf.t)}
                    onkeydown={(e) => onKeyframeKey(e, layer.id, prop, kf.t)}
                    ondblclick={() => removeKeyframe(layer.id, prop, kf.t)}></button>
                {/each}
              {/each}
              <button class="tlw-trim right" type="button" disabled={Boolean(layer.locked)}
                aria-label="Конец клипа: {layer.name}"
                onpointerdown={(e) => onTrimDown(e, layer.id, "trim-out")}
                onkeydown={(e) => onTrimKey(e, layer.id, "trim-out")}></button>
            </div>
            <div class="tlw-playhead" style="left:{playhead * pxPerMs}px"></div>
          </div>
        </div>
      {/each}
    </div>
    <div class="tlw-status">
      <span class="tlw-message" role="status" aria-live="polite">{message}</span>
      {#if busy && renderState}
        <span class="tlw-render-info">
          рендер: {renderState.status}{renderState.framesTotal ? " " + (renderState.framesDone || 0) + "/" + renderState.framesTotal : ""}
        </span>
        {#if renderId}
          <button class="tlw-btn danger small" data-act="render-cancel" onclick={() => void cancelRender()}>Отменить рендер</button>
        {/if}
      {/if}
      {#if renderState?.status === "done" && renderState?.downloadUrl}
        <a class="tlw-download" data-act="render-download" href={renderState.downloadUrl} download>Скачать ролик</a>
      {/if}
      <span class="tlw-hint">клик по линейке — скраб (←/→ — кадр) · ◆ — кейфрейм (тянуть, ←/→ — сдвиг, Del — удалить)</span>
    </div>
  </div>
</div>

<style>
  .tlw-root { position: fixed; inset: 0; z-index: 80; display: flex; flex-direction: column;
    background: var(--dna-panel); color: var(--dna-text-2); font-size: 13px;
    /* Акцент таймлайна — motion-розовый семейства DNA; активные кнопки — --dna-action. */
    --tlw-accent: var(--dna-motion);
    --tlw-accent-soft: color-mix(in srgb, var(--dna-motion) 22%, var(--dna-elevated));
    --tlw-accent-line: color-mix(in srgb, var(--dna-motion) 45%, transparent);
    --tlw-clip-bg: color-mix(in srgb, var(--dna-motion) 16%, var(--dna-elevated));
    --tlw-clip-border: color-mix(in srgb, var(--dna-motion) 40%, var(--dna-border-strong));
    --tlw-preview-bg: color-mix(in srgb, var(--dna-violet) 14%, var(--dna-panel-2));
    /* Цвета данных: свойства анимации различаются намеренно. */
    --tlw-prop-x: #5aa9ff; --tlw-prop-y: #67d98f; --tlw-prop-scale: #f2c14e;
    --tlw-prop-rotation: #c792ea; --tlw-prop-opacity: #ff8a80; }
  .tlw-top, .tlw-ai, .tlw-preview { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    border-bottom: 1px solid var(--dna-border); flex-wrap: wrap; }
  .tlw-title { font-weight: 600; margin-right: 8px; }
  .tlw-time { font-variant-numeric: tabular-nums; color: var(--dna-muted); min-width: 120px; }
  .tlw-spacer { flex: 1; }
  .tlw-btn { background: var(--dna-elevated); color: var(--dna-text-2); border: 1px solid var(--dna-border-strong); border-radius: 7px;
    padding: 5px 10px; cursor: pointer; font-size: 12px; }
  .tlw-btn:hover:not(:disabled) { background: var(--dna-hover); }
  .tlw-btn:disabled { opacity: 0.45; cursor: default; }
  .tlw-btn.primary { background: var(--dna-action); border-color: var(--dna-action); color: #fff; }
  .tlw-btn.primary:hover:not(:disabled) { background: var(--dna-action-h); }
  .tlw-btn.danger { color: var(--dna-danger-text); }
  .tlw-btn.small { padding: 2px 6px; }
  .tlw-btn.wide { width: 100%; margin: 6px 0; }
  .tlw-select { background: var(--dna-elevated); color: var(--dna-text-2); border: 1px solid var(--dna-border-strong); border-radius: 6px; padding: 4px 6px; }
  .tlw-select.small { padding: 1px 4px; font-size: 11px; }
  .tlw-input { width: 72px; background: var(--dna-elevated); color: var(--dna-text-2); border: 1px solid var(--dna-border-strong); border-radius: 6px; padding: 4px 6px; }
  .tlw-inline { display: flex; align-items: center; gap: 6px; color: var(--dna-muted); }
  .tlw-ai-input { flex: 1; background: var(--dna-sunken); color: var(--dna-text); border: 1px solid var(--dna-border-strong); border-radius: 8px; padding: 7px 10px; }
  .tlw-preview { background: var(--tlw-preview-bg); }
  .tlw-preview-main { color: var(--dna-violet-text); }
  .tlw-preview-warn { color: var(--dna-amber); }
  .tlw-body { flex: 1; display: grid; grid-template-columns: 230px 1fr 260px; min-height: 0; }
  .tlw-layers, .tlw-inspector { border-right: 1px solid var(--dna-border); overflow-y: auto; padding: 8px; }
  .tlw-inspector { border-right: none; border-left: 1px solid var(--dna-border); }
  .tlw-panel-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--dna-faint); margin: 4px 0 8px; }
  .tlw-group { margin: 10px 0 4px; color: var(--dna-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .tlw-layer { display: flex; align-items: center; gap: 6px; width: 100%; background: transparent; border: none;
    color: var(--dna-text-2); padding: 5px 6px; border-radius: 6px; cursor: pointer; text-align: left; }
  .tlw-layer:hover { background: var(--dna-elevated); }
  .tlw-layer[aria-pressed="true"] { background: var(--tlw-accent-soft); color: var(--dna-text); }
  .tlw-layer-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tlw-layer-time { color: var(--dna-faint); font-size: 11px; font-variant-numeric: tabular-nums; }
  .tlw-stage { display: flex; align-items: center; justify-content: center; overflow: hidden; background: var(--dna-bg); }
  .tlw-artboard { position: relative; transform-origin: center center; box-shadow: 0 0 0 1px var(--dna-border-strong); flex: none; }
  .tlw-irhost { position: absolute; inset: 0; overflow: hidden; }
  .tlw-empty { color: var(--dna-faint); padding: 12px 6px; }
  .tlw-insp-name { font-weight: 600; margin-bottom: 8px; }
  .tlw-prop-pick { display: flex; gap: 4px; flex-wrap: wrap; margin: 8px 0; }
  .tlw-prop-chip { border: 1px solid var(--pc); color: var(--pc); background: transparent; border-radius: 6px;
    padding: 2px 8px; cursor: pointer; font-size: 11px; }
  .tlw-prop-chip[aria-pressed="true"] { background: var(--pc); color: var(--dna-bg); }
  .tlw-kf-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
  .tlw-kf-row { display: flex; align-items: center; gap: 6px; background: var(--dna-sunken); border-radius: 6px; padding: 4px 6px; }
  .tlw-kf-row span:nth-child(2) { flex: 1; font-variant-numeric: tabular-nums; }
  .tlw-timeline { border-top: 1px solid var(--dna-border); background: var(--dna-panel-2); max-height: 38vh; overflow: auto; }
  .tlw-ruler { padding: 6px 8px 0 148px; cursor: ew-resize; outline-offset: 2px; }
  .tlw-ruler-track { position: relative; height: 22px; }
  .tlw-ruler-mark { position: absolute; top: 0; font-size: 10px; color: var(--dna-faint); border-left: 1px solid var(--dna-border-strong); padding-left: 3px; height: 100%; }
  .tlw-tracks { padding: 4px 8px 8px 0; }
  .tlw-track { display: flex; align-items: center; }
  .tlw-track.active .tlw-track-name { color: var(--dna-text); }
  .tlw-track-name { width: 140px; flex: none; padding: 4px 8px; font-size: 11px; color: var(--dna-muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: transparent; border: none;
    cursor: pointer; text-align: left; }
  .tlw-track-name:hover { color: var(--dna-text-2); }
  .tlw-track-lane { position: relative; height: 40px; background: var(--dna-sunken); border-radius: 6px; margin: 2px 0; }
  .tlw-clip { position: absolute; top: 2px; bottom: 2px; background: var(--tlw-clip-bg); border: 1px solid var(--tlw-clip-border); border-radius: 6px; }
  .tlw-trim { position: absolute; top: 0; bottom: 0; width: 9px; left: 0; cursor: ew-resize;
    background: transparent; border: none; padding: 0; }
  .tlw-trim.right { left: auto; right: 0; }
  .tlw-trim:hover:not(:disabled), .tlw-trim:focus-visible { background: var(--tlw-accent-line); }
  .tlw-trim:disabled { cursor: default; }
  .tlw-key { position: absolute; width: 8px; height: 8px; transform: rotate(45deg); cursor: ew-resize;
    border-radius: 1px; border: none; padding: 0; }
  .tlw-key:disabled { cursor: default; opacity: 0.5; }
  .tlw-playhead { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--dna-action); pointer-events: none; }
  .tlw-status { display: flex; align-items: center; gap: 12px; padding: 6px 12px; border-top: 1px solid var(--dna-border); color: var(--dna-muted); }
  .tlw-status .tlw-hint { margin-left: auto; font-size: 11px; color: var(--dna-faint-2); }
  .tlw-render-info { font-size: 11px; color: var(--dna-muted); font-variant-numeric: tabular-nums; }
  .tlw-download { color: var(--dna-success-text); text-decoration: underline; }
</style>
