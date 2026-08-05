import type { Edge, Node } from "@xyflow/react";

/* Типы данных нод — зеркало defaultData() из legacy nodes.js:266-275
 * (provider у клона объявлен явно, см. FLOW-MIGRATION.md §1.6).
 * Runtime-поля legacy (el/geo/history) в новый UI не переносятся. */

export type PortKind = "text" | "ir";

export type NodeType =
  | "prompt"
  | "reference"
  | "generator"
  | "edit"
  | "mix"
  | "clone"
  | "reproduce";

export type IRObject = Record<string, unknown>;

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
  variants: IRObject[];
  active: number;
};
export type EditNodeData = { ir: IRObject | null };
export type MixNodeData = {
  inputs: string[];
  weights: Record<string, number>;
  ir: IRObject | null;
};
export type CloneNodeData = {
  url: string;
  component: string;
  provider: string;
  ir: IRObject | null;
};
export type ReproduceNodeData = {
  image: string | null;
  fileName: string;
  url: string;
  provider: string;
  result: Record<string, unknown> | null;
};

export type AnyNodeData =
  | PromptNodeData
  | ReferenceNodeData
  | GeneratorNodeData
  | EditNodeData
  | MixNodeData
  | CloneNodeData
  | ReproduceNodeData;

export type PromptFlowNode = Node<PromptNodeData, "prompt">;
export type ReferenceFlowNode = Node<ReferenceNodeData, "reference">;
export type GeneratorFlowNode = Node<GeneratorNodeData, "generator">;
export type EditFlowNode = Node<EditNodeData, "edit">;
export type MixFlowNode = Node<MixNodeData, "mix">;
export type CloneFlowNode = Node<CloneNodeData, "clone">;
export type ReproduceFlowNode = Node<ReproduceNodeData, "reproduce">;

export type FlowNode =
  | PromptFlowNode
  | ReferenceFlowNode
  | GeneratorFlowNode
  | EditFlowNode
  | MixFlowNode
  | CloneFlowNode
  | ReproduceFlowNode;

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
