import type { AnyNodeData, MixNodeData, NodeType, PortKind } from "./types";

export type PortDecl = { name: string; label: string; kind: PortKind };

/* Зеркало NODE_DEFS (nodes.js:24-32) */
export const NODE_DEFS: Record<NodeType, { title: string; icon: string; w: number }> = {
  prompt: { title: "Промпт", icon: "✎", w: 260 },
  reference: { title: "Референс", icon: "▣", w: 270 },
  generator: { title: "Генератор", icon: "◈", w: 300 },
  edit: { title: "Редактор (DNA)", icon: "⬚", w: 780 },
  mix: { title: "Микс", icon: "⊕", w: 290 },
  clone: { title: "Клон (сайт)", icon: "", w: 310 },
  reproduce: { title: "Reproduce (pixel)", icon: "◎", w: 340 },
};

/* Зеркало PORTS (nodes.js:35-48); у mix входы динамические — из data.inputs (portsOfNode) */
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
    ],
    out: [{ name: "ir", label: "варианты", kind: "ir" }],
  },
  edit: {
    in: [{ name: "ir", label: "IR", kind: "ir" }],
    out: [{ name: "ir", label: "IR", kind: "ir" }],
  },
  mix: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
  clone: { in: [], out: [{ name: "ir", label: "IR", kind: "ir" }] },
  reproduce: {
    in: [],
    out: [
      { name: "ir", label: "IR", kind: "ir" },
      { name: "html", label: "HTML", kind: "text" },
      { name: "diff", label: "diff", kind: "text" },
    ],
  },
};

/* Зеркало portsOf (nodes.js:77-83): у mix входы строятся из data.inputs, все kind "ir" */
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
  return PORTS[n.type];
}

/* Зеркало defaultData (nodes.js:266-275); provider у clone объявлен явно */
export function defaultData(type: NodeType): AnyNodeData {
  switch (type) {
    case "prompt":
      return { text: "" };
    case "reference":
      return { brief: "", image: null, fileName: "", decomposed: false };
    case "generator":
      return { provider: "qwen", count: 2, ownPrompt: "", variants: [], active: 0 };
    case "edit":
      return { ir: null };
    case "mix":
      return { inputs: ["a", "b"], weights: { a: 70, b: 30 }, ir: null };
    case "clone":
      return { url: "", component: "", provider: "qwen", ir: null };
    case "reproduce":
      return { image: null, fileName: "", url: "", provider: "qwen", result: null };
  }
}

/* Зеркало CTX_ITEMS (nodes.js:1096-1104) — состав контекстного меню создания ноды */
export const CTX_ITEMS: { type: NodeType; note: string }[] = [
  { type: "prompt", note: "текст задачи" },
  { type: "reference", note: "изображение + стиль" },
  { type: "generator", note: "LLM → варианты IR" },
  { type: "edit", note: "DNA-редактор" },
  { type: "mix", note: "смешение по весам" },
  { type: "clone", note: "клон с сайта по URL" },
  { type: "reproduce", note: "pixel-perfect из скриншота" },
];
