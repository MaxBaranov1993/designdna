import { pullInput } from "./dataflow";
import { inputFingerprint } from "./fingerprint";
import { generatorVisualReference } from "./generator-visual";
import type { FlowNode, FlowEdge, GeneratorNodeData } from "./types";

/** Only effective inputs, never output variants, viewport or canvas selection. */
export function generatorInputKey(nodes: FlowNode[], edges: FlowEdge[], node: FlowNode, picker: unknown, ignoreDesignSystem = false, ignoreAssetSettings = false): string {
  const data = node.data as GeneratorNodeData;
  return inputFingerprint({
    brief: String(pullInput(nodes, edges, node, "prompt") || data.ownPrompt || "").trim(),
    reference: pullInput(nodes, edges, node, "reference"),
    visualReference: generatorVisualReference(nodes, edges, node), conceptMode: data.conceptMode,
    designSystem: ignoreDesignSystem ? null : pullInput(nodes, edges, node, "designSystem"),
    provider: data.provider, effort: data.effort, count: data.count,
    assetMode: ignoreAssetSettings ? undefined : data.assetMode, assetModel: ignoreAssetSettings ? undefined : data.assetModel,
    assetConsistency: ignoreAssetSettings ? undefined : data.assetConsistency,
    surface: data.surface, designStyle: data.designStyle, preset: data.preset,
    selectedDirection: (data as Record<string, unknown>).selectedDirection,
    designSystemSelection: (data as Record<string, unknown>).designSystemSelection,
    designSystemUsageMode: data.designSystemUsageMode,
    picker,
  });
}
