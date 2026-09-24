import type { AnyNodeData, EditNodeData, MixNodeData, NodeType, PageNodeData, PortDecl, PortKind, SourceImportNodeData, TimelineNodeData } from "./types";

/* Зеркало NODE_DEFS (nodes.js:24-32), расширено дизайн-хендоффом
 * design_handoff_node_editor: sub — подзаголовок шапки, accent — цвет типа
 * (иконка, выделение, прогресс), ширины 300–334px по макету. */
export const NODE_DEFS: Record<NodeType, { title: string; icon: string; w: number; sub: string; accent: string }> = {
  prompt: { title: "Prompt", icon: "✎", w: 300, sub: "task text", accent: "#FF691D" },
  reference: { title: "Reference", icon: "▣", w: 300, sub: "lightweight style hint", accent: "#FF691D" },
  generator: { title: "Generator", icon: "◈", w: 322, sub: "LLM → IR variants", accent: "#9B5CFF" },
  edit: { title: "Editor (DNA)", icon: "⬚", w: 330, sub: "DNA editor", accent: "#35B8A0" },
  mix: { title: "Mix", icon: "⊕", w: 334, sub: "blend variants by weight", accent: "#9B5CFF" },
  page: { title: "Page", icon: "▤", w: 330, sub: "merge: page from blocks", accent: "#22C55E" },
  sourceimport: { title: "Source Import", icon: "⌁", w: 322, sub: "URL/screenshot → blocks + Source", accent: "#FF691D" },
  designui: { title: "Design UI (legacy)", icon: "UI", w: 380, sub: "legacy artifact", accent: "#35B8A0" },
  derive: { title: "Derive", icon: "↳", w: 310, sub: "related component", accent: "#9B5CFF" },
  reskin: { title: "Reskin", icon: "✦", w: 310, sub: "variant with locked structure", accent: "#9B5CFF" },
  qualitypass: { title: "Quality Pass", icon: "✓", w: 310, sub: "judge + repair + scorecard", accent: "#22C55E" },
  recorder: { title: "Interaction Recorder", icon: "REC", w: 334, sub: "IR actions → Interaction IR", accent: "#22C55E" },
  motion: { title: "Motion Editor", icon: "M", w: 322, sub: "Design IR → editable timeline", accent: "#E05FB0" },
  motiondesign: { title: "Motion Design", icon: "MD", w: 334, sub: "prompt / video → Seedance 2.5", accent: "#4F7CFF" },
  timeline: { title: "Video", icon: "▶", w: 350, sub: "page · prompt · timeline", accent: "#FF5F56" },
  pagebridge: { title: "Page Bridge", icon: "↔", w: 300, sub: "share a component between pages", accent: "#35B8A0" },
  designsystem: { title: "Design System / UI Kit", icon: "◈", w: 300, sub: "Source → UI Kit → publish", accent: "#9B5CFF" },
  image: { title: "Image", icon: "◐", w: 320, sub: "GPT Image · PNG / JPEG", accent: "#3FB950" },
  removebackground: { title: "Remove background", icon: "◒", w: 320, sub: "GPT Image · transparent PNG", accent: "#3FB950" },
};

/* Зеркало PORTS (nodes.js:35-48); у mix входы динамические — из data.inputs (portsOfNode),
 * у Source Import выходы динамические — из выбранных блоков (portsOfNode, docs/NODES.md) */
type RawPortDecl = Omit<PortDecl, "kinds"> & { kinds?: PortKind[] };
const RAW_PORTS: Record<NodeType, { in: RawPortDecl[]; out: RawPortDecl[] }> = {
  prompt: { in: [], out: [{ name: "out", label: "text", kind: "text" }] },
  reference: {
    in: [
      { name: "ir", label: "IR", kind: "ir" },
      { name: "image", label: "image", kind: "image" },
    ],
    out: [
      { name: "out", label: "style", kind: "text" },
      { name: "image", label: "image", kind: "image" },
      { name: "ir", label: "Reference IR", kind: "ir" },
    ],
  },
  generator: {
    in: [
      { name: "prompt", label: "Prompt", kind: "text", kinds: ["text"] },
      { name: "designSystem", label: "Design system", kind: "ds", kinds: ["ds"] },
      { name: "reference", label: "Reference", kind: "ir", kinds: ["ir", "text", "image"] },
    ],
    out: [{ name: "ir", label: "active variant", kind: "ir" }],
  },
  edit: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  mix: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
  page: { in: [], out: [{ name: "ir", label: "page", kind: "ir" }] },
  // Source Artifact enters as measured evidence. Consumption still happens
  // through project registry and DesignSystemPicker, so there is no output wire.
  // Best practice: wire Design system → Generator. Tokens out is for Reskin/Derive/Page only.
  designsystem: {
    in: [{ name: "artifact", label: "Source", kind: "artifact" }],
    out: [
      { name: "system", label: "Design system", kind: "ds" },
      { name: "tokens", label: "Tokens", kind: "tokens" },
    ],
  },
  sourceimport: { in: [], out: [
    { name: "artifact", label: "Source", kind: "artifact" },
    { name: "tokens", label: "Tokens", kind: "tokens" },
  ] },
  designui: {
    in: [{ name: "artifact", label: "Source", kind: "artifact" }],
    out: [{ name: "artifact", label: "Design UI", kind: "artifact" }],
  },
  derive: {
    in: [
      { name: "prompt", label: "task", kind: "text" },
      { name: "reference", label: "ref IR", kind: "ir" },
      { name: "tokens", label: "Tokens", kind: "tokens" },
    ],
    out: [{ name: "ir", label: "active variant", kind: "ir" }],
  },
  reskin: {
    in: [
      { name: "ir", label: "IR", kind: "ir" },
      { name: "tokens", label: "Tokens", kind: "tokens" },
    ],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  qualitypass: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "reviewed IR", kind: "ir" }],
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
      { name: "video", label: "rendered video", kind: "video" },
    ],
  },
  motiondesign: {
    in: [
      { name: "prompt", label: "prompt", kind: "text" },
      { name: "motion", label: "Motion IR", kind: "motion" },
      { name: "timeline", label: "Timeline IR", kind: "timeline" },
      { name: "video", label: "rendered video", kind: "video" },
    ],
    out: [{ name: "video", label: "Seedance video", kind: "video" }],
  },
  timeline: {
    in: [{ name: "ir", label: "Page", kind: "ir" }],
    out: [
      { name: "timeline", label: "timeline", kind: "timeline" },
      { name: "video", label: "rendered video", kind: "video" },
    ],
  },
  image: {
    in: [
      { name: "prompt", label: "Prompt", kind: "text" },
      { name: "reference", label: "reference", kind: "image" },
    ],
    out: [{ name: "image", label: "image", kind: "image" }],
  },
  removebackground: {
    in: [{ name: "image", label: "image", kind: "image" }],
    out: [{ name: "image", label: "transparent image", kind: "image" }],
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
  if (n.type === "timeline") {
    const data = n.data as TimelineNodeData | undefined;
    return { in: (data?.inputs || ["ir"]).map((name, i) => normalizePort({ name, label: data?.pageNames?.[name] || `Page ${i + 1}`, kind: "ir" })), out: PORTS.timeline.out };
  }
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
        normalizePort({ name: "tokens", label: "Tokens", kind: "tokens" }),
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
      return { mode: "url", url: "", image: null, fileName: "", mine: false, authenticatedSession: false, activeViewport: "desktop", previewMode: "reference", importedUrl: null, blocks: [], tokens: null, sourceArtifact: null, importProfile: "fast", aiRefine: true, aiProvider: "openai" };
    case "designui":
      return { artifact: null, selectedComponent: 0 };
    case "derive":
      return { provider: "openai", effort: "medium", prompt: "", count: 2, variants: [], active: 0 };
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
        inputs: ["ir"], pageNames: {}, sourcePages: [],
        prompt: "", provider: "codex", effort: "medium", revisions: [], activeRevisionId: null,
        ir: null, timeline: null,
        settings: { width: 1920, height: 1080, fps: 30, duration: 8000 },
        renderJob: null,
      };
    case "designsystem":
      return ({ systemId: null, name: "", status: "draft", revision: 0, summary: null,
               sourceNodeId: null, defaultSet: false, sourceUpdate: false, autoPublish: true } as unknown as AnyNodeData);
    case "image":
      return { engine: "raster", outputFormat: "png", prompt: "", style: "vector", width: 1024, height: 1024, tileable: false, provider: "codex", effort: "medium", variants: [], active: 0 };
    case "removebackground":
      return { image: null, fileName: "", prompt: "", variants: [], active: 0 };
    case "pagebridge":
      return { channel: "shared-component", mode: "send", ir: null };
  }
}

/* Меню «Создать ноду» по дизайн-хендоффу: стадии пайплайна с цветовым кодом.
 * Состав — реальный реестр CTX_ITEMS, сгруппированный (designui не создаётся). */
export const CTX_GROUPS: { label: string; color: string; items: { type: NodeType; note: string }[] }[] = [
  {
    label: "SOURCE",
    color: "#FF691D",
    items: [
      { type: "prompt", note: "task text" },
      { type: "reference", note: "lightweight style hint" },
      { type: "sourceimport", note: "URL/screenshot → blocks + DNA" },
      { type: "image", note: "GPT Image · PNG / JPEG" },
      { type: "removebackground", note: "remove background · transparent PNG" },
    ],
  },
  {
    label: "GENERATION",
    color: "#9B5CFF",
    items: [
      { type: "generator", note: "LLM → IR variants" },
      { type: "derive", note: "related component" },
      { type: "mix", note: "blend by weight" },
      { type: "reskin", note: "variant with locked structure" },
    ],
  },
  {
    label: "ASSEMBLY",
    color: "#35B8A0",
    items: [
      { type: "edit", note: "DNA editor" },
      { type: "page", note: "page from blocks" },
      { type: "pagebridge", note: "share a component between pages" },
    ],
  },
  {
    label: "QUALITY AND MOTION",
    color: "#22C55E",
    items: [
      // qualitypass снят с палитры: судья+починка встроены в прогон генератора
      // (легаси-графы с нодой Quality Pass по-прежнему загружаются).
      // recorder исключён из меню по хендоффу: Motion сам строит Interaction IR
      // из Design IR (легаси-графы с нодой Recorder по-прежнему загружаются).
      // Motion remains loadable for existing projects until lossless migration.
      { type: "timeline", note: "page → prompt → editable video" },
      { type: "motiondesign", note: "prompt / rendered video → Seedance 2.5" },
      { type: "designsystem", note: "Source → UI Kit → published Design System" },
    ],
  },
];

/* Зеркало CTX_ITEMS (nodes.js:1096-1104) — состав контекстного меню создания ноды */
export const CTX_ITEMS: { type: NodeType; note: string }[] = [
  { type: "prompt", note: "task text" },
  { type: "reference", note: "lightweight style hint" },
  { type: "generator", note: "LLM → IR variants" },
  { type: "sourceimport", note: "URL/screenshot → blocks + DNA" },
  { type: "image", note: "GPT Image · PNG / JPEG" },
  { type: "removebackground", note: "remove background · transparent PNG" },
  { type: "derive", note: "related component" },
  { type: "edit", note: "DNA editor" },
  { type: "mix", note: "blend by weight" },
  { type: "page", note: "page from blocks" },
  { type: "reskin", note: "variant with locked structure" },
  { type: "timeline", note: "page → prompt → editable video" },
  { type: "motiondesign", note: "prompt / rendered video -> Seedance 2.5" },
  { type: "pagebridge", note: "share a component between pages" },
  { type: "designsystem", note: "Source → UI Kit → published Design System" },
];
