import type { AnyNodeData, EditNodeData, MixNodeData, NodeType, PageNodeData, PortDecl, PortKind, SourceImportNodeData } from "./types";

/* Зеркало NODE_DEFS (nodes.js:24-32), расширено дизайн-хендоффом
 * design_handoff_node_editor: sub — подзаголовок шапки, accent — цвет типа
 * (иконка, выделение, прогресс), ширины 300–334px по макету. */
export const NODE_DEFS: Record<NodeType, { title: string; icon: string; w: number; sub: string; accent: string }> = {
  prompt: { title: "Промпт", icon: "✎", w: 300, sub: "текст задачи", accent: "#FF691D" },
  reference: { title: "Референс", icon: "▣", w: 300, sub: "лёгкая стилевая подсказка", accent: "#FF691D" },
  generator: { title: "Генератор", icon: "◈", w: 322, sub: "LLM → варианты IR", accent: "#9B5CFF" },
  edit: { title: "Редактор (DNA)", icon: "⬚", w: 330, sub: "DNA-редактор", accent: "#35B8A0" },
  mix: { title: "Микс", icon: "⊕", w: 334, sub: "смешение вариантов по весам", accent: "#9B5CFF" },
  page: { title: "Страница", icon: "▤", w: 330, sub: "merge: страница из блоков", accent: "#22C55E" },
  sourceimport: { title: "Source Import", icon: "⌁", w: 322, sub: "URL/скрин → блоки + DNA", accent: "#FF691D" },
  designui: { title: "Design UI (legacy)", icon: "UI", w: 380, sub: "legacy-артефакт", accent: "#35B8A0" },
  derive: { title: "Derive", icon: "↳", w: 310, sub: "родственный компонент", accent: "#9B5CFF" },
  reskin: { title: "Reskin", icon: "✦", w: 310, sub: "вариант с локом структуры", accent: "#9B5CFF" },
  qualitypass: { title: "Quality Pass", icon: "✓", w: 310, sub: "judge + repair + scorecard", accent: "#22C55E" },
  recorder: { title: "Interaction Recorder", icon: "REC", w: 334, sub: "IR actions → Interaction IR", accent: "#22C55E" },
  motion: { title: "Motion Editor", icon: "M", w: 322, sub: "Design IR → editable timeline", accent: "#E05FB0" },
  motiondesign: { title: "Motion Design", icon: "MD", w: 334, sub: "prompt / video → Seedance 2.5", accent: "#4F7CFF" },
  timeline: { title: "Video Editor", icon: "▶", w: 322, sub: "слои и кейфреймы → локальный ролик", accent: "#FF5F56" },
  pagebridge: { title: "Page Bridge", icon: "↔", w: 300, sub: "передать компонент между страницами", accent: "#35B8A0" },
  designsystem: { title: "Design System / UI Kit", icon: "◈", w: 300, sub: "Source → published DS", accent: "#9B5CFF" },
};

/* Зеркало PORTS (nodes.js:35-48); у mix входы динамические — из data.inputs (portsOfNode),
 * у Source Import выходы динамические — из выбранных блоков (portsOfNode, docs/NODES.md) */
type RawPortDecl = Omit<PortDecl, "kinds"> & { kinds?: PortKind[] };
const RAW_PORTS: Record<NodeType, { in: RawPortDecl[]; out: RawPortDecl[] }> = {
  prompt: { in: [], out: [{ name: "out", label: "текст", kind: "text" }] },
  reference: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "out", label: "стиль", kind: "text" }],
  },
  generator: {
    in: [
      { name: "prompt", label: "Промт", kind: "text", kinds: ["text"] },
      { name: "designSystem", label: "Дизайн-система", kind: "ds", kinds: ["ds", "tokens"] },
      { name: "reference", label: "Референс", kind: "ir", kinds: ["ir", "text"] },
    ],
    out: [{ name: "ir", label: "варианты", kind: "ir" }],
  },
  edit: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  mix: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
  page: { in: [], out: [{ name: "ir", label: "страница", kind: "ir" }] },
  // Source Artifact enters as measured evidence. Consumption still happens
  // through project registry and DesignSystemPicker, so there is no output wire.
  // Design System заменил отдельную ноду Style DNA: токены системы уходят
  // проводом так же, как раньше уходили из неё. Потребление через реестр и
  // DesignSystemPicker сохраняется — выход не заменяет их, а дополняет.
  designsystem: {
    in: [{ name: "artifact", label: "Source Artifact", kind: "artifact" }],
    out: [
      { name: "system", label: "ДС", kind: "ds" },
      { name: "tokens", label: "style DNA", kind: "tokens" },
    ],
  },
  sourceimport: { in: [], out: [
    { name: "artifact", label: "Source Artifact", kind: "artifact" },
    { name: "tokens", label: "style DNA", kind: "tokens" },
  ] },
  designui: {
    in: [{ name: "artifact", label: "Source Artifact", kind: "artifact" }],
    out: [{ name: "artifact", label: "Design UI", kind: "artifact" }],
  },
  derive: {
    in: [
      { name: "prompt", label: "что сделать", kind: "text" },
      { name: "reference", label: "ref IR", kind: "ir" },
      { name: "tokens", label: "style DNA", kind: "tokens" },
    ],
    out: [{ name: "ir", label: "варианты", kind: "ir" }],
  },
  reskin: {
    in: [
      { name: "ir", label: "IR", kind: "ir" },
      { name: "tokens", label: "токены", kind: "tokens" },
    ],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  qualitypass: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "проверенный IR", kind: "ir" }],
  },
  recorder: {
    in: [{ name: "ir", label: "Design IR", kind: "ir" }],
    out: [{ name: "interaction", label: "Interaction IR", kind: "interaction" }],
  },
  motion: {
    in: [
      { name: "ir", label: "Design IR", kind: "ir" },
      { name: "interaction", label: "Interaction IR", kind: "interaction" },
    ],
    out: [
      { name: "motion", label: "Motion IR", kind: "motion" },
      { name: "video", label: "готовое видео", kind: "video" },
    ],
  },
  motiondesign: {
    in: [
      { name: "prompt", label: "промпт", kind: "text" },
      { name: "motion", label: "Motion IR", kind: "motion" },
      { name: "timeline", label: "Timeline IR", kind: "timeline" },
      { name: "video", label: "готовое видео", kind: "video" },
    ],
    out: [{ name: "video", label: "Seedance video", kind: "video" }],
  },
  timeline: {
    in: [{ name: "ir", label: "Design IR", kind: "ir" }],
    out: [
      { name: "timeline", label: "Timeline IR", kind: "timeline" },
      { name: "video", label: "готовое видео", kind: "video" },
    ],
  },
  pagebridge: {
    in: [{ name: "ir", label: "component", kind: "ir" }],
    out: [{ name: "ir", label: "component", kind: "ir" }],
  },
};

const normalizePort = (p: RawPortDecl): PortDecl => ({
  ...p,
  kinds: [p.kind, ...(p.kinds || []).filter((kind) => kind !== p.kind)],
});
export const PORTS = Object.fromEntries(Object.entries(RAW_PORTS).map(([type, ports]) => [type, {
  in: ports.in.map(normalizePort),
  out: ports.out.map(normalizePort),
}])) as Record<NodeType, { in: PortDecl[]; out: PortDecl[] }>;

/* Зеркало portsOf (nodes.js:77-83): у mix входы строятся из data.inputs, все kind "ir";
 * у Source Import выходы — по именам зажжённых блоков (lit, handle id = имя блока) +
 * постоянный порт tokens (решение владельца 9). */
export function portsOfNode(n: {
  type: NodeType;
  data?: AnyNodeData;
}): { in: PortDecl[]; out: PortDecl[] } {
  if (n.type === "mix") {
    const inputs = (n.data as MixNodeData | undefined)?.inputs || [];
    return {
      in: inputs.map((name) => normalizePort({ name, label: name, kind: "ir" })),
      out: PORTS.mix.out,
    };
  }
  if (n.type === "edit") {
    const inputs = (n.data as EditNodeData | undefined)?.inputs || ["ir"];
    return {
      in: inputs.map((name) => normalizePort({ name, label: name, kind: "ir" })),
      out: PORTS.edit.out,
    };
  }
  if (n.type === "page") {
    const inputs = (n.data as PageNodeData | undefined)?.inputs || [];
    return {
      in: [
        normalizePort({ name: "tokens", label: "style DNA", kind: "tokens" }),
        ...inputs.map((name) => normalizePort({ name, label: name, kind: "ir" })),
      ],
      out: PORTS.page.out,
    };
  }
  if (n.type === "sourceimport") {
    const blocks = (n.data as SourceImportNodeData | undefined)?.blocks || [];
    const lit = blocks.filter((b) => b.lit && !b.error);
    return {
      in: PORTS.sourceimport.in,
      out: [
        ...lit.map((b) => normalizePort({ name: b.name, label: b.name, kind: "ir" })),
        ...PORTS.sourceimport.out,
      ],
    };
  }
  return PORTS[n.type];
}

/* AI-ноды хранят выбранного провайдера (Sol / Codex / Claude) и усилие. */
export function defaultData(type: NodeType): AnyNodeData {
  switch (type) {
    case "prompt":
      return { text: "" };
    case "reference":
      return { brief: "", image: null, fileName: "", decomposed: false };
    case "generator":
      return { provider: "openai", effort: "medium", count: 2, ownPrompt: "", preset: "", variants: [], active: 0 };
    case "edit":
      return { inputs: ["a", "b"], ir: null, sourceRegistry: {}, nodeSources: {} };
    case "mix":
      return { inputs: ["a", "b"], weights: { a: 70, b: 30 }, variants: 3, prompt: "", mixVariants: [], mixActive: 0, ir: null };
    case "page":
      return { inputs: ["a", "b"], ir: null, activeViewport: "desktop" };
    case "sourceimport":
      /* Дизайн-хендофф: AI-уточнение включено по умолчанию (чекбокс из ноды убран). */
      return { mode: "url", url: "", image: null, fileName: "", mine: false, authenticatedSession: false, activeViewport: "desktop", previewMode: "reference", importedUrl: null, blocks: [], tokens: null, sourceArtifact: null, aiRefine: true, aiProvider: "openai" };
    case "designui":
      return { artifact: null, selectedComponent: 0 };
    case "derive":
      return { prompt: "", count: 2, variants: [], active: 0 };
    case "reskin":
      return {
        prompt: "",
        provider: "openai",
        effort: "medium",
        mask: { colors: true, fonts: true, radii: true, shadows: true, texts: false, images: false },
        ir: null,
        log: [],
      };
    case "qualitypass":
      return { brief: "", minScore: 85, repair: true, provider: "openai", ir: null, result: null };
    case "recorder":
      return {
        ir: null, interaction: null, recording: false, selectedTarget: "", selectedPath: "",
        draftEvents: [], draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }],
        mode: "preview", liveUrl: "", mine: false, liveViewport: "desktop",
      };
    case "motion":
      return {
        ir: null, interaction: null,
        scenes: [{ id: "scene-0", viewport: "desktop", patch: [] }],
        motion: null, sceneIrs: [], selectedScene: 0,
        composition: { width: 1920, height: 1080, fps: 30 },
        renderSettings: { format: "mp4", quality: "high" }, renderJob: null, sceneSettings: {},
      };
    case "motiondesign":
      return {
        prompt: "", plannedPrompt: "", planner: "direct", effort: "high", inputMode: "auto",
        settings: { duration: 8, aspectRatio: "16:9", resolution: "720p", generateAudio: false, seed: null },
        sourceMotion: null, sourceTimeline: null, sourceVideo: null, job: null, video: null,
      };
    case "timeline":
      return {
        ir: null, timeline: null,
        settings: { width: 1920, height: 1080, fps: 30, duration: 8000 },
        renderJob: null,
      };
    case "designsystem":
      return ({ systemId: null, name: "", status: "draft", revision: 0, summary: null,
               sourceNodeId: null, defaultSet: false, sourceUpdate: false, autoPublish: true } as unknown as AnyNodeData);
    case "pagebridge":
      return { channel: "shared-component", mode: "send", ir: null };
  }
}

/* Меню «Создать ноду» по дизайн-хендоффу: стадии пайплайна с цветовым кодом.
 * Состав — реальный реестр CTX_ITEMS, сгруппированный (designui не создаётся). */
export const CTX_GROUPS: { label: string; color: string; items: { type: NodeType; note: string }[] }[] = [
  {
    label: "ИСТОЧНИК",
    color: "#FF691D",
    items: [
      { type: "prompt", note: "текст задачи" },
      { type: "reference", note: "лёгкая стилевая подсказка" },
      { type: "sourceimport", note: "URL/скрин → блоки + DNA" },
    ],
  },
  {
    label: "ГЕНЕРАЦИЯ",
    color: "#9B5CFF",
    items: [
      { type: "generator", note: "LLM → варианты IR" },
      { type: "derive", note: "родственный компонент" },
      { type: "mix", note: "смешение по весам" },
      { type: "reskin", note: "вариант с локом структуры" },
    ],
  },
  {
    label: "СБОРКА",
    color: "#35B8A0",
    items: [
      { type: "edit", note: "DNA-редактор" },
      { type: "page", note: "страница из блоков" },
      { type: "pagebridge", note: "передать компонент между страницами" },
    ],
  },
  {
    label: "КОНТРОЛЬ И ДВИЖЕНИЕ",
    color: "#22C55E",
    items: [
      // qualitypass снят с палитры: судья+починка встроены в прогон генератора
      // (легаси-графы с нодой Quality Pass по-прежнему загружаются).
      // recorder исключён из меню по хендоффу: Motion сам строит Interaction IR
      // из Design IR (легаси-графы с нодой Recorder по-прежнему загружаются).
      { type: "motion", note: "Design IR → editable timeline" },
      { type: "timeline", note: "компоненты → слои, кейфреймы и локальный ролик" },
      { type: "motiondesign", note: "prompt / готовое видео → Seedance 2.5" },
      { type: "designsystem", note: "Source → UI Kit → published Design System" },
    ],
  },
];

/* Зеркало CTX_ITEMS (nodes.js:1096-1104) — состав контекстного меню создания ноды */
export const CTX_ITEMS: { type: NodeType; note: string }[] = [
  { type: "prompt", note: "текст задачи" },
  { type: "reference", note: "лёгкая стилевая подсказка" },
  { type: "generator", note: "LLM → варианты IR" },
  { type: "sourceimport", note: "URL/скрин → блоки + DNA" },
  { type: "derive", note: "родственный компонент" },
  { type: "edit", note: "DNA-редактор" },
  { type: "mix", note: "смешение по весам" },
  { type: "page", note: "страница из блоков" },
  { type: "reskin", note: "вариант с локом структуры" },
  { type: "motion", note: "Design IR -> editable timeline" },
  { type: "timeline", note: "компоненты -> ролик: слои и кейфреймы" },
  { type: "motiondesign", note: "prompt / готовое видео -> Seedance 2.5" },
  { type: "pagebridge", note: "передать компонент между страницами" },
  { type: "designsystem", note: "Source → UI Kit → published Design System" },
];
