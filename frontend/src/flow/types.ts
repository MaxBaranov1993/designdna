import type { Edge, Node } from "@xyflow/react";

/* Типы данных актуальных нод графа (см. docs/NODES.md).
 * Runtime-поля legacy (el/geo/history) в React Flow state не переносятся. */

/* kind tokens: design-токены из Source Import/Style DNA в Reskin/Derive. */
export type PortKind = "text" | "ir" | "tokens" | "interaction";

export type NodeType =
  | "prompt"
  | "reference"
  | "generator"
  | "edit"
  | "mix"
  | "page"
  | "sourceimport"
  | "styledna"
  | "derive"
  | "reskin"
  | "qualitypass"
  | "recorder"
  | "pagebridge";

export type IRObject = Record<string, unknown>;
export type SourceViewport = "desktop" | "tablet" | "mobile";
export type FeatureFlags = {
  irV11?: boolean;
  tailwindProjection?: boolean;
  fluidResponsive?: boolean;
  interactionRecorder?: boolean;
  motionEditor?: boolean;
  videoRender?: boolean;
  aiDirector?: boolean;
};

export type PromptNodeData = { text: string };
export type ReferenceNodeData = {
  brief: string;
  image: string | null;
  fileName: string;
  decomposed: boolean;
  // IR, полученный по проводу через propagate (runtime-поле legacy, nodes.js:957-963)
  ir?: IRObject | null;
};
export type GeneratorNodeData = {
  provider: string;
  count: number;
  ownPrompt: string;
  preset: string;
  variants: IRObject[];
  active: number;
};
export type EditNodeData = { ir: IRObject | null };
export type PageNodeData = { inputs: string[]; ir: IRObject | null; activeViewport: SourceViewport };
export type MixNodeData = {
  inputs: string[];
  weights: Record<string, number>;
  ir: IRObject | null;
};
/* Блок Source Import: lit — «зажжён» ли выходной порт блока. */
export type BlockParseBlock = {
  name: string;
  label?: string;
  kind?: string;
  selector: string;
  ir?: IRObject;
  error?: string;
  cached?: boolean;
  source?: "dom" | "llm" | "vision";
  layers?: number;
  size?: { width?: number; height?: number };
  preview?: string;
  previews?: Partial<Record<SourceViewport, string>>;
  sizes?: Partial<Record<SourceViewport, { width?: number; height?: number }>>;
  layersByViewport?: Partial<Record<SourceViewport, number>>;
  coverage?: Partial<Record<SourceViewport, number>>;
  fidelity?: Partial<Record<SourceViewport, number>>;
  warnings?: string[];
  repeat?: { count?: number; kind?: string } | null;
  lit: boolean;
};
export type SourceImportNodeData = {
  mode: "url" | "screenshot";
  url: string;
  image: string | null;
  fileName: string;
  mine: boolean;
  activeViewport: SourceViewport;
  previewMode: "reference" | "ir" | "compare";
  blocks: BlockParseBlock[];
  tokens: Record<string, unknown> | null;
};
export type StyleDnaNodeData = {
  tokens: Record<string, unknown> | null;
  summary: string;
};
export type DeriveNodeData = {
  prompt: string;
  count: number;
  variants: IRObject[];
  active: number;
};

/* Reskin: маска — что модели разрешено менять (merge-back лочит остальное) */
export type ReskinMask = {
  colors: boolean;
  fonts: boolean;
  radii: boolean;
  shadows: boolean;
  texts: boolean;
  images: boolean;
};
export type ReskinNodeData = {
  prompt: string;
  mask: ReskinMask;
  ir: IRObject | null;
  log: string[];
};
export type QualityPassNodeData = {
  brief: string;
  minScore: number;
  repair: boolean;
  ir: IRObject | null;
  result: Record<string, unknown> | null;
};
export type PageBridgeNodeData = {
  channel: string;
  mode: "send" | "receive";
  ir: IRObject | null;
};
export type InteractionObject = Record<string, unknown>;
export type InteractionDraftEvent = {
  id: string;
  time: number;
  type: "click" | "type" | "scroll" | "navigate" | "focus" | "blur" | "submit";
  targetSourceKey: string;
  payload: Record<string, unknown>;
  resultingSceneId: string;
};
export type InteractionDraftScene = {
  id: string;
  viewport: SourceViewport;
  patch: Array<{ op: "add" | "replace" | "remove"; path: string; value?: unknown }>;
};
export type RecorderNodeData = {
  ir: IRObject | null;
  interaction: InteractionObject | null;
  recording: boolean;
  selectedTarget: string;
  selectedPath: string;
  draftEvents: InteractionDraftEvent[];
  draftScenes: InteractionDraftScene[];
};

export type AnyNodeData =
  | PromptNodeData
  | ReferenceNodeData
  | GeneratorNodeData
  | EditNodeData
  | MixNodeData
  | PageNodeData
  | SourceImportNodeData
  | StyleDnaNodeData
  | DeriveNodeData
  | ReskinNodeData
  | QualityPassNodeData
  | RecorderNodeData
  | PageBridgeNodeData;

export type PromptFlowNode = Node<PromptNodeData, "prompt">;
export type ReferenceFlowNode = Node<ReferenceNodeData, "reference">;
export type GeneratorFlowNode = Node<GeneratorNodeData, "generator">;
export type EditFlowNode = Node<EditNodeData, "edit">;
export type MixFlowNode = Node<MixNodeData, "mix">;
export type PageFlowNode = Node<PageNodeData, "page">;
export type SourceImportFlowNode = Node<SourceImportNodeData, "sourceimport">;
export type StyleDnaFlowNode = Node<StyleDnaNodeData, "styledna">;
export type DeriveFlowNode = Node<DeriveNodeData, "derive">;
export type ReskinFlowNode = Node<ReskinNodeData, "reskin">;
export type QualityPassFlowNode = Node<QualityPassNodeData, "qualitypass">;
export type RecorderFlowNode = Node<RecorderNodeData, "recorder">;
export type PageBridgeFlowNode = Node<PageBridgeNodeData, "pagebridge">;

export type FlowNode =
  | PromptFlowNode
  | ReferenceFlowNode
  | GeneratorFlowNode
  | EditFlowNode
  | MixFlowNode
  | PageFlowNode
  | SourceImportFlowNode
  | StyleDnaFlowNode
  | DeriveFlowNode
  | ReskinFlowNode
  | QualityPassFlowNode
  | RecorderFlowNode
  | PageBridgeFlowNode;

/* Ребро RF: id строится по формату из спеки — e<from.node>:<from.port>-<to.node>:<to.port> */
export type FlowEdge = Edge;

/* Legacy-формат designai-graph-v1: id числовые, рёбра с вложенными from/to.
 * Конвертация в типы RF (строковые id) — только в рантайме. */
export type LegacyView = { x: number; y: number; zoom: number };
export type LegacyEdgeEndpoint = { node: number; port: string };
export type LegacyNodePayload = {
  id: number;
  type: NodeType;
  x: number;
  y: number;
  data: AnyNodeData;
};
export type LegacyEdgePayload = {
  from: LegacyEdgeEndpoint;
  to: LegacyEdgeEndpoint;
};
export type LegacyGraphPayload = {
  nodes: LegacyNodePayload[];
  edges: LegacyEdgePayload[];
  view: LegacyView;
  nextId?: number;
};

export type FlowPage = {
  id: string;
  name: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
};
