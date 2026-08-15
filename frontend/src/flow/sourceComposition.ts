import { composePage } from "./compose";
import { deepClone, outValue } from "./dataflow";
import type {
  FlowEdge,
  FlowNode,
  IRObject,
  ParserSourceEnvelope,
  SourceRecordView,
  SourceViewport,
} from "./types";

export type SourceCompositionMeta = {
  sourceRegistry: Record<string, SourceRecordView>;
  nodeSources: Record<string, string>;
};

export type SourceInputBlock = SourceCompositionMeta & {
  name: string;
  ir: IRObject;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function nodeRef(node: Record<string, unknown>): string | null {
  return typeof node.sourceKey === "string" && node.sourceKey
    ? node.sourceKey
    : typeof node.id === "string" && node.id
      ? node.id
      : null;
}

function walkPair(
  source: Record<string, unknown>,
  composed: Record<string, unknown>,
  input: SourceInputBlock,
  output: Record<string, string>,
  inheritedSourceId?: string,
): void {
  const sourceRef = nodeRef(source);
  const sourceId = (sourceRef && input.nodeSources[sourceRef]) || inheritedSourceId;
  const composedRef = nodeRef(composed);
  if (sourceId && composedRef) output[composedRef] = sourceId;
  const sourceChildren = Array.isArray(source.children) ? source.children : [];
  const composedChildren = Array.isArray(composed.children) ? composed.children : [];
  sourceChildren.forEach((child, index) => {
    if (isRecord(child) && isRecord(composedChildren[index])) {
      walkPair(child, composedChildren[index], input, output, sourceId);
    }
  });
}

export function composeSourceInputs(
  blocks: SourceInputBlock[],
  tokensOverride: IRObject | null = null,
  activeViewport: SourceViewport = "desktop",
  forcePage = true,
): { ir: IRObject; sourceRegistry: Record<string, SourceRecordView>; nodeSources: Record<string, string> } {
  const ir = !forcePage && blocks.length === 1
    ? deepClone(blocks[0].ir)
    : composePage(blocks.map(({ name, ir: blockIr }) => ({ name, ir: blockIr })), tokensOverride, activeViewport);
  const sourceRegistry: Record<string, SourceRecordView> = {};
  const nodeSources: Record<string, string> = {};
  const outputTree = Array.isArray(ir.tree) ? ir.tree.filter(isRecord) : [];
  let sectionIndex = 0;
  for (const block of blocks) {
    Object.assign(sourceRegistry, block.sourceRegistry);
    const sourceTree = Array.isArray(block.ir.tree) ? block.ir.tree.filter(isRecord) : [];
    for (const sourceSection of sourceTree) {
      const composedSection = outputTree[sectionIndex++];
      if (composedSection) walkPair(sourceSection, composedSection, block, nodeSources);
    }
  }
  return { ir, sourceRegistry, nodeSources };
}

function sourceMapFromContract(contract: ParserSourceEnvelope): SourceCompositionMeta {
  const record = contract.sourceRecord as SourceRecordView;
  return {
    sourceRegistry: { [record.id]: record },
    nodeSources: Object.fromEntries(Object.keys(contract.nodeStates).map((ref) => [ref, record.id])),
  };
}

function safeId(value: string): string {
  const cleaned = value.toLowerCase().replace(/[^a-z0-9._:-]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || "source";
}

function syntheticSource(node: FlowNode, handle: string, ir: IRObject): SourceCompositionMeta {
  const id = `flow-${safeId(node.type)}-${safeId(node.id)}-${safeId(handle || "ir")}`;
  const label = `${node.type} · ${handle || "IR"}`;
  const record: SourceRecordView = {
    id,
    kind: ["generator", "derive", "reskin", "mix", "qualitypass"].includes(node.type) ? "ai" : "manual",
    label,
    colorToken: `source.${safeId(node.id)}`,
    symbol: `${node.type.slice(0, 1).toUpperCase()}${node.id}`.slice(0, 8),
    confidence: 1,
  };
  const nodeSources: Record<string, string> = {};
  const walk = (value: unknown, inherited = id) => {
    if (!isRecord(value)) return;
    const ref = nodeRef(value);
    if (ref) nodeSources[ref] = inherited;
    if (Array.isArray(value.children)) value.children.forEach((child) => walk(child, inherited));
  };
  if (Array.isArray(ir.tree)) ir.tree.forEach((section) => walk(section));
  return { sourceRegistry: { [id]: record }, nodeSources };
}

export function sourceInputForPort(
  nodes: FlowNode[],
  edges: FlowEdge[],
  target: FlowNode,
  inputName: string,
): SourceInputBlock | null {
  const edge = edges.find((item) => item.target === target.id && item.targetHandle === inputName);
  if (!edge) return null;
  const sourceNode = nodes.find((item) => item.id === edge.source);
  if (!sourceNode) return null;
  const value = outValue(sourceNode, edge.sourceHandle ?? undefined);
  if (!isRecord(value)) return null;
  const sourceData = sourceNode.data as unknown as Record<string, unknown>;
  const existingRegistry = isRecord(sourceData.sourceRegistry)
    ? sourceData.sourceRegistry as Record<string, SourceRecordView>
    : null;
  const existingNodeSources = isRecord(sourceData.nodeSources)
    ? sourceData.nodeSources as Record<string, string>
    : null;
  let meta: SourceCompositionMeta | null = existingRegistry && existingNodeSources
    ? { sourceRegistry: deepClone(existingRegistry), nodeSources: deepClone(existingNodeSources) }
    : null;
  if (!meta && sourceNode.type === "sourceimport") {
    const block = sourceNode.data.blocks.find((item) => item.name === edge.sourceHandle);
    if (block?.parserContract) meta = sourceMapFromContract(block.parserContract);
  }
  if (!meta) meta = syntheticSource(sourceNode, edge.sourceHandle || "ir", value);
  return { name: inputName, ir: value, ...meta };
}
