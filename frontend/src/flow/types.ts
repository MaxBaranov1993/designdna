import type { Node } from "@xyflow/react";

// Типы данных кастомных нод графа. Фаза A: единственная нода — «Промпт».
export type PromptNodeData = { label: string; value: string };
export type PromptFlowNode = Node<PromptNodeData, "prompt">;

export type FlowNode = PromptFlowNode;
