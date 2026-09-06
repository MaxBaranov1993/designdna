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
  import { onMount, tick } from "svelte";
  import VideoModelPicker from "./VideoModelPicker.svelte";
  import { TimelineEngine, Timeline } from "../engine/timeline";
  import { IRRenderer } from "../engine/renderer";
  import { VideoStoryPlayer, storySchedule, actionLabel } from "../engine/video-story";
  import type { VideoStory } from "../engine/video-story";
  import VideoStoryPanel from "./VideoStoryPanel.svelte";
  import VideoStatesPanel from "./VideoStatesPanel.svelte";
  import { flow } from "../flow/state";
  import { api, apiGet } from "../flow/api";
  import { toast } from "../flow/toast";
  import { resizeTimeline, moveTimelineKey, setTimelineKeyValue } from "./timeline-edits";
  import { bodyPortal } from "../lib/bodyPortal";
  import type { TimelineNodeData, VideoRevision, VideoRevisionChange, VideoChatMessage, VideoEffort } from "../flow/types";

  let { nodeId, data, onClose, startWithPrompt = false }: { nodeId: number; data: TimelineNodeData; onClose: () => void; startWithPrompt?: boolean } = $props();

  type AnyDoc = Record<string, any>;

  /* Локальная редактируемая копия: снимок таймлайна ноды на момент открытия.
   * Инициализация в $effect.pre — намеренно разовый захват начального значения. */
  let doc = $state<AnyDoc | null>(null);
  let docInitialized = false;
  let canonical: AnyDoc | null = null;
  let sourceRevision = -1;
  $effect.pre(() => {
    if (docInitialized) return;
    docInitialized = true;
    // JSON-клон безопасен и для plain-объектов, и для реактивных прокси
    doc = data.timeline ? JSON.parse(JSON.stringify(data.timeline)) : null;
    canonical = data.timeline ? JSON.parse(JSON.stringify(data.timeline)) : null;
    sourceRevision = $flow.getNodeIrRevision(nodeId);
  });

  let selectedLayerId = $state<string | null>(null);
  let selectedProp = $state<string>("opacity");
  let playhead = $state(0);
  let playing = $state(false);
  let pxPerMs = $state(0.12);
  let aiPrompt = $state("");
  const chatMessages = $derived(data.chatMessages || []);
  let chatLog = $state<HTMLDivElement | null>(null);
  let chatInput = $state<HTMLTextAreaElement | null>(null);
  let followChat = $state(true);
  let aiRequestSequence = 0;
  let aiRunId: string | null = null;
  let aiController: AbortController | null = null;
  let aiStartedAt = $state(0);
  let aiElapsed = $state(0);
  $effect(() => {
    if (!aiBusy) return;
    const timer = setInterval(() => { aiElapsed = Math.floor((Date.now() - aiStartedAt) / 1000); }, 1000);
    return () => clearInterval(timer);
  });
  $effect(() => {
    chatMessages.length; aiBusy; preview;
    if (followChat) void tick().then(() => { if (chatLog) chatLog.scrollTop = chatLog.scrollHeight; });
  });
  function appendChat(role: VideoChatMessage["role"], content: string, kind: VideoChatMessage["kind"] = "message", provider: "codex" | "claude" = accountProvider) {
    const entry: VideoChatMessage = { id: crypto.randomUUID(), role, content: content.slice(0, 16000), createdAt: new Date().toISOString(), kind, provider };
    $flow.setNodeData(nodeId, { chatMessages: [...(data.chatMessages || []), entry].slice(-100) });
    followChat = true;
    return entry.id;
  }
  function markChat(id: string, kind: VideoChatMessage["kind"]) {
    $flow.setNodeData(nodeId, { chatMessages: (data.chatMessages || []).map(entry => entry.id === id ? { ...entry, kind } : entry) });
  }
  function stopAiDirector() {
    aiRequestSequence++;
    aiController?.abort();
    if (aiRunId) {
      void window.designDNA?.api?.cancel("long", aiRunId).catch(() => undefined);
      void api(`/api/runs/${aiRunId}/cancel`, {}).catch(() => undefined);
    }
    aiRunId = null;
    aiBusy = false;
    appendChat("assistant", "Запрос остановлен. Можно изменить сообщение и отправить снова.", "cancelled");
    void tick().then(() => chatInput?.focus());
  }
  let showVersions = $state(false);
  let pendingRevision: VideoRevisionChange | undefined;
  const accountProvider = $derived(data.provider === "claude" ? "claude" : "codex");
  onMount(() => {
    aiPrompt = data.prompt || "";
    if (startWithPrompt && aiPrompt.trim()) void runAiDirector();
  });
  let busy = $state(false);
  let aiBusy = $state(false);
  let message = $state("");
  let renderState = $state<AnyDoc | null>(null);
  let renderStateInitialized = false;
  $effect.pre(() => {
    if (renderStateInitialized) return;
    renderStateInitialized = true;
    if (data.renderJob?.status === "complete") renderState = { ...data.renderJob, status: "done" };
  });
  let renderId = $state<string | null>(null);
  let historyDepth = $state(0);

  // снапшот-история ручных правок (snapshot ПЕРЕД мутацией, лимит 25)
  const HISTORY_LIMIT = 25;
  const history: AnyDoc[] = [];
  const future: AnyDoc[] = [];
  let futureDepth = $state(0);
  let lastChangeSet = $state<AnyDoc | null>(null);

  // Превью ИИ-монтажа: канонический документ не трогается до «Применить».
  type AiPreview = {
    chatMessageId: string;
    prompt: string;
    provider: "codex" | "claude";
    effort: VideoEffort;
    model: string;
    timeline: AnyDoc;
    changeSet: AnyDoc;
    intent: string;
    planSource: string;
    warning: string | null;
    operations: number;
  };
  let preview = $state<AiPreview | null>(null);

  let irHost: HTMLDivElement | null = $state(null);
  let storyPlayer = $state<VideoStoryPlayer | null>(null);
  let playerError = $state("");
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
    playerError = "";
    if (current.story) {
      try {
        const player = new VideoStoryPlayer(host, current);
        storyPlayer = player;
        return () => { player.destroy(); storyPlayer = null; };
      } catch (error) { playerError = error instanceof Error ? error.message : String(error); host.replaceChildren(); storyPlayer = null; say(playerError); return; }
    }
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
    if (storyPlayer) { storyPlayer.seek(playhead); return; }
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
    future.length = 0;
    futureDepth = 0;
    history.push(cloneDoc(doc));
    if (history.length > HISTORY_LIMIT) history.shift();
    historyDepth = history.length;
  }

  function mutate(fn: (d: AnyDoc) => void) {
    if (!doc || busy || aiBusy) return;
    if (preview) { say("Сначала примените или отмените превью ИИ"); return; }
    const next = JSON.parse(JSON.stringify(doc)) as AnyDoc;
    fn(next);
    if (JSON.stringify(next) === JSON.stringify(doc)) return;
    if (coalescing) {
      if (dragNeedsSnapshot) { snapshot(); dragNeedsSnapshot = false; }
    } else {
      snapshot();
    }
    doc = next;
    renderState = null;
    docSeq++;
    scheduleSync();
  }

  function undo() {
    if (!doc || busy || aiBusy) return;
    if (preview) { say("Сначала примените или отмените превью ИИ"); return; }
    const prev = history.pop();
    historyDepth = history.length;
    if (!prev) { say("История пуста"); return; }
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    future.push(cloneDoc(doc));
    futureDepth = future.length;
    doc = prev;
    renderState = null;
    docSeq++;
    void syncNow();
    say("Отменено");
  }

  function redo() {
    if (!doc || busy || aiBusy || preview) return;
    const next = future.pop();
    if (!next) return;
    history.push(cloneDoc(doc));
    historyDepth = history.length;
    futureDepth = future.length;
    doc = next;
    renderState = null;
    docSeq++;
    void syncNow();
    say("Повторено");
  }

  /* ---------- синхронизация локальных правок с контрактом ---------- */

  const SYNC_DEBOUNCE_MS = 400;
  let syncTimer: ReturnType<typeof setTimeout> | null = null;
  let docSeq = $state(0);        // ревизия локального документа
  let lastValidSeq = $state(0);  // последняя ревизия, подтверждённая валидацией

  function scheduleSync() {
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { syncTimer = null; void syncNow(); }, SYNC_DEBOUNCE_MS);
  }

  async function syncNow() {
    if (!doc) return false;
    const seq = docSeq;
    if (seq === lastValidSeq) return true;
    const payload = cloneDoc(doc);
    try {
      const resp = await api<{ errors?: string[] }>("/api/timeline/validate", { timeline: payload });
      if (seq !== docSeq) return false; // устаревший ответ
      if (seq === lastValidSeq) return true;
      const errors = resp.errors || [];
      if (errors.length) {
        say("Правки не прошли валидацию: " + errors[0]);
        return false; // keep the last valid canonical document
      }
      if (!$flow.commitTimeline(nodeId, canonical, sourceRevision, payload, pendingRevision)) {
        say("Вход или таймлайн изменился вне редактора. Скопируйте черновик перед повторным открытием.");
        return false;
      }
      canonical = payload;
      pendingRevision = undefined;
      lastValidSeq = seq;
      say("");
      return true;
    } catch (error) {
      if (seq !== docSeq) return false;
      say(error instanceof Error ? error.message : String(error));
      return false;
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
      aiRequestSequence++;
      aiController?.abort();
      removeDragListeners();
      flushPendingSync();
    };
  });

  function discardAndClose() {
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    docSeq++;
    lastValidSeq = docSeq;
    onClose();
  }

  async function closeWorkspace() {
    if (busy || aiBusy) { say("Дождитесь операции или отмените рендер"); return; }
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; }
    if (await syncNow()) { if (preview) cancelPreview(); onClose(); }
  }

  function workspaceKey(event: KeyboardEvent) {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select, [contenteditable=true]")) return;
    if ((event.ctrlKey || event.metaKey) && ["z", "y"].includes(event.key.toLowerCase())) {
      event.preventDefault(); event.stopPropagation();
      if (event.key.toLowerCase() === "y" || event.shiftKey) redo(); else undo();
    } else if (event.code === "Space" && target.tagName !== "BUTTON") {
      event.preventDefault(); event.stopPropagation(); togglePlay();
    }
  }

  /* ---------- операции таймлайна ---------- */

  function selectLayer(id: string) { selectedLayerId = id; }

  function setLayerTiming(layerId: string, key: "in" | "out", value: number) {
    if (!Number.isFinite(value)) return;
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
    let moved = oldT;
    mutate((d) => {
      moved = moveTimelineKey(d, layerId, prop, oldT, newT);
    });
    return moved;
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
    const requestSequence = ++aiRequestSequence;
    const runId = crypto.randomUUID();
    aiRunId = runId;
    aiController = new AbortController();
    aiStartedAt = Date.now(); aiElapsed = 0;
    const conversation = chatMessages.filter(entry => entry.kind !== "error").slice(-24)
      .map(entry => ({ role: entry.role, content: entry.content.slice(0, 15800) + (entry.kind === "preview" ? "\n[Предложение не применено]" : entry.kind === "applied" ? "\n[Применено]" : entry.kind === "cancelled" ? "\n[Отменено]" : "") }));
    const provider = accountProvider;
    const effort = data.effort || "medium";
    const model = data.model || (provider === "claude" ? "opus" : "gpt-5.6-sol");
    appendChat("user", prompt);
    aiPrompt = "";
    $flow.setNodeData(nodeId, { prompt: "", provider });
    say("Изучаю визуал, структуру и содержимое страницы, затем готовлю монтаж…");
    try {
      if (!await syncNow()) throw new Error("Сначала сохраните текущие правки");
      if (disposed || requestSequence !== aiRequestSequence) return;
      const resp = await api<{
        timeline?: AnyDoc; changeSet?: AnyDoc; planSource?: string; warning?: string | null; error?: string; understanding?: string;
      }>("/api/timeline/assist", { timeline: doc, prompt, provider, effort, model, require_llm: true, conversation }, { signal: aiController.signal, runId });
      if (disposed || requestSequence !== aiRequestSequence) return;
      if ($flow.getNodeIrRevision(nodeId) !== sourceRevision) throw new Error("Исходная страница изменилась во время запроса. Откройте редактор заново и повторите сообщение.");
      if (resp.error || !resp.timeline || !resp.changeSet) throw new Error(resp.error || "пустой ответ");
      preview = {
        chatMessageId: appendChat("assistant", (resp.understanding ? "Понял страницу: " + resp.understanding + "\n\n" : "") + String(resp.changeSet.intent || "Подготовил изменения монтажа.") + (resp.warning ? "\n\n" + resp.warning : ""), "preview", provider),
        prompt, provider, effort, model,
        timeline: resp.timeline,
        changeSet: resp.changeSet,
        intent: String(resp.changeSet.intent || prompt),
        planSource: String(resp.planSource || "deterministic"),
        warning: resp.warning || null,
        operations: Array.isArray(resp.changeSet.operations) ? resp.changeSet.operations.length : 0,
      };
      say("Превью готово — проверьте монтаж и примените или отмените");
    } catch (error) {
      if (disposed || requestSequence !== aiRequestSequence) return;
      const msg = error instanceof Error ? error.message : String(error);
      const question = msg.startsWith("Нужно уточнить:");
      appendChat("assistant", question ? msg.replace(/^Нужно уточнить:\s*/, "") : msg, question ? "question" : "error", provider);
      say("ИИ-режиссёр: " + msg);
    } finally {
      if (requestSequence === aiRequestSequence) { aiBusy = false; aiRunId = null; void tick().then(() => chatInput?.focus()); }
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
      renderState = null;
      docSeq++;
      pendingRevision = { kind: "prompt", label: applied.intent, prompt: applied.prompt, provider: applied.provider, effort: applied.effort, model: applied.model };
      lastChangeSet = applied.changeSet;
      markChat(applied.chatMessageId, "applied");
      preview = null;
      aiPrompt = "";
      say("Применено: " + applied.intent);
      await syncNow();
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      appendChat("assistant", "Не удалось применить монтаж: " + msg, "error");
      say("Применение: " + msg);
      toast("ИИ-режиссёр: " + msg, "error");
    } finally {
      busy = false;
    }
  }

  function cancelPreview() {
    if (preview) markChat(preview.chatMessageId, "cancelled");
    preview = null;
    say("Превью отменено — таймлайн не изменён");
  }

  async function restoreVersion(version: VideoRevision) {
    if (!doc || busy || aiBusy || preview) return;
    if (JSON.stringify(version.sourceIr) !== JSON.stringify(data.ir)) {
      say("Эта версия создана для другой исходной страницы. Подключите прежнюю страницу перед восстановлением.");
      return;
    }
    busy = true;
    try {
      if (!await syncNow()) return;
      const result = await api<{ errors?: string[] }>("/api/timeline/validate", { timeline: version.timeline });
      if (result.errors?.length) throw new Error(result.errors[0]);
      const next = JSON.parse(JSON.stringify(version.timeline));
      if (!$flow.commitTimeline(nodeId, canonical, sourceRevision, next, {
        kind: "restore", label: "Возврат: " + version.label, restoredFrom: version.id,
        prompt: version.prompt, provider: version.provider, effort: version.effort, model: version.model,
      })) throw new Error("Страница или монтаж изменились вне редактора. Откройте редактор заново.");
      snapshot();
      doc = next;
      canonical = JSON.parse(JSON.stringify(next));
      docSeq++;
      lastValidSeq = docSeq;
      pendingRevision = undefined;
      aiPrompt = version.prompt || "";
      $flow.setNodeData(nodeId, { prompt: aiPrompt });
      renderState = null;
      lastChangeSet = null;
      playing = false;
      playhead = Math.min(playhead, Number(next.composition.duration));
      say("Версия восстановлена. Можно продолжить новым промптом; прежние версии сохранены.");
    } catch (error) {
      say(error instanceof Error ? error.message : String(error));
    } finally {
      busy = false;
    }
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
    } catch (error) {
      say("Откат: " + (error instanceof Error ? error.message : String(error)));
    } finally {
      busy = false;
    }
  }

  /* ---------- рендер ролика и экспорт веб-анимации ---------- */

  async function downloadVideo() {
    const url = renderState?.downloadUrl;
    const files = window.designDNA?.files;
    if (!url || !files) return;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      await files.save(renderState?.filename || "timeline.mp4", btoa(binary));
    } catch (error) { say("Скачивание: " + (error instanceof Error ? error.message : String(error))); }
  }

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
    const current = $flow.nodes.find((node) => Number(node.id) === nodeId);
    if (!current || $flow.getNodeIrRevision(nodeId) !== sourceRevision
      || JSON.stringify((current.data as TimelineNodeData).timeline) !== JSON.stringify(canonical)) return;
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
    if (!doc || busy || aiBusy || preview) return;
    if (!designIr) { say("Нет входного Design IR для рендера"); return; }
    if (!await syncNow()) return;
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
    window.addEventListener("pointercancel", onDragEnd);
  }

  function removeDragListeners() {
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
    window.removeEventListener("pointercancel", onDragEnd);
  }

  function beginDrag(state: DragState, mutatesDoc: boolean) {
    if (mutatesDoc && (busy || aiBusy)) return;
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
        drag.t = setKeyframeT(drag.layerId, drag.prop, drag.t, newT);
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
    mutate((d) => resizeTimeline(d, value));
    playhead = Math.min(playhead, doc?.composition.duration || 0);
  }

  async function editStory(story: VideoStory, polish = false) {
    if (!doc || busy || aiBusy || preview) return;
    if (!await syncNow()) return;
    const seq = docSeq;
    busy = true;
    try {
      const next = JSON.parse(JSON.stringify(doc));
      next.story = story;
      if (polish) next.composition.fps = 60;
      const oldDuration = next.composition.duration;
      const keyEnd = Math.max(0, ...next.layers.flatMap((l: AnyDoc) => Object.values(l.transform.properties).flatMap((track: any) => track.keyframes.map((k: any) => k.t))));
      const clipEnd = Math.max(0, ...next.layers.filter((l: AnyDoc) => l.out !== oldDuration).map((l: AnyDoc) => l.out));
      next.composition.duration = Math.max(1000, story.actions.reduce((sum, a) => sum + a.duration, 0) + 800, keyEnd, clipEnd);
      next.layers.forEach((l: AnyDoc) => { if (l.out === oldDuration) l.out = next.composition.duration; });
      const result = await api<{ errors?: string[] }>("/api/timeline/validate", { timeline: next });
      if (result.errors?.length) throw new Error(result.errors[0]);
      if (docSeq !== seq || disposed) return;
      busy = false;
      mutate((d) => Object.assign(d, next));
      playhead = Math.min(playhead, next.composition.duration);
    } catch (error) { say(error instanceof Error ? error.message : String(error)); }
    finally { busy = false; }
  }

  function timeLabel(ms: number) {
    const s = Math.max(0, ms) / 1000;
    return s.toFixed(2) + "s";
  }
</script>

<div class="tlw-root" role="dialog" aria-modal="true" aria-label="Video Editor"
  aria-busy={busy || aiBusy} onkeydown={workspaceKey} tabindex="-1" use:bodyPortal>
  <div class="tlw-top">
    <button class="tlw-btn" data-act="close" aria-label="Закрыть редактор и вернуться к графу"
      onclick={closeWorkspace}>← Граф</button>
    <span class="tlw-title">Видео</span>
    <button class="tlw-btn" data-act="video-history" aria-expanded={showVersions}
      onclick={() => (showVersions = !showVersions)}>История · {data.revisions?.length || 0}</button>
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
    <button class="tlw-btn" data-act="undo" disabled={busy || aiBusy || Boolean(preview) || !doc || historyDepth === 0}
      onclick={undo}>Отменить</button>
    <button class="tlw-btn" data-act="redo" disabled={busy || aiBusy || Boolean(preview) || futureDepth === 0}
      onclick={redo}>Повторить</button>
    <button class="tlw-btn" data-act="save-draft" disabled={!doc}
      onclick={() => doc && downloadText("timeline-draft.json", JSON.stringify(cloneDoc(doc), null, 2), "application/json")}>Скачать черновик</button>
    {#if message && docSeq !== lastValidSeq}
      <button class="tlw-btn" disabled={busy || aiBusy} onclick={discardAndClose}>Закрыть без последних правок</button>
    {/if}
    {#if lastChangeSet}
      <button class="tlw-btn" data-act="ai-revert" disabled={busy || Boolean(preview)} onclick={() => void undoAi()}>Откатить ИИ-патч</button>
    {/if}
    <button class="tlw-btn" data-act="render-mp4" disabled={busy || !doc || Boolean(preview)}
      onclick={() => void renderVideo("mp4")}>Рендер MP4</button>
    <button class="tlw-btn" data-act="export-css" title={doc?.story?.actions.length ? "Сценарий действий экспортируется в MP4" : "Экспорт анимации компонентов"} disabled={busy || !doc || Boolean(preview) || Boolean(doc?.story?.actions.length)}
      onclick={() => void exportCss()}>Экспорт CSS</button>
  </div>

  <div class="tlw-workspace">
  <div class="tlw-editor">
  {#if showVersions}
    <section class="video-versions" aria-label="История монтажа">
      <div class="video-versions-title">Вернитесь к версии и продолжите новым промптом. Последующие версии сохранятся.</div>
      {#each [...(data.revisions || [])].reverse() as version (version.id)}
        <div class="video-version" class:current={version.id === data.activeRevisionId}>
          <div><strong>{version.label}</strong>
            {#if version.prompt && version.prompt !== version.label}<p>{version.prompt}</p>{/if}
            <small>{new Date(version.createdAt).toLocaleString("ru-RU")}{version.provider ? ` · ${version.provider === "claude" ? "Claude" : "GPT"}` : ""}{version.kind === "restore" ? " · новая ветка" : ""}</small>
          </div>
          <button class="tlw-btn" data-act="restore-version" disabled={busy || aiBusy || Boolean(preview)}
            onclick={() => void restoreVersion(version)}>Вернуться</button>
        </div>
      {:else}
        <p>После применения первого промпта здесь появятся исходный монтаж и результат.</p>
      {/each}
    </section>
  {/if}

  <div class="tlw-body" class:hasSelection={Boolean(selectedLayer)}>
    <div class="tlw-layers">
      {#if activeDoc?.story}
        <VideoStoryPanel story={activeDoc.story} disabled={busy || aiBusy || Boolean(preview)}
          onChange={(story) => void editStory(story)} onPolish={(story) => void editStory(story, true)} onSeek={(time) => { playing = false; playhead = time; }} />
        <VideoStatesPanel story={activeDoc.story} disabled={busy || aiBusy || Boolean(preview)}
          onChange={(story) => void editStory(story)} onSeek={(time) => { playing = false; playhead = time; }} />
      {/if}
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
      {#if playerError}<div class="tlw-player-error" role="alert">Не удалось показать монтаж: {playerError}</div>{/if}
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
        <button class="tlw-btn primary wide" data-act="add-keyframe" disabled={busy || aiBusy || Boolean(preview)}
          onclick={() => addKeyframe(selectedLayer.id, selectedProp)}>
          ◆ Кейфрейм {selectedProp} @ {timeLabel(playhead)}
        </button>
        <div class="tlw-kf-list">
          {#each (selectedLayer.transform?.properties?.[selectedProp]?.keyframes || []) as kf (kf.t)}
            <div class="tlw-kf-row">
              <span style="color:{PROP_COLORS[selectedProp]}">◆</span>
              <span>{timeLabel(kf.t)}</span>
              <input class="tlw-input" data-act="keyframe-value" type="number"
                aria-label="Значение {selectedProp} в {timeLabel(kf.t)}" value={kf.value}
                step={selectedProp === "opacity" || selectedProp === "scale" ? 0.05 : 1}
                min={selectedProp === "opacity" || selectedProp === "scale" ? 0 : undefined}
                max={selectedProp === "opacity" ? 1 : undefined}
                disabled={busy || aiBusy || Boolean(preview)}
                onchange={(e) => mutate((d) => setTimelineKeyValue(d, selectedLayer.id, selectedProp, kf.t, Number(e.currentTarget.value)))} />
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
    {#if activeDoc?.story?.actions.length}
      <div class="story-strip" aria-label="Действия на таймлайне">
        {#each storySchedule(activeDoc.story) as action (action.id)}
          <button class:active={playhead >= action.start && playhead < action.end}
            style:width={`${action.duration * pxPerMs}px`}
            title={`${actionLabel[action.type]} · ${(action.start / 1000).toFixed(1)}–${(action.end / 1000).toFixed(1)}s`}
            onclick={() => { playing = false; playhead = action.start; }}>{actionLabel[action.type]}</button>
        {/each}
      </div>
    {/if}
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
        {#if window.designDNA?.files}
          <button class="tlw-btn" data-act="render-download" onclick={() => void downloadVideo()}>Скачать ролик</button>
        {:else}
          <a class="tlw-download" data-act="render-download" href={renderState.downloadUrl} download>Скачать ролик</a>
        {/if}
      {/if}
      <span class="tlw-hint">клик по линейке — скраб (←/→ — кадр) · ◆ — кейфрейм (тянуть, ←/→ — сдвиг, Del — удалить)</span>
    </div>
  </div>
  </div>
  <aside class="video-chat" aria-label="Чат с ИИ-режиссёром" data-act="video-chat">
    <header class="video-chat-header">
      <div><strong>Чат о видео</strong><span>Сценарий, правки и уточнения</span></div>
      <span class="video-chat-presence" class:working={aiBusy}>{aiBusy ? "Думает" : "На связи"}</span>
    </header>
    <div class="video-chat-model" inert={aiBusy || busy || Boolean(preview)}>
      <VideoModelPicker provider={accountProvider} model={data.model} effort={data.effort || "medium"}
        onChange={(choice) => $flow.setNodeData(nodeId, choice)} />
    </div>
    <div class="video-chat-log" role="log" aria-label="Переписка о видео" aria-live="polite" aria-relevant="additions text"
      bind:this={chatLog} onscroll={() => { if (chatLog) followChat = chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight < 60; }}>
      {#if !chatMessages.length}
        <div class="video-chat-welcome">
          <span class="video-chat-symbol" aria-hidden="true">↗</span>
          <h2>Давайте соберём историю</h2>
          <p>Опишите, что должно происходить на странице. Здесь появятся ответ, вопросы и предложенный монтаж.</p>
          <button type="button" onclick={() => { aiPrompt = "Плавно проведи курсор к основной кнопке, нажми её и задержись на результате."; chatInput?.focus(); }}>Курсор и нажатие <span aria-hidden="true">↗</span></button>
          <button type="button" onclick={() => { aiPrompt = "Сделай движения мягче: плавный разгон и торможение, больше пауз между действиями."; chatInput?.focus(); }}>Смягчить анимацию <span aria-hidden="true">↗</span></button>
        </div>
      {/if}
      {#each chatMessages as entry (entry.id)}
        <article class="video-chat-message" class:user={entry.role === "user"} class:error={entry.kind === "error"} data-act="chat-message" data-role={entry.role}>
          <div class="video-chat-author">{entry.role === "user" ? "Вы" : entry.provider === "claude" ? "Claude" : "GPT"}
            <time datetime={entry.createdAt}>{new Date(entry.createdAt).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</time>
          </div>
          {#if entry.kind === "question"}<span class="video-chat-label">Уточнение</span>{/if}
          {#if entry.kind === "error"}<span class="video-chat-label">Не удалось выполнить запрос</span>{/if}
          <div class="video-chat-text">{entry.content}</div>
          {#if preview?.chatMessageId === entry.id}
            <div class="tlw-preview" role="region" aria-label="Превью ИИ-монтажа" data-act="ai-preview">
              <span>{playerError ? `Монтаж не воспроизводится: ${playerError}` : "Монтаж показан в плеере. Проверьте результат перед применением."}</span>
              <div class="video-chat-actions">
                <button class="tlw-btn" disabled={Boolean(playerError)} onclick={() => { playhead = 0; playing = true; }}>▶ Смотреть</button>
                <button class="tlw-btn primary" data-act="ai-apply" disabled={busy || aiBusy || Boolean(playerError)} onclick={() => void applyPreview()}>{busy ? "Применяю…" : "Применить"}</button>
                <button class="tlw-btn" data-act="ai-cancel" disabled={busy || aiBusy} onclick={cancelPreview}>Отменить</button>
              </div>
            </div>
          {:else if entry.kind === "applied"}<span class="video-chat-outcome">✓ Изменения применены</span>
          {:else if entry.kind === "preview"}<span class="video-chat-outcome">Предложение не применено</span>
          {:else if entry.kind === "cancelled"}<span class="video-chat-outcome">Отменено</span>{/if}
          {#if entry.role === "user" && !aiBusy && !preview}
            <button class="video-chat-reuse" aria-label="Редактировать сообщение" onclick={() => { aiPrompt = entry.content; chatInput?.focus(); }}>Повторить или изменить</button>
          {/if}
        </article>
      {/each}
      {#if aiBusy}
        <div class="video-chat-thinking" role="status"><span class="video-chat-pulse"></span>{accountProvider === "claude" ? "Claude" : "GPT"} готовит ответ <span>{aiElapsed} с</span></div>
      {/if}
    </div>
    <div class="video-chat-composer">
      {#if !followChat && chatMessages.length}
        <button class="video-chat-latest" onclick={() => { followChat = true; if (chatLog) chatLog.scrollTop = chatLog.scrollHeight; }}>К последнему ответу ↓</button>
      {/if}
      {#if preview}<p class="video-chat-compose-hint">Примените или отмените предложенный монтаж, чтобы продолжить.</p>{/if}
      <div class="video-chat-input-box">
        <textarea class="tlw-ai-input" data-act="ai-prompt" bind:this={chatInput} aria-label="Промпт ИИ-режиссёра" rows="3" maxlength="6000"
          placeholder={chatMessages.length ? "Ответьте или опишите следующую правку…" : "Что должно происходить в ролике?"}
          bind:value={aiPrompt} disabled={busy || !doc || Boolean(preview)}
          oninput={(event) => $flow.setNodeData(nodeId, { prompt: event.currentTarget.value })}
          onkeydown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void runAiDirector(); } }}></textarea>
        <div class="video-chat-send-row"><span>Enter — отправить · Shift+Enter — строка</span>
          {#if aiBusy}<button class="tlw-btn" data-act="ai-stop" aria-label="Остановить ответ" onclick={stopAiDirector}>■ Стоп</button>
          {:else}<button class="tlw-btn primary" data-act="ai-run" aria-label="Отправить сообщение" disabled={busy || !doc || !aiPrompt.trim() || Boolean(preview)} onclick={() => void runAiDirector()}>↑ Отправить</button>{/if}
        </div>
      </div>
      <p class="video-chat-footnote">Переписка сохраняется в этой видеоноде.</p>
    </div>
  </aside>
  </div>
</div>

<style>
  .tlw-workspace { display: grid; grid-template-columns: minmax(0, 1fr) clamp(330px, 25vw, 420px); flex: 1; min-height: 0; }
  .tlw-editor { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  .video-chat { display: flex; flex-direction: column; min-height: 0; min-width: 0; border-left: 1px solid var(--dna-border-strong); background: var(--dna-panel); }
  .video-chat-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 20px 20px 12px; }
  .video-chat-header strong { display: block; color: var(--dna-text); font-size: 16px; font-weight: 650; letter-spacing: -.25px; }
  .video-chat-header div > span { display: block; color: var(--dna-muted); font-size: 11px; margin-top: 5px; }
  .video-chat-presence { font-size: 10px; color: var(--dna-muted); white-space: nowrap; }
  .video-chat-presence.working { color: var(--dna-action); }
  .video-chat-model { padding: 0 20px 14px; border-bottom: 1px solid var(--dna-border); }
  .video-chat-model :global(select) { width: 100%; }
  .video-chat-log { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 20px 18px; scrollbar-gutter: stable; }
  .video-chat-welcome { padding: 20px 4px; }
  .video-chat-symbol { display: grid; place-items: center; width: 36px; height: 36px; color: var(--dna-action); border: 1px solid var(--dna-border-strong); border-radius: 12px; font-size: 24px; }
  .video-chat-welcome h2 { color: var(--dna-text); font-size: 20px; line-height: 1.35; margin: 18px 0 10px; letter-spacing: -.4px; }
  .video-chat-welcome p { font-size: 13px; line-height: 1.65; color: var(--dna-muted); margin-bottom: 24px; }
  .video-chat-welcome button { display: flex; width: 100%; justify-content: space-between; text-align: left; background: transparent; color: var(--dna-text-2); border: 1px solid var(--dna-border); border-radius: 10px; padding: 12px; margin-top: 8px; cursor: pointer; }
  .video-chat-welcome button:hover { border-color: var(--dna-action); }
  .video-chat-message { margin-bottom: 26px; overflow-wrap: anywhere; }
  .video-chat-message.user { margin-left: 20px; background: var(--dna-elevated); border: 1px solid var(--dna-border); border-radius: 14px 14px 4px 14px; padding: 13px 14px; }
  .video-chat-author { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; color: var(--dna-text); font-size: 12px; font-weight: 650; }
  .video-chat-author time { color: var(--dna-faint); font-weight: 400; font-size: 10px; }
  .video-chat-text { white-space: pre-wrap; line-height: 1.7; font-size: 13px; color: var(--dna-text-2); user-select: text; }
  .video-chat-label { display: block; font-weight: 600; color: var(--dna-action); margin-bottom: 8px; font-size: 11px; }
  .video-chat-message.error { border-left: 2px solid var(--dna-action); padding-left: 12px; }
  .video-chat-reuse { display: block; padding: 0; margin-top: 12px; background: none; border: none; color: var(--dna-muted); font-size: 10px; cursor: pointer; }
  .video-chat-reuse:hover { color: var(--dna-text); text-decoration: underline; }
  .video-chat-outcome { display: block; color: var(--dna-muted); font-size: 11px; margin-top: 12px; }
  .video-chat .tlw-preview { margin-top: 14px; border: 1px solid var(--dna-border-strong); border-radius: 10px; padding: 12px; font-size: 12px; line-height: 1.55; background: var(--dna-elevated); }
  .video-chat-actions { display: flex; gap: 6px; margin-top: 12px; flex-wrap: wrap; }
  .video-chat-thinking { display: flex; align-items: center; gap: 8px; color: var(--dna-muted); font-size: 12px; min-height: 36px; }
  .video-chat-thinking > span:last-child { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 11px; }
  .video-chat-pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--dna-action); animation: chat-pulse 1.4s ease-in-out infinite; }
  @keyframes chat-pulse { 50% { opacity: .3; } }
  .video-chat-composer { padding: 12px 14px 10px; border-top: 1px solid var(--dna-border); }
  .video-chat-latest { display: block; margin: -4px auto 10px; border: 1px solid var(--dna-border-strong); border-radius: 20px; padding: 5px 12px; background: var(--dna-elevated); color: var(--dna-text-2); cursor: pointer; font-size: 11px; }
  .video-chat-input-box { border: 1px solid var(--dna-border-strong); border-radius: 14px; background: var(--dna-elevated); overflow: hidden; }
  .video-chat-input-box:focus-within { border-color: var(--dna-action); }
  .tlw-ai-input { display: block; box-sizing: border-box; width: 100%; min-height: 90px; max-height: 200px; resize: vertical; background: transparent; color: var(--dna-text); border: none; padding: 13px; font: inherit; font-size: 13px; line-height: 1.6; }
  .tlw-ai-input:focus { outline: none; }
  .tlw-ai-input::placeholder { color: var(--dna-faint); }
  .video-chat-send-row { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 0 10px 10px; }
  .video-chat-send-row > span { margin-right: auto; color: var(--dna-faint); font-size: 9px; max-width: 150px; }
  .video-chat-compose-hint { color: var(--dna-muted); font-size: 11px; line-height: 1.5; margin: 0 0 10px; }
  .video-chat-footnote { font-size: 10px; text-align: center; color: var(--dna-faint); margin: 9px 0 0; }
  .video-chat button:focus-visible { outline: 2px solid var(--dna-action); outline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) { .video-chat-pulse { animation: none; } }
  @media (max-width: 900px) {
    .tlw-workspace { grid-template-columns: minmax(0, 1fr) 310px; }
    .video-chat-header { padding: 14px; }
    .video-chat-log { padding: 14px 12px; }
    .video-chat-model { padding-inline: 14px; }
  }
  .story-strip { display: flex; gap: 0; padding: 5px 0 5px 148px; width: max-content; }
  .story-strip button { box-sizing: border-box; min-width: 0; flex-shrink: 0; border: 1px solid var(--dna-border); border-radius: 4px; background: var(--dna-elevated); color: var(--dna-text-2); padding: 5px 3px; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .story-strip button.active { border-color: var(--dna-action); color: var(--dna-action); }
  .video-versions { flex: 0 0 auto; max-height: 240px; overflow: auto; padding: 10px 16px; border-bottom: 1px solid var(--dna-border); background: var(--dna-sunken); }
  .video-versions-title, .video-versions > p { font-size: 12px; color: var(--dna-dim); }
  .video-version { display: flex; gap: 16px; justify-content: space-between; align-items: center; padding: 10px 8px; border-left: 2px solid transparent; border-bottom: 1px solid var(--dna-border); }
  .video-version.current { border-left-color: var(--dna-success-text); }
  .video-version > div { min-width: 0; }
  .video-version strong, .video-version p { overflow-wrap: anywhere; font-size: 12px; }
  .video-version p { margin: 4px 0; }
  .video-version small { display: block; color: var(--dna-dim); font-size: 10px; margin-top: 4px; }
  .video-version button { flex-shrink: 0; }
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
  .tlw-top { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
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
  .tlw-body { flex: 1; display: grid; grid-template-columns: 200px minmax(0, 1fr); min-height: 0; }
  .tlw-body.hasSelection { grid-template-columns: 180px minmax(0, 1fr) 210px; }
  .tlw-body:not(.hasSelection) .tlw-inspector { display: none; }
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
  .tlw-player-error { position: absolute; z-index: 10; max-width: 80%; padding: 16px; border: 1px solid var(--dna-border-strong); border-radius: 8px; background: var(--dna-panel); color: var(--dna-text); font-size: 13px; }
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
  .tlw-kf-row { display: grid; grid-template-columns: 10px 38px minmax(35px, 1fr) minmax(58px, 1.4fr) 22px; align-items: center; gap: 4px; background: var(--dna-sunken); border-radius: 6px; padding: 4px; }
  .tlw-kf-row span:nth-child(2) { font-variant-numeric: tabular-nums; font-size: 11px; }
  .tlw-kf-row input, .tlw-kf-row select { width: 100%; min-width: 0; padding-inline: 3px; }
  .tlw-kf-row button { padding-inline: 2px; }
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
