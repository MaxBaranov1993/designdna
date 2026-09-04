<script lang="ts">
  import { useFlowStore } from "../flow/store";
  import { IRHistory } from "../engine/irhistory";
  import { compositionFrame, COMP_CARD_STYLE } from "./motion-composition";
  import { untrack } from "svelte";
  import { api, apiGet } from "../flow/api";
  import { flow, flowBusy } from "../flow/state";
  import { bodyPortal } from "../lib/bodyPortal";
  import type { MotionCompLayer, MotionNodeData, MotionRenderJob, MotionSceneSettings } from "../flow/types";
  import { durationOf, interpProp, keyIdxAt, layerVals, scenesOf, type InterpMode, type LayerValues } from "./motion-utils";
  import "./motion.css";

  type PropKey = "p" | "s" | "r" | "o";

  function formatTime(milliseconds: number): string {
    const seconds = Math.max(0, milliseconds) / 1000;
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
  }

  function formatBytes(bytes = 0): string {
    return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
  }

  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

  let { nodeId, data, onClose }: { nodeId: number; data: MotionNodeData; onClose: () => void } = $props();

  /* ---------- справочники (зеркало прототипа хендоффа) ---------- */
  const propDefs: Array<{ k: PropKey; label: string; dims: 1 | 2 }> = [
    { k: "p", label: "Позиция", dims: 2 },
    { k: "s", label: "Масштаб", dims: 1 },
    { k: "r", label: "Поворот", dims: 1 },
    { k: "o", label: "Прозрачность", dims: 1 },
  ];
  const toolDefs = [
    { id: "move", label: "Перемещение", icon: "✥" },
    { id: "scale", label: "Масштаб", icon: "⤢" },
    { id: "rotate", label: "Поворот", icon: "⟳" },
    { id: "opacity", label: "Прозрачность", icon: "◐" },
  ] as const;
  const toolProp: Record<string, PropKey> = { move: "p", scale: "s", rotate: "r", opacity: "o" };

  /* ---------- базовое состояние ---------- */
  let busy = $derived(Boolean($flowBusy[nodeId]));
  let scenes = $derived(scenesOf(data));
  let total = $derived(durationOf(data));
  let playing = $state(false);
  let playhead = $state(0); /* moT: локальное, не персистится по кадрам */
  let playheadInitialized = false;
  let inspectorOpen = $state(window.innerWidth > 760);
  let moTool = $state<(typeof toolDefs)[number]["id"]>("move");
  let moPropSel = $state<PropKey>("p");
  let moLayerSel = $state<string | null>(null);
  let moExpand = $state<Record<string, boolean>>({});
  let moBox = $state<{ w: number; h: number } | null>(null);
  let stageEl = $state<HTMLElement | null>(null);
  let fileInput = $state<HTMLInputElement | null>(null);

  let activeIndex = $derived(
    Math.max(0, scenes.findIndex((scene, index) => playhead >= scene.start && (playhead < scene.start + scene.duration || index === scenes.length - 1))),
  );
  let activeScene = $derived(scenes[activeIndex]);
  let activeSourceId = $derived(activeScene?.interactionSceneId || "");
  let lt = $derived(activeScene ? Math.max(0, Math.min(playhead - activeScene.start, activeScene.duration)) : 0);

  let stageW = $derived(data.composition.width || 1920);
  let stageH = $derived(data.composition.height || 1080);
  let fit = $derived(moBox ? Math.min(moBox.w / stageW, moBox.h / stageH) : 0.35);

  let easing = $derived(data.sceneSettings[activeSourceId]?.easing ?? activeScene?.transition?.easing ?? "linear");
  let interpMode = $derived<InterpMode>(easing === "linear" ? "linear" : "smoothstep");

  let renderSettings = $derived(data.renderSettings || { format: "mp4" as const, quality: "high" as const });
  let renderJob = $derived(data.renderJob);
  let startingRender = $state(false);
  let rendering = $derived(startingRender || renderJob?.status === "queued" || renderJob?.status === "rendering");
  let transition = $derived(activeScene?.transition || { type: "cut" as const, duration: 0, easing: "linear" as const });

  /* ---------- слои композиций ---------- */

  function walkTree(node: unknown, visit: (n: Record<string, unknown>) => void) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;
    const rec = node as Record<string, unknown>;
    visit(rec);
    if (Array.isArray(rec.children)) rec.children.forEach((child) => walkTree(child, visit));
  }

  function collectTexts(ir: unknown): { headings: string[]; first: string } {
    const headings: string[] = [];
    let first = "";
    const tree = ir && typeof ir === "object" ? ((ir as Record<string, unknown>).tree as unknown[]) : null;
    if (Array.isArray(tree)) {
      tree.forEach((section) =>
        walkTree(section, (n) => {
          const text = typeof n.text === "string" ? n.text.trim() : "";
          if (!text) return;
          if (!first) first = text;
          const tag = String(n.variant ?? n.tag ?? "");
          const isHeading = n.type === "heading" || n.role === "heading" || n.type === "title" || /^h[1-6]$/i.test(tag);
          if (isHeading && !headings.includes(text)) headings.push(text);
        }),
      );
    }
    return { headings, first };
  }

  /* Дефолтные слои из IR сцен — детерминированно (без Math.random/Date.now). */
  let defaultLayers = $derived.by<MotionCompLayer[]>(() => {
    const out: MotionCompLayer[] = [];
    const w = stageW;
    const h = stageH;
    scenes.forEach((scene, i) => {
      const ir = data.sceneIrs.find((item) => item.sceneId === scene.id)?.ir || data.ir;
      const { headings, first } = collectTexts(ir);
      const texts = (headings.length ? headings : [first || `Сцена ${String(i + 1).padStart(2, "0")}`]).slice(0, 4);
      texts.forEach((text, k) => {
        out.push({
          id: `d${i}-${k}`,
          sceneId: scene.id,
          name: text.slice(0, 28),
          group: "gen",
          type: "text",
          text,
          size: Math.max(16, Math.round(h * (k === 0 ? 0.096 : 0.042))),
          weight: k === 0 ? 700 : 500,
          color: k === 0 ? "#111114" : "#888888",
          w: Math.round(w * 0.72),
          props: {
            p: {
              keys: [
                { t: 0, v: [Math.round(w / 2), Math.round(h * (0.38 + k * 0.14))] },
                { t: 700, v: [Math.round(w / 2), Math.round(h * (0.36 + k * 0.14))] },
              ],
            },
            s: { keys: k === 0 ? [{ t: 0, v: 0.94 }, { t: 700, v: 1 }] : [{ t: 0, v: 1 }] },
            r: { keys: [{ t: 0, v: 0 }] },
            o: { keys: [{ t: k * 200, v: 0 }, { t: k * 200 + 600, v: 1 }] },
          },
        });
      });
    });
    return out;
  });

  /* Локальная копия на время драга: setNodeData — только на коммите. */
  let localLayers = $state<MotionCompLayer[] | null>(null);
  let persistedLayers = $derived(Array.isArray(data.layers) ? data.layers : null);
  let baselineLayers = $derived(localLayers ?? persistedLayers ?? defaultLayers);
  let sceneLayers = $derived(activeScene ? baselineLayers.filter((l) => (l.sceneId ?? scenes[0]?.id) === activeScene.id) : []);
  let selectedLayer = $derived(sceneLayers.find((l) => l.id === moLayerSel) ?? sceneLayers[0] ?? null);
  let vals = $derived<LayerValues | null>(selectedLayer ? layerVals(selectedLayer, lt, interpMode) : null);

  const layerHistory = IRHistory.createHistory({ limit: 25, coalesceMs: 0 });
  let historyTick = $state(0);
  const canUndo = $derived.by(() => { historyTick; return layerHistory.canUndo(); });
  const canRedo = $derived.by(() => { historyTick; return layerHistory.canRedo(); });
  $effect(() => {
    if (!Array.isArray(data.layers) && defaultLayers.length) {
      $flow.setNodeData(nodeId, { layers: JSON.parse(JSON.stringify(defaultLayers)) });
    }
  });
  const restoreLayers = (redo = false) => {
    if (rendering) return;
    const next = (redo ? layerHistory.redo : layerHistory.undo)(() => baselineLayers);
    if (next) { $flow.setNodeData(nodeId, { layers: next, renderJob: null }); $flow.propagate(nodeId); }
    localLayers = null;
    historyTick++;
  };
  const commitLayers = (next: MotionCompLayer[]) => {
    if (rendering) { localLayers = null; return; }
    layerHistory.push(() => persistedLayers ?? defaultLayers, null);
    historyTick++;
    $flow.setNodeData(nodeId, { layers: next, renderJob: null });
    $flow.propagate(nodeId);
    localLayers = null;
  };

  const mutateLayer = (id: string, fn: (layer: MotionCompLayer) => MotionCompLayer) => {
    commitLayers(baselineLayers.map((l) => (l.id === id ? fn(l) : l)));
  };

  const writeKeys = (layer: MotionCompLayer, key: PropKey, keys: MotionCompLayer["props"][PropKey]["keys"]) =>
    ({ ...layer, props: { ...layer.props, [key]: { keys } } }) as MotionCompLayer;

  /* Правка пишется в ближайший предшествующий кейфрейм свойства. */
  const writeProp = (layer: MotionCompLayer, key: PropKey, value: number | [number, number], ltime: number) => {
    const keys = layer.props[key].keys.slice() as Array<{ t: number; v: never }>;
    if (!keys.length) return layer;
    const i = keyIdxAt(keys, ltime);
    keys[i] = { ...keys[i], v: value as never };
    return writeKeys(layer, key, keys as never);
  };

  const nextLayerId = (layers: MotionCompLayer[]) => {
    const ids = new Set(layers.map((l) => l.id));
    let n = 1;
    while (ids.has(`ly-${n}`)) n += 1;
    return `ly-${n}`;
  };

  /* ---------- панель ПРОЕКТ ---------- */
  let srcDomain = $derived.by(() => {
    const root = data.ir as Record<string, any> | null;
    const raw = String(root?.meta?.sourceUrl || root?.meta?.url || root?.sourceUrl || root?.source?.url || "");
    if (!raw) return "";
    try {
      return new URL(raw).hostname;
    } catch {
      return raw;
    }
  });
  let groupMeta = $derived<Record<MotionCompLayer["group"], { label: string; color: string }>>({
    // Цвета групп — семейство токенов DNA (index.css); в разметку уходят как
    // --group-color, полупрозрачные варианты считает CSS через color-mix.
    src: { label: `Source Import${srcDomain ? " · " + srcDomain : ""}`, color: "var(--dna-action)" },
    kit: { label: "Design System / UI Kit", color: "var(--dna-violet)" },
    gen: { label: "Генератор · Design IR", color: "var(--dna-violet-l)" },
    media: { label: "Медиа · загружено", color: "var(--dna-artifact)" },
  });
  let projectGroups = $derived.by(() => {
    const src: Array<{ name: string; kind: string }> = [];
    const gen: Array<{ name: string; kind: string }> = [];
    const tree = data.ir && typeof data.ir === "object" ? ((data.ir as Record<string, unknown>).tree as unknown[]) : null;
    if (Array.isArray(tree)) {
      tree.forEach((section) => {
        if (!section || typeof section !== "object") return;
        const sec = section as Record<string, unknown>;
        const name = String(sec.id || sec.type || "section");
        const isSource = sec.type === "source-block" || sec.variant === "dom-capture";
        (isSource ? src : gen).push({ name, kind: isSource ? "блок" : "секция" });
      });
    }
    const groups: Array<{ key: MotionCompLayer["group"]; items: Array<{ name: string; kind: string }> }> = [];
    if (src.length) groups.push({ key: "src", items: src });
    if (gen.length) groups.push({ key: "gen", items: gen });
    return groups;
  });
  let mediaLayers = $derived(sceneLayers.filter((l) => l.group === "media"));

  const makeLayer = (init: Partial<MotionCompLayer> & { id: string; name: string; group: MotionCompLayer["group"]; type: MotionCompLayer["type"] }): MotionCompLayer => ({
    text: undefined,
    src: undefined,
    sceneId: activeScene?.id,
    size: Math.max(16, Math.round(stageH * 0.036)),
    weight: 700,
    color: "#111114",
    w: Math.round(stageW * 0.32),
    props: {
      p: { keys: [{ t: Math.round(lt), v: [Math.round(stageW / 2), Math.round(stageH / 2)] }] },
      s: { keys: [{ t: 0, v: 1 }] },
      r: { keys: [{ t: 0, v: 0 }] },
      o: { keys: [{ t: Math.round(lt), v: 0 }, { t: Math.round(lt) + 500, v: 1 }] },
    },
    ...init,
  });

  const addAssetLayer = (name: string, group: MotionCompLayer["group"]) => {
    if (!activeScene) return;
    const base = baselineLayers;
    const id = nextLayerId(base);
    commitLayers(base.concat([makeLayer({ id, name, group, type: "comp", text: name })]));
    moLayerSel = id;
    moPropSel = "p";
    moExpand = { ...moExpand, [id]: true };
  };

  const onUpload = (event: Event) => {
    const input = event.currentTarget as HTMLInputElement;
    const files = Array.from(input.files || []);
    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (!activeScene) return;
        const base = baselineLayers;
        const id = nextLayerId(base);
        commitLayers(
          base.concat([
            makeLayer({ id, name: file.name.slice(0, 20), group: "media", type: "image", src: String(reader.result || ""), w: Math.round(stageW * 0.4) }),
          ]),
        );
        moLayerSel = id;
        moPropSel = "p";
        moExpand = { ...moExpand, [id]: true };
      };
      reader.readAsDataURL(file);
    });
    input.value = "";
  };

  /* ---------- драг слоя во вьюере ---------- */
  let dragCtx: { id: string; key: PropKey; mx: number; my: number; v: LayerValues; lt: number; fit: number; moved: boolean } | null = null;

  const onDragMove = (event: PointerEvent) => {
    const g = dragCtx;
    if (!g) return;
    const dx = (event.clientX - g.mx) / Math.max(0.01, g.fit);
    const dy = (event.clientY - g.my) / Math.max(0.01, g.fit);
    const nv: number | [number, number] =
      g.key === "p" ? [g.v.p[0] + dx, g.v.p[1] + dy]
      : g.key === "s" ? clamp(g.v.s + dx / 400, 0.1, 4)
      : g.key === "r" ? g.v.r + dx / 4
      : clamp(g.v.o + dx / 400, 0, 1);
    g.moved = true;
    localLayers = baselineLayers.map((l) => (l.id === g.id ? writeProp(l, g.key, nv, g.lt) : l));
  };

  const onDragEnd = () => {
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
    window.removeEventListener("pointercancel", onDragEnd);
    const g = dragCtx;
    dragCtx = null;
    /* Персист — только на отпускании мыши, не на каждом движении. */
    if (g?.moved && localLayers) commitLayers(localLayers);
  };

  const onLayerPointerDown = (event: PointerEvent, layer: MotionCompLayer) => {
    if (event.button !== 0 || rendering) return;
    event.preventDefault();
    event.stopPropagation();
    const key = toolProp[moTool] || "p";
    moLayerSel = layer.id;
    moPropSel = key;
    dragCtx = { id: layer.id, key, mx: event.clientX, my: event.clientY, v: layerVals(layer, lt, interpMode), lt, fit, moved: false };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
    window.addEventListener("pointercancel", onDragEnd);
  };

  /* ---------- инспектор: степперы и кейфреймы ---------- */
  let transformRows = $derived(
    vals
      ? [
          { k: "X", v: `${Math.round(vals.p[0])}`, f: "x", d: 20 },
          { k: "Y", v: `${Math.round(vals.p[1])}`, f: "y", d: 20 },
          { k: "Масштаб", v: vals.s.toFixed(2), f: "s", d: 0.05 },
          { k: "Поворот", v: `${Math.round(vals.r)}°`, f: "r", d: 5 },
          { k: "Прозрачность", v: vals.o.toFixed(2), f: "o", d: 0.1 },
        ]
      : [],
  );

  const bump = (field: string, delta: number) => {
    const layer = selectedLayer;
    if (!layer || !vals) return;
    if (field === "x" || field === "y") {
      const np: [number, number] = field === "x" ? [vals.p[0] + delta, vals.p[1]] : [vals.p[0], vals.p[1] + delta];
      mutateLayer(layer.id, (l) => writeProp(l, "p", np, lt));
    } else {
      const key = field as PropKey;
      let nv = (vals[key as "s" | "r" | "o"] as number) + delta;
      if (key === "o") nv = clamp(nv, 0, 1);
      if (key === "s") nv = clamp(nv, 0.1, 4);
      mutateLayer(layer.id, (l) => writeProp(l, key, nv, lt));
    }
  };

  let propLabel = $derived((propDefs.find((p) => p.k === moPropSel) || propDefs[0]).label);
  let keyInfo = $derived(
    selectedLayer ? `${selectedLayer.props[moPropSel].keys.length} кейфрейм(ов) · ${(lt / 1000).toFixed(2)} с` : "—",
  );

  const addKey = () => {
    const layer = selectedLayer;
    if (!layer) return;
    const key = moPropSel;
    const def = propDefs.find((p) => p.k === key)!;
    const value = def.dims === 2
      ? interpProp(layer.props.p.keys, lt, 2, interpMode)
      : interpProp(layer.props[key].keys as Array<{ t: number; v: number }>, lt, 1, interpMode);
    mutateLayer(layer.id, (l) => {
      /* дубль в ±30мс заменяется */
      const keys = (l.props[key].keys as Array<{ t: number; v: never }>)
        .filter((k) => Math.abs(k.t - lt) > 30)
        .concat([{ t: Math.round(lt), v: value as never }]);
      keys.sort((a, b) => a.t - b.t);
      return writeKeys(l, key, keys as never);
    });
  };

  const delKey = () => {
    const layer = selectedLayer;
    if (!layer || layer.props[moPropSel].keys.length < 2) return;
    const key = moPropSel;
    mutateLayer(layer.id, (l) => {
      const keys = l.props[key].keys as Array<{ t: number }>;
      const next = keys.filter((k) => Math.abs(k.t - lt) > 120);
      /* минимум один кейфрейм остаётся */
      return writeKeys(l, key, (next.length ? next : [keys[keyIdxAt(keys, lt)]]) as never);
    });
  };

  const delLayer = () => {
    const layer = selectedLayer;
    if (!layer) return;
    const next = baselineLayers.filter((l) => l.id !== layer.id);
    commitLayers(next);
    const rest = activeScene ? next.filter((l) => (l.sceneId ?? scenes[0]?.id) === activeScene.id) : [];
    moLayerSel = rest.length ? rest[0].id : null;
  };

  /* ---------- строки таймлайна ---------- */
  type TimelineRow =
    | { kind: "group"; id: string; label: string; color: string; count: number; left: number; width: number }
    | { kind: "layer"; id: string; layer: MotionCompLayer; on: boolean; open: boolean; glyph: string; left: number; width: number; keys: number[] }
    | { kind: "prop"; id: string; layer: MotionCompLayer; k: PropKey; label: string; value: string; animated: boolean; on: boolean; keys: number[] };

  const pct = (ms: number) => (total > 0 ? (ms / total) * 100 : 0);

  let timelineRows = $derived.by<TimelineRow[]>(() => {
    const rows: TimelineRow[] = [];
    const scene = activeScene;
    if (!scene) return rows;
    const b0 = scene.start;
    const order: MotionCompLayer["group"][] = [];
    sceneLayers.forEach((l) => {
      if (!order.includes(l.group)) order.push(l.group);
    });
    order.forEach((gk) => {
      const meta = groupMeta[gk] || { label: gk, color: "var(--dna-dim)" };
      const inGroup = sceneLayers.filter((l) => l.group === gk);
      rows.push({ kind: "group", id: `g-${gk}`, label: meta.label, color: meta.color, count: inGroup.length, left: pct(b0), width: pct(scene.duration) });
      inGroup.forEach((l) => {
        const on = selectedLayer?.id === l.id;
        const open = Boolean(moExpand[l.id]);
        const allKeys: number[] = [];
        propDefs.forEach((pd) => l.props[pd.k].keys.forEach((k) => {
          if (!allKeys.includes(k.t)) allKeys.push(k.t);
        }));
        allKeys.sort((a, b) => a - b);
        rows.push({
          kind: "layer", id: l.id, layer: l, on, open,
          glyph: l.type === "text" ? "T" : l.type === "image" ? "▣" : "◈",
          left: pct(b0), width: pct(scene.duration),
          keys: allKeys.map((t) => b0 + t),
        });
        if (open) {
          propDefs.forEach((pd) => {
            const raw = pd.dims === 2
              ? interpProp(l.props.p.keys, lt, 2, interpMode)
              : interpProp(l.props[pd.k].keys as Array<{ t: number; v: number }>, lt, 1, interpMode);
            const value = pd.dims === 2
              ? `${Math.round((raw as [number, number])[0])}, ${Math.round((raw as [number, number])[1])}`
              : pd.k === "r" ? `${Math.round(raw as number)}°` : (raw as number).toFixed(2);
            rows.push({
              kind: "prop", id: `${l.id}-${pd.k}`, layer: l, k: pd.k, label: pd.label, value,
              animated: l.props[pd.k].keys.length > 1,
              on: on && moPropSel === pd.k,
              keys: l.props[pd.k].keys.map((k) => b0 + k.t),
            });
          });
        }
      });
    });
    return rows;
  });

  let ticks = $derived.by(() => {
    if (total <= 0) return [] as Array<{ label: string; left: number }>;
    const stepS = Math.max(1, Math.ceil(total / 6000));
    const out: Array<{ label: string; left: number }> = [];
    for (let s = 0; s * 1000 <= total; s += stepS) out.push({ label: `${s}с`, left: pct(s * 1000) });
    return out;
  });

  const seekLane = (event: MouseEvent) => {
    const el = event.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    playing = false;
    playhead = clamp(((event.clientX - rect.left) / Math.max(1, rect.width)) * total, 0, total);
  };

  const seekKey = (event: MouseEvent, gt: number) => {
    event.stopPropagation();
    playing = false;
    playhead = clamp(gt, 0, total);
  };

  /* ---------- жизненный цикл ---------- */
  $effect(() => {
    if (playheadInitialized) return;
    playhead = scenes[data.selectedScene]?.start || 0;
    const first = sceneLayers[0];
    if (first) {
      moLayerSel = first.id;
      moExpand = { [first.id]: true };
    }
    playheadInitialized = true;
  });

  /* Превью: интервал 50мс (~20 к/с), стоп в конце — по README. */
  $effect(() => {
    if (!playing || total <= 0) return;
    const timer = window.setInterval(() => {
      const next = playhead + 50;
      if (next >= total) {
        playhead = total;
        playing = false;
        return;
      }
      playhead = next;
    }, 50);
    return () => window.clearInterval(timer);
  });

  /* Замер ячейки вьюера (moBox) — кадр вписывается по обеим осям. */
  $effect(() => {
    const el = stageEl;
    if (!el) return;
    const read = () => {
      const cs = getComputedStyle(el);
      const w = el.clientWidth - parseFloat(cs.paddingLeft || "0") - parseFloat(cs.paddingRight || "0");
      const h = el.clientHeight - parseFloat(cs.paddingTop || "0") - parseFloat(cs.paddingBottom || "0");
      untrack(() => {
        if (w > 20 && h > 20 && (!moBox || Math.abs(moBox.w - w) > 1 || Math.abs(moBox.h - h) > 1)) moBox = { w, h };
      });
    };
    const observer = new ResizeObserver(read);
    observer.observe(el);
    read();
    return () => observer.disconnect();
  });

  $effect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      const target = event.target as HTMLElement;
      if (!target.closest("input, textarea, select, [contenteditable=true]") && (event.ctrlKey || event.metaKey)
        && ["z", "y"].includes(event.key.toLowerCase())) {
        event.preventDefault(); event.stopPropagation();
        restoreLayers(event.shiftKey || event.key.toLowerCase() === "y");
      }
      if (event.code === "Space" && !event.repeat) {
        const tag = (event.target as HTMLElement | null)?.tagName || "";
        if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
        event.preventDefault();
        if (playhead >= total) playhead = 0;
        playing = !playing;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const selectScene = (index: number) => {
    const scene = scenes[index];
    if (!scene) return;
    playing = false;
    playhead = scene.start;
    $flow.setNodeData(nodeId, { selectedScene: index });
  };

  const updateScene = (patch: Partial<MotionSceneSettings>) => {
    if (!activeScene) return;
    const current = data.sceneSettings[activeScene.interactionSceneId] || {};
    $flow.setNodeData(nodeId, {
      sceneSettings: {
        ...data.sceneSettings,
        [activeScene.interactionSceneId]: { ...current, ...patch },
      },
    });
  };

  /* ---------- рендер / экспорт (существующая интеграция) ---------- */
  // Desktop: якорь href="/api/.../download" под file:// не работает (нет HTTP и
  // навигация закрыта политикой) — качаем через IPC и системный диалог сохранения.
  const desktopFiles = typeof window !== "undefined" ? window.designDNA?.files : undefined;
  const downloadVideo = async () => {
    if (!renderJob?.downloadUrl || !desktopFiles) return;
    const resp = await fetch(renderJob.downloadUrl);
    if (!resp.ok) return;
    const buf = new Uint8Array(await resp.arrayBuffer());
    let binary = "";
    for (let i = 0; i < buf.length; i += 32_768) binary += String.fromCharCode(...buf.subarray(i, i + 32_768));
    await desktopFiles.save(renderJob.filename || "motion.mp4", btoa(binary));
  };

  const startRender = async () => {
    if (!data.ir || !data.interaction || !data.motion || rendering) return;
    startingRender = true;
    const sourceRevision = $flow.getNodeIrRevision(nodeId);
    const sourcePage = $flow.activePageId;
    const isCurrent = () => useFlowStore.getState().activePageId === sourcePage && $flow.getNodeIrRevision(nodeId) === sourceRevision;
    const snapshot = JSON.parse(JSON.stringify(data)) as MotionNodeData;
    const layers = JSON.parse(JSON.stringify(baselineLayers)) as MotionCompLayer[];
    try {
      // Rebuild scene timing/format from the visible settings before export.
      const built = await api<{ motion: MotionNodeData["motion"] }>("/api/motion/build", {
        base_ir: snapshot.ir, interaction: snapshot.interaction, composition: snapshot.composition,
        scene_settings: snapshot.sceneSettings, render_settings: snapshot.renderSettings,
      });
      if (!built.motion) throw new Error("Не удалось собрать движение");
      if (!isCurrent()) throw new Error("Вход изменился — повторите рендер");
      $flow.setNodeData(nodeId, { motion: built.motion, layers, renderJob: null });
      let job = await api<MotionRenderJob>("/api/motion/render", {
        base_ir: snapshot.ir,
        interaction: snapshot.interaction,
        motion: built.motion,
        layers,
      });
      if (!isCurrent()) return;
      $flow.setNodeData(nodeId, { renderJob: job });
      const deadline = Date.now() + 15 * 60_000;
      while (job.status === "queued" || job.status === "rendering") {
        if (Date.now() > deadline) throw new Error("Рендер не завершился за 15 минут. Проверьте состояние сервера.");
        await new Promise((resolve) => window.setTimeout(resolve, 400));
        job = await apiGet<MotionRenderJob>(`/api/motion/render/${job.id}`);
        if (!isCurrent()) return;
        $flow.setNodeData(nodeId, { renderJob: job });
      }
      if (job.status === "complete") $flow.propagate(nodeId);
    } catch (error) {
      if (!isCurrent()) return;
      $flow.setNodeData(nodeId, {
        renderJob: {
          id: renderJob?.id || "failed",
          status: "error",
          progress: 0,
          error: error instanceof Error ? error.message : String(error),
        },
      });
    } finally {
      startingRender = false;
    }
  };
</script>

<div class="motion-workspace" role="dialog" aria-modal="true" aria-label="Motion Editor" use:bodyPortal>
  <header class="motion-topbar">
    <div class="motion-title">
      <span class="motion-m-icon">M</span>
      <strong>Motion Editor</strong>
      <span class="motion-comp-meta">{data.composition.width} × {data.composition.height} · {data.composition.fps} fps</span>
    </div>
    <div class="motion-transport">
      <button class="motion-jump" title="В начало" aria-label="В начало · Jump to start" onclick={() => { playing = false; playhead = 0; }}>|◀</button>
      <button class="motion-play" aria-label={playing ? "Pause" : "Play"} onclick={() => { if (playhead >= total) playhead = 0; playing = !playing; }}>{playing ? "❙❙" : "▶"}</button>
      <span class="motion-time">{formatTime(playhead)} / {formatTime(total)}</span>
    </div>
    <div class="motion-actions">
      <button disabled={rendering || !canUndo} onclick={() => restoreLayers()}>Отменить</button>
      <button disabled={rendering || !canRedo} onclick={() => restoreLayers(true)}>Повторить</button>
      <span class="motion-badge">Design IR</span>
      {#if rendering}<span class="motion-render-progress">Рендер {renderJob?.progress || 0}%</span>{/if}
      {#if renderJob?.status === "complete" && renderJob.downloadUrl}
        {#if desktopFiles}
          <button class="motion-download" onclick={downloadVideo}><span class="motion-desktop-label">Скачать {renderJob.result?.bytes ? formatBytes(renderJob.result.bytes) : "видео"}</span><span class="motion-mobile-label">Сохранить</span></button>
        {:else}
          <a class="motion-download" href={renderJob.downloadUrl} download={renderJob.filename}><span class="motion-desktop-label">Скачать {renderJob.result?.bytes ? formatBytes(renderJob.result.bytes) : "видео"}</span><span class="motion-mobile-label">Сохранить</span></a>
        {/if}
      {/if}
      <button class="motion-inspector-toggle" onclick={() => (inspectorOpen = !inspectorOpen)}>{inspectorOpen ? "Кадр" : "Инспектор"}</button>
      <button class="motion-close" title="Закрыть Motion Editor" onclick={onClose}>Закрыть</button>
      <button
        class="motion-export"
        aria-label={`Экспорт ${renderSettings.format.toUpperCase()} · Export ${renderSettings.format.toUpperCase()}`}
        disabled={busy || rendering || !data.motion}
        onclick={startRender}
      >{rendering ? "Экспортирую..." : `Экспорт ${renderSettings.format.toUpperCase()}`}</button>
    </div>
  </header>

  <div class="motion-main">
    <aside class="motion-project">
      <div class="motion-sec-title">ПРОЕКТ · ИЗ ПРЕДЫДУЩИХ НОД</div>
      <div class="motion-project-groups">
        {#each projectGroups as group (group.key)}
          <div class="motion-project-group">
            <div class="motion-project-head"><i style="background:{groupMeta[group.key].color}"></i><span>{groupMeta[group.key].label}</span></div>
            {#each group.items as item, i (group.key + "-" + i)}
              <button class="motion-project-item" title="Добавить слоем" onclick={() => addAssetLayer(item.name, group.key)}>
                <span class="motion-project-glyph" style="--group-color:{groupMeta[group.key].color}">◈</span>
                <span class="motion-project-name">{item.name}</span>
                <span class="motion-project-kind">{item.kind}</span>
              </button>
            {/each}
          </div>
        {/each}
        <div class="motion-project-group">
          <div class="motion-project-head"><i style="background:{groupMeta.media.color}"></i><span>{groupMeta.media.label}</span></div>
          {#each mediaLayers as layer (layer.id)}
            <button class="motion-project-item" onclick={() => (moLayerSel = layer.id)}>
              <span class="motion-project-glyph" style="--group-color:{groupMeta.media.color}">▣</span>
              <span class="motion-project-name">{layer.name}</span>
              <span class="motion-project-kind">слой</span>
            </button>
          {/each}
        </div>
      </div>
      <div class="motion-import">
        <button class="motion-dropzone" onclick={() => fileInput?.click()}>
          <span class="motion-dropzone-icon">↥</span>
          <strong>Импорт изображений</strong>
          <span>PNG, JPG, WebP → слой</span>
        </button>
        <input class="motion-file-input" type="file" multiple accept="image/*" bind:this={fileInput} onchange={onUpload} />
      </div>
    </aside>

    <section class="motion-center">
      <div class="motion-clips">
        {#each scenes as scene, index (scene.id)}
          <button class={index === activeIndex ? "active" : ""} onclick={() => selectScene(index)}>
            <strong>{String(index + 1).padStart(2, "0")}</strong>
            <span>{(scene.duration / 1000).toFixed(1)}s</span>
          </button>
        {/each}
      </div>

      <div class="motion-tools">
        {#each toolDefs as tool (tool.id)}
          <button class={moTool === tool.id ? "active" : ""} onclick={() => { moTool = tool.id; moPropSel = toolProp[tool.id]; }}>
            <span class="motion-tool-icon">{tool.icon}</span>{tool.label}
          </button>
        {/each}
        <span class="motion-tools-hint">Тяните слой в кадре — правка пишется в кейфрейм</span>
      </div>

      <div class="motion-stage" bind:this={stageEl}>
        <div class="motion-frame" style="width:{Math.round(stageW * fit)}px; height:{Math.round(stageH * fit)}px;">
          <div class="motion-frame-scale" style="font-family:Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#fff; width:{stageW}px; height:{stageH}px; transform:scale({fit});">
            <div class="motion-scene">
              {#each compositionFrame(data, baselineLayers, playhead) as frame (frame.layer.id)}
                {@const layer = frame.layer}
                {@const v = frame.values}
                <div
                  class="motion-layer {layer.type} {selectedLayer?.id === layer.id ? 'selected' : ''}"
                  style="left:{v.p[0]}px; top:{v.p[1]}px; width:{layer.w}px; transform:translate(-50%,-50%) scale({v.s}) rotate({v.r}deg); opacity:{v.o}; font-size:{layer.size}px; font-weight:{layer.weight}; color:{layer.color};"
                  role="button"
                  tabindex="-1"
                  onpointerdown={(event) => onLayerPointerDown(event, layer)}
                >
                  {#if layer.type === "text"}{layer.text}
                  {:else if layer.type === "image"}<span class="motion-layer-img" style="background-image:url({layer.src})"></span>
                  {:else}<span class="motion-layer-comp" style={COMP_CARD_STYLE}>{layer.name}</span>{/if}
                </div>
              {/each}
            </div>
          </div>
          <span class="motion-scene-badge">{String(activeIndex + 1).padStart(2, "0")} · Сцена</span>
        </div>
      </div>

      <footer class="motion-timeline">
        <div class="motion-timeline-head">
          <div class="motion-cols-label">СЛОИ И СВОЙСТВА</div>
          <div class="motion-timebar">
            <input
              aria-label="Motion playhead"
              type="range"
              min="0"
              max={Math.max(1, total)}
              step="10"
              value={Math.min(playhead, total)}
              oninput={(event) => { playing = false; playhead = Number(event.currentTarget.value); }}
            />
            <div class="motion-ruler">
              {#each ticks as tick (tick.label)}
                <span style="left:{tick.left}%">{tick.label}</span>
              {/each}
            </div>
          </div>
        </div>
        <div class="motion-rows">
          {#each timelineRows as row (row.kind + "-" + row.id)}
            {#if row.kind === "group"}
              <div class="motion-row motion-group-row">
                <div class="motion-row-name" style="color:{row.color}">{row.label} · {row.count}</div>
                <div class="motion-lane motion-group-lane" role="presentation" onclick={seekLane}>
                  <i class="motion-group-bar" style="left:{row.left}%; width:{row.width}%; --group-color:{row.color}"></i>
                  <i class="motion-playhead-line" style="left:{pct(playhead)}%"></i>
                </div>
              </div>
            {:else if row.kind === "layer"}
              <div class="motion-row motion-layer-row {row.on ? 'on' : ''}">
                <div class="motion-row-name motion-layer-name">
                  <button class="motion-twirl" onclick={() => (moExpand = { ...moExpand, [row.layer.id]: !moExpand[row.layer.id] })}>{row.open ? "▾" : "▸"}</button>
                  <button class="motion-layer-pick" onclick={() => (moLayerSel = row.layer.id)}>
                    <span class="motion-type-glyph">{row.glyph}</span>
                    <span class="motion-layer-label">{row.layer.name}</span>
                  </button>
                </div>
                <div class="motion-lane motion-layer-lane" role="presentation" onclick={seekLane}>
                  <i class="motion-layer-span" style="left:{row.left}%; width:{row.width}%"></i>
                  {#each row.keys as gt, i (i)}
                    <i class="motion-key" style="left:{pct(gt)}%" role="presentation" onclick={(event) => seekKey(event, gt)}></i>
                  {/each}
                  <i class="motion-playhead-line" style="left:{pct(playhead)}%"></i>
                </div>
              </div>
            {:else}
              <div class="motion-row motion-prop-row {row.on ? 'on' : ''}">
                <button class="motion-row-name motion-prop-name" onclick={() => { moLayerSel = row.layer.id; moPropSel = row.k; }}>
                  <i class="motion-stopwatch {row.animated ? 'animated' : ''}"></i>
                  <span class="motion-prop-label">{row.label}</span>
                  <span class="motion-prop-value">{row.value}</span>
                </button>
                <div class="motion-lane motion-prop-lane" role="presentation" onclick={seekLane}>
                  {#each row.keys as gt, i (i)}
                    <i class="motion-key small {row.on ? 'hot' : ''}" style="left:{pct(gt)}%" role="presentation" onclick={(event) => seekKey(event, gt)}></i>
                  {/each}
                  <i class="motion-playhead-line" style="left:{pct(playhead)}%"></i>
                </div>
              </div>
            {/if}
          {/each}
        </div>
      </footer>
    </section>

    <aside class={`motion-inspector ${inspectorOpen ? "open" : ""}`} inert={rendering}>
      <div class="motion-insp-head">
        <span class="motion-sec-title">СЛОЙ</span>
        <button class="motion-del-layer" onclick={delLayer}>Удалить</button>
      </div>
      <div class="motion-layer-chip">{selectedLayer ? selectedLayer.name : "—"}</div>

      <div class="motion-sec-title">ТРАНСФОРМАЦИЯ</div>
      <div class="motion-steppers">
        {#each transformRows as row (row.f)}
          <div class="motion-stepper">
            <span class="motion-stepper-k">{row.k}</span>
            <span class="motion-stepper-v">{row.v}</span>
            <button aria-label={`${row.k} −`} onclick={() => bump(row.f, -row.d)}>−</button>
            <button aria-label={`${row.k} +`} onclick={() => bump(row.f, row.d)}>+</button>
          </div>
        {/each}
      </div>

      <div class="motion-kf-card">
        <div class="motion-kf-title">Кейфреймы · {propLabel}</div>
        <div class="motion-kf-info">{keyInfo}</div>
        <div class="motion-kf-actions">
          <button class="motion-kf-add" onclick={addKey}>◆ Добавить</button>
          <button class="motion-kf-del" onclick={delKey}>Убрать</button>
        </div>
      </div>

      <div class="motion-divider"></div>
      <div class="motion-sec-title">КОМПОЗИЦИЯ</div>

      <div class="motion-chip-group">
        <div class="motion-chip-label">Кадр</div>
        <div class="motion-chips">
          <button class={data.composition.width > data.composition.height ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1920, height: 1080 } })}>16:9</button>
          <button class={data.composition.height > data.composition.width ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1920 } })}>9:16</button>
          <button class={data.composition.height === data.composition.width ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, width: 1080, height: 1080 } })}>1:1</button>
        </div>
      </div>
      <div class="motion-chip-group">
        <div class="motion-chip-label">Частота кадров</div>
        <div class="motion-chips">
          {#each [24, 30, 60] as fps (fps)}
            <button class={data.composition.fps === fps ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { composition: { ...data.composition, fps } })}>{fps} fps</button>
          {/each}
        </div>
      </div>
      <div class="motion-chip-group">
        <div class="motion-chip-label">Формат</div>
        <div class="motion-chips">
          <button class={renderSettings.format === "mp4" ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { renderSettings: { ...renderSettings, format: "mp4" }, renderJob: null })}>MP4 / H.264</button>
          <button class={renderSettings.format === "webm" ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { renderSettings: { ...renderSettings, format: "webm" }, renderJob: null })}>WebM / VP9</button>
        </div>
      </div>
      <div class="motion-chip-group">
        <div class="motion-chip-label">Качество</div>
        <div class="motion-chips">
          {#each [["draft", "Draft"], ["high", "High"], ["lossless", "Lossless"]] as [value, label] (value)}
            <button
              class={renderSettings.quality === value ? "active" : ""}
              onclick={() => $flow.setNodeData(nodeId, { renderSettings: { ...renderSettings, quality: value as "draft" | "high" | "lossless" }, renderJob: null })}
            >{label}</button>
          {/each}
        </div>
      </div>
      {#if renderJob?.status === "error"}<div class="motion-render-error">{renderJob.error || "Рендер не удался"}</div>{/if}

      <div class="motion-divider"></div>
      <div class="motion-sec-title">КОМПОЗИЦИЯ · {String(activeIndex + 1).padStart(2, "0")}</div>
      <label class="motion-field">Длительность · Duration, ms
        <input type="number" min="250" max="30000" value={data.sceneSettings[activeSourceId]?.duration ?? activeScene?.duration ?? 1200} oninput={(event) => updateScene({ duration: Number(event.currentTarget.value) })} />
      </label>
      <label class="motion-field">Переход · Transition
        <select value={data.sceneSettings[activeSourceId]?.transition ?? transition.type} onchange={(event) => updateScene({ transition: event.currentTarget.value as MotionSceneSettings["transition"] })}>
          <option value="cut">Cut</option>
          <option value="fade">Fade</option>
          <option value="slide-left">Slide left</option>
          <option value="slide-up">Slide up</option>
          <option value="zoom">Zoom</option>
        </select>
      </label>
      <label class="motion-field">Длительность перехода, мс
        <input type="number" min="0" max="30000" value={data.sceneSettings[activeSourceId]?.transitionDuration ?? transition.duration} oninput={(event) => updateScene({ transitionDuration: Number(event.currentTarget.value) })} />
      </label>
      <label class="motion-field">Easing
        <select value={data.sceneSettings[activeSourceId]?.easing ?? transition.easing} onchange={(event) => updateScene({ easing: event.currentTarget.value as MotionSceneSettings["easing"] })}>
          <option value="linear">Linear</option>
          <option value="ease">Ease</option>
          <option value="ease-in">Ease in</option>
          <option value="ease-out">Ease out</option>
          <option value="ease-in-out">Ease in/out</option>
        </select>
      </label>

      <button class="motion-apply" aria-label="Применить таймлайн · Apply timeline" disabled={busy} onclick={() => $flow.runNode(nodeId)}>{busy ? "Применяю..." : "Применить таймлайн"}</button>
    </aside>
  </div>
</div>
