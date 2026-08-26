import { useFlowStore } from "../flow/store";
import type { FlowEdge, FlowNode, NodeType } from "../flow/types";

type LiveRequest = {
  commandId: string;
  projectId: string;
  pageId?: string | null;
  baseRevision?: string;
  action: string;
  arguments?: Record<string, unknown>;
  mode: "preview" | "apply";
};

type UndoMove = { action: "graph.node.move"; nodeId: number; x: number; y: number; pageId: string };
type StyleMutation = { action: "editor.style.patch"; nodeId: number; sourceKey: string; style: Record<string, string | number | null>; pageId: string };
type NodeCreateMutation = { action: "graph.node.create"; nodeType: NodeType; x: number; y: number; pageId: string; expectedNodeId?: number };
type NodeDeleteMutation = { action: "graph.node.delete"; nodeId: number; pageId: string };
type NodeRestoreMutation = { action: "graph.node.restore"; node: FlowNode; edges: FlowEdge[]; pageId: string };
type UndoMutation = UndoMove | StyleMutation | NodeCreateMutation | NodeDeleteMutation | NodeRestoreMutation;
const undoStack: Array<{ commandId: string; inverse: UndoMutation; forward: UndoMutation }> = [];
const NODE_TYPES = new Set<NodeType>([
  "prompt", "reference", "generator", "edit", "mix", "page", "sourceimport", "styledna", "derive",
  "reskin", "qualitypass", "recorder", "motion", "pagebridge", "designsystem",
]);
const STYLE_KEYS = new Set([
  "color", "background", "backgroundColor", "borderColor", "borderRadius", "borderWidth", "borderStyle",
  "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "textAlign", "textTransform",
  "padding", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "margin", "gap", "opacity",
  "boxShadow", "width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight",
]);

function commandError(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}

function finiteCoordinate(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1_000_000) {
    throw commandError("ARGUMENT_INVALID", `${field} must be a finite bounded number`);
  }
  return Math.round(value);
}

function nodeMove(request: LiveRequest) {
  const args = request.arguments || {};
  const nodeIdText = String(args.nodeId || "");
  if (!/^[1-9][0-9]{0,15}$/.test(nodeIdText)) throw commandError("ARGUMENT_INVALID", "nodeId must be a numeric node identifier");
  const nodeId = Number(nodeIdText);
  const state = useFlowStore.getState();
  const pageId = request.pageId || state.activePageId;
  if (pageId !== state.activePageId) throw commandError("PAGE_NOT_ACTIVE", "Open the target page before applying this command");
  const node = state.nodes.find((item) => item.id === nodeIdText);
  if (!node) throw commandError("NODE_NOT_FOUND", `Node ${nodeIdText} does not exist on the active page`);
  const x = finiteCoordinate(args.x, "x");
  const y = finiteCoordinate(args.y, "y");
  const forward: UndoMove = { action: "graph.node.move", nodeId, x, y, pageId };
  const inverse: UndoMove = { action: "graph.node.move", nodeId, x: Math.round(node.position.x), y: Math.round(node.position.y), pageId };
  const affectedObjects = [{ kind: "graph.node", id: nodeIdText, pageId }];
  if (request.mode === "preview") {
    return {
      previewId: `preview-${request.commandId}`,
      baseRevision: request.baseRevision,
      patch: [forward],
      inversePatch: [inverse],
      affectedObjects,
      preservedRules: ["graph.structure", "node.data", "edges", "page.identity"],
      violations: [],
      qualityReport: { gate: "structural", passed: true },
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    };
  }
  state.moveNode(nodeId, x, y);
  undoStack.push({ commandId: request.commandId, inverse, forward });
  if (undoStack.length > 100) undoStack.shift();
  return {
    inverseCommand: inverse,
    undoEntry: { commandId: request.commandId, label: `Move node ${nodeIdText}`, action: request.action },
    affectedObjects,
    qualityReport: { gate: "structural", passed: true },
  };
}

function activePage(request: LiveRequest): { state: ReturnType<typeof useFlowStore.getState>; pageId: string } {
  const state = useFlowStore.getState();
  const pageId = request.pageId || state.activePageId;
  if (pageId !== state.activePageId) throw commandError("PAGE_NOT_ACTIVE", "Open the target page before applying this command");
  return { state, pageId };
}

function nodeIdentifier(value: unknown): number {
  const text = String(value || "");
  if (!/^[1-9][0-9]{0,15}$/.test(text)) throw commandError("ARGUMENT_INVALID", "nodeId must be a numeric node identifier");
  const result = Number(text);
  if (!Number.isSafeInteger(result)) throw commandError("ARGUMENT_INVALID", "nodeId exceeds the safe integer range");
  return result;
}

function graphNodeCreate(request: LiveRequest) {
  const args = request.arguments || {};
  const nodeType = String(args.nodeType || "") as NodeType;
  if (!NODE_TYPES.has(nodeType)) throw commandError("ARGUMENT_INVALID", "nodeType is not supported");
  const x = finiteCoordinate(args.x, "x");
  const y = finiteCoordinate(args.y, "y");
  const { state, pageId } = activePage(request);
  const expectedNodeId = state.nextId;
  const forward: NodeCreateMutation = { action: "graph.node.create", nodeType, x, y, pageId, expectedNodeId };
  const inverse: NodeDeleteMutation = { action: "graph.node.delete", nodeId: expectedNodeId, pageId };
  const affectedObjects = [{ kind: "graph.node", id: String(expectedNodeId), pageId }];
  if (request.mode === "preview") {
    return {
      previewId: `preview-${request.commandId}`, baseRevision: request.baseRevision,
      patch: [forward], inversePatch: [inverse], affectedObjects,
      preservedRules: ["existing.nodes", "existing.edges", "page.identity"], violations: [],
      qualityReport: { gate: "structural", passed: true }, expiresAt: new Date(Date.now() + 60_000).toISOString(),
    };
  }
  const created = state.addNode(nodeType, x, y);
  if (created.id !== expectedNodeId) throw commandError("NODE_ID_CONFLICT", "The graph changed while creating the node");
  undoStack.push({ commandId: request.commandId, inverse, forward });
  if (undoStack.length > 100) undoStack.shift();
  return {
    inverseCommand: inverse,
    undoEntry: { commandId: request.commandId, label: `Create ${nodeType} node ${created.id}`, action: request.action },
    affectedObjects, qualityReport: { gate: "structural", passed: true },
  };
}

function restoreNode(mutation: NodeRestoreMutation): void {
  const state = useFlowStore.getState();
  if (state.activePageId !== mutation.pageId) throw commandError("PAGE_NOT_ACTIVE", "Open the affected page before restoring this node");
  if (state.nodes.some((node) => node.id === mutation.node.id)) throw commandError("NODE_ID_CONFLICT", "The deleted node identifier is already in use");
  const liveIds = new Set(state.nodes.map((node) => node.id));
  liveIds.add(mutation.node.id);
  const restoredEdges = mutation.edges.filter((edge) => liveIds.has(edge.source) && liveIds.has(edge.target));
  if (restoredEdges.length !== mutation.edges.length) throw commandError("EDGE_ENDPOINT_MISSING", "A connected node required for undo no longer exists");
  const existingEdgeIds = new Set(state.edges.map((edge) => edge.id));
  if (restoredEdges.some((edge) => existingEdgeIds.has(edge.id))) throw commandError("EDGE_ID_CONFLICT", "A deleted edge identifier is already in use");
  useFlowStore.setState({
    nodes: [...state.nodes, structuredClone(mutation.node)],
    edges: [...state.edges, ...structuredClone(restoredEdges)],
    nextId: Math.max(state.nextId, Number(mutation.node.id) + 1),
  });
}

function graphNodeDelete(request: LiveRequest) {
  const nodeId = nodeIdentifier((request.arguments || {}).nodeId);
  const { state, pageId } = activePage(request);
  const node = state.nodes.find((item) => item.id === String(nodeId));
  if (!node) throw commandError("NODE_NOT_FOUND", `Node ${nodeId} does not exist on the active page`);
  const edges = state.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  const snapshotBytes = new TextEncoder().encode(JSON.stringify({ node, edges })).length;
  if (snapshotBytes > 196_608) throw commandError("UNDO_SNAPSHOT_TOO_LARGE", "The node is too large for a safe live-command undo snapshot");
  const forward: NodeDeleteMutation = { action: "graph.node.delete", nodeId, pageId };
  const inverse: NodeRestoreMutation = { action: "graph.node.restore", node: structuredClone(node), edges: structuredClone(edges), pageId };
  const affectedObjects = [{ kind: "graph.node", id: String(nodeId), pageId }, ...edges.map((edge) => ({ kind: "graph.edge", id: edge.id, pageId }))];
  if (request.mode === "preview") {
    return {
      previewId: `preview-${request.commandId}`, baseRevision: request.baseRevision,
      patch: [forward], inversePatch: [inverse], affectedObjects,
      preservedRules: ["unrelated.nodes", "unrelated.edges", "page.identity"], violations: [],
      qualityReport: { gate: "structural", passed: true }, expiresAt: new Date(Date.now() + 60_000).toISOString(),
    };
  }
  state.deleteNode(nodeId);
  undoStack.push({ commandId: request.commandId, inverse, forward });
  if (undoStack.length > 100) undoStack.shift();
  return {
    inverseCommand: inverse,
    undoEntry: { commandId: request.commandId, label: `Delete node ${nodeId}`, action: request.action },
    affectedObjects, qualityReport: { gate: "structural", passed: true },
  };
}

function styleValues(value: unknown): Record<string, string | number | null> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw commandError("ARGUMENT_INVALID", "style must be an object");
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length || entries.length > 32) throw commandError("ARGUMENT_INVALID", "style must contain 1 to 32 properties");
  const result: Record<string, string | number | null> = {};
  for (const [key, item] of entries) {
    if (!STYLE_KEYS.has(key)) throw commandError("STYLE_PROPERTY_FORBIDDEN", `Style property ${key} is not controllable`);
    if (item !== null && typeof item !== "string" && (typeof item !== "number" || !Number.isFinite(item))) {
      throw commandError("ARGUMENT_INVALID", `Style property ${key} must be string, finite number or null`);
    }
    if (typeof item === "string" && item.length > 500) throw commandError("ARGUMENT_INVALID", `Style property ${key} is too long`);
    result[key] = item as string | number | null;
  }
  return result;
}

function findSourceNode(root: unknown, sourceKey: string, seen = new Set<object>(), depth = 0): Record<string, unknown> | null {
  if (depth > 64) throw commandError("IR_INVALID", "Design IR exceeds the supported nesting depth");
  if (Array.isArray(root)) {
    if (seen.has(root)) throw commandError("IR_INVALID", "Design IR contains a cycle");
    seen.add(root);
    for (const item of root) {
      const found = findSourceNode(item, sourceKey, seen, depth + 1);
      if (found) return found;
    }
    seen.delete(root);
    return null;
  }
  if (!root || typeof root !== "object") return null;
  const record = root as Record<string, unknown>;
  if (record.sourceKey === sourceKey) return record;
  if (seen.has(record)) throw commandError("IR_INVALID", "Design IR contains a cycle");
  seen.add(record);
  for (const value of Object.values(record)) {
    const found = findSourceNode(value, sourceKey, seen, depth + 1);
    if (found) return found;
  }
  seen.delete(record);
  return null;
}

function applyStyleMutation(mutation: StyleMutation): void {
  const state = useFlowStore.getState();
  if (state.activePageId !== mutation.pageId) throw commandError("PAGE_NOT_ACTIVE", "Open the affected page before changing its style");
  const graphNode = state.nodes.find((item) => item.id === String(mutation.nodeId));
  const rawIr = graphNode ? (graphNode.data as Record<string, unknown>).ir : null;
  if (!graphNode || !rawIr || typeof rawIr !== "object") throw commandError("IR_NOT_FOUND", "The graph node has no editable Design IR");
  const ir = structuredClone(rawIr) as Record<string, unknown>;
  const target = findSourceNode(ir.tree, mutation.sourceKey);
  if (!target) throw commandError("SOURCE_KEY_NOT_FOUND", `Source key ${mutation.sourceKey} does not exist`);
  const currentStyle = target.style && typeof target.style === "object" && !Array.isArray(target.style)
    ? { ...(target.style as Record<string, unknown>) }
    : {};
  for (const [key, value] of Object.entries(mutation.style)) {
    if (value === null) delete currentStyle[key];
    else currentStyle[key] = value;
  }
  target.style = currentStyle;
  state.setNodeData(mutation.nodeId, { ir });
}

function editorStylePatch(request: LiveRequest) {
  const args = request.arguments || {};
  const nodeIdText = String(args.nodeId || "");
  const sourceKey = typeof args.sourceKey === "string" ? args.sourceKey : "";
  if (!/^[1-9][0-9]{0,15}$/.test(nodeIdText)) throw commandError("ARGUMENT_INVALID", "nodeId must be a numeric node identifier");
  if (!sourceKey || sourceKey.length > 500) throw commandError("ARGUMENT_INVALID", "sourceKey must be a bounded string");
  const nodeId = Number(nodeIdText);
  const state = useFlowStore.getState();
  const pageId = request.pageId || state.activePageId;
  if (pageId !== state.activePageId) throw commandError("PAGE_NOT_ACTIVE", "Open the target page before applying this command");
  const graphNode = state.nodes.find((item) => item.id === nodeIdText);
  const rawIr = graphNode ? (graphNode.data as Record<string, unknown>).ir : null;
  if (!rawIr || typeof rawIr !== "object") throw commandError("IR_NOT_FOUND", "The graph node has no editable Design IR");
  const target = findSourceNode((rawIr as Record<string, unknown>).tree, sourceKey);
  if (!target) throw commandError("SOURCE_KEY_NOT_FOUND", `Source key ${sourceKey} does not exist`);
  const patch = styleValues(args.style);
  const currentStyle = target.style && typeof target.style === "object" && !Array.isArray(target.style)
    ? target.style as Record<string, unknown>
    : {};
  const inverseStyle: Record<string, string | number | null> = {};
  for (const key of Object.keys(patch)) {
    const previous = currentStyle[key];
    inverseStyle[key] = typeof previous === "string" || typeof previous === "number" ? previous : null;
  }
  const forward: StyleMutation = { action: "editor.style.patch", nodeId, sourceKey, style: patch, pageId };
  const inverse: StyleMutation = { action: "editor.style.patch", nodeId, sourceKey, style: inverseStyle, pageId };
  const affectedObjects = [{ kind: "design-ir.object", nodeId: nodeIdText, sourceKey, pageId }];
  if (request.mode === "preview") {
    return {
      previewId: `preview-${request.commandId}`,
      baseRevision: request.baseRevision,
      patch: [forward], inversePatch: [inverse], affectedObjects,
      preservedRules: ["tree.structure", "sourceKey", "content", "component.identity", "responsive.structure"],
      violations: [], qualityReport: { gate: "style-only", passed: true },
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    };
  }
  applyStyleMutation(forward);
  undoStack.push({ commandId: request.commandId, inverse, forward });
  if (undoStack.length > 100) undoStack.shift();
  return {
    inverseCommand: inverse,
    undoEntry: { commandId: request.commandId, label: `Style ${sourceKey}`, action: request.action },
    affectedObjects,
    qualityReport: { gate: "style-only", passed: true },
  };
}

function historyUndo(request: LiveRequest) {
  const entry = undoStack.at(-1);
  if (!entry) throw commandError("UNDO_EMPTY", "There is no live command to undo");
  const inverse = entry.inverse;
  const affectedObjects = inverse.action === "editor.style.patch"
    ? [{ kind: "design-ir.object", nodeId: String(inverse.nodeId), sourceKey: inverse.sourceKey, pageId: inverse.pageId }]
    : inverse.action === "graph.node.restore"
      ? [
          { kind: "graph.node", id: inverse.node.id, pageId: inverse.pageId },
          ...inverse.edges.map((edge) => ({ kind: "graph.edge", id: edge.id, pageId: inverse.pageId })),
        ]
      : [{ kind: "graph.node", id: String(inverse.action === "graph.node.create" ? inverse.expectedNodeId : inverse.nodeId), pageId: inverse.pageId }];
  const styleOnly = inverse.action === "editor.style.patch";
  if (request.mode === "preview") {
    return {
      previewId: `preview-${request.commandId}`,
      baseRevision: request.baseRevision,
      patch: [inverse],
      inversePatch: [entry.forward],
      affectedObjects,
      preservedRules: styleOnly
        ? ["tree.structure", "sourceKey", "content", "component.identity", "responsive.structure"]
        : ["graph.structure", "node.data", "edges", "page.identity"],
      violations: [],
      qualityReport: { gate: styleOnly ? "style-only" : "structural", passed: true },
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    };
  }
  const state = useFlowStore.getState();
  if (state.activePageId !== inverse.pageId) throw commandError("PAGE_NOT_ACTIVE", "Open the affected page before undoing this command");
  if (inverse.action === "graph.node.move") {
    const node = state.nodes.find((item) => item.id === String(inverse.nodeId));
    if (!node) throw commandError("NODE_NOT_FOUND", "The affected node no longer exists");
    state.moveNode(inverse.nodeId, inverse.x, inverse.y);
  } else if (inverse.action === "editor.style.patch") {
    applyStyleMutation(inverse);
  } else if (inverse.action === "graph.node.delete") {
    const node = state.nodes.find((item) => item.id === String(inverse.nodeId));
    if (!node) throw commandError("NODE_NOT_FOUND", "The affected node no longer exists");
    state.deleteNode(inverse.nodeId);
  } else if (inverse.action === "graph.node.restore") {
    restoreNode(inverse);
  } else {
    const created = state.addNode(inverse.nodeType, inverse.x, inverse.y);
    if (inverse.expectedNodeId != null && created.id !== inverse.expectedNodeId) {
      state.deleteNode(created.id);
      throw commandError("NODE_ID_CONFLICT", "The original node identifier cannot be restored");
    }
  }
  undoStack.pop();
  return {
    inverseCommand: entry.forward,
    undoEntry: { commandId: request.commandId, label: `Undo ${entry.commandId}`, action: request.action },
    affectedObjects,
    qualityReport: { gate: styleOnly ? "style-only" : "structural", passed: true },
  };
}

export function executeRendererLiveCommand(request: LiveRequest): Record<string, unknown> {
  if (!request || typeof request !== "object") throw commandError("COMMAND_INVALID", "Live command must be an object");
  if (!new Set(["preview", "apply"]).has(request.mode)) throw commandError("COMMAND_INVALID", "Unsupported command mode");
  if (request.action === "graph.node.create") return graphNodeCreate(request);
  if (request.action === "graph.node.delete") return graphNodeDelete(request);
  if (request.action === "graph.node.move") return nodeMove(request);
  if (request.action === "editor.style.patch") return editorStylePatch(request);
  if (request.action === "history.undo") return historyUndo(request);
  throw commandError("HANDLER_NOT_REGISTERED", `Renderer action ${String(request.action)} is not implemented`);
}

export function installRendererLiveCommands(): () => void {
  const commands = window.designDNA?.commands;
  if (!commands?.onRequest || !commands?.respond) return () => {};
  return commands.onRequest(async ({ requestId, command }) => {
    try {
      const result = executeRendererLiveCommand(command as LiveRequest);
      await commands.respond(requestId, { ok: true, result });
    } catch (reason) {
      const error = reason as Error & { code?: string };
      await commands.respond(requestId, {
        ok: false,
        error: { code: error.code || "RENDERER_COMMAND_FAILED", message: error.message || String(reason) },
      });
    }
  });
}
