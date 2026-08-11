import type { AnyNodeData, MixNodeData, NodeType, PageNodeData, PortKind, SourceImportNodeData } from "./types";

export type PortDecl = { name: string; label: string; kind: PortKind };

/* Зеркало NODE_DEFS (nodes.js:24-32) */
export const NODE_DEFS: Record<NodeType, { title: string; icon: string; w: number }> = {
  prompt: { title: "Промпт", icon: "✎", w: 260 },
  reference: { title: "Референс", icon: "▣", w: 270 },
  generator: { title: "Генератор", icon: "◈", w: 300 },
  edit: { title: "Редактор (DNA)", icon: "⬚", w: 430 },
  mix: { title: "Микс", icon: "⊕", w: 290 },
  page: { title: "Страница", icon: "▤", w: 340 },
  sourceimport: { title: "Source Import", icon: "⌁", w: 360 },
  styledna: { title: "Style DNA", icon: "◇", w: 320 },
  derive: { title: "Derive", icon: "↳", w: 330 },
  reskin: { title: "Reskin", icon: "✦", w: 340 },
  qualitypass: { title: "Quality Pass", icon: "✓", w: 350 },
  recorder: { title: "Interaction Recorder", icon: "REC", w: 390 },
  pagebridge: { title: "Page Bridge", icon: "↔", w: 300 },
};

/* Зеркало PORTS (nodes.js:35-48); у mix входы динамические — из data.inputs (portsOfNode),
 * у Source Import выходы динамические — из выбранных блоков (portsOfNode, docs/NODES.md) */
export const PORTS: Record<NodeType, { in: PortDecl[]; out: PortDecl[] }> = {
  prompt: { in: [], out: [{ name: "out", label: "текст", kind: "text" }] },
  reference: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "out", label: "стиль", kind: "text" }],
  },
  generator: {
    in: [
      { name: "prompt", label: "промт", kind: "text" },
      { name: "style", label: "стиль", kind: "text" },
      { name: "tokens", label: "style DNA", kind: "tokens" },
    ],
    out: [{ name: "ir", label: "варианты", kind: "ir" }],
  },
  edit: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  mix: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
  page: { in: [], out: [{ name: "ir", label: "страница", kind: "ir" }] },
  sourceimport: { in: [], out: [{ name: "tokens", label: "style DNA", kind: "tokens" }] },
  styledna: {
    in: [
      { name: "ir", label: "IR", kind: "ir" },
      { name: "tokens", label: "tokens", kind: "tokens" },
    ],
    out: [
      { name: "tokens", label: "style DNA", kind: "tokens" },
      { name: "summary", label: "summary", kind: "text" },
    ],
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
  pagebridge: {
    in: [{ name: "ir", label: "component", kind: "ir" }],
    out: [{ name: "ir", label: "component", kind: "ir" }],
  },
};

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
      in: inputs.map((name) => ({ name, label: name, kind: "ir" as PortKind })),
      out: PORTS.mix.out,
    };
  }
  if (n.type === "page") {
    const inputs = (n.data as PageNodeData | undefined)?.inputs || [];
    return {
      in: [
        { name: "tokens", label: "style DNA", kind: "tokens" as PortKind },
        ...inputs.map((name) => ({ name, label: name, kind: "ir" as PortKind })),
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
        ...lit.map((b) => ({ name: b.name, label: b.name, kind: "ir" as PortKind })),
        ...PORTS.sourceimport.out,
      ],
    };
  }
  return PORTS[n.type];
}

/* Каждая AI-нода идёт через OpenRouter в закреплённую роль ROUTING.
 * Прямой выбор провайдера в UI убран: он создавал расхождение с модельной картой. */
export function defaultData(type: NodeType): AnyNodeData {
  switch (type) {
    case "prompt":
      return { text: "" };
    case "reference":
      return { brief: "", image: null, fileName: "", decomposed: false };
    case "generator":
      return { provider: "openrouter", count: 2, ownPrompt: "", preset: "", variants: [], active: 0 };
    case "edit":
      return { ir: null };
    case "mix":
      return { inputs: ["a", "b"], weights: { a: 70, b: 30 }, ir: null };
    case "page":
      return { inputs: ["a", "b"], ir: null, activeViewport: "desktop" };
    case "sourceimport":
      return { mode: "url", url: "", image: null, fileName: "", mine: false, activeViewport: "desktop", previewMode: "reference", blocks: [], tokens: null };
    case "styledna":
      return { tokens: null, summary: "" };
    case "derive":
      return { prompt: "", count: 2, variants: [], active: 0 };
    case "reskin":
      return {
        prompt: "",
        mask: { colors: true, fonts: true, radii: true, shadows: true, texts: false, images: false },
        ir: null,
        log: [],
      };
    case "qualitypass":
      return { brief: "", minScore: 85, repair: true, ir: null, result: null };
    case "recorder":
      return { ir: null, interaction: null, recording: false, selectedTarget: "", selectedPath: "", draftEvents: [], draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }] };
    case "pagebridge":
      return { channel: "shared-component", mode: "send", ir: null };
  }
}

/* Зеркало CTX_ITEMS (nodes.js:1096-1104) — состав контекстного меню создания ноды */
export const CTX_ITEMS: { type: NodeType; note: string }[] = [
  { type: "prompt", note: "текст задачи" },
  { type: "reference", note: "лёгкая стилевая подсказка" },
  { type: "generator", note: "LLM → варианты IR" },
  { type: "sourceimport", note: "URL/скрин → блоки + DNA" },
  { type: "styledna", note: "палитра, шрифты, отступы" },
  { type: "derive", note: "родственный компонент" },
  { type: "edit", note: "DNA-редактор" },
  { type: "mix", note: "смешение по весам" },
  { type: "page", note: "страница из блоков" },
  { type: "reskin", note: "вариант с локом структуры" },
  { type: "qualitypass", note: "judge + repair + scorecard" },
  { type: "recorder", note: "IR actions -> Interaction IR" },
  { type: "pagebridge", note: "передать компонент между страницами" },
];
